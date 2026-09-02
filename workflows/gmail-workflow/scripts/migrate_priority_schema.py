#!/usr/bin/env python3
"""Migrate ``state.json`` off the legacy single-field ``importance`` schema.

Nothing else in this workflow requires this script to run first —
``build_attention_view.py`` (via ``utils.priority.quadrant_from_record`` /
``quadrant_from_ledger_entry``) already falls back to mapping the legacy
3-value ``importance`` (``urgent`` / ``important`` / ``low``) onto the same
quadrant space a record with the new ``urgency`` + ``importance`` axes
resolves to. This script exists so a `state.json` can be brought fully onto
the new schema in place — useful for inspection, and so newly-classified
messages and long-since-classified ones read the same way in tooling that
looks at raw records instead of going through ``build_attention_view``.

Legacy -> new-axis mapping (matches ``utils.priority.LEGACY_IMPORTANCE_TO_QUADRANT``):
  urgent    -> urgency=urgent,     importance=important      (do_now)
  important -> urgency=not_urgent, importance=important      (schedule)
  low       -> urgency=not_urgent, importance=not_important  (eliminate)

Out of scope: Gmail labels already applied by past runs (``Casper/Urgent``,
``Casper/Important``, ``Casper/Low``) are left as-is — they are just
historical labels, not read by any script, and harmless leftovers. Only
newly-classified messages get the new ``Casper/<Quadrant>`` label going
forward (``apply_classifications.py``).

Usage:
    migrate_priority_schema.py --dry-run --json   # report only, no writes
    migrate_priority_schema.py                    # apply and save state.json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from utils.priority import QUADRANT_AXES, legacy_quadrant, quadrant_for
from utils.state_io import STATE_PATH, load_state, save_state, state_lock


def migrate_message(rec: dict[str, Any]) -> bool:
    """Add urgency/importance/quadrant in place; return True if changed."""
    if "urgency" in rec and "quadrant" in rec:
        return False
    quadrant = legacy_quadrant(rec.get("importance"))
    urgency, importance = QUADRANT_AXES[quadrant]
    rec["urgency"] = urgency
    rec["importance"] = importance
    rec["quadrant"] = quadrant
    return True


def migrate_ledger_entry(entry: dict[str, Any]) -> bool:
    if "last_quadrant" in entry:
        return False
    quadrant = legacy_quadrant(entry.get("last_importance"))
    urgency, importance = QUADRANT_AXES[quadrant]
    entry["last_urgency"] = urgency
    entry["last_importance"] = importance
    entry["last_quadrant"] = quadrant
    return True


def plan_migration(state: dict[str, Any]) -> dict[str, Any]:
    messages = state.get("messages", {})
    ledger = state.get("notification_ledger", {})
    message_ids = [mid for mid, rec in messages.items() if isinstance(rec, dict) and "urgency" not in rec]
    ledger_keys = [key for key, entry in ledger.items() if isinstance(entry, dict) and "last_quadrant" not in entry]
    return {
        "messages_total": len(messages) if isinstance(messages, dict) else 0,
        "messages_to_migrate": len(message_ids),
        "ledger_entries_total": len(ledger) if isinstance(ledger, dict) else 0,
        "ledger_entries_to_migrate": len(ledger_keys),
    }


def apply_migration(state: dict[str, Any]) -> dict[str, Any]:
    messages = state.get("messages", {})
    ledger = state.get("notification_ledger", {})
    migrated_messages = sum(
        1 for rec in messages.values() if isinstance(rec, dict) and migrate_message(rec)
    ) if isinstance(messages, dict) else 0
    migrated_ledger = sum(
        1 for entry in ledger.values() if isinstance(entry, dict) and migrate_ledger_entry(entry)
    ) if isinstance(ledger, dict) else 0
    return {"messages_migrated": migrated_messages, "ledger_entries_migrated": migrated_ledger}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate state.json message records and notification_ledger entries "
        "off the legacy single-field 'importance' schema onto urgency+importance+quadrant."
    )
    parser.add_argument("--dry-run", action="store_true", help="Report planned changes without saving state")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.dry_run:
        state = load_state()
        plan = plan_migration(state)
        result = {"dry_run": True, "state_path": str(STATE_PATH), **plan}
    else:
        with state_lock():
            state = load_state()
            plan = plan_migration(state)
            applied = apply_migration(state)
            if applied["messages_migrated"] or applied["ledger_entries_migrated"]:
                save_state(state)
        result = {"dry_run": False, "state_path": str(STATE_PATH), **plan, **applied}

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        mode = "dry-run" if result["dry_run"] else "live"
        print(
            f"gmail priority-schema migration {mode}: "
            f"messages {result['messages_to_migrate']}/{result['messages_total']} to migrate, "
            f"ledger {result['ledger_entries_to_migrate']}/{result['ledger_entries_total']} to migrate"
            + (
                f"; migrated messages={result['messages_migrated']} ledger={result['ledger_entries_migrated']}"
                if not result["dry_run"]
                else ""
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
