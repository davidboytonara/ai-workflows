#!/usr/bin/env python3
"""List ClickUp tasks in the pinned list, with per-assignee workload summary."""
import argparse
import json
import sys
from datetime import datetime

import clickup_common as cu

PRIORITY_NAMES = {1: 'urgent', 2: 'high', 3: 'normal', 4: 'low'}


def fetch_all_tasks(cfg, list_id, query):
    """Paginate until a short/empty page (ClickUp has no last-page marker;
    newer responses do include a 'last_page' bool — honor it when present)."""
    tasks, page = [], 0
    while True:
        status, resp = cu.api('GET', f'/api/v2/list/{list_id}/task', cfg,
                              query={**query, 'page': page})
        if not (200 <= status < 300) or not isinstance(resp, dict):
            return status, resp, tasks
        batch = resp.get('tasks', [])
        tasks.extend(batch)
        if resp.get('last_page') is True or len(batch) < 100:
            return status, resp, tasks
        page += 1


def main():
    cfg = cu.get_config()

    parser = argparse.ArgumentParser(
        description='List ClickUp tasks with status + assignees and per-assignee counts.',
        epilog=('Examples:\n'
                '  clickup_list_tasks.py\n'
                '  clickup_list_tasks.py --assignee-name "Jane Doe" --status "in progress"\n'
                '  clickup_list_tasks.py --include-closed --format json\n\n'
                'By default closed tasks are excluded.'),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--list-id', default=cfg['list_id'],
                        help=f"List id (default from ~/.agents/.config: {cfg['list_id']})")
    parser.add_argument('--assignee-name', action='append',
                        help='Filter by username/email (repeatable, resolved to ids)')
    parser.add_argument('--status', action='append',
                        help='Filter by status name (repeatable)')
    parser.add_argument('--include-closed', action='store_true',
                        help='Include tasks in closed statuses')
    parser.add_argument('--subtasks', action='store_true',
                        help='Include subtasks in results')
    parser.add_argument('--format', choices=('json', 'text'), default='text')
    args = parser.parse_args()

    cu.require_token(cfg)
    if not args.list_id:
        cu.fail_usage('No list id — pass --list-id or run clickup_resolve_ids.py --write')

    query = {}
    if args.include_closed:
        query['include_closed'] = 'true'
    if args.subtasks:
        query['subtasks'] = 'true'
    if args.status:
        query['statuses[]'] = args.status
    if args.assignee_name:
        ids = cu.resolve_assignees_or_die(args.assignee_name, cfg)
        query['assignees[]'] = ids

    status, resp, tasks = fetch_all_tasks(cfg, args.list_id, query)
    if not (200 <= status < 300):
        print(json.dumps({'ok': False, 'status': status, 'response': resp}))
        sys.exit(1)

    rows = []
    for t in tasks:
        prio = t.get('priority') or {}
        due_ms = t.get('due_date')
        rows.append({
            'id': t.get('id'),
            'name': t.get('name', ''),
            'status': (t.get('status') or {}).get('status', ''),
            'status_type': (t.get('status') or {}).get('type', ''),
            'priority': prio.get('priority') if isinstance(prio, dict) else None,
            'assignees': [a.get('username') or a.get('email') or str(a.get('id'))
                          for a in (t.get('assignees') or [])] or ['Unassigned'],
            'due_date': (None if not due_ms else
                         datetime.fromtimestamp(int(due_ms) / 1000)
                         .strftime('%Y-%m-%d')),
            'url': t.get('url'),
        })

    if args.format == 'json':
        print(json.dumps({'ok': True, 'list_id': args.list_id,
                          'scope': 'all' if args.include_closed else 'open',
                          'count': len(rows), 'tasks': rows}, indent=2))
        return

    scope = 'all' if args.include_closed else 'open'
    name = cfg.get('list_name') or args.list_id
    print(f'List: {name} — {len(rows)} {scope} tasks\n')

    by_assignee, by_status = {}, {}
    for r in rows:
        by_status[r['status'] or 'unknown'] = by_status.get(r['status'] or 'unknown', 0) + 1
        for a in r['assignees']:
            by_assignee[a] = by_assignee.get(a, 0) + 1
    if by_assignee:
        print('By assignee (workload):')
        for n, c in sorted(by_assignee.items(), key=lambda kv: (-kv[1], kv[0].lower())):
            print(f'  {c:>3}  {n}')
        print()
    if by_status:
        print('By status:')
        for s, c in sorted(by_status.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f'  {c:>3}  {s}')
        print()

    current = None
    for r in sorted(rows, key=lambda r: (r['assignees'][0].lower(), r['name'].lower())):
        head = r['assignees'][0]
        if head != current:
            current = head
            print(f'=== {head} ===')
        extra = []
        if r['priority']:
            extra.append(f"prio:{r['priority']}")
        if r['due_date']:
            extra.append(f"due:{r['due_date']}")
        suffix = f"  ({', '.join(extra)})" if extra else ''
        print(f"  [{r['id']}] {r['status']}: {r['name']}{suffix}")


if __name__ == '__main__':
    main()
