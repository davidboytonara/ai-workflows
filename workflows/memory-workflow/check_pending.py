#!/usr/bin/env python3
"""Heartbeat precondition: exit 0 if any session source needs distilling, else 1.

Loads `extract_session_history.py` as a sibling module (it is not on sys.path),
calls its public API to detect unprocessed or changed source files, and uses the
exit code as a deterministic gate for the heartbeat daemon's `memory-distill` task.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

EXTRACTOR_PATH = Path(__file__).resolve().parent / "extract_session_history.py"


def _load_extractor():
    spec = importlib.util.spec_from_file_location("casper_extract_session_history", EXTRACTOR_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load extractor: {EXTRACTOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    extractor = _load_extractor()
    sources = extractor.collect_source_files([], "all")
    state = extractor.load_state()
    for _provider, path in sources:
        if not extractor.is_already_processed(state, path):
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
