from __future__ import annotations

import json
import logging
import os
import re
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


# Patch importlib.metadata on older Python builds before importing Google libs.
try:  # pragma: no cover
    import importlib.metadata as _importlib_metadata  # type: ignore
except ImportError:  # pragma: no cover
    import importlib_metadata as _importlib_metadata  # type: ignore

if not hasattr(_importlib_metadata, 'packages_distributions'):
    try:  # pragma: no cover
        import importlib_metadata as _importlib_metadata_backport  # type: ignore
        if hasattr(_importlib_metadata_backport, 'packages_distributions'):
            _importlib_metadata.packages_distributions = _importlib_metadata_backport.packages_distributions  # type: ignore[attr-defined]
    except ImportError:  # pragma: no cover
        def _empty_packages_distributions():  # type: ignore
            return {}
        _importlib_metadata.packages_distributions = _empty_packages_distributions  # type: ignore[attr-defined]

warnings.filterwarnings('ignore', message='.*importlib.metadata.*')
warnings.filterwarnings('ignore', category=FutureWarning, module='google.api_core')
warnings.filterwarnings('ignore', message='.*urllib3.*OpenSSL.*')

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# google_auth_oauthlib.flow.InstalledAppFlow is lazy-imported inside
# get_credentials_oauth (first-time OAuth path only) — saves ~16ms on the
# cached-token hot path that runs 99% of the time.

from google_auth_profiles import GoogleAuthProfile, GoogleNamedAccountProfile


DEFAULT_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
URL_PATTERN = re.compile(r"https://[^\s\]>)\"']+")


@dataclass
class VerificationResult:
    ok: bool
    message: str
    user_email: Optional[str] = None
    remediation_url: Optional[str] = None


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logger.level)
    handler.setFormatter(logging.Formatter(DEFAULT_FORMAT, datefmt=DATE_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


class GoogleAuthHelper:
    def __init__(
        self,
        *,
        profile: GoogleAuthProfile,
        credential_root: str | Path,
        logger_name: str,
    ) -> None:
        self.profile = profile
        self.credential_root = Path(credential_root).resolve()
        self.logger = setup_logger(logger_name)

    def get_all_scopes(self) -> List[str]:
        return list(self.profile.scopes.values())

    def get_named_account_profile(
        self,
        account: Optional[str],
    ) -> Optional[GoogleNamedAccountProfile]:
        alias = self.normalize_account_alias(account)
        if alias is None:
            return None
        return self.profile.named_accounts.get(alias)

    def get_expected_email(self, account: Optional[str]) -> Optional[str]:
        named_account = self.get_named_account_profile(account)
        if named_account is None:
            return None
        return named_account.expected_email

    def get_login_hint(self, account: Optional[str]) -> Optional[str]:
        named_account = self.get_named_account_profile(account)
        if named_account is None:
            return None
        return named_account.login_hint or named_account.expected_email

    def normalize_account_alias(self, account: Optional[str]) -> Optional[str]:
        if account is None:
            return None

        normalized = account.strip().lower()
        if not normalized:
            raise ValueError('Account alias cannot be empty')

        if not re.fullmatch(r'[a-z0-9._-]+', normalized):
            raise ValueError(
                "Invalid account alias. Use only letters, numbers, '.', '_', or '-'"
            )

        named_account = self.profile.named_accounts.get(normalized)
        if named_account is not None:
            return named_account.canonical_alias

        return normalized

    def resolve_token_file(
        self,
        account: Optional[str] = None,
        token_file: Optional[str] = None,
    ) -> str:
        if token_file is not None:
            return token_file

        alias = self.normalize_account_alias(account)
        if alias is None:
            return str(self.credential_root / 'token.json')

        return str(self.credential_root / f'token.{alias}.json')

    def resolve_client_secrets_file(
        self,
        client_secrets_file: Optional[str] = None,
        account: Optional[str] = None,
    ) -> str:
        if client_secrets_file is not None:
            return client_secrets_file

        alias = self.normalize_account_alias(account)
        if alias is not None:
            account_specific = self.credential_root / f'client_secret.{alias}.json'
            if account_specific.exists():
                return str(account_specific)

        return str(self.credential_root / 'client_secret.json')

    @staticmethod
    def build_terminal_hyperlink(url: str, label: str) -> str:
        return f'\033]8;;{url}\a{label}\033]8;;\a'

    def build_oauth_prompt_message(self) -> str:
        clickable_link = self.build_terminal_hyperlink('{url}', 'Open Google authorization page')
        return (
            'Open the Google authorization page in your browser:\n'
            f'{clickable_link}\n'
            'Raw URL (copy/paste fallback):\n'
            '{url}'
        )

    def find_help_url(self, value: Any) -> Optional[str]:
        if isinstance(value, str):
            match = URL_PATTERN.search(value)
            return match.group(0) if match else None

        if isinstance(value, dict):
            for key in ('extendedHelp', 'help', 'url', 'documentationLink'):
                url = self.find_help_url(value.get(key))
                if url:
                    return url
            for nested_value in value.values():
                url = self.find_help_url(nested_value)
                if url:
                    return url
            return None

        if isinstance(value, list):
            for item in value:
                url = self.find_help_url(item)
                if url:
                    return url

        return None

    def load_client_config(self, client_secrets_file: str) -> Dict[str, Any]:
        try:
            with open(client_secrets_file, 'r', encoding='utf-8') as handle:
                client_config = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f'OAuth client configuration is not valid JSON: {client_secrets_file}'
            ) from exc

        if not isinstance(client_config, dict):
            raise ValueError(
                f'OAuth client configuration must be a JSON object: {client_secrets_file}'
            )

        return client_config

    def validate_client_config(
        self,
        client_config: Dict[str, Any],
        client_secrets_file: str,
    ) -> Dict[str, Any]:
        if 'installed' in client_config:
            oauth_config = client_config['installed']
            client_type = 'installed'
        elif 'web' in client_config:
            oauth_config = client_config['web']
            client_type = 'web'
        else:
            raise ValueError(
                "OAuth client configuration must contain either an 'installed' or 'web' section. "
                f'File: {client_secrets_file}'
            )

        if not isinstance(oauth_config, dict):
            raise ValueError(
                f'OAuth client configuration section must be an object: {client_secrets_file}'
            )

        required_keys = ('client_id', 'client_secret', 'auth_uri', 'token_uri')
        missing_keys = [key for key in required_keys if not oauth_config.get(key)]
        if missing_keys:
            missing_list = ', '.join(missing_keys)
            raise ValueError(
                f'OAuth client configuration is missing required fields ({missing_list}): '
                f'{client_secrets_file}'
            )

        if client_type == 'web':
            redirect_uris = oauth_config.get('redirect_uris') or []
            localhost_redirects = [
                uri for uri in redirect_uris
                if isinstance(uri, str)
                and (uri.startswith('http://localhost') or uri.startswith('http://127.0.0.1'))
            ]
            if not localhost_redirects:
                raise ValueError(
                    'OAuth client configuration uses a Web application client without a localhost redirect URI. '
                    'This helper starts a local callback server and usually works best with a Desktop app client. '
                    'Create a Desktop app OAuth client in Google Cloud Console or add an authorized localhost redirect URI, '
                    f'then replace: {client_secrets_file}'
                )
            self.logger.warning(
                'Using a Web application OAuth client for a local desktop auth flow. '
                'If Google rejects the redirect, create a Desktop app OAuth client instead.'
            )

        if client_type == 'installed':
            redirect_uris = oauth_config.get('redirect_uris') or []
            if not any(
                isinstance(uri, str) and uri.startswith('http://localhost')
                for uri in redirect_uris
            ):
                self.logger.warning(
                    'Installed OAuth client does not advertise a localhost redirect URI. '
                    'Google Desktop app clients normally include http://localhost. File: %s',
                    client_secrets_file,
                )

        return client_config

    def summarize_http_error(self, error: HttpError) -> VerificationResult:
        status_code = getattr(getattr(error, 'resp', None), 'status', None)
        reason = (getattr(error, 'reason', '') or str(error)).strip()
        error_details = getattr(error, 'error_details', None)
        remediation_url = self.find_help_url(error_details) or self.find_help_url(reason)
        details_text = json.dumps(error_details, ensure_ascii=False) if error_details else ''

        if status_code == 403 and (
            'accessNotConfigured' in details_text
            or 'has not been used in project' in reason
            or 'it is disabled' in reason
        ):
            api_name_match = re.search(r'([A-Za-z0-9 ]+ API) has not been used', reason)
            api_name = api_name_match.group(1) if api_name_match else 'the required Google API'
            message = (
                'OAuth credentials were created successfully, but verification could not call '
                f'{api_name}. This usually means the API is disabled in the Google Cloud '
                'project attached to this OAuth client.'
            )
            return VerificationResult(
                ok=False,
                message=message,
                remediation_url=remediation_url,
            )

        if status_code == 403 and 'insufficient authentication scopes' in reason.lower():
            return VerificationResult(
                ok=False,
                message=(
                    'OAuth credentials were created, but they do not include the scopes required '
                    'for this verification step. Delete the token and run the auth flow again if you '
                    'changed scopes or replaced the OAuth client.'
                ),
                remediation_url=remediation_url,
            )

        return VerificationResult(
            ok=False,
            message=f"API verification failed{f' (HTTP {status_code})' if status_code else ''}: {reason}",
            remediation_url=remediation_url,
        )

    def get_credentials_oauth(
        self,
        client_secrets_file: Optional[str] = None,
        token_file: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        account: Optional[str] = None,
        open_browser: bool = True,
        timeout_seconds: Optional[int] = None,
    ) -> Credentials:
        client_secrets_file = self.resolve_client_secrets_file(client_secrets_file, account=account)
        token_file = self.resolve_token_file(account=account, token_file=token_file)

        if scopes is None:
            scopes = self.get_all_scopes()

        creds = None
        token_exists = os.path.exists(token_file)
        client_secrets_exists = os.path.exists(client_secrets_file)

        if token_exists:
            try:
                creds = Credentials.from_authorized_user_file(token_file, scopes)
                self.logger.debug(f'Loaded credentials from {token_file}')
            except Exception as exc:
                self.logger.warning(f'Failed to load credentials from {token_file}: {exc}')
                creds = None

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            try:
                self.logger.info('Refreshing expired credentials...')
                creds.refresh(Request())
                self.logger.info('Credentials refreshed successfully')
            except Exception as exc:
                self.logger.warning(f'Failed to refresh credentials from {token_file}: {exc}')
                if not client_secrets_exists:
                    raise FileNotFoundError(
                        'Stored OAuth credentials could not be refreshed and interactive re-authentication '
                        'requires a shared client secret file in the google-auth credential home, '
                        f'which was not found at: {client_secrets_file}'
                    ) from exc
                creds = None

        if creds and creds.valid:
            self._write_token_file(token_file, creds)
            return creds

        if not client_secrets_exists:
            if token_exists:
                raise FileNotFoundError(
                    'Stored OAuth credentials were found but are unusable, and interactive re-authentication '
                    'requires a shared client secret file in the google-auth credential home, '
                    f'which was not found at: {client_secrets_file}'
                )
            raise FileNotFoundError(
                'OAuth credentials not found. To authenticate for the first time, add client_secret.json '
                f'to the shared google-auth credential home at: {client_secrets_file}'
            )

        client_config = self.validate_client_config(
            self.load_client_config(client_secrets_file),
            client_secrets_file,
        )

        self.logger.info('Starting OAuth flow...')
        from google_auth_oauthlib.flow import InstalledAppFlow  # lazy: first-time OAuth only
        flow = InstalledAppFlow.from_client_config(client_config, scopes)
        auth_kwargs: Dict[str, str] = {}
        login_hint = self.get_login_hint(account)
        if login_hint:
            auth_kwargs['login_hint'] = login_hint
            auth_kwargs['prompt'] = 'select_account consent'

        creds = flow.run_local_server(
            port=0,
            open_browser=open_browser,
            timeout_seconds=timeout_seconds,
            authorization_prompt_message=self.build_oauth_prompt_message(),
            **auth_kwargs,
        )
        self.logger.info('OAuth flow completed successfully')

        self._write_token_file(token_file, creds)
        return creds

    def _write_token_file(self, token_file: str, creds: Credentials) -> None:
        token_dir = os.path.dirname(token_file)
        if token_dir and not os.path.exists(token_dir):
            os.makedirs(token_dir)

        with open(token_file, 'w', encoding='utf-8') as token:
            token.write(creds.to_json())

        try:
            os.chmod(token_file, 0o600)
        except OSError:
            pass

        self.logger.info(f'Credentials saved to {token_file}')

    def get_credentials_service_account(
        self,
        service_account_file: str,
        scopes: Optional[List[str]] = None,
    ) -> service_account.Credentials:
        if not os.path.exists(service_account_file):
            raise FileNotFoundError(f'Service account file not found: {service_account_file}')

        if scopes is None:
            scopes = self.get_all_scopes()

        self.logger.debug(f'Loading service account credentials from {service_account_file}')
        creds = service_account.Credentials.from_service_account_file(
            service_account_file,
            scopes=scopes,
        )
        self.logger.info('Service account credentials loaded successfully')
        return creds

    def get_credentials(
        self,
        auth_method: Optional[str] = None,
        client_secrets_file: Optional[str] = None,
        service_account_file: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        token_file: Optional[str] = None,
        account: Optional[str] = None,
        open_browser: bool = True,
        timeout_seconds: Optional[int] = None,
    ) -> Credentials:
        if auth_method is None:
            oauth_file = self.resolve_client_secrets_file(client_secrets_file, account=account)
            resolved_token_file = self.resolve_token_file(account=account, token_file=token_file)

            if os.path.exists(resolved_token_file) or os.path.exists(oauth_file):
                auth_method = 'oauth'
                self.logger.info('Using OAuth 2.0 authentication')
            elif service_account_file and os.path.exists(service_account_file):
                auth_method = 'service_account'
                self.logger.info('Using Service Account authentication')
            else:
                raise ValueError(
                    'No authentication method configured. Provide an existing OAuth token file or '
                    'client_secret.json in the shared google-auth credential home for OAuth, or provide '
                    'service_account_file for Service Account authentication.'
                )

        if auth_method == 'oauth':
            return self.get_credentials_oauth(
                client_secrets_file=client_secrets_file,
                token_file=token_file,
                scopes=scopes,
                account=account,
                open_browser=open_browser,
                timeout_seconds=timeout_seconds,
            )
        if auth_method == 'service_account':
            if not service_account_file:
                raise ValueError('service_account_file parameter is required for Service Account authentication')
            return self.get_credentials_service_account(service_account_file, scopes=scopes)

        raise ValueError(f'Unknown authentication method: {auth_method}')

    def validate_account_email(
        self,
        account: Optional[str],
        user_email: Optional[str],
    ) -> Optional[VerificationResult]:
        expected_email = self.get_expected_email(account)
        if not expected_email or not user_email:
            return None

        if user_email.lower() == expected_email.lower():
            return None

        return VerificationResult(
            ok=False,
            message=(
                f"Account alias '{self.normalize_account_alias(account)}' is reserved for {expected_email}, "
                f'but Google authenticated as {user_email}. Re-run auth and choose the correct Google account.'
            ),
            user_email=user_email,
        )

    def build_service(
        self,
        service_name: str,
        version: str,
        credentials: Optional[Credentials] = None,
        account: Optional[str] = None,
    ):
        if credentials is None:
            credentials = self.get_credentials(account=account)

        self.logger.debug(f'Building {service_name} {version} service')
        service = build(service_name, version, credentials=credentials, cache_discovery=False)
        self.logger.info(f'✓ {service_name.capitalize()} API service ready')
        return service

    def verify_authentication_detailed(
        self,
        credentials: Optional[Credentials] = None,
        account: Optional[str] = None,
        open_browser: bool = True,
        timeout_seconds: Optional[int] = None,
    ) -> VerificationResult:
        self.logger.info('Verifying authentication...')

        try:
            if credentials is None:
                creds = self.get_credentials(
                    account=account,
                    open_browser=open_browser,
                    timeout_seconds=timeout_seconds,
                )
            else:
                creds = credentials
        except Exception as exc:
            message = f'Could not load OAuth credentials: {exc}'
            self.logger.error(f'✗ {message}')
            return VerificationResult(ok=False, message=message)

        try:
            if self.profile.verification_mode == 'gmail_profile':
                service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
                results = service.users().getProfile(userId='me').execute()
                user_email = results.get('emailAddress', 'Unknown')
            else:
                service = build('drive', 'v3', credentials=creds, cache_discovery=False)
                results = service.about().get(fields='user').execute()
                user_email = results.get('user', {}).get('emailAddress', 'Unknown')

            account_validation = self.validate_account_email(account, user_email)
            if account_validation is not None:
                self.logger.error(f'✗ {account_validation.message}')
                return account_validation

            self.logger.info(f'✓ Authentication successful! Logged in as: {user_email}')
            return VerificationResult(
                ok=True,
                message=f'Authentication successful. Logged in as: {user_email}',
                user_email=user_email,
            )
        except HttpError as exc:
            result = self.summarize_http_error(exc)
            self.logger.error(f'✗ {result.message}')
            if result.remediation_url:
                self.logger.error(f'Help: {result.remediation_url}')
            return result
        except Exception as exc:
            message = 'OAuth credentials were created, but API verification failed: ' f'{exc}'
            self.logger.error(f'✗ {message}')
            return VerificationResult(ok=False, message=message)

    def verify_authentication(
        self,
        credentials: Optional[Credentials] = None,
        account: Optional[str] = None,
        open_browser: bool = True,
        timeout_seconds: Optional[int] = None,
    ) -> bool:
        return self.verify_authentication_detailed(
            credentials=credentials,
            account=account,
            open_browser=open_browser,
            timeout_seconds=timeout_seconds,
        ).ok

    def get_authenticated_user_email(
        self,
        credentials: Optional[Credentials] = None,
        account: Optional[str] = None,
    ) -> str:
        if credentials is None:
            credentials = self.get_credentials(account=account)

        if self.profile.verification_mode == 'gmail_profile':
            service = build('gmail', 'v1', credentials=credentials, cache_discovery=False)
            results = service.users().getProfile(userId='me').execute()
            return results.get('emailAddress', 'Unknown')

        service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
        results = service.about().get(fields='user').execute()
        return results.get('user', {}).get('emailAddress', 'Unknown')

    def revoke_credentials(
        self,
        token_file: Optional[str] = None,
        account: Optional[str] = None,
    ) -> None:
        token_file = self.resolve_token_file(account=account, token_file=token_file)

        if os.path.exists(token_file):
            try:
                creds = Credentials.from_authorized_user_file(token_file)
                creds.revoke(Request())
                self.logger.info('Credentials revoked')
            except Exception as exc:
                self.logger.warning(f'Failed to revoke credentials: {exc}')

            os.remove(token_file)
            self.logger.info(f'Token file removed: {token_file}')
        else:
            self.logger.info('No token file found')
