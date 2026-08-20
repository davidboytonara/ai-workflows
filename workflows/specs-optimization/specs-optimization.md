---
trigger: "Optimize how our specs are split for AI", "are our docs well categorized for agents", "recommend a spec re-split", "why do agents struggle to find specs".
---

## Trigger

"Evaluate / optimize how our specs are split for AI", "are our docs well categorized for agents", "recommend a spec re-split", "why do agents struggle to find specs".

## Goal

`$RUN/report.md` exists with metric-backed per-domain navigation friction and concrete re-categorization recommendations, derived from real probe behavior over the repo's spec corpus. No spec files are changed.

## Context

**Mechanism.** `COUNT` read-only feature-investigation probes run as **headless CLI processes** through `../casper/LLM_harness.sh`, so the workflow works under any driving harness that can run a shell command; a script then mines their transcripts for friction (searching, cross-domain hops, re-reads, dead-ends, index reliance). Bundled: `discover_specs.py` (corpus detection), `run_probes.py` (fan-out + transcript resolution), `probe_backends.py` (per-harness profiles), `harvest_nav.py` (miner), `verify_run.py` (done gate). Only prompt generation and the final report are LLM steps.

**Probe identity.** Agent ids do not exist outside Claude Code. `run_probes.py` mints a run token `SPECPROBE-<8hex>` and embeds `[probe <token>#<i>]` in each prompt; transcripts are located by scanning the backend's root for files modified at/after run start whose first user message holds that marker. The read-only probe system instruction is `PROBE_PREAMBLE` in `run_probes.py` (it replaced the deleted `spec-probe.agent`), prepended to every prompt — nothing is installed into `~/.claude/agents`.

**Backend capabilities (what degrades where).** `probe_backends.py` holds one profile per backend and reports a `capabilities` dict into `metrics.json` and the digest header. `claude` (`projects/<slug>/<uuid>.jsonl` + nested `agent-<hex>.jsonl`) has both `tool_results` and `nesting`. `pi` (`sessions/<slug>/<ISO>_<uuid>.jsonl`, session-level `cwd` only) has **no `nesting`** — a `subagent` result carries no session pointer — and declares `tool_results` false, upgraded only when transcripts truly carry `role:"toolResult"` (pi ≥ 0.84). Without `tool_results` the `failed` term is **dropped** from the friction sum (never zero) and the digest says `failed-read signal unavailable on <harness>`; without `nesting`, how many spawns went unmined.

**Inputs and run setup.** `PROJECT_ROOT` (default cwd), `SPECS_DIR` (auto-detected; override only if detection is wrong), `COUNT` (default **17**), model/effort (default **Sonnet 5 / `xhigh`**), `RUN` (one per invocation):

```bash
PY="$HOME/.agents/.venv/bin/python"; WF="$HOME/.agents/workflows/specs-optimization"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"; COUNT="${COUNT:-17}"
MODEL="${MODEL:-sonnet}"; EFFORT="${EFFORT:-xhigh}"; STOPWATCH="${STOPWATCH:-3600}"
RUN="$HOME/.agents/state/specs-optimization/$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"; mkdir -p "$RUN/logs"
```

**Corpus detection.** `"$PY" "$WF/discover_specs.py" --repo-root "$PROJECT_ROOT" --out "$RUN/manifest.json"` — the manifest holds categories, file counts, nav-aids, declared map. Exit `1` → no corpus: ask for `SPECS_DIR`, re-run with `--repo-root "$SPECS_DIR/.."`. Exit `2` → fix args.

**Probe prompts.** *LLM needed because:* crafting diverse, realistic "investigate/develop `<feature>`" tasks from a freshly-discovered category list needs semantic understanding of each domain — a template yields generic probes that don't exercise real navigation. Write `COUNT` **distinct** prompts spanning all manifest categories (≥1 each; remainder to the largest or most-coupled), each a deep investigation of one concrete feature in `$PROJECT_ROOT`, as a JSON array of strings in `$RUN/prompts.json`.

**Fan-out (detached + tracked watcher).** The fleet outlives any single tool call: launch detached, then immediately start a watcher whose completion notification wakes the driver (pattern from [`casper.md`](../casper/casper.md)):

```bash
setsid nohup "$PY" "$WF/run_probes.py" --prompts "$RUN/prompts.json" --run-dir "$RUN" \
  --model "$MODEL" --effort "$EFFORT" --stopwatch "$STOPWATCH" \
  >> "$RUN/logs/run_probes.log" 2>&1 & disown
```

Then in a **separate** call start the watcher — Claude Code: Bash with `run_in_background: true`; pi: the `job_start` tool. Same command either way:

```bash
while [ ! -f "$RUN/probes.json" ]; do sleep 20; done; tail -5 "$RUN/logs/run_probes.log"
```

Substitute `$RUN` literally — shell state does not persist between calls. `run_probes.py` runs `min(COUNT, 8)` probes in parallel (`--concurrency`), writes each stdout to `logs/probe-NN.log`, then `probes.json` = `[{index, token, prompt, exit_code, transcript}]`. Exit `1` → a probe failed or was unlocated (indices named); `2` → fix args. `--dry-run` prints the resolved model/harness/token and the exact command, launching nothing.

**Harvest.** After `probes.json` exists:

```bash
SPECS=$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['specs_root'])" "$RUN/manifest.json")
"$PY" "$WF/harvest_nav.py" --probes "$RUN/probes.json" --harness auto --specs-root "$SPECS" \
  --manifest "$RUN/manifest.json" --out-dir "$RUN" --digest-budget-bytes 24000
```

`--harness auto` infers the backend from the transcript paths (and refuses a mixed run). Writes `metrics.json`, `nav_traces.md`, `digest.md`. Exit `1` → no transcripts located, or no spec navigation (check `SPECS_DIR`/prompts); report and stop. `2` → fix args. Artifacts in `$RUN`: `manifest.json`, `prompts.json`, `probes.json`, `metrics.json`, `nav_traces.md`, `digest.md`, `report.md`, `logs/`.

**Report.** *LLM needed because:* turning friction signals into causal explanations and concrete re-split recommendations is open-ended synthesis no rule can encode. Read `$RUN/digest.md` (budget-bounded; `nav_traces.md` for trace detail) and write `$RUN/report.md`: (a) per-domain friction, highest first, with the metric evidence; (b) inefficiency patterns (split domains, universally re-read files, dead ends, whole-corpus searching, missing nav-aids); (c) concrete re-categorization recommendations. Carry the digest's capability caveats through — never present an unavailable metric as a good score.

## Constraints

- **Analyze-only.** This workflow edits no spec files; every probe prompt **must end with the exact line**: `Do not make any change yet.`
- **Only `harvest_nav.py` reads `*.jsonl`.** The session reads `digest.md` (and `nav_traces.md` if needed) — **never** `cat` raw transcripts or full probe logs; they overflow context.
- **One backend and one model/effort per run.** `run_probes.py` takes one `--model`/`--effort` for the fleet and `harvest_nav.py` refuses mixed harnesses — mixed models make the metrics incomparable.
- Probes are token/time heavy and run `min(COUNT, 8)` at a time — lower `COUNT` for trials. Do not harvest before `$RUN/probes.json` exists; re-running `run_probes.py` overwrites it.
- Report degraded metrics honestly: without `tool_results`, failed reads/searches are unknown, not zero.
- If `discover_specs.py` exits `1`, ask the user for `SPECS_DIR` — do not guess a corpus root.
- Run Python via `$HOME/.agents/.venv/bin/python` only.

## Verify

```bash
# Workflow still discoverable
"$PY" "$HOME/.agents/workflows/work-with-workflow/list_workflows.py" | grep specs-optimization

# One gate for every deterministic done-criterion: the seven artifacts parse, every
# prompt carries the read-only suffix, one probes.json entry per prompt with exit_code
# 0 and an existing transcript, digest within budget, specs_root clean per git status.
"$PY" "$WF/verify_run.py" --run-dir "$RUN" --digest-budget-bytes 24000
```

Done when discovery lists the workflow and `verify_run.py` exits `0`. Exit `1` prints one line per failed check — fix and re-run; `2` → fix args.
