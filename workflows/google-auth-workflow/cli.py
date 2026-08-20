#!/usr/bin/env python3
"""Thin auth dispatcher for Google Docs, Sheets, and Slides workflows.

Routes auth requests to the existing per-workflow CLI entrypoints so each
workflow keeps its own environment bootstrap and auth behavior.

Exit codes:
  0  success
  1  child / business failure
  2  usage error
  3  environment / venv issue
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WORKFLOWS_DIR = SCRIPT_DIR.parent

TARGETS: dict[str, Path] = {
    "docs": WORKFLOWS_DIR / "gdocs-workflow" / "cli.py",
    "sheets": WORKFLOWS_DIR / "gsheet-workflow" / "cli.py",
    "slides": WORKFLOWS_DIR / "gslides-workflow" / "cli.py",
}


def build_parser() -> argparse.ArgumentParser:
    command_help = "\n".join(
        [
            "  docs       verify Google Docs auth via gdocs-workflow",
            "  sheets     verify Google Sheets auth via gsheet-workflow",
            "  slides     verify Google Slides auth via gslides-workflow",
        ]
    )
    parser = argparse.ArgumentParser(
        description="Google auth workflow CLI dispatcher.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Targets:\n"
            f"{command_help}\n\n"
            "Examples:\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/google-auth-workflow/cli.py docs --account work --no-browser\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/google-auth-workflow/cli.py sheets --account personal\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/google-auth-workflow/cli.py slides --account work --timeout-seconds 120\n"
        ),
    )
    parser.add_argument("target", nargs="?", choices=sorted(TARGETS))
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments passed through to target workflow auth command",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_args = list(sys.argv[1:] if argv is None else argv)

    if not raw_args or raw_args[0] in {"-h", "--help"}:
        parser.print_help()
        return 0

    target = raw_args[0]
    if target not in TARGETS:
        parser.error(f"invalid choice: {target!r} (choose from {', '.join(sorted(TARGETS))})")

    target_script = TARGETS[target]
    if not target_script.exists():
        print(f"Missing target workflow CLI: {target_script}", file=sys.stderr)
        return 2

    return subprocess.call([sys.executable, str(target_script), "auth", *raw_args[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
