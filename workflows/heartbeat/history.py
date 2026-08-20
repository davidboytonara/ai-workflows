"""Per-task run history as JSONL, truncated to the last N runs."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_HISTORY_DIR = Path.home() / ".agents" / "state" / "history"
MAX_RUNS_PER_TASK = 100


def append(history_dir: Path, task_name: str, entry: dict[str, Any]) -> None:
    """Append one JSON entry and truncate the file to MAX_RUNS_PER_TASK lines."""
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"{task_name}.jsonl"
    path.touch(exist_ok=True)
    line = json.dumps(entry, sort_keys=True) + "\n"

    with path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0, os.SEEK_END)
            fh.write(line)
            fh.flush()

            fh.seek(0)
            lines = fh.readlines()
            if len(lines) > MAX_RUNS_PER_TASK:
                tail = lines[-MAX_RUNS_PER_TASK:]
                fh.seek(0)
                fh.truncate()
                fh.writelines(tail)
                fh.flush()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def read_all(history_dir: Path, task_name: str) -> list[dict[str, Any]]:
    path = history_dir / f"{task_name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
