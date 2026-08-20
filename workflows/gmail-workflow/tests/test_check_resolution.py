#!/usr/bin/env python3
"""Tests for triage resolution cross-check (entity keys + verdict logic)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from check_resolution import decide_verdict, extract_entity_keys  # noqa: E402


def related(is_own: bool, newer: bool, key: str = "8200020368") -> dict:
    return {
        "id": "m-related",
        "thread_id": "t-related",
        "from": "Me <me@example.com>" if is_own else "Vendor <v@example.com>",
        "subject": "Re: Request Approval",
        "internal_date_ms": 2_000 if newer else 500,
        "is_own": is_own,
        "newer_than_candidate": newer,
        "matched_key": key,
    }


class ExtractEntityKeysTest(unittest.TestCase):
    def test_extracts_all_known_reference_formats(self) -> None:
        text = (
            "PR Number 8200020368 for i-Memo IM-ABC-26061344, "
            "invoice PIINV/2026/00531 and INVID26026 under PO ABC-PO-01-26-0003."
        )
        keys = extract_entity_keys(text)
        self.assertEqual(
            keys,
            ["8200020368", "PIINV/2026/00531", "INVID26026", "IM-ABC-26061344", "ABC-PO-01-26-0003"],
        )

    def test_quotation_ref_and_case_insensitive_dedupe(self) -> None:
        keys = extract_entity_keys("Quotation 075/QUO/ABC/VII/2026 aka piinv/2026/00531 PIINV/2026/00531")
        self.assertEqual(keys, ["piinv/2026/00531", "075/QUO/ABC/VII/2026"])

    def test_caps_at_five_keys(self) -> None:
        text = (
            "8200020368 8200019843 PIINV/2026/00531 PIWIN/2026/0741 "
            "INVID26024 IM-ABC-26061344"
        )
        self.assertEqual(len(extract_entity_keys(text)), 5)

    def test_plain_prose_yields_no_keys(self) -> None:
        self.assertEqual(extract_entity_keys("Please review the attached NDA draft."), [])
        self.assertEqual(extract_entity_keys(""), [])


class DecideVerdictTest(unittest.TestCase):
    def test_in_thread_reply_wins(self) -> None:
        verdict, _ = decide_verdict("replied_after_inbound", [])
        self.assertEqual(verdict, "likely_resolved")

    def test_cross_thread_own_reply_resolves(self) -> None:
        verdict, reason = decide_verdict("not_replied", [related(is_own=True, newer=True)])
        self.assertEqual(verdict, "likely_resolved")
        self.assertIn("8200020368", reason)

    def test_third_party_activity_means_verify(self) -> None:
        verdict, _ = decide_verdict("not_replied", [related(is_own=False, newer=True)])
        self.assertEqual(verdict, "verify")

    def test_older_related_messages_stay_open(self) -> None:
        verdict, _ = decide_verdict("not_replied", [related(is_own=True, newer=False)])
        self.assertEqual(verdict, "open")

    def test_no_evidence_stays_open(self) -> None:
        verdict, _ = decide_verdict("not_replied", [])
        self.assertEqual(verdict, "open")


if __name__ == "__main__":
    unittest.main()
