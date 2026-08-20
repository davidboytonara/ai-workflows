#!/usr/bin/env python3
"""Notebook CRUD.

Subcommands forward to the NotebookLM top-level commands:

  list                       -> notebooklm list
  create "<title>"           -> notebooklm create
  rename <id> "<title>"      -> notebooklm rename
  delete <id>                -> notebooklm delete
  summary                    -> notebooklm summary
  metadata [flags]           -> notebooklm metadata
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import run_cli  # noqa: E402

ALLOWED = {"list", "create", "rename", "delete", "summary", "metadata"}


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd not in ALLOWED:
        print(f"unknown notebook command: {cmd}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 2
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
