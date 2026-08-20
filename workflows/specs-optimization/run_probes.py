#!/usr/bin/env python3
"""Launch the specs-optimization probe fleet through LLM_harness.sh, in parallel.

Replaces the Claude-Code-only Agent-tool fan-out: every probe is one headless
CLI process (`LLM_harness.sh -m MODEL -t EFFORT -s SECONDS -- PROMPT`), so the
workflow runs under any harness that can execute a shell command.

Identity without agentIds: the run mints a token `SPECPROBE-<8hex>` and each
probe's prompt embeds `[probe <token>#<i>]`. After all probes exit, transcripts
are located by scanning the backend's transcript root for files modified at or
after run start whose FIRST user message contains that exact marker.

Each probe's prompt is composed here as:
    PROBE_PREAMBLE + "[probe <token>#<i>]" + <generated prompt>
PROBE_PREAMBLE (below) is the read-only probe system instruction — it replaces
the deleted `spec-probe.agent` definition and is the single place that text
lives now.

Outputs:
  <run>/logs/probe-NN.log   raw stdout+stderr of each harness call
  <run>/probes.json         [{index, token, prompt, exit_code, transcript}]

All probes in one run share one model and one effort — mixed models make the
friction metrics incomparable, so both are single-valued arguments.

Exit codes:
  0  every probe exited 0 and its transcript was located
  1  a probe failed, or a transcript could not be located
  2  usage error
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from probe_backends import HARNESSES, get_backend, harness_for_model

# run_probes.py -> specs-optimization/ -> workflows/ -> repo
REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_SH = REPO_ROOT / "workflows" / "casper" / "LLM_harness.sh"

PROBE_PREAMBLE = """You are a read-only feature-investigation probe.

Investigate the task below against the target repository as deeply as a real
implementer would: locate the relevant specifications/documentation, read them,
follow cross-references, and build a complete picture of how the feature would
be built.

- Navigate the spec corpus naturally — search, read, and follow links as needed.
- You MAY spawn your own subagents for parallel investigation.
- Make no edits of any kind: no file writes, no commands that mutate the repo.

Report what you found: the relevant specs (paths), how the feature would be
implemented, and any gaps or contradictions you hit while navigating.
"""

# Transcripts are matched on mtime >= run_start - SLACK to absorb clock skew
# between this process and the CLI writing the session file.
MTIME_SLACK_S = 120.0


def mint_token() -> str:
    return "SPECPROBE-" + secrets.token_hex(4)


def marker(token: str, index: int) -> str:
    return f"[probe {token}#{index}]"


def compose_prompt(token: str, index: int, prompt: str) -> str:
    return f"{PROBE_PREAMBLE}\n{marker(token, index)}\n\n{prompt}"


def default_model() -> str:
    """Ask LLM_harness.sh for its derived default; fall back to its documented one."""
    try:
        out = subprocess.run([str(HARNESS_SH), "--default-model"],
                             capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    if os.environ.get("PI_CODING_AGENT") and os.environ.get("PI_PROVIDER") and os.environ.get("PI_MODEL"):
        return f"{os.environ['PI_PROVIDER']}/{os.environ['PI_MODEL']}"
    return "opus"


def run_one(run_dir: Path, model: str, effort: str, stopwatch: int,
            index: int, prompt: str) -> int:
    log = run_dir / "logs" / f"probe-{index:02d}.log"
    cmd = [str(HARNESS_SH), "-m", model, "-t", effort, "-s", str(stopwatch), "--", prompt]
    with log.open("wb") as fh:
        fh.write(f"$ LLM_harness.sh -m {model} -t {effort} -s {stopwatch} -- <prompt>\n".encode())
        fh.flush()
        try:
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
        except OSError as exc:
            fh.write(f"\n[run_probes] failed to launch: {exc}\n".encode())
            return 127
    return proc.returncode


def locate_transcripts(backend, token: str, count: int, since: float) -> dict[int, str]:
    """Map probe index -> transcript path, by scanning for the run marker."""
    wanted = {marker(token, i): i for i in range(1, count + 1)}
    found: dict[int, str] = {}
    for path in backend.discover(since=since - MTIME_SLACK_S):
        head = backend.first_user_text(path)
        if token not in head:
            continue
        for mk, idx in wanted.items():
            if mk in head and idx not in found:
                found[idx] = str(path)
                break
    return found


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run specs-optimization probes as headless LLM_harness.sh processes.")
    ap.add_argument("--prompts", required=True, help="prompts.json: JSON array of prompt strings.")
    ap.add_argument("--run-dir", required=True, help="Run directory ($RUN); logs/ and probes.json land here.")
    ap.add_argument("--model", default="", help="One model for ALL probes (default: harness default).")
    ap.add_argument("--effort", default="xhigh", help="One thinking effort for ALL probes (default: %(default)s).")
    ap.add_argument("--stopwatch", type=int, default=3600, help="Per-probe wall-clock seconds (default: %(default)s).")
    ap.add_argument("--concurrency", type=int, default=0, help="Parallel probes (default: min(COUNT, 8)).")
    ap.add_argument("--harness", default="auto", choices=("auto",) + HARNESSES,
                    help="Which transcript tree to search (default: auto, derived from the model).")
    ap.add_argument("--token", default="", help="Run token (default: freshly minted SPECPROBE-<8hex>).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Resolve model/harness/token and print the plan; launch nothing.")
    args = ap.parse_args()

    prompts_path = Path(args.prompts).expanduser()
    try:
        prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"error: cannot read --prompts: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: --prompts is not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(prompts, list) or not prompts or not all(isinstance(p, str) and p.strip() for p in prompts):
        print("error: --prompts must be a non-empty JSON array of non-empty strings", file=sys.stderr)
        return 2
    if not HARNESS_SH.is_file():
        print(f"error: LLM_harness.sh not found at {HARNESS_SH}", file=sys.stderr)
        return 2
    if args.stopwatch <= 0:
        print("error: --stopwatch must be > 0", file=sys.stderr)
        return 2

    run_dir = Path(args.run_dir).expanduser()
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)

    model = args.model.strip() or default_model()
    effort = args.effort.strip()
    if not effort:
        print("error: --effort must not be empty", file=sys.stderr)
        return 2
    harness = args.harness if args.harness != "auto" else harness_for_model(model)
    token = args.token.strip() or mint_token()
    count = len(prompts)
    workers = args.concurrency if args.concurrency > 0 else min(count, 8)
    backend = get_backend(harness)

    print(f"run_probes: {count} probes · model={model} · effort={effort} · harness={harness} "
          f"· token={token} · concurrency={workers} · stopwatch={args.stopwatch}s", file=sys.stderr)

    if args.dry_run:
        print(json.dumps({
            "token": token, "model": model, "effort": effort, "harness": harness,
            "concurrency": workers, "stopwatch": args.stopwatch, "probes": count,
            "transcript_roots": [str(r) for r in backend.roots()],
            "command": [str(HARNESS_SH), "-m", model, "-t", effort, "-s",
                        str(args.stopwatch), "--", "<composed prompt>"],
            "first_prompt_head": compose_prompt(token, 1, prompts[0])[:400],
        }, indent=2))
        return 0

    started = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, run_dir, model, effort, args.stopwatch,
                               i, compose_prompt(token, i, p))
                   for i, p in enumerate(prompts, start=1)]
        codes = [f.result() for f in futures]

    located = locate_transcripts(backend, token, count, started)

    entries = []
    for i, prompt in enumerate(prompts, start=1):
        entries.append({
            "index": i,
            "token": marker(token, i),
            "prompt": prompt,
            "exit_code": codes[i - 1],
            "transcript": located.get(i, ""),
        })
    (run_dir / "probes.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")

    failed = [e["index"] for e in entries if e["exit_code"] != 0]
    missing = [e["index"] for e in entries if not e["transcript"]]
    print(f"run_probes: located={len(located)}/{count} failed={len(failed)} "
          f"elapsed={round(time.time() - started)}s -> {run_dir / 'probes.json'}", file=sys.stderr)
    if failed:
        print(f"run_probes: probes with nonzero exit: {failed} (see {run_dir / 'logs'})", file=sys.stderr)
    if missing:
        print(f"run_probes: transcripts NOT located for probes {missing} under "
              f"{', '.join(str(r) for r in backend.roots())}", file=sys.stderr)
    return 1 if (failed or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
