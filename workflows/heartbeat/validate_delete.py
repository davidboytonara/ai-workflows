#!/usr/bin/env python3
"""Post-delete residue validation for a heartbeat task.

Deterministic version of the Delete done-criteria in heartbeat-task.md: after a
task is removed, verify nothing still references it and its per-task locations
are gone. Read-only — never modifies tasks.yaml, state, or secrets.

Checks (one PASS/FAIL line each):
  1. tasks.yaml has no entry named <task> and no depends_on referencing it.
  2. No text-file hit for the task name under <casper-root>/workflows/.
     Skips this folder's own lifecycle docs (heartbeat-task.md,
     lifecycle-reference.md — they cite task names as examples).
  3. workflows/<task>/, state/<task>/ and secrets/<task>/ are gone.
  4. state/history/<task>.jsonl is gone — or present when --keep-history says
     the user chose to keep the audit trail.
  5. No open clarify file state/clarify/<task>-*.md
     (archived ones under state/clarify/resolved/ may stay).
  6. No secrets/heartbeat.env line mentioning the task name (checks the
     underscore variant too). Task-unique vars whose names do not contain the
     task name still need operator judgment — this check cannot see those.

WARN only (never affects the exit code):
  - Residual <task> key in state/heartbeat/tasks.json — the daemon ignores
    names absent from tasks.yaml; the default is to leave it and tell the user.

Exit codes:
  0  clean — every check passed
  1  residue — one or more FAIL lines printed
  2  usage error (invalid task name, missing casper root, unreadable tasks.yaml)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# validate_delete.py -> heartbeat/ -> workflows/ -> ~/.agents
REPO_ROOT = Path(__file__).resolve().parents[2]

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")  # same identity rule as config.py
PRUNE_DIRS = {"__pycache__", ".venv", "node_modules", ".git", ".cache"}
# Lifecycle docs in this folder mention task names as examples; skip them.
SKIP_FILES = {
    Path(__file__).resolve().parent / "heartbeat-task.md",
    Path(__file__).resolve().parent / "lifecycle-reference.md",
}
MAX_HITS_SHOWN = 20


def is_text(path: Path) -> bool:
    try:
        return b"\x00" not in path.open("rb").read(4096)
    except OSError:
        return False


def grep_tree(root: Path, needle: str) -> list[str]:
    """Return 'relpath:lineno' hits for needle in text files under root."""
    hits: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.resolve() in SKIP_FILES:
            continue
        if any(part in PRUNE_DIRS for part in path.parts):
            continue
        if not is_text(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if needle in line:
                hits.append(f"{path.relative_to(root)}:{i}")
    return hits


def check_tasks_yaml(path: Path, task: str, results: list[tuple[bool, str]]) -> None:
    import yaml  # PyYAML lives in the shared $HOME/.agents/.venv

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = data.get("tasks", []) if isinstance(data, dict) else []
    named = [e for e in entries if isinstance(e, dict) and e.get("name") == task]
    dependents = [
        e.get("name", "?")
        for e in entries
        if isinstance(e, dict) and task in (e.get("depends_on") or [])
    ]
    if named:
        results.append((False, f"tasks.yaml still has an entry named {task!r}"))
    elif dependents:
        results.append((False, f"tasks.yaml depends_on still references {task!r} in: {dependents}"))
    else:
        results.append((True, f"tasks.yaml has no entry or depends_on for {task!r}"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a deleted heartbeat task left no residue (read-only)."
    )
    parser.add_argument("task", help="Task name that was deleted ([a-z0-9][a-z0-9-]*).")
    parser.add_argument(
        "--keep-history",
        action="store_true",
        help="User chose to keep state/history/<task>.jsonl; require it to still exist.",
    )
    parser.add_argument(
        "--casper-root",
        default=str(REPO_ROOT),
        help="Casper root holding workflows/, state/, secrets/ (default: %(default)s).",
    )
    args = parser.parse_args()

    task = args.task
    if not NAME_RE.match(task):
        print(f"error: invalid task name {task!r} (expected [a-z0-9][a-z0-9-]*)", file=sys.stderr)
        return 2
    root = Path(args.casper_root).expanduser().resolve()
    workflows = root / "workflows"
    tasks_yaml = workflows / "heartbeat" / "tasks.yaml"
    if not workflows.is_dir():
        print(f"error: no workflows/ under {root}", file=sys.stderr)
        return 2

    results: list[tuple[bool, str]] = []  # (passed, message)
    warns: list[str] = []

    # 1. tasks.yaml entry + depends_on
    try:
        check_tasks_yaml(tasks_yaml, task, results)
    except Exception as exc:  # noqa: BLE001 - unreadable config is an environment error
        print(f"error: cannot read {tasks_yaml}: {exc}", file=sys.stderr)
        return 2

    # 2. name residue across workflows/
    hits = grep_tree(workflows, task)
    if hits:
        shown = ", ".join(hits[:MAX_HITS_SHOWN])
        more = f" (+{len(hits) - MAX_HITS_SHOWN} more)" if len(hits) > MAX_HITS_SHOWN else ""
        results.append((False, f"{len(hits)} hit(s) for {task!r} under workflows/: {shown}{more}"))
    else:
        results.append((True, f"no hit for {task!r} under workflows/ (lifecycle docs excluded)"))

    # 3. per-task dirs gone
    for d in (workflows / task, root / "state" / task, root / "secrets" / task):
        if d.exists():
            results.append((False, f"still exists: {d}"))
        else:
            results.append((True, f"gone: {d}"))

    # 4. history per the user's choice
    history = root / "state" / "history" / f"{task}.jsonl"
    if args.keep_history:
        if history.is_file():
            results.append((True, f"history kept as requested: {history}"))
        else:
            results.append((False, f"--keep-history given but history is missing: {history}"))
    elif history.exists():
        results.append((False, f"history still exists (use --keep-history if intended): {history}"))
    else:
        results.append((True, f"history gone: {history}"))

    # 5. open clarify files
    clarify_dir = root / "state" / "clarify"
    open_clarify = sorted(p.name for p in clarify_dir.glob(f"{task}-*.md")) if clarify_dir.is_dir() else []
    if open_clarify:
        results.append((False, f"open clarify file(s) remain in state/clarify/: {open_clarify}"))
    else:
        results.append((True, "no open clarify files (resolved/ archive may keep them)"))

    # 6. heartbeat.env mentions
    env_file = root / "secrets" / "heartbeat.env"
    env_hits: list[str] = []
    if env_file.is_file():
        needles = {task.lower(), task.lower().replace("-", "_")}
        for i, line in enumerate(env_file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if any(n in line.lower() for n in needles):
                env_hits.append(f"heartbeat.env:{i}")
    if env_hits:
        results.append((False, f"heartbeat.env still mentions {task!r}: {env_hits}"))
    else:
        results.append((True, "heartbeat.env has no line mentioning the task name"))

    # WARN: residual daemon-state key (informational by design)
    tasks_json = root / "state" / "heartbeat" / "tasks.json"
    if tasks_json.is_file():
        try:
            daemon_state = json.loads(tasks_json.read_text(encoding="utf-8"))
            if task in (daemon_state.get("tasks") or {}):
                warns.append(
                    f"residual key {task!r} in state/heartbeat/tasks.json — daemon ignores it; "
                    "leave it (hand-edit only with the daemon stopped)"
                )
        except (OSError, ValueError) as exc:
            warns.append(f"could not parse {tasks_json}: {exc}")

    for ok, msg in results:
        print(("PASS: " if ok else "FAIL: ") + msg)
    for msg in warns:
        print("WARN: " + msg)
    failed = sum(1 for ok, _ in results if not ok)
    if failed:
        print(f"residue: {failed}/{len(results)} check(s) failed for task {task!r}")
        return 1
    print(f"clean: no residue for task {task!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
