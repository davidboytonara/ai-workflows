"""Cron-based scheduling with missed-slot catchup."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter

from config import TaskConfig


def compute_due_runs(
    task: TaskConfig,
    last_run_at: datetime | None,
    now: datetime,
) -> list[datetime]:
    """Return cron slots in (last_run_at, now], filtered by task.catchup.

    First boot (last_run_at is None) returns [] — the daemon plants a marker and
    waits for the next scheduled slot. Subsequent ticks recognize any slot that
    elapsed while the daemon was down.
    """
    if last_run_at is None:
        return []

    tz = ZoneInfo(task.cron_tz)
    base = last_run_at.astimezone(tz)
    itr = croniter(task.cron, base)
    slots: list[datetime] = []
    while True:
        nxt = itr.get_next(datetime).astimezone(timezone.utc)
        if nxt > now:
            break
        slots.append(nxt)

    if not slots:
        return []
    if task.catchup == "none":
        return []
    if task.catchup == "one":
        return [slots[-1]]
    return slots
