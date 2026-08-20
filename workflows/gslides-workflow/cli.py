#!/usr/bin/env python3
"""Project-local CLI proxy for Google Slides workflow operations.

Wraps workflow-local auth and Google Slides scripts behind stable workflow
entrypoints and shared Casper venv bootstrap.

Exit codes:
  0  success
  1  child / business failure
  2  usage error
  3  environment / venv issue
  4  validated update: changes JSON invalid
  5  validated update: dry-run failed
  6  validated update: live apply failed
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _env import AUTH_SCRIPT, SLIDES_SCRIPT_DIR, run_script

PRESENTATION_URL_RE = re.compile(r"/presentation/d/([a-zA-Z0-9_-]+)")

COMMANDS: dict[str, dict[str, object]] = {
    "auth": {
        "script": AUTH_SCRIPT,
        "defaults": [],
        "help": "verify shared Google OAuth for Slides",
    },
    "create": {
        "script": SLIDES_SCRIPT_DIR / "create_presentation.py",
        "defaults": [],
        "help": "create presentation",
    },
    "content": {
        "script": SLIDES_SCRIPT_DIR / "add_content.py",
        "defaults": [],
        "help": "add slide content from JSON",
    },
    "brand": {
        "script": SLIDES_SCRIPT_DIR / "apply_brand.py",
        "defaults": [],
        "help": "apply brand JSON to deck",
    },
    "inspect": {
        "script": SLIDES_SCRIPT_DIR / "get_deck_content.py",
        "defaults": [],
        "help": "extract deck content and object ids",
    },
    "update": {
        "script": SLIDES_SCRIPT_DIR / "update_slides.py",
        "defaults": [],
        "help": "apply JSON updates to existing deck (supports --validated)",
    },
    "export": {
        "script": SLIDES_SCRIPT_DIR / "export_pptx.py",
        "defaults": [],
        "help": "export deck to PPTX",
    },
}



VALIDATED_FLAG = "--validated"


def extract_presentation_id(value: str) -> str:
    match = PRESENTATION_URL_RE.search(value)
    return match.group(1) if match else value



def extract_option(args: list[str], name: str) -> str | None:
    """Return the value of `<name> X` or `<name>=X` from forwarded args."""
    for index, token in enumerate(args):
        if token == name and index + 1 < len(args):
            return args[index + 1]
        if token.startswith(f"{name}="):
            return token.split("=", 1)[1]
    return None



def run_validated_update(target: Path, argv: list[str]) -> int:
    """Validated apply: JSON check -> dry-run -> live apply.

    Stops at the first failed stage: 4 invalid JSON, 5 dry-run failed,
    6 live apply failed.
    """
    if "--dry-run" in argv:
        print(f"{VALIDATED_FLAG} already runs a dry-run stage; drop --dry-run.", file=sys.stderr)
        return 2
    changes_file = extract_option(argv, "--changes-file")
    if changes_file is None:
        print(f"{VALIDATED_FLAG} requires --changes-file.", file=sys.stderr)
        return 2
    try:
        with open(changes_file, encoding="utf-8") as handle:
            json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"validated update stopped: changes JSON invalid: {exc}", file=sys.stderr)
        return 4
    if run_script(target, [*argv, "--dry-run"]) != 0:
        print("validated update stopped: dry-run failed; nothing was applied.", file=sys.stderr)
        return 5
    if run_script(target, argv) != 0:
        print("validated update stopped: live apply failed after a clean dry-run.", file=sys.stderr)
        return 6
    return 0



def normalize_forwarded_args(args: list[str]) -> list[str]:
    normalized: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--presentation-id" and index + 1 < len(args):
            normalized.extend([token, extract_presentation_id(args[index + 1])])
            index += 2
            continue
        if token.startswith("--presentation-id="):
            _, value = token.split("=", 1)
            normalized.append(f"--presentation-id={extract_presentation_id(value)}")
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
        description="Google Slides workflow CLI proxy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Commands:\n"
            f"{command_help}\n\n"
            "Examples:\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gslides-workflow/cli.py auth --account work --no-browser\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gslides-workflow/cli.py create --title 'Team Deck' --output info.json --account work\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gslides-workflow/cli.py content --presentation-id <id-or-url> --content-file slides.json --account work\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gslides-workflow/cli.py update --validated --presentation-id <id-or-url> --changes-file changes.json --account work\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gslides-workflow/cli.py export --presentation-id <id-or-url> --output ./deck.pptx --account work\n"
            "\n"
            "Validated apply:\n"
            "  update --validated runs JSON validation, then --dry-run, then the live apply,\n"
            "  stopping at the first failure: exit 4 invalid JSON, 5 dry-run failed, 6 apply failed.\n"
            "  Use update ... --dry-run (without --validated) for a preview-only run.\n"
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
    if VALIDATED_FLAG in forwarded:
        if parsed.command != "update":
            print(f"{VALIDATED_FLAG} is only supported with the update command.", file=sys.stderr)
            return 2
        forwarded = [token for token in forwarded if token != VALIDATED_FLAG]
        return run_validated_update(target, [*meta["defaults"], *forwarded])
    argv = [*meta["defaults"], *forwarded]
    return run_script(target, argv)


if __name__ == "__main__":
    raise SystemExit(main())
