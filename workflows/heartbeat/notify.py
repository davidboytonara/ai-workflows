"""Slack notifications for heartbeat task outcomes."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Load ~/.agents/.env and ~/.agents/.config into os.environ (see .env.example).
import os as _os, sys as _sys
_d = _os.path.dirname(_os.path.abspath(__file__))
while _d != _os.path.dirname(_d):
    if _os.path.isfile(_os.path.join(_d, '_shared', 'agents_config.py')):
        _sys.path.insert(0, _os.path.join(_d, '_shared'))
        break
    _d = _os.path.dirname(_d)
import agents_config  # noqa: F401,E402


LOG = logging.getLogger(__name__)

WEBHOOK_ENV = "CASPER_SLACK_WEBHOOK_URL"
NOTIFY_ON_ENV = "CASPER_HEARTBEAT_NOTIFY_ON"
VALID_NOTIFY_ON = frozenset({"failed", "timeout", "blocked_on_clarification", "precondition_skip"})
DEFAULT_NOTIFY_ON = frozenset({"failed", "timeout", "blocked_on_clarification"})
MAX_FIELD_CHARS = 700
SCHEDULE_TZ = ZoneInfo(os.environ.get("CASPER_HEARTBEAT_TZ", "UTC"))


def _scheduled_time(dt: datetime) -> str:
    local = dt.astimezone(SCHEDULE_TZ).replace(microsecond=0)
    return f"{local.isoformat()} ({SCHEDULE_TZ.key})"


def _shorten(value: str | None, limit: int = MAX_FIELD_CHARS) -> str:
    if not value:
        return "(none)"
    text = value.strip()
    if not text:
        return "(none)"
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _parse_notify_on(value: str | None) -> set[str]:
    if value is None or not value.strip():
        return set(DEFAULT_NOTIFY_ON)
    notify_on = {part.strip() for part in value.split(",") if part.strip()}
    unknown = notify_on - VALID_NOTIFY_ON
    if unknown:
        valid = ", ".join(sorted(VALID_NOTIFY_ON))
        invalid = ", ".join(sorted(unknown))
        raise ValueError(f"invalid {NOTIFY_ON_ENV}: {invalid}; valid values: {valid}")
    return notify_on


def _duration_seconds(result: Any) -> float | None:
    started_at = getattr(result, "started_at", None)
    finished_at = getattr(result, "finished_at", None)
    if started_at is None or finished_at is None:
        return None
    return (finished_at - started_at).total_seconds()


@dataclass(frozen=True)
class SlackNotifier:
    """Best-effort Slack Incoming Webhook notifier."""

    webhook_url: str | None
    notify_on: set[str]

    @classmethod
    def from_env(cls) -> "SlackNotifier":
        return cls(
            webhook_url=os.environ.get(WEBHOOK_ENV),
            notify_on=_parse_notify_on(os.environ.get(NOTIFY_ON_ENV)),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def notify_run(self, task_name: str, result: Any, history_dir: Path) -> None:
        """Notify for configured non-success states. Never raises."""
        status = result.pending_reason
        if status is None or status not in self.notify_on:
            return
        if not self.enabled:
            return

        payload = self._payload(task_name, status, result, history_dir)
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - configured Slack webhook
                status_code = getattr(resp, "status", None) or getattr(resp, "code", None)
                if status_code is not None and int(status_code) >= 400:
                    LOG.warning("slack notification failed: HTTP %s", status_code)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            LOG.warning("slack notification failed: %s", exc)
        except Exception as exc:  # defensive: notifications must never affect heartbeat state
            LOG.warning("slack notification failed unexpectedly: %s", exc)

    def _payload(self, task_name: str, status: str, result: Any, history_dir: Path) -> dict[str, str]:
        history_path = history_dir / f"{task_name}.jsonl"
        lines = [
            f"Casper heartbeat: {task_name}",
            f"status: {status}",
            f"run_id: {result.run_id}",
            f"scheduled_for: {_scheduled_time(result.scheduled_for)}",
            f"history: {history_path}",
        ]
        duration = _duration_seconds(result)
        if duration is not None:
            lines.append(f"duration_seconds: {duration}")
        lines.append(f"summary: {_shorten(getattr(result, 'tldr', None) or getattr(result, 'summary', None))}")
        clarify_obj = getattr(result, "clarify", None)
        if status == "blocked_on_clarification" and clarify_obj is not None:
            lines.extend(
                [
                    f"clarify_file: {clarify_obj.path}",
                    f"question: {_shorten(clarify_obj.question)}",
                ]
            )
        return {"text": "\n".join(lines)}
