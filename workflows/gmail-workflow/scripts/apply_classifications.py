#!/usr/bin/env python3
"""Apply classifications to Gmail messages and persist state.

Reads a JSON array on stdin (or from ``--input PATH``):

    [
      {
        "id": "<message id>",
        "account": "work",
        "thread_id": "...",
        "from": "boss@example.com",
        "from_domain": "example.com",
        "subject": "...",
        "internal_date_ms": 1745539200000,
        "category": "Work",
        "urgency": "urgent",
        "importance": "important",
        "needs_action": true,
        "topic_key": "example.com|q3-budget",
        "summary": "..."
      },
      ...
    ]

``urgency`` and ``importance`` are independent Eisenhower-matrix axes (see
``utils/priority.py``); together they collapse into one of four quadrants
(do_now / schedule / delegate / eliminate).

For each entry:
- Ensures ``Casper/<Category>``, ``Casper/<Quadrant>``, ``Casper/Processed``
  labels exist (creates if missing).
- Calls ``messages.modify`` to add the labels (skipped under ``--dry-run``).
- Updates ``~/.agents/state/gmail-ingest/state.json`` with the per-message
  record and increments ``topic_counts.daily`` for today.

Idempotent via the ``Casper/Processed`` label and the state ``messages``
keyed by Gmail message id.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from utils.auth_helper import build_gmail_service
from utils.logger import setup_logger, log_error_with_context
from utils.priority import QUADRANT_LABEL, normalize_importance, normalize_urgency, quadrant_for
from utils.state_io import load_state, prune, save_state, state_lock, utc_now

logger = setup_logger(__name__)

VALID_CATEGORIES = {
    "Personal", "Work", "Project", "Finance", "Travel", "Calendar",
    "Newsletter", "Promotion", "System", "Social", "Information", "Other",
}


def normalize_classification(entry: dict) -> dict:
    cat = entry.get("category") or "Other"
    if cat not in VALID_CATEGORIES:
        cat = "Other"
    entry["category"] = cat
    entry["urgency"] = normalize_urgency(entry.get("urgency"))
    entry["importance"] = normalize_importance(entry.get("importance"))
    entry["quadrant"] = quadrant_for(entry["urgency"], entry["importance"])
    entry["needs_action"] = bool(entry.get("needs_action", False))
    entry["summary"] = (entry.get("summary") or "")[:200]
    return entry


def get_or_create_label(service, name: str, cache: dict[str, str]) -> str:
    if name in cache:
        return cache[name]
    try:
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
    except Exception as exc:
        log_error_with_context(logger, exc, {"operation": "labels.list"})
        raise SystemExit(1) from exc

    for lbl in labels:
        cache[lbl["name"]] = lbl["id"]
    if name in cache:
        return cache[name]

    try:
        created = service.users().labels().create(
            userId="me",
            body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        ).execute()
    except Exception as exc:
        log_error_with_context(logger, exc, {"operation": "labels.create", "name": name})
        raise SystemExit(1) from exc

    cache[created["name"]] = created["id"]
    return created["id"]


def labels_for(category: str, quadrant: str) -> list[str]:
    return [
        f"Casper/{category}",
        f"Casper/{QUADRANT_LABEL[quadrant]}",
        "Casper/Processed",
    ]


def increment_topic_counts(state: dict, topic_key: str) -> None:
    if not topic_key:
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bucket = state.setdefault("topic_counts", {}).setdefault(topic_key, {"daily": []})
    daily = bucket.setdefault("daily", [])
    if daily and daily[-1].get("date") == today:
        daily[-1]["n"] = int(daily[-1].get("n", 0)) + 1
    else:
        daily.append({"date": today, "n": 1})


def apply_one(service, entry: dict, cache: dict[str, str], dry_run: bool) -> dict:
    entry = normalize_classification(entry)
    label_names = labels_for(entry["category"], entry["quadrant"])
    if entry.get("needs_action"):
        label_names.append("Casper/Action")

    if dry_run:
        return {"id": entry["id"], "labels": label_names, "dry_run": True}

    label_ids = [get_or_create_label(service, name, cache) for name in label_names]

    try:
        service.users().messages().modify(
            userId="me",
            id=entry["id"],
            body={"addLabelIds": label_ids, "removeLabelIds": []},
        ).execute()
    except Exception as exc:
        log_error_with_context(logger, exc, {"operation": "messages.modify", "id": entry["id"]})
        return {"id": entry["id"], "error": str(exc)}

    return {"id": entry["id"], "labels": label_names}


def persist(state: dict, entry: dict, label_names: list[str], error: str | None) -> None:
    rec = state["messages"].get(entry["id"], {})
    rec.update({
        "account": entry.get("account"),
        "thread_id": entry.get("thread_id"),
        "from": entry.get("from"),
        "from_domain": entry.get("from_domain"),
        "subject": entry.get("subject"),
        "internal_date_ms": int(entry.get("internal_date_ms", 0)),
        "category": entry["category"],
        "urgency": entry["urgency"],
        "importance": entry["importance"],
        "quadrant": entry["quadrant"],
        "needs_action": entry["needs_action"],
        "topic_key": entry.get("topic_key", ""),
        "summary": entry.get("summary", ""),
        "ingested_at": rec.get("ingested_at") or utc_now(),
        "labels_applied": label_names,
        "pushed": rec.get("pushed") or {"urgent": None, "digest": None},
        "error": error,
        "error_count": int(rec.get("error_count", 0)) + (1 if error else 0),
    })
    state["messages"][entry["id"]] = rec
    if not error:
        increment_topic_counts(state, entry.get("topic_key", ""))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apply classifications + labels and persist state.")
    p.add_argument("--input", default="-", help="JSON file path or '-' for stdin (default '-')")
    p.add_argument("--dry-run", action="store_true", help="Skip Gmail label calls and state write")
    return p.parse_args()


def read_input(path: str) -> list[dict]:
    if path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Input must be a JSON array")
    return data


def main() -> int:
    args = parse_args()
    entries = read_input(args.input)

    if not entries:
        print(json.dumps({"applied": [], "errors": 0}))
        return 0

    accounts = {e.get("account") for e in entries if e.get("account")}
    services: dict[str, object] = {}
    for acc in accounts:
        if not args.dry_run:
            services[acc] = build_gmail_service(account=acc)

    label_caches: dict[str, dict[str, str]] = {acc: {} for acc in accounts}

    applied: list[dict] = []
    errors = 0

    with state_lock():
        state = load_state()
        prune(state)

        for entry in entries:
            entry = normalize_classification(entry)
            acc = entry.get("account")
            svc = services.get(acc) if not args.dry_run else None

            if args.dry_run or svc is None:
                names = labels_for(entry["category"], entry["quadrant"])
                if entry["needs_action"]:
                    names.append("Casper/Action")
                applied.append({"id": entry["id"], "labels": names, "dry_run": args.dry_run})
                if not args.dry_run:
                    persist(state, entry, names, error=None)
                continue

            result = apply_one(svc, entry, label_caches[acc], dry_run=False)
            applied.append(result)
            err = result.get("error")
            persist(state, entry, result.get("labels") or [], error=err)
            if err:
                errors += 1

        if accounts:
            for acc in accounts:
                state["last_ingest_per_account"][acc] = utc_now()

        if not args.dry_run:
            save_state(state)

    print(json.dumps({"applied": applied, "errors": errors}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
