#!/usr/bin/env python3
"""Detect candidate dead PRODUCTION code in a target repo (unused files,
unused exports, unused dependencies) by driving knip and normalizing its
JSON report.

This is a bounded recon aid producing candidate EVIDENCE, not an oracle:
every item is a lead with recorded evidence for later human/LLM vetting
(see detection-guide.md). Nothing here proves a removal is safe — dynamic
references (route registration, CLI dispatch, glob discovery, reflection,
build-script copies) are invisible to the import graph.

Detector resolution (recorded in hints.mode):
  repo-native
      the target repo ships its own knip config (knip.json / knip.jsonc /
      knip.ts, or a "knip" key in the root package.json): run the repo's
      own pinned knip via `npx --no-install knip --reporter json`.
  fallback-generated-config
      no repo config: generate a minimal temp config from package.json
      (main / bin / exports string leaves, plus src/index.* heuristics),
      run pinned `npx --yes knip@5 --reporter json`, delete the temp
      config. ALL confidence is capped low in this mode.

Categories emitted:
  unused-file           no import path from any entry point reaches it
  unused-export         exported symbol never imported elsewhere
  unused-type-export    exported type/interface/enum never imported
  unused-dependency     package.json dependency never imported
  unused-devdependency  devDependency never imported by modeled tooling
knip "unlisted"/"unresolved" issues are recorded under hints as repo-health
flags (missing declarations / broken specifiers), never delete candidates.

Test code is out of scope (route to the dead-test-cleanup workflow): items
under tests/, test/, __tests__ or named *.test.* / *.spec.* are dropped and
counted in hints.excluded_test_items.

Exit codes:
  0  inventory written, >=1 candidate
  1  inventory written, zero candidates
  2  usage error (bad flags, --repo-root not a git repo root)
  3  detector unrunnable/failed (a partial report with the reason is still
     written to --out under detector.error)
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import posixpath
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# find_dead_code.py -> dead-code-cleanup/ -> workflows/ -> ~/.agents
REPO_ROOT = Path(__file__).resolve().parents[2]

KNIP_TIMEOUT = 900  # seconds; knip on a large repo is minutes, not hours
CATEGORY_ORDER = [
    "unused-file", "unused-export", "unused-type-export",
    "unused-dependency", "unused-devdependency",
]
TEST_DIR_NAMES = {"tests", "test", "__tests__"}
TEST_NAME_PATTERNS = ("*.test.*", "*.spec.*")
INDEX_HEURISTICS = (
    "src/index.ts", "src/index.tsx", "src/index.mts", "src/index.cts",
    "src/index.js", "src/index.mjs", "src/index.cjs",
    "src/main.ts", "src/main.js", "src/cli.ts", "src/cli.js",
    "index.ts", "index.js",
)
REPO_KNIP_CONFIGS = ("knip.json", "knip.jsonc", "knip.ts")


def norm_rel(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return posixpath.normpath(p) if p else p


def is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    if any(part in TEST_DIR_NAMES for part in parts[:-1]):
        return True
    return any(fnmatch.fnmatch(parts[-1], pat) for pat in TEST_NAME_PATTERNS)


def entry_name(e) -> str | None:
    if isinstance(e, str):
        return e
    if isinstance(e, dict):
        return e.get("name") or e.get("file")
    return None


def entry_loc(e) -> str:
    if isinstance(e, dict) and e.get("line") is not None:
        return f" (L{e['line']}:{e.get('col', '?')})"
    return ""


def iter_issue_entries(value):
    """Yield entries from a knip issue field, flattening one nested level
    (duplicates-style lists of lists) and tolerating strings or dicts."""
    if not isinstance(value, list):
        return
    for e in value:
        if isinstance(e, list):
            yield from e
        else:
            yield e


def string_leaves(value):
    """Yield all string leaves of a nested dict/list (package.json exports/bin)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from string_leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from string_leaves(v)


def repo_knip_source(root: Path) -> str | None:
    for name in REPO_KNIP_CONFIGS:
        if (root / name).is_file():
            return name
    pj = root / "package.json"
    if pj.is_file():
        try:
            if "knip" in json.loads(pj.read_text(errors="replace")):
                return 'package.json "knip" key'
        except json.JSONDecodeError:
            pass
    return None


def build_fallback_entries(root: Path) -> list[str]:
    entries: list[str] = []
    pj: dict = {}
    pj_path = root / "package.json"
    if pj_path.is_file():
        try:
            pj = json.loads(pj_path.read_text(errors="replace"))
        except json.JSONDecodeError:
            pj = {}
    cands: list[str] = []
    main = pj.get("main")
    if isinstance(main, str):
        cands.append(main)
    cands += list(string_leaves(pj.get("bin")))
    cands += list(string_leaves(pj.get("exports")))
    for c in cands:
        rel = norm_rel(c)
        if rel and not rel.startswith("..") and (root / rel).is_file():
            entries.append(rel)
    for h in INDEX_HEURISTICS:
        if (root / h).is_file():
            entries.append(h)
    return sorted(set(entries))


def run_knip(cmd: list[str], cwd: Path):
    """Run knip; return (data, error, exit_code). knip exits 0 (clean) or
    1 (issues found) with JSON on stdout either way — parseability of the
    JSON, not the exit code, decides success."""
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=KNIP_TIMEOUT)
    except FileNotFoundError:
        return None, "npx not found on PATH (Node.js is required to run knip)", None
    except subprocess.TimeoutExpired:
        return None, f"knip timed out after {KNIP_TIMEOUT}s", None
    stdout = (proc.stdout or "").strip()
    start = stdout.find("{")
    if start != -1:
        try:
            return json.loads(stdout[start:]), None, proc.returncode
        except json.JSONDecodeError:
            pass
    tail = " | ".join(((proc.stderr or "") + "\n" + stdout).strip().splitlines()[-8:])
    return None, f"knip exit {proc.returncode}, unparsable output: {tail}", proc.returncode


def write_report(out_path: str, payload: dict) -> None:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Detect candidate dead production code via knip "
                    "(recon aid, not an oracle; test code routes to dead-test-cleanup)."
    )
    ap.add_argument("--repo-root", required=True, help="absolute path to target git repo root")
    ap.add_argument("--out", required=True, help="path for the JSON inventory")
    ap.add_argument("--protected", nargs="+", action="extend", default=[],
                    help="path prefixes; matching items become flag_only")
    ap.add_argument("--summary", action="store_true", help="print a markdown summary table")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    if not root.is_dir() or not (root / ".git").exists():
        print(f"error: --repo-root {root} is not a git repo root", file=sys.stderr)
        return 2

    base = {
        "schema": "dead-code-inventory/v1",
        "repo_root": str(root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    def fail(mode: str, cmd, reason: str) -> int:
        write_report(args.out, base | {
            "detector": {"mode": mode, "command": cmd, "error": reason},
            "hints": {"mode": mode}, "items": [], "counts": {},
        })
        print(f"error: {reason}; partial report written to {args.out}", file=sys.stderr)
        return 3

    # ---- detector resolution --------------------------------------------
    src = repo_knip_source(root)
    tmp_cfg: Path | None = None
    if src:
        mode = "repo-native"
        cmd = ["npx", "--no-install", "knip", "--reporter", "json"]
    else:
        mode = "fallback-generated-config"
        entries = build_fallback_entries(root)
        if not entries:
            return fail(mode, None, "cannot derive entry points from package.json "
                                    "(main/bin/exports) or src/index.* heuristics")
        cfg = {"entry": entries}
        if (root / "src").is_dir():
            cfg["project"] = ["src/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"]
        tmp_cfg = root / f".knip-deadcode-{os.getpid()}.json"
        tmp_cfg.write_text(json.dumps(cfg, indent=2) + "\n")
        src = f"generated from package.json + heuristics ({len(entries)} entry point(s))"
        cmd = ["npx", "--yes", "knip@5", "--config", tmp_cfg.name, "--reporter", "json"]

    try:
        data, err, knip_exit = run_knip(cmd, root)
    finally:
        if tmp_cfg is not None:
            tmp_cfg.unlink(missing_ok=True)
    if data is None:
        return fail(mode, cmd, err)

    # ---- normalize --------------------------------------------------------
    items: list[dict] = []
    unlisted: list[dict] = []
    unresolved: list[dict] = []

    def add(path: str, category: str, kind: str, symbol: str | None, evidence: list[str]):
        items.append({"path": path, "category": category, "kind": kind,
                      "symbol": symbol, "evidence": evidence})

    for f in iter_issue_entries(data.get("files") or []):
        rel = norm_rel(entry_name(f) or "")
        if rel:
            add(rel, "unused-file", "file", None,
                ["knip: no import path from any entry point reaches this file"])
    for issue in data.get("issues") or []:
        f = norm_rel(issue.get("file") or "")
        for e in iter_issue_entries(issue.get("exports")):
            name = entry_name(e)
            if name:
                add(f, "unused-export", "export", name,
                    [f"knip: exported symbol '{name}' never imported elsewhere{entry_loc(e)}"])
        for e in iter_issue_entries(issue.get("types")):
            name = entry_name(e)
            if name:
                add(f, "unused-type-export", "type-export", name,
                    [f"knip: exported type '{name}' never imported elsewhere{entry_loc(e)}"])
        for e in iter_issue_entries(issue.get("dependencies")):
            name = entry_name(e)
            if name:
                add(f, "unused-dependency", "dependency", name,
                    [f"knip: dependency '{name}' in {f} never imported "
                     "(script/CI/config usage NOT proven absent here — vetting checklist item 6)"])
        for e in iter_issue_entries(issue.get("devDependencies")):
            name = entry_name(e)
            if name:
                add(f, "unused-devdependency", "devDependency", name,
                    [f"knip: devDependency '{name}' in {f} never imported by modeled tooling "
                     "(script/CI/config usage NOT proven absent here — vetting checklist item 6)"])
        for e in iter_issue_entries(issue.get("unlisted")):
            name = entry_name(e)
            if name:
                unlisted.append({"file": f, "name": name})
        for e in iter_issue_entries(issue.get("unresolved")):
            name = entry_name(e)
            if name:
                unresolved.append({"file": f, "name": name})

    # ---- test-code exclusion (dead-test-cleanup's territory) -------------
    kept = [i for i in items if not is_test_path(i["path"])]
    excluded_tests = len(items) - len(kept)
    items = kept

    # ---- confidence + protected -------------------------------------------
    prefixes = [norm_rel(p).rstrip("/") for p in args.protected]

    def is_protected(path: str) -> bool:
        return any(path == p or path.startswith(p + "/") for p in prefixes)

    for item in items:
        if mode == "fallback-generated-config":
            item["confidence"] = "low"
        elif item["category"] in ("unused-dependency", "unused-devdependency"):
            item["confidence"] = "medium"
        else:
            item["confidence"] = "high"
        item["flag_only"] = is_protected(item["path"])

    items.sort(key=lambda i: (CATEGORY_ORDER.index(i["category"]), i["path"], i["symbol"] or ""))
    for n, item in enumerate(items, 1):
        item["id"] = f"dc-{n:03d}"

    counts = {c: sum(1 for i in items if i["category"] == c) for c in CATEGORY_ORDER}
    counts["flag_only"] = sum(1 for i in items if i["flag_only"])

    hints = {
        "mode": mode,
        "detector_source": src,
        "unlisted": unlisted,
        "unresolved": unresolved,
        "excluded_test_items": excluded_tests,
        "protected_paths_used": prefixes,
    }
    if mode == "fallback-generated-config":
        hints["confidence_note"] = ("entry points guessed from package.json + src/index.* "
                                    "heuristics; whole subtrees may be falsely orphaned — "
                                    "all confidence capped low")

    write_report(args.out, base | {
        "detector": {"mode": mode, "command": cmd, "knip_exit": knip_exit},
        "hints": hints,
        "items": [{k: i[k] for k in
                   ("id", "path", "category", "kind", "symbol", "evidence",
                    "confidence", "flag_only")} for i in items],
        "counts": counts,
    })

    if args.summary:
        print(f"# dead-code inventory — {len(items)} candidate(s), "
              f"{counts['flag_only']} flag-only, mode={mode}")
        print("| id | path | symbol | category | confidence | flag_only |")
        print("|---|---|---|---|---|---|")
        for i in items:
            print(f"| {i['id']} | {i['path']} | {i['symbol'] or ''} | {i['category']} "
                  f"| {i['confidence']} | {str(i['flag_only']).lower()} |")
        if unlisted or unresolved:
            print(f"\n{len(unlisted)} unlisted + {len(unresolved)} unresolved knip issue(s) "
                  "recorded under hints — repo-health flags, never delete candidates.")
        if excluded_tests:
            print(f"{excluded_tests} test-code item(s) excluded — route to dead-test-cleanup.")

    return 0 if items else 1


if __name__ == "__main__":
    raise SystemExit(main())
