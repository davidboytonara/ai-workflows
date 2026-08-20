"""Persistent task state (last-run, blocked-on-clarification markers)."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path.home() / ".agents" / "state" / "heartbeat"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"expected ISO datetime string, got {type(value).__name__}")
    return datetime.fromisoformat(value).astimezone(timezone.utc)


@dataclass
class TaskState:
    last_run_at: datetime | None = None
    blocked_runid: str | None = None
    blocked_since: datetime | None = None
    blocked_scheduled_for: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_run_at": _iso(self.last_run_at),
            "blocked_runid": self.blocked_runid,
            "blocked_since": _iso(self.blocked_since),
            "blocked_scheduled_for": _iso(self.blocked_scheduled_for),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TaskState":
        return cls(
            last_run_at=_parse(raw.get("last_run_at")),
            blocked_runid=raw.get("blocked_runid"),
            blocked_since=_parse(raw.get("blocked_since")),
            blocked_scheduled_for=_parse(raw.get("blocked_scheduled_for")),
        )


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskState] = {}
        self._last_clarify_scan_at: datetime | None = None

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._tasks = {}
                self._last_clarify_scan_at = None
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            raw_tasks = data.get("tasks", {}) if isinstance(data, dict) else {}
            self._tasks = {
                name: TaskState.from_dict(ts)
                for name, ts in raw_tasks.items()
                if isinstance(ts, dict)
            }
            self._last_clarify_scan_at = _parse(data.get("last_clarify_scan_at")) if isinstance(data, dict) else None

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated": _iso(utc_now()),
                "last_clarify_scan_at": _iso(self._last_clarify_scan_at),
                "tasks": {name: ts.to_dict() for name, ts in self._tasks.items()},
            }
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)

    def get(self, name: str) -> TaskState:
        with self._lock:
            return self._tasks.setdefault(name, TaskState())

    def update(self, name: str, **changes: Any) -> TaskState:
        with self._lock:
            ts = self._tasks.setdefault(name, TaskState())
            for key, value in changes.items():
                setattr(ts, key, value)
            return ts

    @property
    def last_clarify_scan_at(self) -> datetime | None:
        with self._lock:
            return self._last_clarify_scan_at

    @last_clarify_scan_at.setter
    def last_clarify_scan_at(self, value: datetime | None) -> None:
        with self._lock:
            self._last_clarify_scan_at = value
