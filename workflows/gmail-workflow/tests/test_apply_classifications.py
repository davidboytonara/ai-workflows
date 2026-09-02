#!/usr/bin/env python3
"""Tests for apply_classifications.py's two-axis (urgency x importance) schema."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply_classifications.py"

# apply_classifications.py resolves "utils.*" against its own directory, same
# as when it's run as `python apply_classifications.py` (sys.path[0] = scripts/).
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))

# The functions under test (normalize_classification, labels_for) never touch
# Gmail; stub out utils.auth_helper so loading this module doesn't require
# the google-api-python-client dependency chain to be installed.
if "utils.auth_helper" not in sys.modules:
    stub = types.ModuleType("utils.auth_helper")
    stub.build_gmail_service = lambda *args, **kwargs: None
    sys.modules["utils.auth_helper"] = stub


def load_module():
    spec = importlib.util.spec_from_file_location("apply_classifications", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class NormalizeClassificationTest(unittest.TestCase):
    def test_urgent_and_important_is_do_now(self) -> None:
        module = load_module()
        entry = module.normalize_classification(
            {"category": "Work", "urgency": "urgent", "importance": "important"}
        )
        self.assertEqual(entry["urgency"], "urgent")
        self.assertEqual(entry["importance"], "important")
        self.assertEqual(entry["quadrant"], "do_now")

    def test_urgent_but_not_important_is_delegate_not_do_now(self) -> None:
        module = load_module()
        entry = module.normalize_classification(
            {"category": "Newsletter", "urgency": "urgent", "importance": "not_important"}
        )
        self.assertEqual(entry["quadrant"], "delegate")

    def test_important_but_not_urgent_is_schedule(self) -> None:
        module = load_module()
        entry = module.normalize_classification(
            {"category": "Work", "urgency": "not_urgent", "importance": "important"}
        )
        self.assertEqual(entry["quadrant"], "schedule")

    def test_missing_axes_default_to_eliminate(self) -> None:
        module = load_module()
        entry = module.normalize_classification({"category": "Promotion"})
        self.assertEqual(entry["urgency"], "not_urgent")
        self.assertEqual(entry["importance"], "not_important")
        self.assertEqual(entry["quadrant"], "eliminate")

    def test_invalid_axis_values_fall_back_to_defaults(self) -> None:
        module = load_module()
        entry = module.normalize_classification(
            {"category": "Work", "urgency": "asap", "importance": "yes"}
        )
        self.assertEqual(entry["urgency"], "not_urgent")
        self.assertEqual(entry["importance"], "not_important")
        self.assertEqual(entry["quadrant"], "eliminate")

    def test_unknown_category_falls_back_to_other(self) -> None:
        module = load_module()
        entry = module.normalize_classification({"category": "Sports"})
        self.assertEqual(entry["category"], "Other")


class LabelsForTest(unittest.TestCase):
    def test_labels_shape_matches_category_quadrant_processed(self) -> None:
        module = load_module()
        labels = module.labels_for("Work", "do_now")
        self.assertEqual(labels, ["Casper/Work", "Casper/DoNow", "Casper/Processed"])

    def test_each_quadrant_has_a_distinct_label(self) -> None:
        module = load_module()
        labels = {module.labels_for("Work", q)[1] for q in ("do_now", "delegate", "schedule", "eliminate")}
        self.assertEqual(len(labels), 4)


if __name__ == "__main__":
    unittest.main()
