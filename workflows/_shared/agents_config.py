"""Single source of configuration for every workflow.

Two files, both outside the repository, both gitignored:

    ~/.agents/.env      secrets      (template: .env.example)
    ~/.agents/.config   settings     (template: .config.example)

Precedence, highest first:

    1. a real environment variable
    2. ~/.agents/.env
    3. ~/.agents/.config

SIDE EFFECT ON IMPORT: importing this module loads both files into os.environ
once, filling in only names that are not already set. That is deliberate --
it means existing ``os.environ.get("GMAIL_QUIET_HOURS")`` call sites keep
working unchanged, and a workflow opts in with a single import.

FILE FORMAT is a strict KEY=VALUE subset:

    * comments only on their own line, starting with #
    * no ``export ``, no $VAR interpolation, no inline trailing comments
    * no multi-line values
    * matched surrounding quotes are stripped

The subset is mandatory, not stylistic: the heartbeat systemd unit reads
~/.agents/.env directly via EnvironmentFile=, and systemd understands only
this much. Anything richer would work in Python and silently break the daemon.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "agents_home",
    "config_path",
    "env_path",
    "google_credentials_dir",
    "load",
    "parse_file",
    "read_files",
]

ENV_FILENAME = ".env"
CONFIG_FILENAME = ".config"
CREDENTIALS_DIRNAME = "credentials"

_loaded = False


def agents_home() -> Path:
    """Directory holding .env and .config. $AGENTS_HOME overrides ~/.agents."""
    override = os.environ.get("AGENTS_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".agents"


def env_path() -> Path:
    return agents_home() / ENV_FILENAME


def config_path() -> Path:
    return agents_home() / CONFIG_FILENAME


def parse_file(path) -> dict[str, str]:
    """Parse one KEY=VALUE file. A missing or unreadable file yields {}."""
    values: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return values

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue  # not an assignment; ignore rather than guess
        key = key.strip()
        if not key.isidentifier():
            # Rejects `export FOO=bar` and any other non-identifier left-hand
            # side. Accepting it would invent a key named "export FOO" that no
            # one can read back, and systemd would reject the same line.
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def read_files() -> dict[str, str]:
    """Merge both files without touching os.environ. .env wins over .config."""
    merged = parse_file(config_path())
    merged.update(parse_file(env_path()))
    return merged


def load(*, force: bool = False) -> dict[str, str]:
    """Inject both files into os.environ. Existing variables are never clobbered.

    Returns the values that came from the files, whether or not each one was
    applied. Runs at most once unless ``force`` is set (used by tests).
    """
    global _loaded
    if _loaded and not force:
        return {}

    values = read_files()
    for key, value in values.items():
        os.environ.setdefault(key, value)
    _loaded = True
    return values


def google_credentials_dir() -> Path:
    """Shared directory for Google OAuth client secrets and token caches.

    These cannot be environment variables: the Google client library needs a
    real file and rewrites the token on refresh. Centralizing them means one
    directory shared by the gsheet, gdocs, gslides and gmail workflows.
    """
    configured = os.environ.get("GOOGLE_CREDENTIALS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return agents_home() / CREDENTIALS_DIRNAME


load()
