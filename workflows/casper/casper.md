---
trigger: "Run casper on this", "execute this goal", "continue the handover" — an approved complex goal needing resumable, claim-safe execution; also any existing handover.
---

## Trigger

"Run casper on this", "execute this goal", "continue the handover" — any approved complex goal needing resumable, claim-safe execution; also any existing handover under `~/.agents/handovers/<slug>/`.

## Goal

The approved `$HD/goal.md` is completed — by default one whole-goal plan and one executor call — every acceptance criterion passes verification, the result is reported, and the transient handover directory is cleaned up.

## Context

**Pipeline and files.** `casper_fanout.py` claims open plans and makes one `LLM_harness.sh` executor call per plan; `casper_verify.py` decides the acceptance criteria; `casper_cleanup.py` retires the handover directory; `casper_status.py` maintains the `plans.json` status/lease ledger (plan frontmatter is a mirrored status). `casper_guard.py` (Claude token guard) and `casper_pi_guard.py` (Pi rpc guard) wrap dispatches; aliases, routing, credentials, effort defaults, guard mechanics: [`models-and-guards.md`](models-and-guards.md). Executor and verifier calls default to `medium` effort (GPT 5.6 Sol: `high`); plan authoring stays in the driving session at `xhigh`.

**Setup defaults.**

```bash
PY="$HOME/.agents/.venv/bin/python"
WF="$HOME/.agents/workflows/casper"
SLUG="<kebab-case-goal>"
HD="$HOME/.agents/handovers/$SLUG"
mkdir -p "$HD/logs"

MODEL="" # auto
STOPWATCH=7200
MAXCTX=470000
```

**Goal contract.** `$HD/goal.md` is the execution contract; shape and pairing rules: [`templates.md`](templates.md).

**Plan ledger.**

```bash
"$PY" "$WF/casper_status.py" --scaffold --handover-dir "$HD"  # whole-goal plan-01-$SLUG.md + plans.json, ledger seeded; exit 1 = no goal.md
```

Fill the scaffolded plan's `## Objective`; shapes, optional checklist, and split/wave rules: [`templates.md`](templates.md). For split plans (see Constraints) add plan files + `plans.json` entries yourself, then `--init`.

**Detached fanout + tracked watcher.** A fanout run outlives any single tool call: launch it detached, then immediately start a watcher the harness tracks so completion re-invokes the driver instead of stalling until the user asks:

```bash
BEFORE=$(stat -c %Y "$HD/fanout-result.json" 2>/dev/null || echo 0)
setsid nohup "$PY" "$WF/casper_fanout.py" --handover-dir "$HD" \
  --model "$MODEL" --stopwatch "$STOPWATCH" --max-context-tokens "$MAXCTX" \
  >> "$HD/logs/fanout.log" 2>&1 & disown
```

Then, in a separate Bash call with `run_in_background: true` (its task-notification is the wake-up; if the driver crashes only the watcher dies — the **Resume checklist** recovers the still-running fanout):

```bash
while [ "$(stat -c %Y "$HD/fanout-result.json" 2>/dev/null || echo 0)" = "$BEFORE" ]; do sleep 30; done
cat "$HD/fanout-result.json"
```

Substitute `$BEFORE` with its literal value — shell state does not persist between calls. Fanout appends per-plan output to `logs/<plan>.log` and replaces `fanout-result.json` with the latest outcomes; re-runs are idempotent — done plans skipped, paused/failed retried, live claims never duplicated.

**Completion semantics.** A resolver must explicitly mark its plan done through `casper_status.py`; exit `0` alone is not completion — without that signal the plan pauses. Timeout and token-budget exits (`124`/`137`) pause; other nonzero exits fail. An explicit done signal stays authoritative even if the process later times out or exits nonzero — except an open `NEEDS-USER:` always wins and pauses the plan. Warm resume and zero-progress stops: [`models-and-guards.md`](models-and-guards.md).

**Checkpoint and escalation.** The plan's `## Progress / Handover` section is a bounded replacement checkpoint, never an append-only journal — fanout embeds the exact replacement contract and wind-down obedience in every resolver prompt and compacts the section to 4000 characters (logs retain detail). An executor facing an irreversible/destructive or underivable decision records exactly one open **NEEDS-USER** line — `NEEDS-USER: <question and concrete options>` — finishes independent safe work, and stops. A `failed` plan's next attempt raises base effort by one (`medium`→`high`→`xhigh`→`max`; `max` stays); a pause never escalates effort.

**Lease safety.** Claims are atomic under a file lock; a claim lasts 7800 seconds (7200 stopwatch + 300 checkpoint grace + 300 slack), recorded in the lease; `--stale-secs` can lengthen protection but never shorten a recorded claim, even at `0` — wait for expiry. `casper_status.py --list-open` prints dispatchable work, not live-leased plans.

**Verification semantics.**

```bash
"$PY" "$WF/casper_verify.py" --handover-dir "$HD" --cwd "<project-root>" --model "$MODEL"
```

The verifier refuses while any plan is unresolved (including live `in_progress`), decides each `command` method only from its declared timeout (default 300 seconds) and exit status, batches all `judgment` methods into one harness call — command-only verification makes no LLM call — and never fixes work. Every run atomically replaces `$HD/verify.json`, even on contract or execution failures, so stale passing evidence cannot authorize cleanup. On a failed criterion: map the evidence to the responsible plan, `"$PY" "$WF/casper_status.py" --set "plan-01-$SLUG.md" failed --handover-dir "$HD"`, replace its checkpoint with the exact repair and next action, reopen affected checklist items, rerun fanout, verify again.

## Constraints

- **Goal approval gate**: show `goal.md` to the user and pause; do not plan or execute until the user approves it. The approved file is the contract — changes to its outcome or constraints require renewed approval.
- Do not create specification documents, test scripts, or other artifacts unless the approved goal itself requires them.
- One whole-goal plan and one executor call by default. Split only when a single executor cannot safely finish within the 7200-second / 470,000-token budget or when genuinely independent streams give useful concurrency; a plan whose inputs alone approach the token budget must be split.
- Never edit `plans.json` by hand — `casper_status.py` is its only writer.
- On wake, act without waiting for the user: surface any `NEEDS-USER:`, triage paused/failed plans, re-run fanout (fresh watcher) while open plans remain.
- A `NEEDS-USER:` is answered by the user, never by you: ask, replace the line with the recorded answer (e.g. `ANSWERED:` plus `USER-ANSWER:`), update the next action, rerun fanout. Fanout keeps only the latest line and will not redispatch while it stands.
- Verify only when every plan is done. Report unresolved criteria or `NEEDS-USER` blockers rather than claiming success.
- Clean up only after the result is reported: `"$PY" "$WF/casper_cleanup.py" --handover-dir "$HD"` refuses unless the directory contains `goal.md`, the ledger has no unresolved plans, and `verify.json` is non-empty all-pass. `--force` is only for a goal the user has explicitly abandoned, and still enforces the shape check.
- **Resume checklist**: re-read this file from disk first — the on-disk workflow wins over context; reuse the approved `$HD/goal.md`; inspect `plans.json`, checkpoints, `fanout-result.json`, log tails; resolve open `NEEDS-USER:` before dispatch; fanout detached + tracked watcher; verify when all done; clean up only on all-pass, else keep `$HD`.

## Verify

```bash
"$PY" "$WF/casper_status.py" --health --handover-dir "$HD"
[ ! -d "$HD" ] && echo cleaned # after cleanup only
```

Exit `0` = healthy: every plan done, no open `NEEDS-USER:`, `verify.json` non-empty all-pass. Exit `1` prints each failing check (or nothing-to-check when `$HD` is gone). If the script itself breaks, fall back to `--list-open` plus `cat` of `fanout-result.json` and `verify.json`.
