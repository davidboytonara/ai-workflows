#!/usr/bin/env python3
"""Shared helpers for the ClickUp workflow scripts.

Conventions:
- stdlib only (argparse, urllib, json).
- Secret CLICKUP_API_TOKEN lives in ~/.agents/.env; non-secret pinned IDs
  live in ~/.agents/.config. Both are loaded by _shared/agents_config.py.
- Every script prints one JSON object {'ok', 'status', 'response'} and
  exits 0 on 2xx, 1 on API/network error, 2 on local usage error.
"""
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

# Locate the shared config loader. The workflows are flat directories with no
# package layout, so walk up to workflows/_shared/ and put it on sys.path.
_d = os.path.dirname(os.path.abspath(__file__))
while _d != os.path.dirname(_d):
    if os.path.isfile(os.path.join(_d, '_shared', 'agents_config.py')):
        sys.path.insert(0, os.path.join(_d, '_shared'))
        break
    _d = os.path.dirname(_d)
import agents_config  # noqa: E402  (importing loads ~/.agents/.env and .config)

DEFAULT_BASE_URL = 'https://api.clickup.com'
DEFAULT_USER_AGENT = 'casper-clickup/1.0'

DEFAULT_SPACE_NAME = ''
DEFAULT_PROJECT_NAME = ''

# ClickUp priority is a fixed 1-4 scale (not customizable). Common synonyms
# are accepted too (medium -> normal).
PRIORITY_WORDS = {
    'urgent': 1, '1': 1,
    'high': 2, '2': 2,
    'normal': 3, 'medium': 3, '3': 3,
    'low': 4, '4': 4,
}

def script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def env_file_path():
    """File that --write persists resolved IDs into (~/.agents/.config)."""
    return str(agents_config.config_path())


def get_config():
    """Merged config. agents_config has already layered ~/.agents/.config then
    ~/.agents/.env into os.environ without clobbering real environment
    variables, so reading os.environ preserves the documented precedence:
    environment > .env > .config."""

    def pick(key, default=None):
        return os.environ.get(key) or default

    return {
        'base_url': (pick('CLICKUP_BASE_URL', DEFAULT_BASE_URL)).rstrip('/'),
        'token': pick('CLICKUP_API_TOKEN'),
        'team_id': pick('CLICKUP_TEAM_ID'),
        'space_id': pick('CLICKUP_SPACE_ID'),
        'folder_id': pick('CLICKUP_FOLDER_ID'),
        'list_id': pick('CLICKUP_LIST_ID'),
        'list_name': pick('CLICKUP_LIST_NAME', DEFAULT_PROJECT_NAME),
        'epic_model': pick('CLICKUP_EPIC_MODEL'),
        'epic_field_id': pick('CLICKUP_EPIC_FIELD_ID'),
        'epic_field_name': pick('CLICKUP_EPIC_FIELD_NAME'),
    }


def fail_usage(message, **extra):
    print(json.dumps({'ok': False, 'error': message, **extra}))
    sys.exit(2)


def require_token(cfg):
    if not cfg['token']:
        fail_usage('Missing CLICKUP_API_TOKEN in environment or ~/.agents/.env '
                   '(add: CLICKUP_API_TOKEN=pk_...). See .env.example.')
    return cfg['token']


def parse_json_or_raw(body):
    if not body:
        return {}
    try:
        return json.loads(body)
    except Exception:
        return {'raw': body[:500]}


def make_request(method, url, token, payload=None, raw_body=None,
                 content_type=None):
    """One HTTP request. Personal tokens go bare in Authorization (no Bearer).

    Returns (status, parsed_body, headers). status 0 = network failure.
    """
    headers = {
        'Accept': 'application/json',
        'User-Agent': DEFAULT_USER_AGENT,
        'Authorization': token,
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    elif raw_body is not None:
        data = raw_body
        if content_type:
            headers['Content-Type'] = content_type
    req = urllib.request.Request(url=url, method=method, headers=headers,
                                 data=data)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode('utf-8')
            return resp.getcode(), parse_json_or_raw(body), dict(resp.headers)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8') if e.fp else ''
        return e.code, parse_json_or_raw(err_body), dict(e.headers or {})
    except urllib.error.URLError as e:
        return 0, {'error': str(e)}, {}


def api(method, path, cfg, payload=None, query=None):
    """Request against the ClickUp API; path like '/api/v2/team'."""
    url = cfg['base_url'] + path
    if query:
        # urlencode with doseq so repeatable params (statuses[]) serialize
        url += '?' + urllib.parse.urlencode(query, doseq=True)
    status, resp, headers = make_request(method, url, cfg['token'], payload)
    if status == 429:
        reset = headers.get('X-RateLimit-Reset') or headers.get('x-ratelimit-reset')
        if reset:
            try:
                resp['retry_after_s'] = max(0, int(float(reset)) - int(time.time()))
            except Exception:
                pass
    return status, resp


def finish(status, resp, extra=None):
    """Standard output + exit for write-style scripts."""
    ok = 200 <= status < 300
    out = {'ok': ok, 'status': status, 'response': resp}
    if extra:
        out.update(extra)
    print(json.dumps(out))
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------- hierarchy

def get_workspaces(cfg):
    status, resp = api('GET', '/api/v2/team', cfg)
    teams = resp.get('teams', []) if isinstance(resp, dict) else []
    return status, teams


def get_spaces(cfg, team_id):
    status, resp = api('GET', f'/api/v2/team/{team_id}/space', cfg,
                       query={'archived': 'false'})
    return status, resp.get('spaces', []) if isinstance(resp, dict) else []


def get_folders(cfg, space_id):
    status, resp = api('GET', f'/api/v2/space/{space_id}/folder', cfg,
                       query={'archived': 'false'})
    return status, resp.get('folders', []) if isinstance(resp, dict) else []


def get_folderless_lists(cfg, space_id):
    status, resp = api('GET', f'/api/v2/space/{space_id}/list', cfg,
                       query={'archived': 'false'})
    return status, resp.get('lists', []) if isinstance(resp, dict) else []


def get_lists_in_folder(cfg, folder_id):
    status, resp = api('GET', f'/api/v2/folder/{folder_id}/list', cfg,
                       query={'archived': 'false'})
    return status, resp.get('lists', []) if isinstance(resp, dict) else []


def get_list(cfg, list_id):
    return api('GET', f'/api/v2/list/{list_id}', cfg)


def get_list_fields(cfg, list_id):
    status, resp = api('GET', f'/api/v2/list/{list_id}/field', cfg)
    return status, resp.get('fields', []) if isinstance(resp, dict) else []


# ------------------------------------------------------------------ members

def get_team_roster(cfg, team_id=None):
    """Workspace-wide roster: [{'id': int, 'username': str, 'email': str}].

    Uses GET /team (not /list/{id}/member, which misses members whose access
    is inherited from the Space/Folder).
    """
    status, teams = get_workspaces(cfg)
    if not (200 <= status < 300):
        return status, []
    roster = []
    for team in teams:
        if team_id and str(team.get('id')) != str(team_id):
            continue
        for m in team.get('members', []):
            u = m.get('user') or {}
            if u.get('id'):
                roster.append({
                    'id': u['id'],
                    'username': u.get('username') or '',
                    'email': u.get('email') or '',
                })
    return status, roster


def get_list_members(cfg, list_id):
    """Roster fallback: guest tokens see an empty workspace roster, but the
    list-member endpoint still returns everyone with access to the list."""
    status, resp = api('GET', f'/api/v2/list/{list_id}/member', cfg)
    members = resp.get('members', []) if isinstance(resp, dict) else []
    roster = [{'id': m['id'], 'username': m.get('username') or '',
               'email': m.get('email') or ''}
              for m in members if m.get('id')]
    return status, roster


def resolve_member_ids(names, roster):
    """Case-insensitive match on username or email. Returns (ids, not_found)."""
    ids, not_found = [], []
    for want in names:
        wl = want.lower().strip()
        hits = [r['id'] for r in roster
                if wl in (r['username'].lower(), r['email'].lower())]
        if hits:
            ids.extend(hits)
        else:
            not_found.append(want)
    return ids, not_found


def resolve_assignees_or_die(names, cfg):
    """Resolve --assignee-name values; on failure exit 2 listing the roster."""
    if not names:
        return []
    status, roster = get_team_roster(cfg, cfg.get('team_id'))
    if not roster and cfg.get('list_id'):
        status, roster = get_list_members(cfg, cfg['list_id'])
    if not (200 <= status < 300):
        fail_usage(f'Failed to fetch workspace members (HTTP {status})')
    ids, not_found = resolve_member_ids(names, roster)
    if not_found:
        fail_usage(
            f"Could not resolve assignee names: {', '.join(not_found)}",
            valid_members=[f"{r['username']} <{r['email']}>" for r in roster])
    return ids


# ----------------------------------------------------------------- statuses

def get_status_names(cfg, list_id):
    status, resp = get_list(cfg, list_id)
    if not (200 <= status < 300) or not isinstance(resp, dict):
        return status, []
    return status, [s.get('status') for s in resp.get('statuses', [])
                    if s.get('status')]


def validate_status_or_die(wanted, cfg, list_id):
    """Return the canonical status name (list-scoped, matched case-insensitively)."""
    status, names = get_status_names(cfg, list_id)
    if not names:
        fail_usage(f'Could not fetch statuses for list {list_id} (HTTP {status})')
    for name in names:
        if name.lower() == wanted.lower().strip():
            return name
    fail_usage(f"Unknown status '{wanted}' for this list", valid_statuses=names)


# ---------------------------------------------------------- field coercions

def priority_to_int(word):
    """Map a priority word to ClickUp's 1-4 (or None for 'none' = clear)."""
    w = str(word).lower().strip()
    if w in ('none', 'null', 'clear'):
        return None
    if w in PRIORITY_WORDS:
        return PRIORITY_WORDS[w]
    fail_usage(f"Unknown priority '{word}'",
               valid_priorities=['urgent', 'high', 'normal|medium', 'low', 'none'])


def to_unix_ms(date_str):
    """YYYY-MM-DD -> epoch ms at local NOON.

    ClickUp stores date-only due dates at 4 am in the setter's timezone;
    converting at midnight can render as the previous day for other viewers.
    """
    try:
        dt = datetime.strptime(date_str.strip(), '%Y-%m-%d').replace(hour=12)
    except ValueError:
        fail_usage(f"Invalid date '{date_str}' (expected YYYY-MM-DD)")
    return int(dt.timestamp() * 1000)


# --------------------------------------------------------------------- epic

def find_epic_field(fields):
    """Pick the custom field that models epics: name contains 'epic'."""
    for f in fields:
        if 'epic' in str(f.get('name', '')).lower():
            return f
    return None


def epic_custom_field_value(field, epic_value):
    """Coerce --epic input to the field's expected value shape."""
    ftype = field.get('type')
    options = (field.get('type_config') or {}).get('options') or []
    if ftype in ('drop_down', 'labels'):
        wl = str(epic_value).lower().strip()
        for opt in options:
            label = str(opt.get('name') or opt.get('label') or '').strip()
            if label.lower() == wl:
                return [opt['id']] if ftype == 'labels' else opt['id']
        fail_usage(
            f"Unknown epic option '{epic_value}' for field '{field.get('name')}'",
            valid_options=[opt.get('name') or opt.get('label') for opt in options])
    if ftype == 'list_relationship':
        return {'add': [epic_value]}  # epic_value is a task id
    return epic_value  # short_text and friends: pass through


def set_custom_field(cfg, task_id, field_id, value):
    return api('POST', f'/api/v2/task/{task_id}/field/{field_id}', cfg,
               payload={'value': value})


def resolve_epic_or_die(epic_value, cfg):
    """Return ('parent', task_id) or ('custom_field', field_id, value).

    Requires CLICKUP_EPIC_MODEL to be pinned by clickup_resolve_ids.py.
    """
    model = cfg.get('epic_model')
    if model == 'parent':
        return ('parent', epic_value)
    if model == 'custom_field':
        field_id = cfg.get('epic_field_id')
        if not field_id:
            fail_usage('CLICKUP_EPIC_MODEL=custom_field but CLICKUP_EPIC_FIELD_ID '
                       'is unset — re-run clickup_resolve_ids.py --write')
        status, fields = get_list_fields(cfg, cfg['list_id'])
        field = next((f for f in fields if str(f.get('id')) == str(field_id)), None)
        if field is None:
            fail_usage(f'Pinned epic field {field_id} not found on list '
                       f"{cfg['list_id']} (HTTP {status})")
        return ('custom_field', field_id, epic_custom_field_value(field, epic_value))
    fail_usage('Epic model not configured — run clickup_resolve_ids.py --write '
               'first (sets CLICKUP_EPIC_MODEL in ~/.agents/.config)')


# --------------------------------------------------------------- attachment

def encode_multipart(file_path, field_name, extra_fields=None):
    """Hand-built multipart/form-data body (stdlib has no encoder)."""
    boundary = '----CasperFormBoundary' + os.urandom(16).hex()
    filename = os.path.basename(file_path)
    with open(file_path, 'rb') as f:
        file_data = f.read()
    parts = []
    for key, value in (extra_fields or {}).items():
        parts.append(f'--{boundary}'.encode())
        parts.append(f'Content-Disposition: form-data; name="{key}"'.encode())
        parts.append(b'')
        parts.append(str(value).encode())
    parts.append(f'--{boundary}'.encode())
    parts.append(('Content-Disposition: form-data; '
                  f'name="{field_name}"; filename="{filename}"').encode())
    guessed, _ = mimetypes.guess_type(file_path)
    parts.append(f'Content-Type: {guessed or "application/octet-stream"}'.encode())
    parts.append(b'')
    parts.append(file_data)
    parts.append(f'--{boundary}--'.encode())
    return f'multipart/form-data; boundary={boundary}', b'\r\n'.join(parts)
