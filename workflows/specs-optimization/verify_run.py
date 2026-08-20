#!/usr/bin/env python3
"""Verify the deterministic done-criteria of a specs-optimization run directory.

Scriptable half of the workflow's Verify section (specs-optimization.md).
Read-only — inspects the run dir and, for the cleanliness check, runs
`git status --porcelain` against the manifest's repo_root.

Checks (one PASS/FAIL line each):
  1. Every run artifact exists and is non-empty: manifest.json prompts.json
     probes.json metrics.json nav_traces.md digest.md report.md;
     the .json artifacts must parse as JSON.
  2. prompts.json is a non-empty JSON array of strings and every prompt ends
     with the exact read-only line: 'Do not make any change yet.'
  3. probes.json has exactly one entry per prompt, every entry exited 0, and
     every entry's transcript path exists on disk (harness-agnostic — replaces
     the old Claude-only hex agentId check).
  4. digest.md is within --digest-budget-bytes (default 24000, matching
     harvest_nav.py's default).
  5. No change under the manifest's specs_root per
     `git -C <repo_root> status --porcelain`. WARN-skips (not a failure) when
     repo_root no longer exists, is not a git work tree, or git is missing —
     stale run dirs stay verifiable.

Exit codes:
  0  all checks passed
  1  one or more checks failed
  2  usage error
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# verify_run.py -> specs-optimization/ -> workflows/ -> repo
REPO_ROOT = Path(__file__).resolve().parents[2]

ARTIFACTS = (
    "manifest.json",
    "prompts.json",
    "probes.json",
    "metrics.json",
    "nav_traces.md",
    "digest.md",
    "report.md",
)
READONLY_SUFFIX = "Do not make any change yet."


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def git_specs_dirt(repo_root: Path, specs_root: Path) -> tuple[list[str] | None, str | None]:
    """Return (paths dirty under specs_root, None) or (None, warn-reason to skip)."""
    if not repo_root.is_dir():
        return None, f"repo_root no longer exists: {repo_root}"
    try:
        top = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return None, "git executable not found"
    except subprocess.TimeoutExpired:
        return None, "git rev-parse timed out"
    if top.returncode != 0:
        return None, f"not a git work tree: {repo_root}"
    toplevel = Path(top.stdout.strip())
    status = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        capture_output=True, text=True, timeout=120,
    )
    if status.returncode != 0:
        return None, f"git status failed: {status.stderr.strip()}"
    dirty: list[str] = []
    specs = specs_root.resolve()
    for line in status.stdout.splitlines():
        if len(line) < 4:
            continue
        rel = line[3:]
        if " -> " in rel:  # rename: check the destination
            rel = rel.split(" -> ", 1)[1]
        rel = rel.strip().strip('"')
        p = (toplevel / rel).resolve()
        if p == specs or specs in p.parents:
            dirty.append(rel)
    return dirty, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a specs-optimization run dir's deterministic done-criteria (read-only)."
    )
    parser.add_argument("--run-dir", required=True, help="The $RUN directory of the invocation.")
    parser.add_argument(
        "--digest-budget-bytes", type=int, default=24000,
        help="Max digest.md size in bytes (default: %(default)s).",
    )
    args = parser.parse_args()

    run = Path(args.run_dir).expanduser()
    if not run.is_dir():
        print(f"error: run-dir not a directory: {run}", file=sys.stderr)
        return 2

    results: list[tuple[bool, str]] = []
    warns: list[str] = []

    # 1. artifact presence + JSON validity
    parsed: dict[str, object] = {}
    for name in ARTIFACTS:
        path = run / name
        if not path.is_file() or path.stat().st_size == 0:
            results.append((False, f"missing or empty artifact: {name}"))
            continue
        if name.endswith(".json"):
            try:
                parsed[name] = load_json(path)
            except ValueError as exc:
                results.append((False, f"invalid JSON in {name}: {exc}"))
                continue
        results.append((True, f"artifact ok: {name}"))

    # 2. prompt suffix
    prompts = parsed.get("prompts.json")
    if isinstance(prompts, list) and prompts and all(isinstance(p, str) for p in prompts):
        bad = [i for i, p in enumerate(prompts) if not p.rstrip().endswith(READONLY_SUFFIX)]
        if bad:
            results.append((False, f"{len(bad)}/{len(prompts)} prompt(s) missing the read-only suffix (indices {bad})"))
        else:
            results.append((True, f"all {len(prompts)} prompts end with {READONLY_SUFFIX!r}"))
    elif "prompts.json" in parsed:
        results.append((False, "prompts.json is not a non-empty JSON array of strings"))
        prompts = None

    # 3. probes: one entry per prompt, each exited 0 with an existing transcript
    probes = parsed.get("probes.json")
    if isinstance(probes, list) and probes and all(isinstance(p, dict) for p in probes):
        problems: list[str] = []
        if isinstance(prompts, list) and len(probes) != len(prompts):
            problems.append(f"{len(probes)} probe entries for {len(prompts)} prompts — counts must match")
        bad_exit = [p.get("index", i + 1) for i, p in enumerate(probes) if p.get("exit_code") != 0]
        if bad_exit:
            problems.append(f"probe(s) with nonzero exit_code: {bad_exit}")
        no_tx = [p.get("index", i + 1) for i, p in enumerate(probes)
                 if not (isinstance(p.get("transcript"), str) and p["transcript"]
                         and Path(p["transcript"]).expanduser().is_file())]
        if no_tx:
            problems.append(f"probe(s) with a missing transcript: {no_tx}")
        if problems:
            results.append((False, "probes.json: " + "; ".join(problems)))
        else:
            results.append((True, f"probes.json holds {len(probes)} probes, all exit 0 with an existing transcript"))
    elif "probes.json" in parsed:
        results.append((False, "probes.json is not a non-empty JSON array of probe objects"))

    # 4. digest budget
    digest = run / "digest.md"
    if digest.is_file():
        size = digest.stat().st_size
        if size <= args.digest_budget_bytes:
            results.append((True, f"digest.md {size} bytes <= budget {args.digest_budget_bytes}"))
        else:
            results.append((False, f"digest.md {size} bytes exceeds budget {args.digest_budget_bytes}"))

    # 5. spec tree unchanged (per the manifest's own roots)
    manifest = parsed.get("manifest.json")
    if isinstance(manifest, dict) and manifest.get("repo_root") and manifest.get("specs_root"):
        dirty, warn = git_specs_dirt(Path(manifest["repo_root"]), Path(manifest["specs_root"]))
        if warn is not None:
            warns.append(f"spec-cleanliness check skipped: {warn}")
        elif dirty:
            shown = ", ".join(dirty[:20]) + (f" (+{len(dirty) - 20} more)" if len(dirty) > 20 else "")
            results.append((False, f"{len(dirty)} changed file(s) under specs_root: {shown}"))
        else:
            results.append((True, "git status reports no change under specs_root"))
    elif isinstance(manifest, dict):
        results.append((False, "manifest.json lacks repo_root/specs_root"))

    for ok, msg in results:
        print(("PASS: " if ok else "FAIL: ") + msg)
    for msg in warns:
        print("WARN: " + msg)
    failed = sum(1 for ok, _ in results if not ok)
    if failed:
        print(f"verify: {failed}/{len(results)} check(s) failed for {run}")
        return 1
    print(f"verify: all {len(results)} checks passed for {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
