#!/usr/bin/env python3
"""Project-local CLI proxy for Gmail workflow operations.

Wraps workflow-local auth and Gmail scripts behind stable entrypoints and shared
Casper venv bootstrap.

Safety: never sends email and never permanently deletes. Only reversible
operations are exposed: draft create/update, move-to-Trash, and label changes
(e.g. mark read/unread).

Exit codes:
  0  success
  1  child / business failure
  2  usage error
  3  environment / venv issue
"""

from __future__ import annotations

import argparse
from pathlib import Path

from _env import AUTH_SCRIPT, GMAIL_SCRIPT_DIR, run_script

COMMANDS: dict[str, dict[str, object]] = {
    "auth": {
        "script": AUTH_SCRIPT,
        "defaults": [],
        "help": "verify shared Google OAuth for Gmail",
    },
    "read": {
        "script": GMAIL_SCRIPT_DIR / "read_emails.py",
        "defaults": [],
        "help": "read Gmail messages with filters",
    },
    "attachments": {
        "script": GMAIL_SCRIPT_DIR / "download_attachments.py",
        "defaults": [],
        "help": "download attachments from one message",
    },
    "draft": {
        "script": GMAIL_SCRIPT_DIR / "draft_email.py",
        "defaults": [],
        "help": "create Gmail draft only; never send",
    },
    "modify": {
        "script": GMAIL_SCRIPT_DIR / "modify_messages.py",
        "defaults": [],
        "help": "reversible trash / mark-read / label changes (never permanent-delete, never send)",
    },
    "list-unprocessed": {
        "script": GMAIL_SCRIPT_DIR / "list_unprocessed.py",
        "defaults": [],
        "help": "list unprocessed inbox messages (gmail-summarizer)",
    },
    "fetch-bodies": {
        "script": GMAIL_SCRIPT_DIR / "fetch_bodies.py",
        "defaults": [],
        "help": "fetch text bodies for given message IDs (gmail-summarizer)",
    },
    "check-resolution": {
        "script": GMAIL_SCRIPT_DIR / "check_resolution.py",
        "defaults": [],
        "help": "cross-check ACTION candidates for resolution evidence in threads + sent mail (read-only)",
    },
    "apply-classifications": {
        "script": GMAIL_SCRIPT_DIR / "apply_classifications.py",
        "defaults": [],
        "help": "apply Casper labels and persist state (gmail-summarizer)",
    },
    "push-slack": {
        "script": GMAIL_SCRIPT_DIR / "slack_push.py",
        "defaults": [],
        "help": "push a Slack message via CASPER_SLACK_WEBHOOK_URL (gmail-summarizer)",
    },
    "detect-anomalies": {
        "script": GMAIL_SCRIPT_DIR / "detect_anomalies.py",
        "defaults": [],
        "help": "detect topic-frequency spikes from state (gmail-summarizer)",
    },
    "build-attention": {
        "script": GMAIL_SCRIPT_DIR / "build_attention_view.py",
        "defaults": [],
        "help": "build grouped gmail work-item view from ingest state",
    },
    "compose": {
        "script": GMAIL_SCRIPT_DIR / "compose_notification.py",
        "defaults": [],
        "help": "compose digest/urgent Slack message from build-attention JSON (deterministic)",
    },
    "stamp-notifications": {
        "script": GMAIL_SCRIPT_DIR / "stamp_notifications.py",
        "defaults": [],
        "help": "stamp work-item notification ledger and message pushed markers",
    },
    "backfill-notifications": {
        "script": GMAIL_SCRIPT_DIR / "backfill_notification_ledger.py",
        "defaults": [],
        "help": "seed notification ledger from existing pushed markers",
    },
}



def build_parser() -> argparse.ArgumentParser:
    command_help = "\n".join(
        f"  {name:<12} {meta['help']}" for name, meta in COMMANDS.items()
    )
    parser = argparse.ArgumentParser(
        description="Gmail workflow CLI proxy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Commands:\n"
            f"{command_help}\n\n"
            "Examples:\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gmail-workflow/cli.py auth --account personal --no-browser\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gmail-workflow/cli.py read --from 'alerts@example.com' --body 'error' --account personal\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gmail-workflow/cli.py attachments --message-id 18f3a2b1c4d5e6f7 --output-dir ./downloads --account personal\n"
            "  $HOME/.agents/.venv/bin/python .agents/workflows/gmail-workflow/cli.py draft --to 'user@example.com' --subject 'Follow-up' --body 'Just checking in.' --account personal\n"
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
    argv = [*meta["defaults"], *parsed.args]
    return run_script(target, argv)


if __name__ == "__main__":
    raise SystemExit(main())
