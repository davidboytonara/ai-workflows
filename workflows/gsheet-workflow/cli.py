#!/usr/bin/env python3
"""Project-local CLI proxy for Google Sheets workflow operations.

Wraps workflow-local auth and Google Sheets scripts behind stable workflow
entrypoints and shared Casper venv bootstrap.

Exit codes:
  0  success
  1  child / business failure
  2  usage error
  3  environment / venv issue
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from _env import AUTH_SCRIPT, SHEETS_SCRIPT_DIR, run_script

SPREADSHEET_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")

COMMANDS: dict[str, dict[str, object]] = {
    "auth": {
        "script": AUTH_SCRIPT,
        "defaults": [],
        "help": "verify shared Google OAuth for Sheets",
    },
    "create": {
        "script": SHEETS_SCRIPT_DIR / "create_spreadsheet.py",
        "defaults": [],
        "help": "create spreadsheet",
    },
    "read": {
        "script": SHEETS_SCRIPT_DIR / "read_spreadsheet.py",
        "defaults": [],
        "help": "read spreadsheet info or values",
    },
    "update": {
        "script": SHEETS_SCRIPT_DIR / "update_spreadsheet.py",
        "defaults": [],
        "help": "update, append, or clear values",
    },
    "sheets": {
        "script": SHEETS_SCRIPT_DIR / "manage_sheets.py",
        "defaults": [],
        "help": "create, delete, or rename tabs",
    },
    "format": {
        "script": SHEETS_SCRIPT_DIR / "format_cells.py",
        "defaults": [],
        "help": "format cells, conditional rules, alternating colors",
    },
    "charts": {
        "script": SHEETS_SCRIPT_DIR / "create_charts.py",
        "defaults": [],
        "help": "create, list, or delete charts",
    },
    "formulas": {
        "script": SHEETS_SCRIPT_DIR / "formulas.py",
        "defaults": [],
        "help": "insert formulas or manage named ranges",
    },
    "validation": {
        "script": SHEETS_SCRIPT_DIR / "data_validation.py",
        "defaults": [],
        "help": "create or clear validation rules",
    },
    "verify": {
        "script": SHEETS_SCRIPT_DIR / "verify_values.py",
        "defaults": [],
        "help": "re-read a range and compare against the written values (exit 1 = mismatch)",
    },
}



def extract_spreadsheet_id(value: str) -> str:
    match = SPREADSHEET_URL_RE.search(value)
    return match.group(1) if match else value



def normalize_forwarded_args(args: list[str]) -> list[str]:
    normalized: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--spreadsheet" and index + 1 < len(args):
            normalized.extend([token, extract_spreadsheet_id(args[index + 1])])
            index += 2
            continue
        if token.startswith("--spreadsheet="):
            _, value = token.split("=", 1)
            normalized.append(f"--spreadsheet={extract_spreadsheet_id(value)}")
            index += 1
            continue
        normalized.append(token)
        index += 1
    return normalized



def build_parser() -> argparse.ArgumentParser:
    command_help = "\n".join(
        f"  {name:<10} {meta['help']}" for name, meta in COMMANDS.items()
    )
    parser = argparse.ArgumentParser(
        description="Google Sheets workflow CLI proxy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Commands:\n"
            f"{command_help}\n\n"
            "Examples:\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gsheet-workflow/cli.py auth --account work --no-browser\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gsheet-workflow/cli.py create --title 'Ops Tracker' --sheets 'Data,Summary'\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gsheet-workflow/cli.py read --info <spreadsheet-id-or-url>\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gsheet-workflow/cli.py update --spreadsheet <id> --range 'Data!A1' --values '[[\"Name\",\"Value\"]]'\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gsheet-workflow/cli.py verify --spreadsheet <id> --range 'Data!A1:B1' --values '[[\"Name\",\"Value\"]]'\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gsheet-workflow/cli.py verify --spreadsheet <id> --range 'Data!A1:Z100' --expect-empty\n"
        ),
    )
    parser.add_argument("command", nargs="?", choices=sorted(COMMANDS))
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed through to child script")
    return parser



def main() -> int:
    parser = build_parser()
    parsed = parser.parse_args()

    if not parsed.command:
        parser.print_help()
        return 0

    meta = COMMANDS[parsed.command]
    target = Path(meta["script"])
    forwarded = normalize_forwarded_args(parsed.args)
    argv = [*meta["defaults"], *forwarded]
    return run_script(target, argv)


if __name__ == "__main__":
    raise SystemExit(main())
