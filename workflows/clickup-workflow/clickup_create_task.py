#!/usr/bin/env python3
"""Create a ClickUp task in the list pinned in ~/.agents/.config."""
import argparse
import json
import sys

import clickup_common as cu


def main():
    cfg = cu.get_config()

    parser = argparse.ArgumentParser(
        description='Create a ClickUp task with a markdown description.',
        epilog=('Examples:\n'
                '  clickup_create_task.py --title "Fix VPN" --description "**why** ..."\n'
                '  clickup_create_task.py --title "Story" --description-file story.md \\\n'
                '      --priority medium --target-date 2026-08-01 --assignee-name "Jane Doe"\n'),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--list-id', default=cfg['list_id'],
                        help=f"Target list id (default from ~/.agents/.config: {cfg['list_id']})")
    parser.add_argument('--title', required=True, help='Task name')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--description', help='Task description (markdown)')
    group.add_argument('--description-file', help='Path to a markdown file')
    parser.add_argument('--status', help='Status name (validated against the list)')
    parser.add_argument('--priority',
                        help='urgent|high|normal|medium|low|none (Plane words accepted)')
    parser.add_argument('--target-date', help='Due date YYYY-MM-DD (alias: --due-date)')
    parser.add_argument('--due-date', dest='target_date', help=argparse.SUPPRESS)
    parser.add_argument('--assignee-id', action='append', type=int,
                        help='ClickUp user id (repeatable)')
    parser.add_argument('--assignee-name', action='append',
                        help='Username or email, resolved via workspace roster (repeatable)')
    parser.add_argument('--epic',
                        help='Epic to attach: option name (custom-field model) '
                             'or parent task id (parent model)')
    parser.add_argument('--parent', help='Parent task id (create as subtask)')
    args = parser.parse_args()

    cu.require_token(cfg)
    if not args.list_id:
        cu.fail_usage('No list id — pass --list-id or run clickup_resolve_ids.py --write')
    cfg['list_id'] = args.list_id

    if args.description is not None:
        description = args.description
    else:
        try:
            with open(args.description_file, 'r', encoding='utf-8') as f:
                description = f.read()
        except Exception as e:
            cu.fail_usage(f'Failed to read description file: {e}')

    # markdown_content silently wins over description if both are sent, so
    # send only markdown_content.
    payload = {'name': args.title, 'markdown_content': description}

    if args.status:
        payload['status'] = cu.validate_status_or_die(args.status, cfg, args.list_id)
    if args.priority is not None:
        payload['priority'] = cu.priority_to_int(args.priority)
    if args.target_date:
        payload['due_date'] = cu.to_unix_ms(args.target_date)
        payload['due_date_time'] = False
    if args.parent:
        payload['parent'] = args.parent

    assignee_ids = list(args.assignee_id or [])
    assignee_ids += cu.resolve_assignees_or_die(args.assignee_name or [], cfg)
    if assignee_ids:
        payload['assignees'] = assignee_ids

    epic_field_set = None
    if args.epic:
        resolved = cu.resolve_epic_or_die(args.epic, cfg)
        if resolved[0] == 'parent':
            payload['parent'] = resolved[1]
        else:
            # create accepts custom fields inline
            payload['custom_fields'] = [{'id': resolved[1], 'value': resolved[2]}]
            epic_field_set = resolved[1]

    status, resp = cu.api('POST', f'/api/v2/list/{args.list_id}/task', cfg,
                          payload=payload)

    extra = {}
    if isinstance(resp, dict) and resp.get('id'):
        extra = {'task_id': resp['id'], 'url': resp.get('url')}
        if epic_field_set:
            extra['epic_field_id'] = epic_field_set
    cu.finish(status, resp, extra)


if __name__ == '__main__':
    main()
