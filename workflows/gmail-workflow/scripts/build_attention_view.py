#!/usr/bin/env python3
"""Build a grouped Gmail attention/work-item view.

Default mode is read-only over ``~/.agents/state/gmail-ingest/state.json``. When
``--enrich-replies`` is passed, candidate work items fetch Gmail thread metadata
only to infer whether the user has replied.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from email.utils import getaddresses
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from utils.state_io import STATE_PATH  # noqa: E402

# Load ~/.agents/.env and ~/.agents/.config into os.environ (see .env.example).
import os as _os, sys as _sys
_d = _os.path.dirname(_os.path.abspath(__file__))
while _d != _os.path.dirname(_d):
    if _os.path.isfile(_os.path.join(_d, '_shared', 'agents_config.py')):
        _sys.path.insert(0, _os.path.join(_d, '_shared'))
        break
    _d = _os.path.dirname(_d)
import agents_config  # noqa: F401,E402


LOOKBACK_DAYS = 30
LEDGER_RETENTION_DAYS = 45
DEFAULT_MAX_THREAD_FETCH = 25
DEFAULT_REPLY_RESOLUTION_DAYS = 3
IMPORTANCE_RANK = {"low": 0, "important": 1, "urgent": 2}
ACTIONABLE_IMPORTANCE = {"urgent", "important"}
DIGEST_IMPORTANCE = {"important", "low"}
WAITING_ON_OTHER_STATUSES = {"awaiting_other_party", "likely_resolved"}
HIGH_RISK_SIGNAL_TERMS = (
    "deadline",
    "due",
    "overdue",
    "security",
    "breach",
    "password",
    "payment",
    "invoice",
    "renewal",
    "expires",
    "risk",
)
BLOCKED_CHANGE_SIGNAL_TERMS = (
    "deadline",
    "due",
    "overdue",
    "approve",
    "approval",
    "approved",
    "unblock",
    "unblocked",
)
ThreadFetcher = Callable[[str], dict[str, Any]]


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_importance(value: Any) -> str:
    text = str(value or "low").lower()
    return text if text in IMPORTANCE_RANK else "low"


def load_state_readonly(path: Path = STATE_PATH) -> dict[str, Any]:
    """Load state without invoking state_io.load_state side effects."""
    if not path.exists():
        return {"messages": {}, "notification_ledger": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state.get("messages"), dict):
        state["messages"] = {}
    if not isinstance(state.get("notification_ledger"), dict):
        state["notification_ledger"] = {}
    return state


def group_key(message_id: str, rec: dict[str, Any]) -> str:
    account = str(rec.get("account") or "")
    thread_id = str(rec.get("thread_id") or "")
    if thread_id:
        return f"thread:{account}:{thread_id}"
    topic_key = str(rec.get("topic_key") or "")
    if topic_key:
        return f"topic:{account}:{topic_key}"
    return f"message:{account}:{message_id}"


def latest_message(messages: list[tuple[str, dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    return max(messages, key=lambda pair: (to_int(pair[1].get("internal_date_ms")), pair[0]))


def fingerprint_for(item: dict[str, Any]) -> str:
    stable = {
        "item_key": item["item_key"],
        "importance_current": item["importance_current"],
        "needs_action": item["needs_action"],
        "latest_message_id": item["latest_message_id"],
        "latest_summary": item["latest_summary"],
        "last_seen_ms": item["last_seen_ms"],
    }
    raw = json.dumps(stable, sort_keys=True, separators=(",", ":"))
    return "sha1:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def usable_ledger_entry(ledger_entry: Any, ledger_cutoff_ms: int | None = None) -> dict[str, Any] | None:
    if not isinstance(ledger_entry, dict):
        return None
    if ledger_entry.get("last_notified_channel") not in {"urgent", "digest"}:
        return None
    if not isinstance(ledger_entry.get("last_notified_at"), str):
        return None
    if not isinstance(ledger_entry.get("last_fingerprint"), str):
        return None
    last_seen_ms = to_int(ledger_entry.get("last_seen_ms"), -1)
    if last_seen_ms < 0 or (ledger_cutoff_ms is not None and last_seen_ms < ledger_cutoff_ms):
        return None
    if normalize_importance(ledger_entry.get("last_importance")) != ledger_entry.get("last_importance"):
        return None
    if not isinstance(ledger_entry.get("last_status"), str):
        return None
    if not isinstance(ledger_entry.get("notified_message_ids", []), list):
        return None
    return ledger_entry


def default_reply_fields() -> dict[str, Any]:
    return {
        "reply_state": "unknown",
        "latest_user_reply_ms": None,
        "latest_inbound_ms": None,
        "waiting_on": "unknown",
    }


def get_header(headers: list[dict[str, Any]], name: str) -> str:
    for header in headers:
        if str(header.get("name") or "").lower() == name.lower():
            return str(header.get("value") or "")
    return ""


def extract_email_addresses(raw: str) -> list[str]:
    if not raw:
        return []
    addresses = [addr.strip().lower() for _, addr in getaddresses([raw.replace(";", ",")]) if addr]
    if addresses:
        return addresses
    text = raw.strip().lower()
    return [text] if "@" in text else []


def normalize_own_addresses(values: list[str] | tuple[str, ...] | None) -> set[str]:
    out: set[str] = set()
    for value in values or []:
        out.update(extract_email_addresses(value))
    return out


def is_own_from(from_header: str, own_addresses: set[str]) -> bool:
    return any(addr in own_addresses for addr in extract_email_addresses(from_header))


def high_risk_signal(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("latest_subject", "latest_summary", "category", "importance_current")
    ).lower()
    return any(term in text for term in HIGH_RISK_SIGNAL_TERMS)


def blocked_change_signal(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("latest_subject", "latest_summary")
    ).lower()
    return any(term in text for term in BLOCKED_CHANGE_SIGNAL_TERMS)


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def strip_yaml_scalar(value: str) -> str:
    return value.strip().strip("'\"")


def frontmatter_list_from_file(record: dict[str, Any], field: str) -> list[str]:
    """Read a simple inline or block-list frontmatter field from a memory file."""
    path_text = str(record.get("path") or "")
    if not path_text:
        return []
    try:
        text = Path(path_text).read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.startswith("---\n"):
        return []
    end = text.find("\n---\n", 4)
    if end < 0:
        return []

    lines = text[4:end].splitlines()
    values: list[str] = []
    in_block = False
    prefix = f"{field}:"
    for raw_line in lines:
        stripped = raw_line.strip()
        if in_block:
            if not stripped:
                continue
            if raw_line[:1].isspace() and stripped.startswith("- "):
                values.append(strip_yaml_scalar(stripped[2:]))
                continue
            break
        if not raw_line.startswith(prefix):
            continue
        raw_value = raw_line[len(prefix):].strip()
        if not raw_value:
            in_block = True
            continue
        if raw_value.startswith("[") and raw_value.endswith("]"):
            inner = raw_value[1:-1].strip()
            return [strip_yaml_scalar(part) for part in inner.split(",") if part.strip()]
        return [strip_yaml_scalar(raw_value)]
    return values


def memory_values(record: dict[str, Any], field: str) -> list[Any]:
    values = as_list(record.get(field))
    if values:
        return values
    return frontmatter_list_from_file(record, field)


def norm_exact(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_subject_slug(subject: Any) -> str:
    text = str(subject or "").strip().lower()
    while True:
        stripped = re.sub(r"^(re|fw|fwd)\s*:\s*", "", text, flags=re.IGNORECASE).strip()
        if stripped == text:
            break
        text = stripped
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def parse_memory_date(value: Any) -> datetime.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def item_last_seen_date(item: dict[str, Any]) -> datetime.date | None:
    last_seen_ms = to_int(item.get("last_seen_ms"), -1)
    if last_seen_ms < 0:
        return None
    return datetime.fromtimestamp(last_seen_ms / 1000, tz=timezone.utc).date()


def latest_email_newer_than_memory(item: dict[str, Any], memory: dict[str, Any]) -> bool:
    latest_date = item_last_seen_date(item)
    updated_date = parse_memory_date(memory.get("updated"))
    return bool(latest_date and updated_date and latest_date > updated_date)


def latest_email_same_or_older_than_memory(item: dict[str, Any], memory: dict[str, Any]) -> bool:
    latest_date = item_last_seen_date(item)
    updated_date = parse_memory_date(memory.get("updated"))
    return bool(latest_date and updated_date and latest_date <= updated_date)


def load_active_task_memory(project: str | None) -> list[dict[str, Any]]:
    script = Path.home() / ".agents" / "workflows" / "memory-workflow" / "search_memory.py"
    cmd = [sys.executable, str(script), "--active-tasks", "--format", "json"]
    if project:
        cmd.extend(["--project", project])
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, check=True)
        data = json.loads(proc.stdout or "[]")
    except Exception as exc:  # noqa: BLE001
        print(f"warning: memory lookup disabled: {exc}", file=sys.stderr)
        return []
    if not isinstance(data, list):
        return []
    return [record for record in data if isinstance(record, dict)]


def memory_scope_matches(record: dict[str, Any], project: str | None) -> bool:
    if not project:
        return True
    return str(record.get("scope") or "") == f"project:{project}"


def memory_payload(record: dict[str, Any], match_reason: str) -> dict[str, Any]:
    payload = {
        "matched": True,
        "path": str(record.get("path") or ""),
        "status": str(record.get("status") or ""),
        "updated": record.get("updated"),
        "match_reason": match_reason,
    }
    for key in ("next_action", "blocked_by", "body"):
        if record.get(key) not in (None, ""):
            payload[key] = record.get(key)
    return payload


def explicit_memory_match_reason(item: dict[str, Any], record: dict[str, Any]) -> str | None:
    account = str(item.get("account") or "")
    related = {str(value).strip() for value in memory_values(record, "related") if str(value).strip()}
    for thread_id in as_list(item.get("thread_ids")):
        if f"gmail-thread:{account}:{thread_id}" in related:
            return "related:gmail-thread"
    topic_key = str(item.get("topic_key") or "")
    if topic_key and f"gmail-topic:{account}:{topic_key}" in related:
        return "related:gmail-topic"
    return None


def keyword_memory_match_reason(item: dict[str, Any], record: dict[str, Any]) -> str | None:
    candidates = {norm_exact(item.get("topic_key")), normalize_subject_slug(item.get("latest_subject"))}
    candidates.discard("")
    for keyword in memory_values(record, "keywords"):
        if norm_exact(keyword) in candidates:
            return "keyword:exact"
    return None


def match_memory(item: dict[str, Any], memory_records: list[dict[str, Any]], project: str | None) -> dict[str, Any] | None:
    scoped = [record for record in memory_records if memory_scope_matches(record, project)]
    for record in scoped:
        reason = explicit_memory_match_reason(item, record)
        if reason:
            return memory_payload(record, reason)
    for record in scoped:
        reason = keyword_memory_match_reason(item, record)
        if reason:
            return memory_payload(record, reason)
    return None


def attach_memory(items: list[dict[str, Any]], memory_records: list[dict[str, Any]], project: str | None) -> None:
    for item in items:
        memory = match_memory(item, memory_records, project)
        if memory:
            item["memory"] = memory


def prepare_memory_policy(items: list[dict[str, Any]]) -> None:
    for item in items:
        memory = item.get("memory")
        if not isinstance(memory, dict):
            continue
        status = str(memory.get("status") or "").lower()
        if status == "done":
            if latest_email_same_or_older_than_memory(item, memory):
                item["_memory_policy"] = "done_suppress"
            elif latest_email_newer_than_memory(item, memory):
                item["status"] = "reopened"
                item["_memory_policy"] = "done_reopen"
        elif status == "blocked":
            item["_memory_policy"] = "blocked"
        elif status in {"active", "pending"}:
            item["_memory_policy"] = "active_pending"


def notification_includes(notification: dict[str, Any]) -> bool:
    return str(notification.get("action") or "") in {"push_urgent", "include_digest"}


def apply_memory_notification_policy(items: list[dict[str, Any]]) -> None:
    for item in items:
        policy = str(item.pop("_memory_policy", "") or "")
        notification = item.get("notification")
        memory = item.get("memory")
        if not policy or not isinstance(notification, dict) or not isinstance(memory, dict):
            continue

        if policy == "done_suppress":
            notification["action"] = "suppress"
            notification["reason"] = "memory_done"
            continue

        if policy == "done_reopen":
            if notification_includes(notification):
                notification["reason"] = "new_email_after_memory_done"
            continue

        if not notification_includes(notification):
            continue

        reason = str(notification.get("reason") or "")
        status = str(item.get("status") or "")
        urgent = item.get("importance_current") == "urgent"
        newer_than_memory = latest_email_newer_than_memory(item, memory)
        inbound_after_reply = item.get("reply_state") == "inbound_after_reply"
        actionable = (bool(item.get("needs_action")) or status in {"awaiting_user", "reopened"}) and newer_than_memory
        reopened = status == "reopened" or reason in {"reopened", "new_email_after_memory_done"}
        urgent_escalation = reason == "escalated" or (urgent and newer_than_memory and reason in {"new_item", "changed", "reopened"})

        if policy == "blocked":
            if not (urgent_escalation or inbound_after_reply or reopened or blocked_change_signal(item)):
                notification["action"] = "suppress"
                notification["reason"] = "memory_blocked"
        elif policy == "active_pending":
            thread_changed = reopened or (reason in {"changed", "new_item"} and newer_than_memory)
            if not (thread_changed or urgent_escalation or actionable):
                notification["action"] = "suppress"
                notification["reason"] = "memory_static"


def is_actionable_item(item: dict[str, Any]) -> bool:
    return item.get("importance_current") in ACTIONABLE_IMPORTANCE or bool(item.get("needs_action"))


def build_thread_fetcher(account: str | None) -> ThreadFetcher:
    # auth_helper/google_auth_core log to stdout by default. Import/build while
    # stdout points at stderr so JSON output stays clean.
    with contextlib.redirect_stdout(sys.stderr):
        from utils.auth_helper import build_gmail_service  # noqa: WPS433

        service = build_gmail_service(account=account)

    def fetch(thread_id: str) -> dict[str, Any]:
        return (
            service.users()
            .threads()
            .get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=["From", "To", "Cc", "Date", "Subject"],
            )
            .execute()
        )

    return fetch


def analyze_thread_reply_status(
    thread: dict[str, Any],
    *,
    own_addresses: set[str],
    now_ms: int,
    resolution_days: int,
    actionable: bool,
) -> dict[str, Any]:
    latest_user_reply_ms: int | None = None
    latest_inbound_ms: int | None = None

    for message in thread.get("messages", []):
        if not isinstance(message, dict):
            continue
        timestamp_ms = to_int(message.get("internalDate"), -1)
        if timestamp_ms < 0:
            continue
        headers = message.get("payload", {}).get("headers", [])
        if not isinstance(headers, list):
            headers = []
        from_header = get_header(headers, "From")
        if not extract_email_addresses(from_header):
            continue
        if is_own_from(from_header, own_addresses):
            latest_user_reply_ms = max(latest_user_reply_ms or 0, timestamp_ms)
        else:
            latest_inbound_ms = max(latest_inbound_ms or 0, timestamp_ms)

    fields = default_reply_fields()
    fields["latest_user_reply_ms"] = latest_user_reply_ms
    fields["latest_inbound_ms"] = latest_inbound_ms

    if latest_user_reply_ms is None and latest_inbound_ms is None:
        return fields

    if latest_user_reply_ms is None and latest_inbound_ms is not None:
        fields["reply_state"] = "not_replied"
        if actionable:
            fields["waiting_on"] = "user"
            fields["status"] = "awaiting_user"
        return fields

    if latest_user_reply_ms is not None and (
        latest_inbound_ms is None or latest_user_reply_ms > latest_inbound_ms
    ):
        fields["reply_state"] = "replied_after_inbound"
        fields["waiting_on"] = "other_party"
        quiet_ms = now_ms - latest_user_reply_ms
        resolution_ms = max(resolution_days, 0) * 86400 * 1000
        fields["status"] = "likely_resolved" if quiet_ms >= resolution_ms else "awaiting_other_party"
        return fields

    if latest_inbound_ms is not None and latest_user_reply_ms is not None and latest_inbound_ms > latest_user_reply_ms:
        fields["reply_state"] = "inbound_after_reply"
        if actionable:
            fields["waiting_on"] = "user"
            fields["status"] = "reopened"
        return fields

    return fields


def reply_candidate(
    item: dict[str, Any],
    ledger: dict[str, Any],
    ledger_cutoff_ms: int | None,
) -> bool:
    if is_actionable_item(item):
        return True
    memory = item.get("memory")
    if isinstance(memory, dict) and str(memory.get("status") or "").lower() in {"blocked", "active", "pending"}:
        return True
    previous = usable_ledger_entry(ledger.get(item["item_key"]), ledger_cutoff_ms)
    if not previous:
        return False
    return str(previous.get("last_status") or "") not in {"resolved", "likely_resolved"}


def enrich_reply_status(
    items: list[dict[str, Any]],
    state: dict[str, Any],
    *,
    own_addresses: set[str],
    now_ms: int,
    account: str | None = "work",
    max_thread_fetch: int = DEFAULT_MAX_THREAD_FETCH,
    resolution_days: int = DEFAULT_REPLY_RESOLUTION_DAYS,
    thread_fetcher: ThreadFetcher | None = None,
) -> None:
    if not own_addresses:
        print("warning: reply enrichment skipped: no --own-address provided", file=sys.stderr)
        return
    if max_thread_fetch <= 0:
        return

    ledger = state.get("notification_ledger", {})
    if not isinstance(ledger, dict):
        ledger = {}
    ledger_cutoff_ms = now_ms - LEDGER_RETENTION_DAYS * 86400 * 1000

    candidates = [item for item in items if item.get("thread_ids") and reply_candidate(item, ledger, ledger_cutoff_ms)]
    candidates.sort(
        key=lambda item: (
            IMPORTANCE_RANK.get(str(item.get("importance_current")), 0),
            to_int(item.get("last_seen_ms")),
        ),
        reverse=True,
    )
    if not candidates:
        return

    if thread_fetcher is None:
        try:
            thread_fetcher = build_thread_fetcher(account)
        except Exception as exc:  # noqa: BLE001
            print(f"warning: reply enrichment disabled: could not initialize Gmail service: {exc}", file=sys.stderr)
            return

    fetched = 0
    thread_cache: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if fetched >= max_thread_fetch:
            break
        thread_id = str(item.get("thread_ids", [""])[0] or "")
        if not thread_id:
            continue
        try:
            if thread_id not in thread_cache:
                thread_cache[thread_id] = thread_fetcher(thread_id)
                fetched += 1
            reply_fields = analyze_thread_reply_status(
                thread_cache[thread_id],
                own_addresses=own_addresses,
                now_ms=now_ms,
                resolution_days=resolution_days,
                actionable=is_actionable_item(item),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"warning: reply enrichment failed for thread {thread_id}: {exc}", file=sys.stderr)
            continue

        item.update(reply_fields)
        if "status" in reply_fields:
            item["status"] = str(reply_fields["status"])


def notification_for(
    item: dict[str, Any],
    ledger_entry: Any,
    channel: str,
    ledger_cutoff_ms: int | None = None,
) -> dict[str, Any]:
    previous = usable_ledger_entry(ledger_entry, ledger_cutoff_ms)
    previous_channel = previous.get("last_notified_channel") if previous else None
    previous_at = previous.get("last_notified_at") if previous else None
    previous_fingerprint = str(previous.get("last_fingerprint") or "") if previous else ""
    previous_importance = normalize_importance(previous.get("last_importance")) if previous else "low"
    previous_status = str(previous.get("last_status") or "") if previous else ""
    current_fingerprint = item["current_fingerprint"]
    importance = item["importance_current"]
    status = str(item.get("status") or "open")

    if channel == "urgent":
        if importance != "urgent":
            action, reason = "suppress", "low_no_action"
        elif status == "reopened":
            if not previous or previous_fingerprint != current_fingerprint or previous_status != "reopened":
                action, reason = "push_urgent", "reopened"
            else:
                action, reason = "suppress", "same_fingerprint"
        elif status in WAITING_ON_OTHER_STATUSES:
            if previous and previous_importance != "urgent":
                action, reason = "push_urgent", "escalated"
            elif previous and previous_fingerprint != current_fingerprint and high_risk_signal(item):
                action, reason = "push_urgent", "changed"
            else:
                action, reason = "suppress", status
        elif not previous:
            action, reason = "push_urgent", "new_item"
        elif previous_importance != "urgent":
            action, reason = "push_urgent", "escalated"
        elif previous_fingerprint != current_fingerprint:
            action, reason = "push_urgent", "changed"
        else:
            action, reason = "suppress", "same_fingerprint"
    elif channel == "digest":
        if status == "reopened":
            if not previous or previous_fingerprint != current_fingerprint or previous_status != "reopened":
                action, reason = "include_digest", "reopened"
            else:
                action, reason = "suppress", "same_fingerprint"
        elif status in WAITING_ON_OTHER_STATUSES:
            action, reason = "suppress", status
        elif importance in DIGEST_IMPORTANCE:
            if not previous:
                action, reason = "include_digest", "new_item"
            elif previous_fingerprint != current_fingerprint:
                action, reason = "include_digest", "changed"
            else:
                action, reason = "suppress", "same_fingerprint"
        elif importance == "urgent":
            if not previous:
                action, reason = "include_digest", "new_item"
            elif previous_fingerprint != current_fingerprint:
                action, reason = "include_digest", "changed"
            else:
                action, reason = "suppress", "same_fingerprint"
        else:
            action, reason = "suppress", "same_fingerprint"
    else:  # pragma: no cover - argparse constrains this.
        action, reason = "suppress", "low_no_action"

    return {
        "action": action,
        "reason": reason,
        "previous_channel": previous_channel,
        "previous_at": previous_at,
    }


def build_item(item_key: str, messages: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    ordered = sorted(messages, key=lambda pair: (to_int(pair[1].get("internal_date_ms")), pair[0]))
    latest_id, latest = latest_message(ordered)
    timestamps = [to_int(rec.get("internal_date_ms")) for _, rec in ordered]

    importances = [normalize_importance(rec.get("importance")) for _, rec in ordered]
    importance_current = max(importances, key=lambda imp: IMPORTANCE_RANK[imp]) if importances else "low"

    categories_by_time = [str(rec.get("category") or "") for _, rec in ordered if rec.get("category")]
    category = categories_by_time[-1] if categories_by_time else ""
    categories_seen = sorted(set(categories_by_time))

    topic_keys_by_time = [str(rec.get("topic_key") or "") for _, rec in ordered if rec.get("topic_key")]
    thread_ids = sorted({str(rec.get("thread_id")) for _, rec in ordered if rec.get("thread_id")})
    needs_action_count = sum(1 for _, rec in ordered if bool(rec.get("needs_action")))

    item = {
        "item_key": item_key,
        "account": str(latest.get("account") or ""),
        "thread_ids": thread_ids,
        "topic_key": topic_keys_by_time[-1] if topic_keys_by_time else "",
        "message_ids": [mid for mid, _ in ordered],
        "message_count": len(ordered),
        "first_seen_ms": min(timestamps) if timestamps else 0,
        "last_seen_ms": max(timestamps) if timestamps else 0,
        "latest_message_id": latest_id,
        "latest_from": str(latest.get("from") or ""),
        "latest_subject": str(latest.get("subject") or ""),
        "latest_summary": str(latest.get("summary") or ""),
        "category": category,
        "importance_current": importance_current,
        "needs_action": needs_action_count > 0,
        "needs_action_count": needs_action_count,
        "status": str(latest.get("status") or "open"),
        **default_reply_fields(),
    }
    if len(categories_seen) > 1:
        item["categories_seen"] = categories_seen
    item["current_fingerprint"] = fingerprint_for(item)
    return item


def build_attention_items(
    state: dict[str, Any],
    *,
    now_ms: int | None = None,
    lookback_days: int = LOOKBACK_DAYS,
    only_actionable: bool = False,
    channel: str | None = None,
    enrich_replies: bool = False,
    own_addresses: list[str] | tuple[str, ...] | set[str] | None = None,
    account: str | None = "work",
    max_thread_fetch: int = DEFAULT_MAX_THREAD_FETCH,
    reply_resolution_days: int | None = None,
    thread_fetcher: ThreadFetcher | None = None,
    use_memory: bool = False,
    memory_project: str | None = None,
    memory_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    cutoff_ms = now_ms - lookback_days * 86400 * 1000

    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for message_id, rec in state.get("messages", {}).items():
        if not isinstance(rec, dict):
            continue
        timestamp_ms = to_int(rec.get("internal_date_ms"))
        if timestamp_ms < cutoff_ms or to_int(rec.get("error_count")) >= 5:
            continue
        mid = str(message_id)
        groups.setdefault(group_key(mid, rec), []).append((mid, rec))

    items = [build_item(key, grouped) for key, grouped in groups.items()]
    if use_memory:
        records = memory_records if memory_records is not None else load_active_task_memory(memory_project)
        attach_memory(items, records, memory_project)
    if enrich_replies:
        if isinstance(own_addresses, set):
            own_set = {addr.lower() for addr in own_addresses}
        else:
            own_set = normalize_own_addresses(list(own_addresses or []))
        resolution_days = (
            reply_resolution_days
            if reply_resolution_days is not None
            else to_int(os.environ.get("GMAIL_REPLY_RESOLUTION_DAYS"), DEFAULT_REPLY_RESOLUTION_DAYS)
        )
        enrich_reply_status(
            items,
            state,
            own_addresses=own_set,
            now_ms=now_ms,
            account=account,
            max_thread_fetch=max_thread_fetch,
            resolution_days=resolution_days,
            thread_fetcher=thread_fetcher,
        )
    if use_memory:
        prepare_memory_policy(items)
    if channel:
        ledger = state.get("notification_ledger", {})
        if not isinstance(ledger, dict):
            ledger = {}
        ledger_cutoff_ms = now_ms - LEDGER_RETENTION_DAYS * 86400 * 1000
        for item in items:
            item["notification"] = notification_for(
                item,
                ledger.get(item["item_key"]),
                channel,
                ledger_cutoff_ms,
            )
        if use_memory:
            apply_memory_notification_policy(items)
    if only_actionable:
        items = [
            item for item in items
            if item["importance_current"] in ACTIONABLE_IMPORTANCE or item["needs_action"]
        ]
    items.sort(key=lambda item: (item["last_seen_ms"], item["item_key"]), reverse=True)
    return items


def render_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No Gmail attention items."
    lines = [f"Gmail attention items: {len(items)}"]
    for item in items:
        action = " action" if item["needs_action"] else ""
        reply = ""
        if item.get("reply_state") and item.get("reply_state") != "unknown":
            reply = f" | {item['status']}/{item['reply_state']}"
        lines.append(
            f"- {item['importance_current']}{action} | {item['message_count']} msg | "
            f"{item['latest_from']} | {item['latest_subject']} | {item['item_key']}{reply}"
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build grouped Gmail work-item view from ingest state.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    mode.add_argument("--summary", action="store_true", help="Emit compact text summary to stdout")
    parser.add_argument(
        "--only-actionable",
        action="store_true",
        help="Only include urgent/important items or items with needs_action=true",
    )
    parser.add_argument(
        "--channel",
        choices=("urgent", "digest"),
        help="Attach per-channel notification decision metadata",
    )
    parser.add_argument(
        "--enrich-replies",
        action="store_true",
        help="Fetch candidate Gmail threads and infer user reply status",
    )
    parser.add_argument(
        "--own-address",
        action="append",
        default=[],
        help="User email address for reply detection; repeat or comma-separate",
    )
    parser.add_argument(
        "--account",
        default="work",
        help="Gmail account alias for reply enrichment (default: work)",
    )
    parser.add_argument(
        "--max-thread-fetch",
        type=int,
        default=DEFAULT_MAX_THREAD_FETCH,
        help=f"Max Gmail threads to fetch for reply enrichment (default: {DEFAULT_MAX_THREAD_FETCH})",
    )
    parser.add_argument(
        "--use-memory",
        action="store_true",
        help="Read Casper open-task memory and apply memory-aware notification suppression",
    )
    parser.add_argument(
        "--memory-project",
        default=None,
        help="Casper memory project slug to read/filter, e.g. my-project",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.enrich_replies and not normalize_own_addresses(args.own_address):
        print("error: --enrich-replies requires --own-address", file=sys.stderr)
        return 2

    state = load_state_readonly()
    items = build_attention_items(
        state,
        only_actionable=args.only_actionable,
        channel=args.channel,
        enrich_replies=args.enrich_replies,
        own_addresses=args.own_address,
        account=args.account,
        max_thread_fetch=args.max_thread_fetch,
        use_memory=args.use_memory,
        memory_project=args.memory_project,
    )

    if args.summary:
        print(render_summary(items))
    else:
        print(json.dumps({"items": items}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
