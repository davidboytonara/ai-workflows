#!/usr/bin/env python3
"""Artifacts + downloads.

`artifact.py` wraps both the `artifact` group (list/get/rename/delete/
export/poll/wait/suggestions) and the top-level `download <type>` group.

Examples:
  artifact.py list [--type report]
  artifact.py get <artifact_id>
  artifact.py rename <artifact_id> "<title>"
  artifact.py delete <artifact_id>
  artifact.py export <artifact_id> --type docs --title "<t>"
  artifact.py download <type> <local-path> [--format <fmt>]

Types for `download`: audio, video, cinematic-video, slide-deck, report,
quiz, flashcards, infographic, data-table, mind-map.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import run_cli  # noqa: E402

ARTIFACT_SUBS = {
    "list", "get", "rename", "delete", "export",
    "poll", "wait", "suggestions",
}


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "download":
        return run_cli(["download", *rest])
    if cmd in ARTIFACT_SUBS:
        return run_cli(["artifact", cmd, *rest])
    print(f"unknown artifact command: {cmd}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
