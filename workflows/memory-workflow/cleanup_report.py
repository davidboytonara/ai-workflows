#!/usr/bin/env python3
"""Report the maintain-memory cleanup buckets: file count + total size each.

Read-only — never deletes anything; it only sizes the destructive offer so the
user can pick which buckets to drop. Buckets:
  sources  workflows/memory-workflow/sources/  (raw provider exports staged
           for extraction)
  review   $HOME/.agents/memory/review/        (extracted review dumps)
  state    $HOME/.agents/state/memory-distill/ (distillation/extraction state)

Exit codes:
  0  at least one bucket has content
  1  nothing to clean — every bucket is empty or missing
  2  usage error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BUCKETS = {
    "sources": Path(__file__).resolve().parent / "sources",
    "review": Path.home() / ".agents" / "memory" / "review",
    "state": Path.home() / ".agents" / "state" / "memory-distill",
}


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


def measure(root: Path) -> dict[str, int | str | bool]:
    files = 0
    total = 0
    if root.is_dir():
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                files += 1
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
    return {"path": str(root), "exists": root.is_dir(), "files": files, "bytes": total}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Count + size the memory cleanup buckets (read-only).")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    report = {name: measure(root) for name, root in BUCKETS.items()}

    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"{'bucket':<9} {'files':>6} {'size':>10}  path")
        for name, info in report.items():
            note = "" if info["exists"] else "  (missing)"
            print(f"{name:<9} {info['files']:>6} {human_size(int(info['bytes'])):>10}  {info['path']}{note}")

    return 0 if any(info["files"] for info in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
