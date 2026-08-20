#!/usr/bin/env python3
"""Stamp Gmail work-item notification ledger after a successful Slack push."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from utils.state_io import load_state, prune, save_state, state_lock, utc_now

VALID_CHANNELS = {"urgent", "digest"}


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read_input(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise ValueError("Input must be a JSON object")
    return data


def normalize_message_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(mid) for mid in value if mid is not None]


def stamp_item(state: dict[str, Any], channel: str, item: dict[str, Any], now: str) -> int:
    item_key = str(item.get("item_key") or "")
    if not item_key:
        return 0

    message_ids = normalize_message_ids(item.get("message_ids"))
    ledger = state.setdefault("notification_ledger", {})
    ledger[item_key] = {
        "last_notified_at": now,
        "last_notified_channel": channel,
        "last_fingerprint": str(item.get("current_fingerprint") or ""),
        "last_importance": str(item.get("importance_current") or "low"),
        "last_status": str(item.get("status") or "open"),
        "last_seen_ms": to_int(item.get("last_seen_ms")),
        "notified_message_ids": message_ids,
    }

    stamped_messages = 0
    messages = state.setdefault("messages", {})
    for mid in message_ids:
        rec = messages.get(mid)
        if not isinstance(rec, dict):
            continue
        pushed = rec.setdefault("pushed", {})
        if not isinstance(pushed, dict):
            pushed = {}
            rec["pushed"] = pushed
        if pushed.get(channel) in (None, ""):
            pushed[channel] = now
        stamped_messages += 1
    return stamped_messages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stamp Gmail notification ledger and message pushed markers.")
    parser.add_argument("--input", default="-", help="JSON file path or '-' for stdin (default '-')")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = read_input(args.input)
    channel = str(payload.get("channel") or "")
    if channel not in VALID_CHANNELS:
        print("stamp-notifications: channel must be 'urgent' or 'digest'", file=sys.stderr)
        return 2

    items = payload.get("items")
    if not isinstance(items, list):
        print("stamp-notifications: items must be a JSON array", file=sys.stderr)
        return 2

    now = utc_now()
    stamped_items = 0
    stamped_messages = 0
    with state_lock():
        state = load_state()
        prune(state)
        for item in items:
            if not isinstance(item, dict):
                continue
            stamped = stamp_item(state, channel, item, now)
            if str(item.get("item_key") or ""):
                stamped_items += 1
                stamped_messages += stamped
        save_state(state)

    print(json.dumps({"channel": channel, "stamped_items": stamped_items, "stamped_messages": stamped_messages}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
