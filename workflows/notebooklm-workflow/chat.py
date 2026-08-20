#!/usr/bin/env python3
"""Chat / conversation — forwards to `notebooklm <ask|configure|history>`.

Subcommands:
  ask "<prompt>" [--json] [--save-as-note --note-title "<t>"]
  configure --mode <learning-guide|...>
  history [--show-all]

Run `chat.py <subcommand> --help` for flags.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import run_cli  # noqa: E402

ALLOWED = {"ask", "configure", "history"}


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd not in ALLOWED:
        print(f"unknown chat command: {cmd}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 2
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
