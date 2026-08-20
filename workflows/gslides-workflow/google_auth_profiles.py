from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Literal

# Shared config loader (workflows/_shared/agents_config.py).
import os as _os, sys as _sys
_d = _os.path.dirname(_os.path.abspath(__file__))
while _d != _os.path.dirname(_d):
    if _os.path.isfile(_os.path.join(_d, '_shared', 'agents_config.py')):
        _sys.path.insert(0, _os.path.join(_d, '_shared'))
        break
    _d = _os.path.dirname(_d)
import agents_config as _agents_config  # noqa: E402



@dataclass(frozen=True)
class GoogleNamedAccountProfile:
    canonical_alias: str
    expected_email: str
    login_hint: str | None = None


@dataclass(frozen=True)
class GoogleAuthProfile:
    key: str
    display_name: str
    skill_dir_name: str
    cli_description: str
    success_skill_name: str
    scopes: Dict[str, str]
    verification_mode: Literal['drive_about', 'gmail_profile'] = 'drive_about'
    named_accounts: Dict[str, GoogleNamedAccountProfile] = field(default_factory=dict)


# Optional account aliases. Fill in `expected_email` to have the auth flow
# assert that the token really belongs to that account, and `login_hint` to
# pre-select it on the Google consent screen. Left blank on purpose: no real
# addresses are shipped in this repository.
NAMED_ACCOUNTS = {
    'work': GoogleNamedAccountProfile(
        canonical_alias='work',
        expected_email='',
        login_hint=None,
    ),
    'personal': GoogleNamedAccountProfile(
        canonical_alias='personal',
        expected_email='',
        login_hint=None,
    ),
}


GOOGLE_DOCS_PROFILE = GoogleAuthProfile(
    key='google-docs',
    display_name='Google Docs',
    skill_dir_name='gdocs-workflow',
    cli_description='Verify Google Docs authentication for the gdocs-workflow.',
    success_skill_name='gdocs-workflow',
    scopes={
        'docs': 'https://www.googleapis.com/auth/documents',
        'drive': 'https://www.googleapis.com/auth/drive',
        'drive_file': 'https://www.googleapis.com/auth/drive.file',
    },
    named_accounts=NAMED_ACCOUNTS,
)


GOOGLE_SHEETS_PROFILE = GoogleAuthProfile(
    key='google-sheets',
    display_name='Google Sheets',
    skill_dir_name='gsheet-workflow',
    cli_description='Verify Google Sheets authentication for the gsheet-workflow.',
    success_skill_name='gsheet-workflow',
    scopes={
        'sheets': 'https://www.googleapis.com/auth/spreadsheets',
        'drive': 'https://www.googleapis.com/auth/drive',
        'drive_file': 'https://www.googleapis.com/auth/drive.file',
    },
    named_accounts=NAMED_ACCOUNTS,
)


GOOGLE_SLIDES_PROFILE = GoogleAuthProfile(
    key='google-slides',
    display_name='Google Slides',
    skill_dir_name='gslides-workflow',
    cli_description='Verify Google Slides authentication for the gslides-workflow.',
    success_skill_name='gslides-workflow',
    scopes={
        'slides': 'https://www.googleapis.com/auth/presentations',
        'drive': 'https://www.googleapis.com/auth/drive',
        'drive_file': 'https://www.googleapis.com/auth/drive.file',
        'sheets': 'https://www.googleapis.com/auth/spreadsheets',
    },
    named_accounts=NAMED_ACCOUNTS,
)


GMAIL_PROFILE = GoogleAuthProfile(
    key='gmail',
    display_name='Gmail',
    skill_dir_name='gmail-workflow',
    cli_description='Verify Gmail authentication for the gmail-workflow.',
    success_skill_name='gmail-workflow',
    scopes={
        'gmail_readonly': 'https://www.googleapis.com/auth/gmail.readonly',
        'gmail_compose': 'https://www.googleapis.com/auth/gmail.compose',
    },
    verification_mode='gmail_profile',
    named_accounts=NAMED_ACCOUNTS,
)


PROFILES = {
    'docs': GOOGLE_DOCS_PROFILE,
    'google-docs': GOOGLE_DOCS_PROFILE,
    'sheets': GOOGLE_SHEETS_PROFILE,
    'google-sheets': GOOGLE_SHEETS_PROFILE,
    'slides': GOOGLE_SLIDES_PROFILE,
    'google-slides': GOOGLE_SLIDES_PROFILE,
    'gmail': GMAIL_PROFILE,
}


def get_profile(name: str) -> GoogleAuthProfile:
    normalized = name.strip().lower()
    if normalized not in PROFILES:
        raise KeyError(f'Unknown Google auth profile: {name}')
    return PROFILES[normalized]


def resolve_workflow_root(current_file: str | Path) -> Path:
    current_path = Path(current_file).resolve()
    search_start = current_path.parent if current_path.is_file() else current_path
    fallback: Path | None = None
    for candidate in (search_start, *search_start.parents):
        if not (candidate / 'google_auth_core.py').exists():
            continue
        if (candidate / 'credentials').is_dir():
            return candidate
        if fallback is None:
            fallback = candidate
    if fallback is not None:
        # `credentials/` holds secrets, is git-ignored and is never shipped:
        # it is created by you on first use. See CREDENTIALS.md in the
        # workflow root for what goes in it.
        return fallback
    raise ValueError(f'Could not resolve workflow root from: {current_file}')


def resolve_workflow_credential_root(current_file: str | Path) -> Path:
    """Shared directory holding the OAuth client secret and token cache.

    Centralized across the gsheet, gdocs, gslides and gmail workflows via
    GOOGLE_CREDENTIALS_DIR in ~/.agents/.env (default ~/.agents/credentials).
    These stay real files rather than environment variables because the Google
    client library rewrites the token on every refresh. See .env.example.

    `current_file` is retained for call-site compatibility and is unused.
    """
    return _agents_config.google_credentials_dir()
