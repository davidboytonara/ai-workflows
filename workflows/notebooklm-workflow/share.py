#!/usr/bin/env python3
"""Sharing — forwards to `notebooklm share ...`.

Subcommands: status, public, view-level, add, update, remove.
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
        return run_cli(["share", "--help"])
    return run_cli(["share", *argv])


if __name__ == "__main__":
    raise SystemExit(main())
