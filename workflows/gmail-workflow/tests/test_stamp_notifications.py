#!/usr/bin/env python3
"""Tests for stamp_notifications.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "stamp_notifications.py"


class StampNotificationsTest(unittest.TestCase):
    def test_stamps_ledger_and_preserves_existing_message_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / ".agents" / "state" / "gmail-ingest"
            state_dir.mkdir(parents=True)
            state_path = state_dir / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "updated": "2026-04-26T00:00:00Z",
                        "messages": {
                            "m1": {
                                "internal_date_ms": 2_000_000_000_000,
                                "pushed": {"urgent": None, "digest": "old-digest"},
                            },
                            "m2": {
                                "internal_date_ms": 2_000_000_000_001,
                                "pushed": {"urgent": None, "digest": None},
                            },
                        },
                        "topic_counts": {},
                        "last_ingest_per_account": {},
                        "notification_ledger": {},
                    }
                ),
                encoding="utf-8",
            )
            payload = {
                "channel": "digest",
                "items": [
                    {
                        "item_key": "thread:work:t1",
                        "current_fingerprint": "sha1:abc",
                        "urgency_current": "not_urgent",
                        "importance_current": "important",
                        "quadrant_current": "schedule",
                        "status": "open",
                        "last_seen_ms": 2_000_000_000_001,
                        "message_ids": ["m1", "m2"],
                    }
                ],
            }
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", "-"],
                input=json.dumps(payload),
                env={**os.environ, "HOME": tmp},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            result = json.loads(proc.stdout)
            self.assertEqual(result["stamped_items"], 1)
            self.assertEqual(result["stamped_messages"], 2)

            state = json.loads(state_path.read_text(encoding="utf-8"))
            ledger = state["notification_ledger"]["thread:work:t1"]
            self.assertEqual(ledger["last_notified_channel"], "digest")
            self.assertEqual(ledger["last_fingerprint"], "sha1:abc")
            self.assertEqual(ledger["last_quadrant"], "schedule")
            self.assertEqual(ledger["notified_message_ids"], ["m1", "m2"])
            self.assertEqual(state["messages"]["m1"]["pushed"]["digest"], "old-digest")
            self.assertRegex(state["messages"]["m2"]["pushed"]["digest"], r"^\d{4}-\d{2}-\d{2}T")


if __name__ == "__main__":
    unittest.main()
