"""work-with-workflow test fixtures: inject only this workflow's dir into sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

_WORKFLOW_DIR = Path(__file__).resolve().parents[1]
if str(_WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKFLOW_DIR))
