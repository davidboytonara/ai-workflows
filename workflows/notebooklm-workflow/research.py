#!/usr/bin/env python3
"""Research monitoring — forwards to `notebooklm research ...`.

To START research, use `source.py add-research "<query>" [--mode deep] [--no-wait]`.
To MONITOR an ongoing research, use the subcommands here:

  status                                 -> notebooklm research status
  wait [--timeout N] [--import-all]      -> notebooklm research wait ...

Alias: `add` in this script maps to `source add-research` for convenience.
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
    if cmd == "add":
        return run_cli(["source", "add-research", *rest])
    if cmd in {"status", "wait"}:
        return run_cli(["research", cmd, *rest])
    print(f"unknown research command: {cmd}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
