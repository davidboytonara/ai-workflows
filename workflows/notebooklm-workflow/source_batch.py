#!/usr/bin/env python3
"""Batch source ingestion: add every source, then wait for each to process.

Wraps this folder's `source.py add --json` / `source.py wait --json` so a
multi-source batch emits one status line per source (stderr) plus a compact
JSON summary (stdout) instead of N screens of polling output.

Usage:
  source_batch.py [SOURCE ...] [--from-file FILE] [--notebook ID]
                  [--timeout N] [--interval N] [--plan]

  SOURCE       url / local path / youtube link (same auto-detection as
               `source.py add`)
  --from-file  read additional sources, one per line ('-' = stdin;
               blank lines and lines starting with '#' are skipped)
  --notebook   target notebook id (default: the session-selected notebook)
  --timeout    per-source wait budget in seconds (default 900)
  --interval   wait poll interval in seconds (default 5)
  --plan       print the commands that would run, execute nothing, exit 0

Summary JSON: {ok, requested, ready_count, failed_count, ready_ids,
sources: [{input, source_id, title, status, stage, error}]} where status is
ready | add_failed | not_found | error | timeout | skipped.

Exit codes:
  0  all sources added and ready
  1  at least one source failed (see summary JSON; continue with ready_ids)
  2  usage error (no sources, unreadable --from-file)
  3  environment / venv bootstrap failure (propagated from _env.py)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_PY = HERE / "source.py"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _parse_json(text: str):
    """Best-effort: pull the JSON object out of captured CLI stdout."""
    for candidate in (text, text[text.find("{"):] if "{" in text else ""):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def _error_text(proc: subprocess.CompletedProcess) -> str:
    payload = _parse_json(proc.stdout or "")
    if isinstance(payload, dict):
        for key in ("error", "message"):
            if payload.get(key):
                return str(payload[key])
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return tail[-1] if tail else f"exit code {proc.returncode}"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 3:  # env/bootstrap failure: nothing else can succeed
        log((proc.stderr or "environment/bootstrap failure").strip())
        sys.exit(3)
    return proc


def read_sources(args: argparse.Namespace) -> list[str]:
    sources = list(args.sources)
    if args.from_file:
        if args.from_file == "-":
            lines = sys.stdin.read().splitlines()
        else:
            path = Path(args.from_file)
            if not path.is_file():
                log(f"--from-file not found: {path}")
                sys.exit(2)
            lines = path.read_text().splitlines()
        sources += [s.strip() for s in lines
                    if s.strip() and not s.strip().startswith("#")]
    return list(dict.fromkeys(sources))  # dedupe, keep order


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add many NotebookLM sources and wait for each (compact output).",
        epilog="Exit codes: 0 all ready, 1 some failed, 2 usage, 3 environment.",
    )
    parser.add_argument("sources", nargs="*", help="urls / paths / youtube links")
    parser.add_argument("--from-file", help="file with one source per line ('-' = stdin)")
    parser.add_argument("--notebook", help="notebook id (default: session-selected)")
    parser.add_argument("--timeout", type=int, default=900,
                        help="per-source wait budget in seconds (default 900)")
    parser.add_argument("--interval", type=int, default=5,
                        help="wait poll interval in seconds (default 5)")
    parser.add_argument("--plan", action="store_true",
                        help="print the commands that would run and exit")
    args = parser.parse_args()

    sources = read_sources(args)
    if not sources:
        parser.print_usage(sys.stderr)
        log("no sources given (positional and/or --from-file)")
        return 2

    py = sys.executable
    nb = ["--notebook", args.notebook] if args.notebook else []
    if args.plan:
        for src in sources:
            print(f"{py} {SOURCE_PY} add {src!r} --json" + (" " + " ".join(nb) if nb else ""))
        print(f"# then per returned id: {py} {SOURCE_PY} wait <id> "
              f"--timeout {args.timeout} --interval {args.interval} --json"
              + (" " + " ".join(nb) if nb else ""))
        print(f"# plan only: {len(sources)} source(s), nothing executed")
        return 0

    results = [{"input": s, "source_id": None, "title": None,
                "status": "skipped", "stage": None, "error": None} for s in sources]

    # Phase 1: add everything (processing continues server-side in parallel).
    for i, row in enumerate(results, 1):
        proc = _run([py, str(SOURCE_PY), "add", row["input"], "--json", *nb])
        payload = _parse_json(proc.stdout or "") or {}
        source = payload.get("source") or {}
        if proc.returncode == 0 and source.get("id"):
            row.update(source_id=source["id"], title=source.get("title"),
                       status="added", stage="add")
            log(f"[{i}/{len(results)}] added {source['id']}  <- {row['input']}")
        else:
            row.update(status="add_failed", stage="add", error=_error_text(proc))
            log(f"[{i}/{len(results)}] ADD FAILED  <- {row['input']}: {row['error']}")
            if i == 1 and "auth missing" in (proc.stderr or "").lower():
                log("auth missing: aborting batch (remaining sources skipped)")
                break

    # Phase 2: wait for each added source.
    added = [r for r in results if r["status"] == "added"]
    for i, row in enumerate(added, 1):
        proc = _run([py, str(SOURCE_PY), "wait", row["source_id"],
                     "--timeout", str(args.timeout), "--interval", str(args.interval),
                     "--json", *nb])
        payload = _parse_json(proc.stdout or "") or {}
        status = payload.get("status") or ("ready" if proc.returncode == 0 else "error")
        row.update(status=status, stage="wait",
                   title=payload.get("title") or row["title"],
                   error=payload.get("error"))
        log(f"[{i}/{len(added)}] wait {row['source_id']}: {status}")

    ready = [r for r in results if r["status"] == "ready"]
    failed = [r for r in results if r["status"] != "ready"]
    summary = {
        "ok": not failed,
        "requested": len(results),
        "ready_count": len(ready),
        "failed_count": len(failed),
        "ready_ids": [r["source_id"] for r in ready],
        "sources": results,
    }
    print(json.dumps(summary, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
