#!/usr/bin/env python3
"""Smoke tests for build_attention_view.py."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_attention_view.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_attention_view", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BuildAttentionViewTest(unittest.TestCase):
    def test_missing_state_json_returns_empty_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp}
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--json"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"items": []})

    def test_groups_thread_and_aggregates_fields(self) -> None:
        module = load_module()
        day_ms = 86400 * 1000
        now_ms = 2_000_000_000_000
        state = {
            "messages": {
                "old": {
                    "account": "work",
                    "thread_id": "old-thread",
                    "internal_date_ms": now_ms - 31 * day_ms,
                    "importance": "urgent",
                },
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "topic_key": "example.com|renewal",
                    "internal_date_ms": now_ms - day_ms,
                    "from": "a@example.com",
                    "subject": "First",
                    "summary": "First summary",
                    "category": "Work",
                    "importance": "low",
                    "needs_action": False,
                },
                "m2": {
                    "account": "work",
                    "thread_id": "t1",
                    "topic_key": "example.com|renewal",
                    "internal_date_ms": now_ms,
                    "from": "b@example.com",
                    "subject": "Latest",
                    "summary": "Latest summary",
                    "category": "Finance",
                    "importance": "important",
                    "needs_action": True,
                },
            }
        }

        items = module.build_attention_items(state, now_ms=now_ms)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["item_key"], "thread:work:t1")
        self.assertEqual(item["message_ids"], ["m1", "m2"])
        self.assertEqual(item["message_count"], 2)
        self.assertEqual(item["latest_message_id"], "m2")
        self.assertEqual(item["latest_subject"], "Latest")
        self.assertEqual(item["category"], "Finance")
        self.assertEqual(item["categories_seen"], ["Finance", "Work"])
        self.assertEqual(item["importance_current"], "important")
        self.assertTrue(item["needs_action"])
        self.assertEqual(item["needs_action_count"], 1)
        self.assertEqual(item["status"], "open")
        self.assertTrue(item["current_fingerprint"].startswith("sha1:"))

    def test_digest_notification_suppresses_same_fingerprint(self) -> None:
        module = load_module()
        now_ms = 2_000_000_000_000
        state = {
            "messages": {
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "internal_date_ms": now_ms,
                    "from": "a@example.com",
                    "subject": "Update",
                    "summary": "Needs review",
                    "category": "Work",
                    "importance": "important",
                    "needs_action": True,
                }
            },
            "notification_ledger": {},
        }

        first = module.build_attention_items(state, now_ms=now_ms, channel="digest")[0]
        self.assertEqual(first["notification"]["action"], "include_digest")
        self.assertEqual(first["notification"]["reason"], "new_item")

        state["notification_ledger"][first["item_key"]] = {
            "last_notified_at": "2026-04-26T03:01:22Z",
            "last_notified_channel": "digest",
            "last_fingerprint": first["current_fingerprint"],
            "last_importance": "important",
            "last_status": "open",
            "last_seen_ms": now_ms,
            "notified_message_ids": ["m1"],
        }
        second = module.build_attention_items(state, now_ms=now_ms, channel="digest")[0]
        self.assertEqual(second["notification"]["action"], "suppress")
        self.assertEqual(second["notification"]["reason"], "same_fingerprint")
        self.assertEqual(second["notification"]["previous_channel"], "digest")

        state["messages"]["m2"] = {
            "account": "work",
            "thread_id": "t1",
            "internal_date_ms": now_ms + 1,
            "from": "b@example.com",
            "subject": "Update 2",
            "summary": "New reply",
            "category": "Work",
            "importance": "important",
            "needs_action": True,
        }
        changed = module.build_attention_items(state, now_ms=now_ms + 1, channel="digest")[0]
        self.assertEqual(changed["notification"]["action"], "include_digest")
        self.assertEqual(changed["notification"]["reason"], "changed")

    def test_malformed_ledger_entry_is_treated_as_new(self) -> None:
        module = load_module()
        now_ms = 2_000_000_000_000
        state = {
            "messages": {
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "internal_date_ms": now_ms,
                    "from": "a@example.com",
                    "subject": "Update",
                    "summary": "Needs review",
                    "category": "Work",
                    "importance": "important",
                    "needs_action": True,
                }
            },
            "notification_ledger": {
                "thread:work:t1": {"last_fingerprint": "sha1:any", "last_notified_channel": "sms"}
            },
        }

        item = module.build_attention_items(state, now_ms=now_ms, channel="digest")[0]
        self.assertEqual(item["notification"]["action"], "include_digest")
        self.assertEqual(item["notification"]["reason"], "new_item")

    def test_stale_ledger_entry_is_treated_as_new(self) -> None:
        module = load_module()
        day_ms = 86400 * 1000
        now_ms = 2_000_000_000_000
        state = {
            "messages": {
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "internal_date_ms": now_ms,
                    "from": "a@example.com",
                    "subject": "Update",
                    "summary": "Needs review",
                    "category": "Work",
                    "importance": "important",
                    "needs_action": True,
                }
            },
            "notification_ledger": {
                "thread:work:t1": {
                    "last_notified_at": "2026-04-26T03:01:22Z",
                    "last_notified_channel": "digest",
                    "last_fingerprint": "sha1:any",
                    "last_importance": "important",
                    "last_status": "open",
                    "last_seen_ms": now_ms - 46 * day_ms,
                    "notified_message_ids": ["m1"],
                }
            },
        }

        item = module.build_attention_items(state, now_ms=now_ms, channel="digest")[0]
        self.assertEqual(item["notification"]["action"], "include_digest")
        self.assertEqual(item["notification"]["reason"], "new_item")

    def test_digest_includes_changed_urgent_fallback(self) -> None:
        module = load_module()
        now_ms = 2_000_000_000_000
        state = {
            "messages": {
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "internal_date_ms": now_ms,
                    "from": "a@example.com",
                    "subject": "Urgent",
                    "summary": "New urgent reply",
                    "category": "Work",
                    "importance": "urgent",
                    "needs_action": True,
                }
            },
            "notification_ledger": {
                "thread:work:t1": {
                    "last_notified_at": "2026-04-26T03:01:22Z",
                    "last_notified_channel": "urgent",
                    "last_fingerprint": "sha1:old",
                    "last_importance": "urgent",
                    "last_status": "open",
                    "last_seen_ms": now_ms - 1,
                    "notified_message_ids": ["m0"],
                }
            },
        }

        item = module.build_attention_items(state, now_ms=now_ms, channel="digest")[0]
        self.assertEqual(item["notification"]["action"], "include_digest")
        self.assertEqual(item["notification"]["reason"], "changed")

    def test_urgent_notification_pushes_escalated_item(self) -> None:
        module = load_module()
        now_ms = 2_000_000_000_000
        state = {
            "messages": {
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "internal_date_ms": now_ms,
                    "from": "a@example.com",
                    "subject": "Escalation",
                    "summary": "Now urgent",
                    "category": "Work",
                    "importance": "urgent",
                    "needs_action": True,
                }
            },
            "notification_ledger": {
                "thread:work:t1": {
                    "last_notified_at": "2026-04-26T03:01:22Z",
                    "last_notified_channel": "digest",
                    "last_fingerprint": "sha1:old",
                    "last_importance": "important",
                    "last_status": "open",
                    "last_seen_ms": now_ms,
                    "notified_message_ids": ["m1"],
                }
            },
        }

        item = module.build_attention_items(state, now_ms=now_ms, channel="urgent")[0]
        self.assertEqual(item["notification"]["action"], "push_urgent")
        self.assertEqual(item["notification"]["reason"], "escalated")

    def test_done_memory_suppresses_same_day_email(self) -> None:
        module = load_module()
        now_ms = int(datetime(2026, 4, 26, 12, tzinfo=timezone.utc).timestamp() * 1000)
        state = {
            "messages": {
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "internal_date_ms": now_ms,
                    "from": "a@example.com",
                    "subject": "Finished task",
                    "summary": "Reminder",
                    "category": "Work",
                    "importance": "important",
                    "needs_action": True,
                }
            },
            "notification_ledger": {},
        }
        memory_records = [
            {
                "scope": "project:demo",
                "path": "/tmp/memory/project/demo/open-task.md",
                "status": "done",
                "updated": "2026-04-26",
                "related": ["gmail-thread:work:t1"],
            }
        ]

        item = module.build_attention_items(
            state,
            now_ms=now_ms,
            channel="digest",
            use_memory=True,
            memory_project="demo",
            memory_records=memory_records,
        )[0]

        self.assertEqual(item["memory"]["match_reason"], "related:gmail-thread")
        self.assertEqual(item["notification"]["action"], "suppress")
        self.assertEqual(item["notification"]["reason"], "memory_done")

    def test_related_block_list_memory_matches_thread(self) -> None:
        module = load_module()
        now_ms = int(datetime(2026, 4, 26, 12, tzinfo=timezone.utc).timestamp() * 1000)
        state = {
            "messages": {
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "internal_date_ms": now_ms,
                    "from": "a@example.com",
                    "subject": "Finished task",
                    "summary": "Reminder",
                    "category": "Work",
                    "importance": "important",
                    "needs_action": True,
                }
            },
            "notification_ledger": {},
        }

        with tempfile.TemporaryDirectory() as tmp:
            memory_path = Path(tmp) / "open-task.md"
            memory_path.write_text(
                "---\n"
                "type: memory\n"
                "memory_type: open\n"
                "related:\n"
                "  - gmail-thread:work:t1\n"
                "---\n"
                "Task body.\n",
                encoding="utf-8",
            )
            item = module.build_attention_items(
                state,
                now_ms=now_ms,
                channel="digest",
                use_memory=True,
                memory_project="demo",
                memory_records=[
                    {
                        "scope": "project:demo",
                        "path": str(memory_path),
                        "status": "done",
                        "updated": "2026-04-26",
                    }
                ],
            )[0]

        self.assertEqual(item["memory"]["match_reason"], "related:gmail-thread")
        self.assertEqual(item["notification"]["reason"], "memory_done")

    def test_done_memory_newer_email_reopens_with_reason(self) -> None:
        module = load_module()
        now_ms = int(datetime(2026, 4, 26, 12, tzinfo=timezone.utc).timestamp() * 1000)
        state = {
            "messages": {
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "internal_date_ms": now_ms,
                    "from": "a@example.com",
                    "subject": "Finished task",
                    "summary": "New urgent follow-up",
                    "category": "Work",
                    "importance": "urgent",
                    "needs_action": True,
                }
            },
            "notification_ledger": {},
        }
        memory_records = [
            {
                "scope": "project:demo",
                "path": "/tmp/memory/project/demo/open-task.md",
                "status": "done",
                "updated": "2026-04-25",
                "related": ["gmail-thread:work:t1"],
            }
        ]

        item = module.build_attention_items(
            state,
            now_ms=now_ms,
            channel="urgent",
            use_memory=True,
            memory_project="demo",
            memory_records=memory_records,
        )[0]

        self.assertEqual(item["status"], "reopened")
        self.assertEqual(item["notification"]["action"], "push_urgent")
        self.assertEqual(item["notification"]["reason"], "new_email_after_memory_done")

    def test_memory_keyword_match_is_exact_and_project_scoped(self) -> None:
        module = load_module()
        now_ms = int(datetime(2026, 4, 26, 12, tzinfo=timezone.utc).timestamp() * 1000)
        state = {
            "messages": {
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "topic_key": "example.com|onboarding",
                    "internal_date_ms": now_ms,
                    "from": "a@example.com",
                    "subject": "Status update",
                    "summary": "Routine reminder",
                    "category": "Work",
                    "importance": "important",
                    "needs_action": False,
                }
            },
            "notification_ledger": {},
        }

        no_match = module.build_attention_items(
            state,
            now_ms=now_ms,
            channel="digest",
            use_memory=True,
            memory_project="demo",
            memory_records=[
                {"scope": "project:demo", "status": "active", "updated": "2026-04-26", "keywords": ["onboarding"]},
                {"scope": "global", "status": "done", "updated": "2026-04-26", "keywords": ["example.com|onboarding"]},
            ],
        )[0]
        self.assertNotIn("memory", no_match)
        self.assertEqual(no_match["notification"]["action"], "include_digest")

        exact_match = module.build_attention_items(
            state,
            now_ms=now_ms,
            channel="digest",
            use_memory=True,
            memory_project="demo",
            memory_records=[
                {
                    "scope": "project:demo",
                    "path": "/tmp/memory/project/demo/open-onboarding.md",
                    "status": "active",
                    "updated": "2026-04-26",
                    "keywords": ["example.com|onboarding"],
                    "next_action": "Wait for vendor",
                }
            ],
        )[0]
        self.assertEqual(exact_match["memory"]["match_reason"], "keyword:exact")
        self.assertEqual(exact_match["memory"]["next_action"], "Wait for vendor")
        self.assertEqual(exact_match["notification"]["action"], "suppress")
        self.assertEqual(exact_match["notification"]["reason"], "memory_static")

    def test_blocked_memory_allows_inbound_after_user_reply_even_when_low(self) -> None:
        module = load_module()
        now_ms = int(datetime(2026, 4, 26, 12, tzinfo=timezone.utc).timestamp() * 1000)
        reply_ms = int(datetime(2026, 4, 25, 12, tzinfo=timezone.utc).timestamp() * 1000)
        state = {
            "messages": {
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "internal_date_ms": now_ms,
                    "from": "a@example.com",
                    "subject": "Blocked task",
                    "summary": "New non-urgent reply",
                    "category": "Work",
                    "importance": "low",
                    "needs_action": False,
                }
            },
            "notification_ledger": {},
        }

        def fetcher(_thread_id: str) -> dict[str, object]:
            return {
                "messages": [
                    {
                        "internalDate": str(reply_ms),
                        "payload": {"headers": [{"name": "From", "value": "Me <me@example.com>"}]},
                    },
                    {
                        "internalDate": str(now_ms),
                        "payload": {"headers": [{"name": "From", "value": "Vendor <a@example.com>"}]},
                    },
                ]
            }

        item = module.build_attention_items(
            state,
            now_ms=now_ms,
            channel="digest",
            enrich_replies=True,
            own_addresses=["me@example.com"],
            thread_fetcher=fetcher,
            use_memory=True,
            memory_project="demo",
            memory_records=[
                {
                    "scope": "project:demo",
                    "path": "/tmp/memory/project/demo/open-blocked.md",
                    "status": "blocked",
                    "updated": "2026-04-25",
                    "related": ["gmail-thread:work:t1"],
                }
            ],
        )[0]

        self.assertEqual(item["reply_state"], "inbound_after_reply")
        self.assertEqual(item["notification"]["action"], "include_digest")
        self.assertNotEqual(item["notification"]["reason"], "memory_blocked")

    def test_blocked_memory_suppresses_normal_reminder(self) -> None:
        module = load_module()
        now_ms = int(datetime(2026, 4, 26, 12, tzinfo=timezone.utc).timestamp() * 1000)
        state = {
            "messages": {
                "m1": {
                    "account": "work",
                    "thread_id": "t1",
                    "internal_date_ms": now_ms,
                    "from": "a@example.com",
                    "subject": "Routine update",
                    "summary": "No change",
                    "category": "Work",
                    "importance": "important",
                    "needs_action": False,
                }
            },
            "notification_ledger": {},
        }
        item = module.build_attention_items(
            state,
            now_ms=now_ms,
            channel="digest",
            use_memory=True,
            memory_project="demo",
            memory_records=[
                {
                    "scope": "project:demo",
                    "path": "/tmp/memory/project/demo/open-blocked.md",
                    "status": "blocked",
                    "updated": "2026-04-25",
                    "blocked_by": "vendor",
                    "related": ["gmail-thread:work:t1"],
                }
            ],
        )[0]

        self.assertEqual(item["memory"]["blocked_by"], "vendor")
        self.assertEqual(item["notification"]["action"], "suppress")
        self.assertEqual(item["notification"]["reason"], "memory_blocked")


if __name__ == "__main__":
    unittest.main()
