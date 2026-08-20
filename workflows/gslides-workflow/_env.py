#!/usr/bin/env python3
"""Shared venv bootstrap + runner for Google Slides workflow scripts.

Uses the shared Casper venv at `$HOME/.agents/.venv` with Google API client deps
required by workflow-local auth and Google Slides scripts.

Exit codes:
  0  success
  3  environment / venv issue
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VENV_DIR = Path.home() / ".agents" / ".venv"
REQUIREMENTS = SCRIPT_DIR / "requirements.txt"
VENV_PY = VENV_DIR / "bin" / "python"
AUTH_SCRIPT = SCRIPT_DIR / "auth.py"
SLIDES_SCRIPT_DIR = SCRIPT_DIR / "scripts"
CREDENTIALS_DIR = SCRIPT_DIR / "credentials"


def _venv_ready() -> bool:
    if not VENV_PY.exists():
        return False
    probe = subprocess.run(
        [
            str(VENV_PY),
            "-c",
            "import googleapiclient.discovery, pptx",
        ],
        capture_output=True,
        text=True,
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
        print(f"gslides venv bootstrap failed: {exc}", file=sys.stderr)
        sys.exit(3)
    except Exception as exc:  # pragma: no cover
        print(f"gslides venv bootstrap failed: {exc}", file=sys.stderr)
        sys.exit(3)



def run_script(target: str | Path, args: list[str]) -> int:
    bootstrap()
    return subprocess.call([str(VENV_PY), str(Path(target)), *args])



def main() -> int:
    parser = argparse.ArgumentParser(
        description="Google Slides workflow environment helper.",
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
        print(f"auth_script={AUTH_SCRIPT}")
        print(f"slides_script_dir={SLIDES_SCRIPT_DIR}")
        print(f"credentials_dir={CREDENTIALS_DIR}")
        return 0

    if args.bootstrap:
        bootstrap(force=True)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
