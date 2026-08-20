#!/usr/bin/env python3
"""Update (or delete) an existing ClickUp task. Only provided flags are sent."""
import argparse
import json
import sys

import clickup_common as cu


def main():
    cfg = cu.get_config()

    parser = argparse.ArgumentParser(
        description='Update fields on a ClickUp task (PUT only what you pass).',
        epilog=('Examples:\n'
                '  clickup_update_task.py --task-id 86abc123 --status "in progress"\n'
                '  clickup_update_task.py --task-id 86abc123 --target-date 2026-08-15 \\\n'
                '      --assignee-name "Jane Doe" --epic "Platform Phase 1"\n'
                '  clickup_update_task.py --task-id 86abc123 --priority none   # clear\n'
                '  clickup_update_task.py --task-id 86abc123 --delete\n'),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--title', help='New task name')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--description', help='New description (markdown)')
    group.add_argument('--description-file', help='Path to a markdown file')
    parser.add_argument('--status', help='Status name (validated against the list)')
    parser.add_argument('--priority',
                        help='urgent|high|normal|medium|low|none (none clears it)')
    parser.add_argument('--target-date', help='Due date YYYY-MM-DD (alias: --due-date)')
    parser.add_argument('--due-date', dest='target_date', help=argparse.SUPPRESS)
    parser.add_argument('--assignee-id', action='append', type=int,
                        help='Add assignee by user id (repeatable)')
    parser.add_argument('--assignee-name', action='append',
                        help='Add assignee by username/email (repeatable)')
    parser.add_argument('--remove-assignee-id', action='append', type=int,
                        help='Remove assignee by user id (repeatable)')
    parser.add_argument('--remove-assignee-name', action='append',
                        help='Remove assignee by username/email (repeatable)')
    parser.add_argument('--epic',
                        help='Epic: option name (custom-field model) or parent task id')
    parser.add_argument('--parent', help='Move under a parent task id')
    parser.add_argument('--archived', choices=('true', 'false'),
                        help='Archive/unarchive the task')
    parser.add_argument('--list-id', default=cfg['list_id'],
                        help='List id for status/epic validation (default from ~/.agents/.config)')
    parser.add_argument('--delete', action='store_true',
                        help='DELETE the task instead of updating (used for smoke-test cleanup)')
    args = parser.parse_args()

    cu.require_token(cfg)
    cfg['list_id'] = args.list_id

    if args.delete:
        status, resp = cu.api('DELETE', f'/api/v2/task/{args.task_id}', cfg)
        cu.finish(status, resp, {'deleted': 200 <= status < 300,
                                 'task_id': args.task_id})

    payload = {}
    if args.title:
        payload['name'] = args.title
    if args.description is not None:
        payload['markdown_content'] = args.description
    elif args.description_file:
        try:
            with open(args.description_file, 'r', encoding='utf-8') as f:
                payload['markdown_content'] = f.read()
        except Exception as e:
            cu.fail_usage(f'Failed to read description file: {e}')
    if args.status:
        if not args.list_id:
            cu.fail_usage('Status validation needs --list-id or a pinned CLICKUP_LIST_ID')
        payload['status'] = cu.validate_status_or_die(args.status, cfg, args.list_id)
    if args.priority is not None:
        payload['priority'] = cu.priority_to_int(args.priority)
    if args.target_date:
        payload['due_date'] = cu.to_unix_ms(args.target_date)
        payload['due_date_time'] = False
    if args.parent:
        payload['parent'] = args.parent
    if args.archived:
        payload['archived'] = args.archived == 'true'

    # Update-shape assignees: {"add": [...], "rem": [...]} (unlike create's array)
    add_ids = list(args.assignee_id or [])
    add_ids += cu.resolve_assignees_or_die(args.assignee_name or [], cfg)
    rem_ids = list(args.remove_assignee_id or [])
    rem_ids += cu.resolve_assignees_or_die(args.remove_assignee_name or [], cfg)
    if add_ids or rem_ids:
        payload['assignees'] = {'add': add_ids, 'rem': rem_ids}

    epic_action = None
    if args.epic:
        resolved = cu.resolve_epic_or_die(args.epic, cfg)
        if resolved[0] == 'parent':
            payload['parent'] = resolved[1]
        else:
            epic_action = resolved  # custom field set is its own endpoint on update

    if not payload and epic_action is None:
        cu.fail_usage('Nothing to update — pass at least one field flag')

    status, resp = 200, {'note': 'no task fields changed, only epic custom field'}
    if payload:
        status, resp = cu.api('PUT', f'/api/v2/task/{args.task_id}', cfg,
                              payload=payload)

    extra = {'task_id': args.task_id}
    if epic_action is not None and 200 <= status < 300:
        f_status, f_resp = cu.set_custom_field(cfg, args.task_id,
                                               epic_action[1], epic_action[2])
        extra['epic_field'] = {'ok': 200 <= f_status < 300,
                               'status': f_status, 'response': f_resp}
        if not extra['epic_field']['ok']:
            cu.finish(f_status, resp, extra)
    cu.finish(status, resp, extra)


if __name__ == '__main__':
    main()
