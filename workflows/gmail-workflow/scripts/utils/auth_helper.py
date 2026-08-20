"""Workflow-local Google auth wrapper used by gmail-workflow scripts."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

SCRIPT_PATH = Path(__file__).resolve()
WORKFLOW_ROOT = SCRIPT_PATH.parents[2]
if str(WORKFLOW_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_ROOT))

from google_auth_core import GoogleAuthHelper
from google_auth_profiles import GMAIL_PROFILE, resolve_workflow_credential_root


HELPER = GoogleAuthHelper(
    profile=GMAIL_PROFILE,
    credential_root=resolve_workflow_credential_root(SCRIPT_PATH),
    logger_name=__name__,
)

get_all_scopes = HELPER.get_all_scopes
normalize_account_alias = HELPER.normalize_account_alias
resolve_token_file = HELPER.resolve_token_file
resolve_client_secrets_file = HELPER.resolve_client_secrets_file
get_credentials_oauth = HELPER.get_credentials_oauth
get_credentials_service_account = HELPER.get_credentials_service_account
get_credentials = HELPER.get_credentials
build_service = HELPER.build_service
verify_authentication_detailed = HELPER.verify_authentication_detailed
verify_authentication = HELPER.verify_authentication
get_authenticated_user_email = HELPER.get_authenticated_user_email
revoke_credentials = HELPER.revoke_credentials



def build_gmail_service(credentials=None, account: Optional[str] = None):
    return HELPER.build_service('gmail', 'v1', credentials, account=account)
