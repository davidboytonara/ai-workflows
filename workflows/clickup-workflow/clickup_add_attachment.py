#!/usr/bin/env python3
"""Upload a file attachment to a ClickUp task (multipart, stdlib only)."""
import argparse
import json
import os
import sys

import clickup_common as cu


def upload(cfg, task_id, file_path, field_name):
    content_type, body = cu.encode_multipart(
        file_path, field_name,
        extra_fields={'filename': os.path.basename(file_path)})
    url = f"{cfg['base_url']}/api/v2/task/{task_id}/attachment"
    status, resp, _ = cu.make_request('POST', url, cfg['token'],
                                      raw_body=body, content_type=content_type)
    return status, resp


def main():
    cfg = cu.get_config()

    parser = argparse.ArgumentParser(
        description='Attach a file to a ClickUp task (max 1 GB).',
        epilog=('Example:\n'
                '  clickup_add_attachment.py --task-id 86abc123 --file-path spec.pdf\n'),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--file-path', required=True)
    args = parser.parse_args()

    cu.require_token(cfg)
    if not os.path.exists(args.file_path):
        cu.fail_usage(f'File not found: {args.file_path}')

    # Docs are ambiguous about the multipart field name ('attachment' in the
    # reference and working examples, 'attachment[]' in the guide) — try the
    # common one, retry once with the indexed form on a 400.
    status, resp = upload(cfg, args.task_id, args.file_path, 'attachment')
    field_used = 'attachment'
    if status == 400:
        status, resp = upload(cfg, args.task_id, args.file_path, 'attachment[0]')
        field_used = 'attachment[0]'

    cu.finish(status, resp, {'task_id': args.task_id, 'field_used': field_used})


if __name__ == '__main__':
    main()
