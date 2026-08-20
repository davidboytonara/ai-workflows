#!/usr/bin/env python3
"""Shared venv bootstrap + CLI proxy for the NotebookLM scripts.

Uses the shared Casper venv at `$HOME/.agents/.venv` and forwards argv to
`notebooklm.notebooklm_cli`. Login is out-of-band (see
`.agents/workflows/notebooklm-workflow/README.md` Auth section); this module never launches a browser.

Exit codes:
  0  success
  1  business-logic failure (propagated from notebooklm CLI)
  2  usage / arg error (propagated from notebooklm CLI)
  3  environment / venv issue (bootstrap failure, missing python3)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VENV_DIR = Path.home() / ".agents" / ".venv"
REQUIREMENTS = SCRIPT_DIR / "requirements.txt"
VENV_PY = VENV_DIR / "bin" / "python"
STORAGE_STATE = Path.home() / ".notebooklm" / "storage_state.json"


def _venv_ready() -> bool:
    if not VENV_PY.exists():
        return False
    probe = subprocess.run(
        [str(VENV_PY), "-c", "import notebooklm.notebooklm_cli"],
        capture_output=True,
    )
    return probe.returncode == 0


def bootstrap(force: bool = False) -> None:
    if not force and _venv_ready():
        return
    try:
        if not VENV_PY.exists():
            VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["python3", "-m", "venv", str(VENV_DIR)], check=True)
        subprocess.run(
            [str(VENV_PY), "-m", "pip", "install", "-q", "-r", str(REQUIREMENTS)],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"venv bootstrap failed: {exc}", file=sys.stderr)
        sys.exit(3)
    except Exception as exc:
        print(f"venv bootstrap failed: {exc}", file=sys.stderr)
        sys.exit(3)


def require_auth() -> None:
    """Fail fast with a clear message if the cookie store is missing."""
    if not STORAGE_STATE.exists():
        print(
            "NotebookLM auth missing. Run the manual login flow documented in "
            "./.agents/workflows/notebooklm-workflow/README.md (Auth section; shared Casper venv + "
            "`notebooklm login`). Cookies are expected at "
            f"{STORAGE_STATE}.",
            file=sys.stderr,
        )
        sys.exit(1)


def run_cli(args: list[str], *, check_auth: bool = True) -> int:
    """Forward args to `python -m notebooklm.notebooklm_cli`."""
    bootstrap()
    wants_help = any(a in {"-h", "--help"} for a in args)
    if check_auth and not wants_help:
        require_auth()
    env = os.environ.copy()
    env.setdefault("NOTEBOOKLM_STORAGE", str(STORAGE_STATE))
    cmd = [str(VENV_PY), "-m", "notebooklm.notebooklm_cli", *args]
    return subprocess.call(cmd, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="NotebookLM scripts environment helper."
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Create or refresh the shared Casper venv and exit.",
    )
    parser.add_argument(
        "--paths",
        action="store_true",
        help="Print resolved paths and exit.",
    )
    args = parser.parse_args()
    if args.paths:
        print(f"script_dir={SCRIPT_DIR}")
        print(f"venv_dir={VENV_DIR}")
        print(f"venv_python={VENV_PY}")
        print(f"requirements={REQUIREMENTS}")
        print(f"storage_state={STORAGE_STATE}")
        return 0
    if args.bootstrap:
        bootstrap(force=True)
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
