#!/usr/bin/env python3
"""Shared Google Docs auth helpers for workflow scripts."""

from __future__ import annotations

from google_auth_core import GoogleAuthHelper
from google_auth_profiles import GOOGLE_DOCS_PROFILE, resolve_workflow_credential_root


def resolve_credential_root():
    return resolve_workflow_credential_root(__file__)



def build_helper() -> GoogleAuthHelper:
    return GoogleAuthHelper(
        profile=GOOGLE_DOCS_PROFILE,
        credential_root=resolve_credential_root(),
        logger_name="google_auth.google-docs",
    )



def normalize_account_alias(account: str | None) -> str | None:
    return build_helper().normalize_account_alias(account)



def resolve_token_file(account: str | None = None) -> str:
    helper = build_helper()
    return helper.resolve_token_file(account=helper.normalize_account_alias(account))



def resolve_client_secrets_file(account: str | None = None) -> str:
    helper = build_helper()
    return helper.resolve_client_secrets_file(account=helper.normalize_account_alias(account))



def get_credentials(
    *,
    account: str | None = None,
    open_browser: bool = True,
    timeout_seconds: int | None = None,
):
    helper = build_helper()
    normalized_account = helper.normalize_account_alias(account)
    return helper.get_credentials(
        account=normalized_account,
        open_browser=open_browser,
        timeout_seconds=timeout_seconds,
    )



def verify_authentication_detailed(
    *,
    credentials=None,
    account: str | None = None,
):
    helper = build_helper()
    normalized_account = helper.normalize_account_alias(account)
    return helper.verify_authentication_detailed(
        credentials=credentials,
        account=normalized_account,
    )



def build_docs_service(credentials=None, account: str | None = None):
    helper = build_helper()
    return helper.build_service("docs", "v1", credentials, account=account)



def build_drive_service(credentials=None, account: str | None = None):
    helper = build_helper()
    return helper.build_service("drive", "v3", credentials, account=account)
