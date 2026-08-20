#!/usr/bin/env python3
"""Tests for reply-aware Gmail attention status."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_attention_view.py"
DAY_MS = 86400 * 1000


def load_module():
    spec = importlib.util.spec_from_file_location("build_attention_view", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def thread_message(timestamp_ms: int, from_header: str) -> dict:
    return {
        "internalDate": str(timestamp_ms),
        "payload": {
            "headers": [
                {"name": "From", "value": from_header},
                {"name": "Subject", "value": "Renewal"},
            ]
        },
    }


def work_state(timestamp_ms: int, *, message_id: str = "m1", thread_id: str = "t1") -> dict:
    return {
        "messages": {
            message_id: {
                "account": "work",
                "thread_id": thread_id,
                "internal_date_ms": timestamp_ms,
                "from": "Vendor <vendor@example.com>",
                "subject": "Renewal",
                "summary": "Vendor asks for renewal approval",
                "category": "Work",
                "importance": "important",
                "needs_action": True,
            }
        },
        "notification_ledger": {},
    }


class ReplyStatusTest(unittest.TestCase):
    def test_empty_state_with_enrichment_does_not_fetch_threads(self) -> None:
        module = load_module()

        def fetcher(_: str) -> dict:
            raise AssertionError("fetcher should not be called")

        items = module.build_attention_items(
            {"messages": {}, "notification_ledger": {}},
            now_ms=2_000_000_000_000,
            enrich_replies=True,
            own_addresses=["me@example.com"],
            thread_fetcher=fetcher,
        )

        self.assertEqual(items, [])

    def test_user_reply_after_inbound_suppresses_digest(self) -> None:
        module = load_module()
        now_ms = 2_000_000_000_000
        inbound_ms = now_ms - 2 * 3600 * 1000
        reply_ms = now_ms - 3600 * 1000
        state = work_state(inbound_ms)

        def fetcher(thread_id: str) -> dict:
            self.assertEqual(thread_id, "t1")
            return {
                "messages": [
                    thread_message(inbound_ms, "Vendor <vendor@example.com>"),
                    thread_message(reply_ms, "Me <me@example.com>"),
                ]
            }

        item = module.build_attention_items(
            state,
            now_ms=now_ms,
            channel="digest",
            enrich_replies=True,
            own_addresses=["me@example.com"],
            thread_fetcher=fetcher,
            reply_resolution_days=3,
        )[0]

        self.assertEqual(item["reply_state"], "replied_after_inbound")
        self.assertEqual(item["latest_user_reply_ms"], reply_ms)
        self.assertEqual(item["latest_inbound_ms"], inbound_ms)
        self.assertEqual(item["waiting_on"], "other_party")
        self.assertEqual(item["status"], "awaiting_other_party")
        self.assertEqual(item["notification"]["action"], "suppress")
        self.assertEqual(item["notification"]["reason"], "awaiting_other_party")

    def test_user_reply_quiet_for_resolution_window_becomes_likely_resolved(self) -> None:
        module = load_module()
        now_ms = 2_000_000_000_000
        inbound_ms = now_ms - 5 * DAY_MS
        reply_ms = now_ms - 4 * DAY_MS
        state = work_state(inbound_ms)

        def fetcher(_: str) -> dict:
            return {
                "messages": [
                    thread_message(inbound_ms, "Vendor <vendor@example.com>"),
                    thread_message(reply_ms, "me@example.com"),
                ]
            }

        item = module.build_attention_items(
            state,
            now_ms=now_ms,
            channel="urgent",
            enrich_replies=True,
            own_addresses=["me@example.com"],
            thread_fetcher=fetcher,
            reply_resolution_days=3,
        )[0]

        self.assertEqual(item["reply_state"], "replied_after_inbound")
        self.assertEqual(item["status"], "likely_resolved")
        self.assertEqual(item["waiting_on"], "other_party")
        self.assertEqual(item["notification"]["action"], "suppress")

    def test_new_inbound_after_user_reply_reopens_item(self) -> None:
        module = load_module()
        now_ms = 2_000_000_000_000
        inbound_1_ms = now_ms - 3 * DAY_MS
        reply_ms = now_ms - 2 * DAY_MS
        inbound_2_ms = now_ms - DAY_MS
        state = work_state(inbound_2_ms, message_id="m2")
        state["messages"]["m1"] = {
            **state["messages"]["m2"],
            "internal_date_ms": inbound_1_ms,
            "summary": "Vendor asks for renewal approval",
        }
        state["notification_ledger"] = {
            "thread:work:t1": {
                "last_notified_at": "2026-04-26T03:01:22Z",
                "last_notified_channel": "digest",
                "last_fingerprint": "sha1:old",
                "last_importance": "important",
                "last_status": "awaiting_other_party",
                "last_seen_ms": inbound_1_ms,
                "notified_message_ids": ["m1"],
            }
        }

        def fetcher(_: str) -> dict:
            return {
                "messages": [
                    thread_message(inbound_1_ms, "Vendor <vendor@example.com>"),
                    thread_message(reply_ms, "Me <me@example.com>"),
                    thread_message(inbound_2_ms, "Vendor <vendor@example.com>"),
                ]
            }

        item = module.build_attention_items(
            state,
            now_ms=now_ms,
            channel="digest",
            enrich_replies=True,
            own_addresses=["me@example.com"],
            thread_fetcher=fetcher,
        )[0]

        self.assertEqual(item["reply_state"], "inbound_after_reply")
        self.assertEqual(item["latest_user_reply_ms"], reply_ms)
        self.assertEqual(item["latest_inbound_ms"], inbound_2_ms)
        self.assertEqual(item["waiting_on"], "user")
        self.assertEqual(item["status"], "reopened")
        self.assertEqual(item["notification"]["action"], "include_digest")
        self.assertEqual(item["notification"]["reason"], "reopened")

        state["notification_ledger"]["thread:work:t1"] = {
            "last_notified_at": "2026-04-26T03:02:22Z",
            "last_notified_channel": "digest",
            "last_fingerprint": item["current_fingerprint"],
            "last_importance": "important",
            "last_status": "reopened",
            "last_seen_ms": inbound_2_ms,
            "notified_message_ids": ["m1", "m2"],
        }
        repeated = module.build_attention_items(
            state,
            now_ms=now_ms,
            channel="digest",
            enrich_replies=True,
            own_addresses=["me@example.com"],
            thread_fetcher=fetcher,
        )[0]
        self.assertEqual(repeated["status"], "reopened")
        self.assertEqual(repeated["notification"]["action"], "suppress")
        self.assertEqual(repeated["notification"]["reason"], "same_fingerprint")

    def test_thread_fetch_failure_degrades_to_phase_two_behavior(self) -> None:
        module = load_module()
        now_ms = 2_000_000_000_000
        state = work_state(now_ms)

        def fetcher(_: str) -> dict:
            raise RuntimeError("api unavailable")

        item = module.build_attention_items(
            state,
            now_ms=now_ms,
            channel="digest",
            enrich_replies=True,
            own_addresses=["me@example.com"],
            thread_fetcher=fetcher,
        )[0]

        self.assertEqual(item["reply_state"], "unknown")
        self.assertEqual(item["waiting_on"], "unknown")
        self.assertEqual(item["status"], "open")
        self.assertEqual(item["notification"]["action"], "include_digest")
        self.assertEqual(item["notification"]["reason"], "new_item")


if __name__ == "__main__":
    unittest.main()
