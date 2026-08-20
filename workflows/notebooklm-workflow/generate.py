#!/usr/bin/env python3
"""Artifact generation — forwards to `notebooklm generate <type> ...`.

Types: audio, video, cinematic-video, slide-deck, revise-slide, report,
quiz, flashcards, infographic, data-table, mind-map.

Examples:
  generate.py report --format briefing-doc --wait
  generate.py audio "deep dive on chapter 3" --format deep-dive --wait
  generate.py slide-deck --format detailed --wait
  generate.py revise-slide "move title up" --artifact <id> --slide 0 --wait
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
        return run_cli(["generate", "--help"])
    return run_cli(["generate", *argv])


if __name__ == "__main__":
    raise SystemExit(main())
