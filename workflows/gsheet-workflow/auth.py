#!/usr/bin/env python3
"""Verify Google Sheets authentication for gsheet-workflow.

Exit codes:
  0  success
  1  auth error
  2  verification incomplete
"""

from __future__ import annotations

import argparse

from scripts.utils.auth_helper import (
    get_credentials,
    normalize_account_alias,
    resolve_client_secrets_file,
    resolve_token_file,
    verify_authentication_detailed,
)



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Google Sheets authentication for the gsheet-workflow.",
    )
    parser.add_argument(
        "--account",
        help="Account alias to select a non-default OAuth token (for example: work or personal)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open a browser; print the authorization URL and wait for manual completion",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        help="Optional timeout for the local OAuth callback server",
    )
    args = parser.parse_args(argv)

    print("Testing Google Sheets Authentication\n")

    try:
        normalized_account = normalize_account_alias(args.account)
        token_path = resolve_token_file(account=normalized_account)
        client_secret_path = resolve_client_secrets_file(account=normalized_account)
        print(f"Using token file: {token_path}")
        print(f"Using client secret: {client_secret_path}")

        creds = get_credentials(
            account=normalized_account,
            open_browser=not args.no_browser,
            timeout_seconds=args.timeout_seconds,
        )
        print("\n✓ OAuth credentials are available.")
        print(f"  Token file: {token_path}")

        verification = verify_authentication_detailed(
            credentials=creds,
            account=normalized_account,
        )
        if verification.ok:
            print("\n✓ SUCCESS: Authentication is working correctly!")
            print(f"  Authenticated as: {verification.user_email}")
            print("\nYou can now use the gsheet-workflow with this account alias.")
            return 0

        print("\n⚠ OAuth credentials were created, but verification is incomplete.")
        print(f"  {verification.message}")
        if verification.remediation_url:
            print(f"  More info: {verification.remediation_url}")
        print(
            "  You usually do not need to log in again. Fix the Google Cloud/API issue above and rerun this helper."
        )
        return 2

    except Exception as exc:
        print(f"\n✗ ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
