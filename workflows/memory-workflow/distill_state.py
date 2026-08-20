#!/usr/bin/env python3
"""Own the distill state file: inventory unprocessed review dumps, record
per-file results, and check consistency.

State: $HOME/.agents/state/memory-distill/distill_memories.json — a flat
mapping of review-file path -> {size, mtime_ns, processed_at,
candidates_written, candidates_skipped, skipped_reasons,
candidates_written_by_type} (shape: **State-file shape** in
distill-reference.md). A review file is unprocessed if its path is not in
state or its size/mtime_ns differ.

Subcommands:
  list    Inventory unprocessed review files under
          $HOME/.agents/memory/review/, oldest mtime first, capped by --limit.
  record  Update the entry for one review file and atomically persist the
          full state (write .tmp, os.replace). candidates_skipped is derived
          from the skipped-reasons array, so the count is consistent by
          construction; reasons are validated against the closed vocabulary.
  check   Verify the state file exists, parses, and every entry satisfies
          candidates_skipped == len(skipped_reasons).

Exit codes:
  0  success (list: pending files exist; record: persisted; check: consistent)
  1  nothing to do / check failed (list: no unprocessed files, incl. missing
     review root or store; check: state missing, unparsable, or inconsistent)
  2  usage or validation error (bad args, bad JSON input, invalid reason or
     type, unreadable state file for list/record)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REVIEW_ROOT = Path.home() / ".agents" / "memory" / "review"
STATE_PATH = Path.home() / ".agents" / "state" / "memory-distill" / "distill_memories.json"
DEFAULT_LIMIT = 100
MEMORY_TYPES = ("rule", "fact", "workflow", "open", "finding")
SKIP_REASONS = {
    "obvious duplicate",
    "near-dup same idea",
    "not durable/task-specific",
    "stale/resolved open item",
    "derivable/documented elsewhere",
    "unsupported/unsafe/uncertain candidate",
    "writer error/conflict",
    "failed-acid-test-or-calibration",
}


def fail(message: str) -> "SystemExit":
    print(f"error: {message}", file=sys.stderr)
    return SystemExit(2)


def load_state(strict: bool = True) -> dict[str, Any] | None:
    """Return the state mapping; {} when the file does not exist yet.

    strict=True raises usage-error (2) on unreadable/invalid state so callers
    never silently clobber a corrupt file; strict=False returns None instead.
    """
    if not STATE_PATH.exists():
        return {}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            raise fail(f"state file unreadable/invalid: {STATE_PATH} ({exc})")
        return None
    if not isinstance(state, dict):
        if strict:
            raise fail(f"state file is not a JSON object: {STATE_PATH}")
        return None
    return state


def save_state_atomic(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=STATE_PATH.parent, prefix=STATE_PATH.name, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_name, STATE_PATH)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def is_unprocessed(state: dict[str, Any], path: Path, stat_result: os.stat_result) -> bool:
    entry = state.get(str(path))
    if not isinstance(entry, dict):
        return True
    return (
        entry.get("size") != stat_result.st_size
        or entry.get("mtime_ns") != stat_result.st_mtime_ns
    )


def cmd_list(args: argparse.Namespace) -> int:
    state = load_state()
    assert state is not None
    pending: list[dict[str, Any]] = []
    if REVIEW_ROOT.is_dir():
        for path in REVIEW_ROOT.rglob("*.md"):
            try:
                stat_result = path.stat()
            except OSError:
                continue
            if is_unprocessed(state, path, stat_result):
                pending.append(
                    {
                        "path": str(path),
                        "size": stat_result.st_size,
                        "mtime_ns": stat_result.st_mtime_ns,
                    }
                )
    pending.sort(key=lambda item: (item["mtime_ns"], item["path"]))
    total = len(pending)
    pending = pending[: args.limit]

    if args.format == "json":
        print(
            json.dumps(
                {"total_unprocessed": total, "returned": len(pending), "limit": args.limit, "pending": pending},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"unprocessed: {total} (showing {len(pending)}, limit {args.limit})")
        for item in pending:
            print(item["path"])
    return 0 if pending else 1


def parse_by_type(raw: str | None, written: int) -> dict[str, int]:
    by_type = {memory_type: 0 for memory_type in MEMORY_TYPES}
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            key, sep, value = part.partition("=")
            if not sep or key.strip() not in MEMORY_TYPES or not value.strip().isdigit():
                raise fail(f"--by-type expects <type>=<count> csv with types {MEMORY_TYPES}; got {part!r}")
            by_type[key.strip()] = int(value.strip())
    if sum(by_type.values()) != written:
        raise fail(
            f"--by-type counts sum to {sum(by_type.values())} but --written is {written}"
            + ("" if raw else " (pass --by-type when --written > 0)")
        )
    return by_type


def parse_skipped(raw: str) -> list[dict[str, str]]:
    if raw == "-":
        raw = sys.stdin.read()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise fail(f"--skipped-json is not valid JSON: {exc}")
    if not isinstance(parsed, list):
        raise fail("--skipped-json must be a JSON array")
    entries: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict) or not {"type", "candidate", "reason"} <= set(item):
            raise fail(f"skipped entry needs type/candidate/reason keys: {item!r}")
        if item["type"] not in MEMORY_TYPES:
            raise fail(f"skipped entry type must be one of {MEMORY_TYPES}: {item!r}")
        if item["reason"] not in SKIP_REASONS:
            raise fail(f"skipped entry reason must be one of {sorted(SKIP_REASONS)}: {item['reason']!r}")
        entries.append({"type": str(item["type"]), "candidate": str(item["candidate"]), "reason": str(item["reason"])})
    return entries


def cmd_record(args: argparse.Namespace) -> int:
    review_path = Path(args.review_file).expanduser().resolve()
    try:
        stat_result = review_path.stat()
    except OSError as exc:
        raise fail(f"review file unreadable: {exc}")

    skipped = parse_skipped(args.skipped_json)
    by_type = parse_by_type(args.by_type, args.written)

    state = load_state()
    assert state is not None
    entry = {
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
        "processed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidates_written": args.written,
        "candidates_skipped": len(skipped),
        "skipped_reasons": skipped,
        "candidates_written_by_type": by_type,
    }
    state[str(review_path)] = entry
    save_state_atomic(state)
    print(json.dumps({"status": "recorded", "state": str(STATE_PATH), "path": str(review_path), "entry": entry}, indent=2, ensure_ascii=False))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    if not STATE_PATH.exists():
        print(f"FAIL: state file missing: {STATE_PATH}")
        return 1
    state = load_state(strict=False)
    if state is None:
        print(f"FAIL: state file unreadable or not a JSON object: {STATE_PATH}")
        return 1
    bad = [
        key
        for key, value in state.items()
        if not isinstance(value, dict)
        or value.get("candidates_skipped") != len(value.get("skipped_reasons", []))
    ]
    print("entries:", len(state), "| inconsistent:", bad or "none")
    return 1 if bad else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Distill state: inventory, record, consistency check. See module docstring for exit codes.")
    parser.add_argument("--state-file", default=None, help="Override the state file path (testing).")
    parser.add_argument("--review-root", default=None, help="Override the review root (testing).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Inventory unprocessed review files, oldest mtime first.")
    p_list.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Per-run cap (default {DEFAULT_LIMIT}).")
    p_list.add_argument("--format", choices=("json", "text"), default="json")
    p_list.set_defaults(func=cmd_list)

    p_record = sub.add_parser("record", help="Record one review file's result and persist the state atomically.")
    p_record.add_argument("review_file", help="Path to the processed review dump.")
    p_record.add_argument("--written", type=int, required=True, help="Count of memories written for this file.")
    p_record.add_argument("--by-type", default=None, metavar="rule=1,finding=2", help="Written counts per memory type; must sum to --written.")
    p_record.add_argument("--skipped-json", default="[]", help="JSON array of {type,candidate,reason} skip entries, or '-' for stdin.")
    p_record.set_defaults(func=cmd_record)

    p_check = sub.add_parser("check", help="Verify state exists and skip counts are consistent.")
    p_check.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str]) -> int:
    global STATE_PATH, REVIEW_ROOT
    args = build_parser().parse_args(argv)
    if args.state_file:
        STATE_PATH = Path(args.state_file).expanduser().resolve()
    if args.review_root:
        REVIEW_ROOT = Path(args.review_root).expanduser().resolve()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
