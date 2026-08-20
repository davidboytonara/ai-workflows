#!/usr/bin/env python3
"""Compose the Slack digest / urgent-push message from build-attention JSON.

Deterministic selection + sort + caps + templating for the heartbeat tasks
(digest.md / urgent-push.md). No LLM, no network. Input is the stdout of
``cli.py build-attention --json --channel <kind> ...`` ({"items": [...]}).

Selection: notification.action == "include_digest" (digest) / "push_urgent"
(urgent). Digest groups by category (ingest-schema order), sorts urgent >
important > low then last_seen_ms desc. Urgent sorts last_seen_ms desc and
caps at --cap (default 5) with a "+ K more urgent in inbox" overflow line.
The output body carries no [GMAIL] prefix — push-slack adds it.

Outputs:
  stdout         Slack message body (only on exit 0)
  stderr         final line is always `SUMMARY: ...` for the heartbeat history
  --stamp-out    on exit 0, stamp-notifications payload JSON
                 ({"channel": ..., "items": [...]}; anomaly-only digest -> [])

Exit codes:
  0  message composed
  1  nothing to send (empty selection; digest: and no anomalies)
  2  usage / input error (bad JSON, or input built for the other channel)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any

from utils.state_io import STATE_PATH

# Load ~/.agents/.env and ~/.agents/.config into os.environ (see .env.example).
import os as _os, sys as _sys
_d = _os.path.dirname(_os.path.abspath(__file__))
while _d != _os.path.dirname(_d):
    if _os.path.isfile(_os.path.join(_d, '_shared', 'agents_config.py')):
        _sys.path.insert(0, _os.path.join(_d, '_shared'))
        break
    _d = _os.path.dirname(_d)
import agents_config  # noqa: F401,E402


CATEGORY_ORDER = [
    "Personal", "Work", "Project", "Finance", "Travel", "Calendar",
    "Newsletter", "Promotion", "System", "Social", "Information", "Other",
]
IMPORTANCE_ORDER = {"urgent": 0, "important": 1, "low": 2}
ACTION_FOR_KIND = {"digest": "include_digest", "urgent": "push_urgent"}
STAMP_KEYS = (
    "item_key", "current_fingerprint", "importance_current",
    "status", "last_seen_ms", "message_ids",
)
SLOT_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")


def fail(message: str) -> int:
    print(f"compose: {message}", file=sys.stderr)
    print("SUMMARY: compose failed", file=sys.stderr)
    return 2


def local_now_hhmm() -> str:
    """Current HH:MM in the configured timezone (GMAIL_WORKFLOW_TZ, default UTC)."""
    tz_name = os.environ.get("GMAIL_WORKFLOW_TZ", "UTC")
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001 - fall back to UTC if the tz is unknown
        now = datetime.now(timezone.utc)
    return now.strftime("%H:%M")


def from_display(raw: str) -> str:
    name, addr = parseaddr(str(raw or ""))
    name = name.strip().strip('"')
    return name or addr or str(raw or "").strip()


def notification_of(item: dict[str, Any]) -> dict[str, Any]:
    notification = item.get("notification")
    return notification if isinstance(notification, dict) else {}


def memory_of(item: dict[str, Any]) -> dict[str, Any]:
    memory = item.get("memory")
    return memory if isinstance(memory, dict) else {}


def category_of(item: dict[str, Any]) -> str:
    return str(item.get("category") or "") or "Other"


def category_sort_key(category: str) -> tuple[int, str]:
    if category in CATEGORY_ORDER:
        return (CATEGORY_ORDER.index(category), "")
    return (len(CATEGORY_ORDER), category)


def load_anomalies(path: str | None) -> list[str]:
    """Render anomaly lines; unreadable/bad input degrades to none (warn only)."""
    if not path:
        return []
    try:
        data = json.loads(open(path, encoding="utf-8").read())
        flagged = data.get("flagged", [])
        if not isinstance(flagged, list):
            raise ValueError("'flagged' must be a list")
    except Exception as exc:  # noqa: BLE001
        print(f"warning: anomalies input unusable, treating as none: {exc}", file=sys.stderr)
        return []
    lines = []
    for entry in flagged:
        if not isinstance(entry, dict):
            continue
        lines.append(
            f":chart_with_upwards_trend: *{entry.get('topic_key')}* — "
            f"{entry.get('today')} today vs avg {entry.get('mean'):g}/day"
        )
    return lines


def common_suffix(item: dict[str, Any]) -> str:
    suffix = ""
    memory = memory_of(item)
    if memory.get("next_action"):
        suffix += f" — memory next: {memory['next_action']}"
    return suffix


def digest_bullet(item: dict[str, Any]) -> list[str]:
    suffix = ""
    if int(item.get("message_count") or 0) > 1:
        suffix += f" — {item['message_count']} msgs in thread, new since last digest"
    suffix += common_suffix(item)
    if notification_of(item).get("reason") == "new_email_after_memory_done":
        suffix += " — *reopened?* new email after completed memory"
    memory = memory_of(item)
    if str(memory.get("status") or "").lower() == "blocked" and memory.get("blocked_by"):
        suffix += f" — was blocked by {memory['blocked_by']}; new email may change blocker"
    return [
        f"  • *{item.get('importance_current')}* — {from_display(item.get('latest_from'))}"
        f" — {item.get('latest_subject')}",
        f"    _{item.get('latest_summary')}_{suffix}",
    ]


def urgent_bullet(item: dict[str, Any]) -> list[str]:
    suffix = common_suffix(item)
    if notification_of(item).get("reason") == "new_email_after_memory_done":
        suffix += " — reopened urgent: new email after completed memory"
    return [
        f"• *{category_of(item)}* — {from_display(item.get('latest_from'))}"
        f" — {item.get('latest_subject')}",
        f"  _{item.get('latest_summary')}_{suffix}",
    ]


def compose_digest(
    selected: list[dict[str, Any]], anomaly_lines: list[str], slot: str
) -> tuple[str, str]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        groups.setdefault(category_of(item), []).append(item)
    ordered_categories = sorted(groups, key=category_sort_key)

    lines = [f"*Digest {slot}* — {len(selected)} work items"]
    lines += anomaly_lines
    cat_counts = []
    for category in ordered_categories:
        group = sorted(
            groups[category],
            key=lambda it: (
                IMPORTANCE_ORDER.get(str(it.get("importance_current")), 3),
                -int(it.get("last_seen_ms") or 0),
            ),
        )
        needs_action = sum(1 for it in group if it.get("needs_action"))
        header = f"*{category}* ({len(group)}"
        if needs_action:
            header += f", {needs_action} needs action"
        header += ")"
        lines += ["", header]
        for item in group:
            lines += digest_bullet(item)
        cat_counts.append(f"{category}:{len(group)}")

    summary = (
        f"SUMMARY: digested {len(selected)} work items "
        f"(cat={','.join(cat_counts) or '-'}; anomalies={len(anomaly_lines)})"
    )
    return "\n".join(lines), summary


def compose_urgent(
    selected: list[dict[str, Any]], cap: int
) -> tuple[str, str, list[dict[str, Any]]]:
    selected = sorted(selected, key=lambda it: -int(it.get("last_seen_ms") or 0))
    pushed = selected[:cap]
    lines = [f"*{len(selected)} urgent in inbox*"]
    for item in pushed:
        lines += urgent_bullet(item)
    if len(selected) > cap:
        lines.append(f"+ {len(selected) - cap} more urgent in inbox")
    summary = f"SUMMARY: pushed {len(pushed)} urgent (cap={cap})"
    return "\n".join(lines), summary, pushed


def stamp_payload(kind: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "channel": kind,
        "items": [{key: item.get(key) for key in STAMP_KEYS} for item in items],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compose the Slack digest/urgent message from build-attention JSON."
    )
    parser.add_argument("--kind", required=True, choices=sorted(ACTION_FOR_KIND))
    parser.add_argument("--input", default="-",
                        help="build-attention JSON file, or '-' for stdin (default '-')")
    parser.add_argument("--anomalies", default=None,
                        help="detect-anomalies --json output file (digest 10:00 slot only)")
    parser.add_argument("--slot", default=None,
                        help="Digest header time label HH:MM (default: now in $GMAIL_WORKFLOW_TZ)")
    parser.add_argument("--cap", type=int, default=5,
                        help="Max urgent work items per push (default 5)")
    parser.add_argument("--stamp-out", default=None,
                        help="Write stamp-notifications payload JSON here on success")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.slot and not SLOT_PATTERN.match(args.slot):
        return fail("--slot must look like HH:MM")
    if args.cap < 1:
        return fail("--cap must be >= 1")

    try:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        data = json.loads(raw)
        items = data.get("items")
        if not isinstance(items, list):
            raise ValueError("input must be a JSON object with an 'items' array")
    except (OSError, ValueError) as exc:
        return fail(f"bad input: {exc}")

    wanted = ACTION_FOR_KIND[args.kind]
    other = next(v for k, v in ACTION_FOR_KIND.items() if k != args.kind)
    selected = [it for it in items if notification_of(it).get("action") == wanted]
    if items and not selected:
        if not any("notification" in it for it in items if isinstance(it, dict)):
            return fail("items carry no 'notification' field — run build-attention with --channel")
        if any(notification_of(it).get("action") == other for it in items if isinstance(it, dict)):
            return fail(f"input was built for the other channel (found '{other}' actions)")

    anomaly_lines = load_anomalies(args.anomalies) if args.kind == "digest" else []

    if args.kind == "digest":
        if not selected and not anomaly_lines:
            if not items and not STATE_PATH.exists():
                print("SUMMARY: no state yet", file=sys.stderr)
            else:
                print("SUMMARY: empty digest", file=sys.stderr)
            return 1
        slot = args.slot or local_now_hhmm()
        message, summary = compose_digest(selected, anomaly_lines, slot)
        stamped = selected
    else:
        if not selected:
            print("SUMMARY: 0 urgent", file=sys.stderr)
            return 1
        message, summary, stamped = compose_urgent(selected, args.cap)

    if args.stamp_out:
        try:
            with open(args.stamp_out, "w", encoding="utf-8") as handle:
                json.dump(stamp_payload(args.kind, stamped), handle, separators=(",", ":"))
        except OSError as exc:
            return fail(f"cannot write --stamp-out: {exc}")

    print(message)
    print(summary, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
