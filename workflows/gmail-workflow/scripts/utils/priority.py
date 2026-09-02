"""Eisenhower-matrix priority: two independent classification axes collapsed
into one quadrant for triage, notification routing, and display.

``urgency`` ("urgent" / "not_urgent") and ``importance`` ("important" /
"not_important") are independent inputs from the classifier (see
``../apply_classifications.py`` and ``../../heartbeat/ingest.md``'s
Classification schema). ``quadrant_for`` collapses them into the standard
Eisenhower quadrant used everywhere else in this workflow (attention view,
notification routing, Slack digest labels).

Backward compatibility: state written before this schema existed carries a
single three-value ``importance`` field (``urgent`` / ``important`` /
``low``). ``legacy_quadrant`` maps that value onto the same quadrant space
so old ``state.json`` records and notification-ledger entries keep working
without a migration being required first (``migrate_priority_schema.py``
performs that migration for callers who want it, but nothing here depends
on it having run).
"""

from __future__ import annotations

from typing import Any

VALID_URGENCY = {"urgent", "not_urgent"}
VALID_IMPORTANCE = {"important", "not_important"}

# do_now = urgent + important; delegate = urgent + not important;
# schedule = not urgent + important; eliminate = neither.
QUADRANTS = ("eliminate", "schedule", "delegate", "do_now")
QUADRANT_RANK = {"eliminate": 0, "schedule": 1, "delegate": 2, "do_now": 3}
QUADRANT_AXES = {
    "do_now": ("urgent", "important"),
    "delegate": ("urgent", "not_important"),
    "schedule": ("not_urgent", "important"),
    "eliminate": ("not_urgent", "not_important"),
}
# Gmail label suffix (no spaces) vs. human-readable Slack display text.
QUADRANT_LABEL = {"do_now": "DoNow", "delegate": "Delegate", "schedule": "Schedule", "eliminate": "Eliminate"}
QUADRANT_DISPLAY = {"do_now": "Do Now", "delegate": "Delegate", "schedule": "Schedule", "eliminate": "Eliminate"}

# Everything except "eliminate" counts as actionable/attention-worthy,
# matching the pre-split behavior where only "low" was excluded.
ACTIONABLE_QUADRANTS = {"do_now", "delegate", "schedule"}

# Legacy single-field importance -> quadrant. The old top bucket ("urgent")
# had no way to express "urgent but not important", so it maps to do_now;
# "important" (not time-pressured) maps to schedule; "low" maps to eliminate.
LEGACY_IMPORTANCE_TO_QUADRANT = {"urgent": "do_now", "important": "schedule", "low": "eliminate"}


def normalize_urgency(value: Any) -> str:
    text = str(value or "not_urgent").lower()
    return text if text in VALID_URGENCY else "not_urgent"


def normalize_importance(value: Any) -> str:
    text = str(value or "not_important").lower()
    return text if text in VALID_IMPORTANCE else "not_important"


def normalize_quadrant(value: Any) -> str:
    text = str(value or "eliminate").lower()
    return text if text in QUADRANT_RANK else "eliminate"


def quadrant_for(urgency: Any, importance: Any) -> str:
    urgency = normalize_urgency(urgency)
    importance = normalize_importance(importance)
    if urgency == "urgent":
        return "do_now" if importance == "important" else "delegate"
    return "schedule" if importance == "important" else "eliminate"


def legacy_quadrant(value: Any) -> str:
    text = str(value or "low").lower()
    return LEGACY_IMPORTANCE_TO_QUADRANT.get(text, "eliminate")


def quadrant_from_record(rec: dict[str, Any]) -> str:
    """Quadrant for a persisted message record, new or legacy schema."""
    if "urgency" in rec:
        return quadrant_for(rec.get("urgency"), rec.get("importance"))
    return legacy_quadrant(rec.get("importance"))


def quadrant_from_ledger_entry(entry: dict[str, Any]) -> str:
    """Quadrant for a notification-ledger entry, new or legacy schema."""
    if "last_quadrant" in entry:
        return normalize_quadrant(entry.get("last_quadrant"))
    return legacy_quadrant(entry.get("last_importance"))
