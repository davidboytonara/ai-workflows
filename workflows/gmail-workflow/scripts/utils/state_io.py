"""Shared state I/O for gmail-summarizer heartbeat workflow.

State file lives at ``~/.agents/state/gmail-ingest/state.json`` and is shared
across the ingest, urgent-push, and digest tasks. Atomic writes via
``tmp + os.replace``. Concurrent runs coordinate via flock on
``~/.agents/state/gmail-ingest/state.lock``.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Load ~/.agents/.env and ~/.agents/.config into os.environ (see .env.example).
import os as _os, sys as _sys
_d = _os.path.dirname(_os.path.abspath(__file__))
while _d != _os.path.dirname(_d):
    if _os.path.isfile(_os.path.join(_d, '_shared', 'agents_config.py')):
        _sys.path.insert(0, _os.path.join(_d, '_shared'))
        break
    _d = _os.path.dirname(_d)
import agents_config  # noqa: F401,E402


STATE_VERSION = 1
# Kept as a literal (not imported from utils.priority) so this module keeps
# loading standalone via importlib.util.spec_from_file_location, as the test
# suite does — it does not put scripts/ on sys.path for a bare "utils" import.
VALID_QUADRANTS = {"eliminate", "schedule", "delegate", "do_now"}
STATE_PATH = Path.home() / ".agents" / "state" / "gmail-ingest" / "state.json"
LOCK_PATH = Path.home() / ".agents" / "state" / "gmail-ingest" / "state.lock"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "updated": utc_now(),
        "messages": {},
        "topic_counts": {},
        "last_ingest_per_account": {},
        "notification_ledger": {},
    }


def normalize_state_shape(state: Any) -> dict[str, Any]:
    """Ensure optional top-level collections exist for older state files."""
    if not isinstance(state, dict):
        state = {}
    state.setdefault("version", STATE_VERSION)
    if not isinstance(state.get("messages"), dict):
        state["messages"] = {}
    if not isinstance(state.get("topic_counts"), dict):
        state["topic_counts"] = {}
    if not isinstance(state.get("last_ingest_per_account"), dict):
        state["last_ingest_per_account"] = {}
    if not isinstance(state.get("notification_ledger"), dict):
        state["notification_ledger"] = {}
    return state


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return empty_state()
    try:
        return normalize_state_shape(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        backup = STATE_PATH.with_suffix(f".corrupt-{utc_now().replace(':', '')}.json")
        STATE_PATH.rename(backup)
        return empty_state()


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated"] = utc_now()
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def valid_ledger_entry(rec: Any, cutoff_ms: int) -> bool:
    if not isinstance(rec, dict):
        return False
    last_seen_ms = to_int(rec.get("last_seen_ms"), -1)
    if last_seen_ms < cutoff_ms:
        return False
    if rec.get("last_notified_channel") not in {"urgent", "digest"}:
        return False
    if not isinstance(rec.get("last_notified_at"), str):
        return False
    if not isinstance(rec.get("last_fingerprint"), str):
        return False
    valid_quadrant = rec.get("last_quadrant") in VALID_QUADRANTS
    valid_legacy_importance = rec.get("last_importance") in {"urgent", "important", "low"}
    if not (valid_quadrant or valid_legacy_importance):
        return False
    if not isinstance(rec.get("last_status"), str):
        return False
    if not isinstance(rec.get("notified_message_ids", []), list):
        return False
    return True


def prune(
    state: dict[str, Any],
    message_retention_days: int = 30,
    count_retention_days: int = 30,
    ledger_retention_days: int = 45,
) -> dict[str, Any]:
    """Drop old messages, trim topic_counts.daily, and prune notification ledger."""
    normalize_state_shape(state)
    cutoff_ms = int((datetime.now(timezone.utc).timestamp() - message_retention_days * 86400) * 1000)
    state["messages"] = {
        mid: rec
        for mid, rec in state.get("messages", {}).items()
        if isinstance(rec, dict) and to_int(rec.get("internal_date_ms")) >= cutoff_ms
    }

    ledger_cutoff_ms = int((datetime.now(timezone.utc).timestamp() - ledger_retention_days * 86400) * 1000)
    state["notification_ledger"] = {
        key: rec
        for key, rec in state.get("notification_ledger", {}).items()
        if isinstance(key, str) and valid_ledger_entry(rec, ledger_cutoff_ms)
    }

    cutoff_date = datetime.now(timezone.utc).date().toordinal() - count_retention_days
    for topic, payload in list(state.get("topic_counts", {}).items()):
        kept = []
        for entry in payload.get("daily", []):
            try:
                d = datetime.strptime(entry["date"], "%Y-%m-%d").date().toordinal()
            except (KeyError, ValueError):
                continue
            if d >= cutoff_date:
                kept.append(entry)
        if kept:
            payload["daily"] = kept
        else:
            del state["topic_counts"][topic]
    return state


@contextlib.contextmanager
def state_lock(non_blocking: bool = False) -> Iterator[None]:
    """Coarse cross-process lock so only one writer mutates state at a time.

    With ``non_blocking=True``, raises ``BlockingIOError`` immediately if held.
    Used by ingest to skip overlapping runs.
    """
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCK_PATH), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        flags = fcntl.LOCK_EX
        if non_blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flags)
        except OSError as exc:
            if non_blocking and exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise BlockingIOError("gmail-summarizer state lock held") from exc
            raise
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def quiet_hours_active(now: datetime | None = None) -> bool:
    """True if current time falls inside ``GMAIL_QUIET_HOURS`` window.

    Format: ``HH:MM-HH:MM`` (local time). Default: ``23:30-07:00``.
    Crosses midnight when end < start.
    """
    raw = os.environ.get("GMAIL_QUIET_HOURS", "23:30-07:00").strip()
    if not raw:
        return False
    try:
        start_str, end_str = raw.split("-")
        sh, sm = (int(p) for p in start_str.split(":"))
        eh, em = (int(p) for p in end_str.split(":"))
    except (ValueError, AttributeError):
        return False

    now = now or datetime.now()
    cur = now.hour * 60 + now.minute
    start = sh * 60 + sm
    end = eh * 60 + em
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end
