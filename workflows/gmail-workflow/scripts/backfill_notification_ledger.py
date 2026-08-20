#!/usr/bin/env python3
"""Seed Gmail work-item notification ledger from existing pushed markers.

Read current gmail-ingest state, rebuild the work-item view, and create/update
``notification_ledger`` entries for work items that already have message-level
``pushed.urgent`` or ``pushed.digest`` markers. No Slack or Gmail calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_attention_view import build_attention_items  # noqa: E402
from utils.state_io import STATE_PATH, load_state, save_state, state_lock, utc_now  # noqa: E402

CHANNELS = ("urgent", "digest")


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def marker_value(rec: dict[str, Any], channel: str) -> str | None:
    pushed = rec.get("pushed")
    if not isinstance(pushed, dict):
        return None
    value = pushed.get(channel)
    if value in (None, ""):
        return None
    return str(value)


def choose_seed_channel(
    messages: dict[str, Any], item: dict[str, Any]
) -> tuple[str, list[str], list[str]] | None:
    """Return first seeded channel per rollout rule: urgent beats digest."""
    for channel in CHANNELS:
        message_ids: list[str] = []
        markers: list[str] = []
        for mid in item.get("message_ids", []):
            rec = messages.get(str(mid))
            if not isinstance(rec, dict):
                continue
            marker = marker_value(rec, channel)
            if marker is None:
                continue
            message_ids.append(str(mid))
            markers.append(marker)
        if message_ids:
            return channel, message_ids, markers
    return None


def latest_marker(markers: list[str]) -> str:
    return max(markers) if markers else utc_now()


def ledger_entry(channel: str, item: dict[str, Any], message_ids: list[str], markers: list[str]) -> dict[str, Any]:
    return {
        "last_notified_at": latest_marker(markers),
        "last_notified_channel": channel,
        "last_fingerprint": str(item.get("current_fingerprint") or ""),
        "last_importance": str(item.get("importance_current") or "low"),
        "last_status": str(item.get("status") or "open"),
        "last_seen_ms": to_int(item.get("last_seen_ms")),
        "notified_message_ids": message_ids,
    }


def change_kind(old: Any, new: dict[str, Any]) -> str:
    if not isinstance(old, dict):
        return "create"
    return "unchanged" if old == new else "update"


def future_dated_messages(state: dict[str, Any]) -> list[dict[str, Any]]:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    out: list[dict[str, Any]] = []
    for mid, rec in state.get("messages", {}).items():
        if not isinstance(rec, dict):
            continue
        timestamp_ms = to_int(rec.get("internal_date_ms"), -1)
        if timestamp_ms > now_ms:
            out.append({"message_id": str(mid), "internal_date_ms": timestamp_ms})
    return out


def plan_backfill(state: dict[str, Any]) -> dict[str, Any]:
    messages = state.get("messages", {})
    if not isinstance(messages, dict):
        messages = {}
    ledger = state.get("notification_ledger", {})
    if not isinstance(ledger, dict):
        ledger = {}

    items = build_attention_items(state)
    changes: list[dict[str, Any]] = []
    counts = {
        "create": 0,
        "update": 0,
        "unchanged": 0,
        "urgent": 0,
        "digest": 0,
    }
    empty_item_keys = 0

    for item in items:
        item_key = str(item.get("item_key") or "")
        if not item_key:
            empty_item_keys += 1
            continue
        seed = choose_seed_channel(messages, item)
        if seed is None:
            continue
        channel, message_ids, markers = seed
        entry = ledger_entry(channel, item, message_ids, markers)
        kind = change_kind(ledger.get(item_key), entry)
        counts[kind] += 1
        counts[channel] += 1
        changes.append(
            {
                "action": kind,
                "item_key": item_key,
                "channel": channel,
                "last_seen_ms": entry["last_seen_ms"],
                "last_fingerprint": entry["last_fingerprint"],
                "importance": entry["last_importance"],
                "status": entry["last_status"],
                "notified_message_ids": message_ids,
            }
        )

    return {
        "items_seen": len(items),
        "eligible_items": len(changes),
        "ledger_creates": counts["create"],
        "ledger_updates": counts["update"],
        "ledger_unchanged": counts["unchanged"],
        "channels": {"urgent": counts["urgent"], "digest": counts["digest"]},
        "empty_item_keys": empty_item_keys,
        "future_dated_messages": future_dated_messages(state),
        "changes": changes,
    }


def apply_plan(state: dict[str, Any], plan: dict[str, Any]) -> None:
    ledger = state.setdefault("notification_ledger", {})
    if not isinstance(ledger, dict):
        ledger = {}
        state["notification_ledger"] = ledger

    by_item = {item["item_key"]: item for item in build_attention_items(state) if item.get("item_key")}
    messages = state.get("messages", {}) if isinstance(state.get("messages"), dict) else {}
    for change in plan.get("changes", []):
        item_key = str(change.get("item_key") or "")
        item = by_item.get(item_key)
        if not item:
            continue
        seed = choose_seed_channel(messages, item)
        if seed is None:
            continue
        channel, message_ids, markers = seed
        ledger[item_key] = ledger_entry(channel, item, message_ids, markers)


def emit_json(result: dict[str, Any]) -> None:
    print(json.dumps(result, indent=2, sort_keys=True))


def emit_text(result: dict[str, Any]) -> None:
    mode = "dry-run" if result["dry_run"] else "live"
    changed = result["ledger_creates"] + result["ledger_updates"]
    print(
        f"gmail notification ledger backfill {mode}: "
        f"{result['eligible_items']} eligible / {result['items_seen']} work items; "
        f"create={result['ledger_creates']} update={result['ledger_updates']} "
        f"unchanged={result['ledger_unchanged']} changed={changed}; "
        f"urgent={result['channels']['urgent']} digest={result['channels']['digest']}"
    )
    if result["future_dated_messages"]:
        print(f"warning: future-dated messages={len(result['future_dated_messages'])}", file=sys.stderr)
    if result["empty_item_keys"]:
        print(f"warning: empty item keys={result['empty_item_keys']}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed notification_ledger from existing pushed.urgent/digest markers."
    )
    parser.add_argument("--dry-run", action="store_true", help="Report planned ledger writes without saving state")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.dry_run:
        state = load_state()
        plan = plan_backfill(state)
        result = {"dry_run": True, "state_path": str(STATE_PATH), **plan}
    else:
        with state_lock():
            state = load_state()
            plan = plan_backfill(state)
            apply_plan(state, plan)
            if plan["ledger_creates"] or plan["ledger_updates"]:
                save_state(state)
        result = {"dry_run": False, "state_path": str(STATE_PATH), **plan}

    if args.json:
        emit_json(result)
    else:
        emit_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
