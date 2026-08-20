#!/usr/bin/env python3
"""Post a comment on a ClickUp task."""
import argparse

import clickup_common as cu


def main():
    cfg = cu.get_config()

    parser = argparse.ArgumentParser(
        description='Add a comment to a ClickUp task.',
        epilog=('Example:\n'
                '  clickup_add_comment.py --task-id 86abc123 --text "Deployed to staging."\n'),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--task-id', required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--text', help='Comment text')
    group.add_argument('--text-file', help='Path to a file with the comment text')
    parser.add_argument('--notify-all', action='store_true',
                        help='Notify everyone on the task (default: no notification)')
    parser.add_argument('--assignee-name',
                        help='Assign the comment to this username/email')
    args = parser.parse_args()

    cu.require_token(cfg)

    if args.text is not None:
        text = args.text
    else:
        try:
            with open(args.text_file, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception as e:
            cu.fail_usage(f'Failed to read text file: {e}')

    payload = {'comment_text': text, 'notify_all': bool(args.notify_all)}
    if args.assignee_name:
        ids = cu.resolve_assignees_or_die([args.assignee_name], cfg)
        payload['assignee'] = ids[0]

    status, resp = cu.api('POST', f'/api/v2/task/{args.task_id}/comment', cfg,
                          payload=payload)
    cu.finish(status, resp, {'task_id': args.task_id})


if __name__ == '__main__':
    main()
