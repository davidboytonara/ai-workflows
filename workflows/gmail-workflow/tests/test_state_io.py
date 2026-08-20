#!/usr/bin/env python3
"""Tests for shared Gmail state I/O helpers."""

from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "utils" / "state_io.py"


def load_module():
    spec = importlib.util.spec_from_file_location("state_io", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class StateIoTest(unittest.TestCase):
    def test_empty_state_includes_notification_ledger(self) -> None:
        module = load_module()
        state = module.empty_state()
        self.assertEqual(state["notification_ledger"], {})

    def test_prune_keeps_recent_valid_ledger_and_drops_old_or_malformed(self) -> None:
        module = load_module()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        recent_ms = now_ms - 10 * 86400 * 1000
        old_ms = now_ms - 46 * 86400 * 1000
        state = {
            "messages": {},
            "topic_counts": {},
            "last_ingest_per_account": {},
            "notification_ledger": {
                "recent": {
                    "last_notified_at": "2026-04-26T03:01:22Z",
                    "last_notified_channel": "digest",
                    "last_fingerprint": "sha1:abc",
                    "last_importance": "important",
                    "last_status": "open",
                    "last_seen_ms": recent_ms,
                    "notified_message_ids": ["m1"],
                },
                "old": {
                    "last_notified_at": "2026-04-26T03:01:22Z",
                    "last_notified_channel": "digest",
                    "last_fingerprint": "sha1:old",
                    "last_seen_ms": old_ms,
                    "notified_message_ids": ["m0"],
                },
                "bad": {"last_seen_ms": recent_ms, "last_notified_channel": "sms"},
            },
        }

        module.prune(state)
        self.assertEqual(list(state["notification_ledger"]), ["recent"])


if __name__ == "__main__":
    unittest.main()
