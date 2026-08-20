#!/usr/bin/env python3
"""Source management — forwards to `notebooklm source ...`.

Subcommands: add, add-drive, add-research, list, get, fulltext, guide,
stale, rename, refresh, wait, delete, delete-by-title.

Run `source.py <subcommand> --help` for full flag reference.
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
        return run_cli(["source", "--help"])
    return run_cli(["source", *argv])


if __name__ == "__main__":
    raise SystemExit(main())
