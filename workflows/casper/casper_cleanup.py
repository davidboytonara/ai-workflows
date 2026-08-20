#!/usr/bin/env python3
"""Remove a fully-resolved casper handover dir — the final workflow step.

The handover dir is transient resumable state; once the goal is proven finished
it is noise. This script deletes it ONLY when that proof holds:
  - the dir looks like a casper handover (goal.md present; never / or $HOME)
  - the ledger exists and every plan is done (including no live in_progress lease)
  - verify.json exists and every criterion has status "pass"

--force skips the resolved/verified checks (for abandoning a goal); the shape
check always applies. Refusal deletes nothing, so it is always safe to attempt.

Exit codes:
  0  removed
  1  refused — nothing deleted
  2  usage error
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import casper_status as cs  # bundled sibling; script dir is on sys.path


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove a fully-resolved casper handover dir.")
    ap.add_argument("--handover-dir", required=True, type=Path)
    ap.add_argument("--force", action="store_true",
                    help="Skip the resolved/verified checks (abandoned goal); "
                         "the shape check still applies")
    args = ap.parse_args()

    hd = args.handover_dir.resolve()
    if hd in (Path("/"), Path.home()) or not (hd / "goal.md").exists():
        print(f"refusing: {hd} does not look like a casper handover dir (no goal.md)",
              file=sys.stderr)
        return 1

    if not args.force:
        if not cs.ledger_path(hd).exists():
            print(f"refusing: no ledger at {cs.ledger_path(hd)} — nothing was dispatched; "
                  "use --force to remove an abandoned goal", file=sys.stderr)
            return 1
        open_plans = cs.list_unresolved(hd)
        if open_plans:
            print("refusing: unresolved plans remain (re-run the fan-out, or --force):",
                  file=sys.stderr)
            for f in open_plans:
                print(f"  {f}", file=sys.stderr)
            return 1
        vpath = hd / "verify.json"
        try:
            verdicts = json.loads(vpath.read_text())
            if not (isinstance(verdicts, list) and verdicts):
                raise ValueError("not a non-empty JSON array")
        except (OSError, ValueError) as e:
            print(f"refusing: {vpath} unusable ({e}) — run step 5 first, or --force",
                  file=sys.stderr)
            return 1
        failing = [v for v in verdicts if v.get("status") != "pass"]
        if failing:
            print("refusing: criteria not passing:", file=sys.stderr)
            for v in failing:
                print(f"  {v.get('criterion', '?')}: {v.get('status')}", file=sys.stderr)
            return 1

    shutil.rmtree(hd)
    print(f"removed {hd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
