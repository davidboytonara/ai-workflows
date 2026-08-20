#!/usr/bin/env python3
"""Session / auth / language commands.

Subcommands mirror the NotebookLM CLI:

  status                     -> notebooklm status
  use <notebook_id>          -> notebooklm use <id>
  clear                      -> notebooklm clear
  auth-check [--test]        -> notebooklm auth check [--test]
  language list|get|set ...  -> notebooklm language ...
  login                      -> notebooklm login   (browser; prefer out-of-band)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import run_cli  # noqa: E402


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "auth-check":
        return run_cli(["auth", "check", *rest], check_auth=False)
    if cmd == "language":
        return run_cli(["language", *rest], check_auth=False)
    if cmd == "login":
        return run_cli(["login", *rest], check_auth=False)
    if cmd in {"status", "use", "clear"}:
        return run_cli([cmd, *rest], check_auth=False)
    print(f"unknown session command: {cmd}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
