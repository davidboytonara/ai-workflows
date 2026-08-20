#!/usr/bin/env python3
"""One-time setup: resolve ClickUp IDs for Space > Project and pin them.

Walks workspace -> space -> project (space/project names come from
--space-name / --project-name or DEFAULT_* in clickup_common.py; the
project is tried as Folder, then folderless List, then List inside any
Folder), prints the resolved chain plus list statuses, custom fields
(epic detection), and the workspace member roster. Dry-run by default;
--write persists the IDs into ~/.agents/.config (preserving unknown keys).
"""
import argparse
import json
import os
import sys

import clickup_common as cu


def match_name(items, wanted, key='name'):
    wl = wanted.lower().strip()
    return next((i for i in items if str(i.get(key, '')).lower() == wl), None)


def resolve_via_shared(cfg, args, team):
    """Guest-token fallback: spaces are hidden, but folders/lists shared with
    the account are visible via GET /team/{id}/shared. Returns a partial
    chain dict, or None when nothing at all is shared."""
    status, resp = cu.api('GET', f"/api/v2/team/{team['id']}/shared", cfg)
    shared = resp.get('shared', {}) if isinstance(resp, dict) else {}
    folders = shared.get('folders') or []
    shared_lists = shared.get('lists') or []
    if not folders and not shared_lists:
        return None

    out = {'via': 'shared'}
    the_list = None
    folder = match_name(folders, args.project_name)
    if folder is not None:
        _, lists = cu.get_lists_in_folder(cfg, folder['id'])
        if len(lists) == 1:
            the_list = lists[0]
        elif args.list_name:
            the_list = match_name(lists, args.list_name)
        if the_list is None:
            cu.fail_usage(
                f"Shared folder '{folder['name']}' has {len(lists)} lists — "
                'pass --list-name',
                lists=[{'id': l['id'], 'name': l['name']} for l in lists])
    else:
        wanted = args.list_name or args.project_name
        the_list = match_name(shared_lists, wanted)
        if the_list is None:
            for f in folders:
                _, flists = cu.get_lists_in_folder(cfg, f['id'])
                hit = match_name(flists, wanted)
                if hit is not None:
                    folder, the_list = f, hit
                    break
    if the_list is None:
        cu.fail_usage(
            f"'{args.project_name}' not found among items shared with this "
            'account (guest token: workspace spaces are hidden)',
            shared_folders=[{'id': f['id'], 'name': f['name']} for f in folders],
            shared_lists=[{'id': l['id'], 'name': l['name']}
                          for l in shared_lists])
    if folder is not None:
        out['folder'] = {'id': folder['id'], 'name': folder['name']}
    space = the_list.get('space') or {}
    if space.get('id'):
        out['space'] = {'id': space['id'], 'name': space.get('name') or ''}
    out['list'] = {'id': the_list['id'], 'name': the_list['name']}
    return out


def resolve_chain(cfg, args):
    result = {}

    status, teams = cu.get_workspaces(cfg)
    if not (200 <= status < 300):
        cu.finish(status, {'error': 'Failed to list workspaces', 'detail': teams})
    if args.team_id:
        team = next((t for t in teams if str(t.get('id')) == str(args.team_id)), None)
        if team is None:
            cu.fail_usage(f'Workspace {args.team_id} not found',
                          workspaces=[{'id': t['id'], 'name': t['name']} for t in teams])
    elif len(teams) == 1:
        team = teams[0]
    else:
        cu.fail_usage('Multiple workspaces — pass --team-id',
                      workspaces=[{'id': t['id'], 'name': t['name']} for t in teams])
    result['team'] = {'id': team['id'], 'name': team['name']}

    status, spaces = cu.get_spaces(cfg, team['id'])
    space = match_name(spaces, args.space_name)
    if space is None:
        shared = resolve_via_shared(cfg, args, team)
        if shared is not None:
            result.update(shared)
            return result
        cu.fail_usage(f"Space '{args.space_name}' not found in workspace "
                      f"'{team['name']}' and nothing is shared with this account",
                      spaces=[{'id': s['id'], 'name': s['name']} for s in spaces])
    result['space'] = {'id': space['id'], 'name': space['name']}

    # Project resolution order: Folder, folderless List, List inside a Folder.
    status, folders = cu.get_folders(cfg, space['id'])
    folder = match_name(folders, args.project_name)
    the_list = None
    if folder is not None:
        result['folder'] = {'id': folder['id'], 'name': folder['name']}
        lists = folder.get('lists') or []
        if not lists:
            _, lists = cu.get_lists_in_folder(cfg, folder['id'])
        if len(lists) == 1:
            the_list = lists[0]
        elif args.list_name:
            the_list = match_name(lists, args.list_name)
        if the_list is None:
            cu.fail_usage(
                f"Folder '{folder['name']}' has {len(lists)} lists — pass --list-name",
                lists=[{'id': l['id'], 'name': l['name']} for l in lists])
    else:
        _, folderless = cu.get_folderless_lists(cfg, space['id'])
        the_list = match_name(folderless, args.project_name)
        if the_list is None:
            for f in folders:
                the_list = match_name(f.get('lists') or [], args.project_name)
                if the_list is not None:
                    result['folder'] = {'id': f['id'], 'name': f['name']}
                    break
    if the_list is None:
        cu.fail_usage(
            f"'{args.project_name}' not found in space '{space['name']}' "
            'as folder or list',
            folders=[{'id': f['id'], 'name': f['name']} for f in folders],
            folderless_lists=[{'id': l['id'], 'name': l['name']}
                              for l in folderless])
    result['list'] = {'id': the_list['id'], 'name': the_list['name']}
    return result


def inspect_list(cfg, list_id):
    """Statuses + custom fields + epic-model detection for the pinned list."""
    out = {}
    status, resp = cu.get_list(cfg, list_id)
    out['statuses'] = [
        {'name': s.get('status'), 'type': s.get('type')}
        for s in (resp.get('statuses', []) if isinstance(resp, dict) else [])
    ]
    status, fields = cu.get_list_fields(cfg, list_id)
    out['custom_fields'] = [
        {'id': f.get('id'), 'name': f.get('name'), 'type': f.get('type')}
        for f in fields
    ]
    epic_field = cu.find_epic_field(fields)
    if epic_field is not None:
        options = (epic_field.get('type_config') or {}).get('options') or []
        out['epic'] = {
            'model': 'custom_field',
            'field_id': epic_field.get('id'),
            'field_name': epic_field.get('name'),
            'field_type': epic_field.get('type'),
            'options': [o.get('name') or o.get('label') for o in options],
        }
    else:
        # No epic-ish custom field: fall back to parent-task modeling. Check
        # whether existing tasks actually use subtask parents as a hint.
        status, resp = cu.api('GET', f'/api/v2/list/{list_id}/task', cfg,
                              query={'page': 0, 'subtasks': 'true'})
        tasks = resp.get('tasks', []) if isinstance(resp, dict) else []
        parents_in_use = sum(1 for t in tasks if t.get('parent'))
        out['epic'] = {
            'model': 'parent',
            'note': ('no custom field named *epic* on this list; --epic will '
                     'set the task parent (epics = top-level tasks with '
                     'subtasks)'),
            'sampled_tasks': len(tasks),
            'tasks_with_parent': parents_in_use,
        }
    return out


def write_env_file(values):
    """Read-modify-write ~/.agents/.config, preserving unknown keys/comments."""
    path = cu.env_file_path()
    lines = []
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
    seen = set()
    out_lines = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split('=', 1)[0].strip() if '=' in stripped else None
        if key in values:
            out_lines.append(f'{key}={values[key]}')
            seen.add(key)
        else:
            out_lines.append(line)
    for key, value in values.items():
        if key not in seen:
            out_lines.append(f'{key}={value}')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines) + '\n')
    return path


def main():
    parser = argparse.ArgumentParser(
        description='Resolve and pin ClickUp IDs for the target Space/Project.')
    parser.add_argument('--space-name', default=cu.DEFAULT_SPACE_NAME)
    parser.add_argument('--project-name', default=cu.DEFAULT_PROJECT_NAME)
    parser.add_argument('--list-name',
                        help='Disambiguate when the project folder has several lists')
    parser.add_argument('--team-id', help='Workspace id if more than one')
    parser.add_argument('--write', action='store_true',
                        help='Persist resolved IDs into ~/.agents/.config (default: dry-run)')
    args = parser.parse_args()

    cfg = cu.get_config()
    cu.require_token(cfg)

    chain = resolve_chain(cfg, args)
    detail = inspect_list(cfg, chain['list']['id'])
    _, roster = cu.get_team_roster(cfg, chain['team']['id'])
    if not roster:
        _, roster = cu.get_list_members(cfg, chain['list']['id'])

    output = {'ok': True, 'chain': chain, 'list_detail': detail,
              'members': roster, 'written': False}

    if args.write:
        values = {
            'CLICKUP_BASE_URL': cfg['base_url'],
            'CLICKUP_TEAM_ID': chain['team']['id'],
            'CLICKUP_SPACE_ID': (chain.get('space') or {}).get('id', ''),
            'CLICKUP_LIST_ID': chain['list']['id'],
            'CLICKUP_LIST_NAME': chain['list']['name'],
            'CLICKUP_EPIC_MODEL': detail['epic']['model'],
        }
        if 'folder' in chain:
            values['CLICKUP_FOLDER_ID'] = chain['folder']['id']
        if detail['epic']['model'] == 'custom_field':
            values['CLICKUP_EPIC_FIELD_ID'] = detail['epic']['field_id']
            values['CLICKUP_EPIC_FIELD_NAME'] = detail['epic']['field_name']
        output['written'] = True
        output['env_file'] = write_env_file(values)

    print(json.dumps(output, indent=2))
    sys.exit(0)


if __name__ == '__main__':
    main()
