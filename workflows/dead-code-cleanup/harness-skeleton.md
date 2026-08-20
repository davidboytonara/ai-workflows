# Cleanup harness skeleton — shared by dead-code-cleanup and dead-test-cleanup

Referenced helper for [`dead-code-cleanup.md`](dead-code-cleanup.md) and [`../dead-test-cleanup/dead-test-cleanup.md`](../dead-test-cleanup/dead-test-cleanup.md). It holds the harness plumbing the two workflows share verbatim; each workflow's own file holds its detector, category payload, and payload-specific rules. `<slug-prefix>` below is `dead-code-cleanup` or `dead-test-cleanup`, per the calling workflow.

## Session variables

Every command in this file and in the calling workflow assumes these:

```bash
REPO=<abs path to target repo main checkout>
SLUG="<slug-prefix>-$(basename "$REPO")"
HD="$HOME/.agents/handovers/$SLUG"; mkdir -p "$HD/logs"
PY="$HOME/.agents/.venv/bin/python"; [ -x "$PY" ] || python3 -m venv "$HOME/.agents/.venv"
WF="$HOME/.agents/workflows/<slug-prefix>"
CWF="$HOME/.agents/workflows/casper"
```

## Harness contract

Everything from goal approval to cleanup runs under `$CWF/casper.md` — re-read it from disk before goal authoring; the on-disk version wins over context. Its load-bearing concepts here: the **goal approval gate**, the **plan ledger** (`casper_status.py --scaffold`), **detached fanout + tracked watcher** execution, **NEEDS-USER** pauses, and the **resume checklist** — a run is resumable anytime with this `$HD`.

## Execution

`"$PY" "$CWF/casper_status.py" --scaffold --handover-dir "$HD"` creates the whole-goal `plan-01-$SLUG.md` + `plans.json` and seeds the ledger (exit `1` = no `$HD/goal.md` — get the goal approved first). Fill the plan's `## Objective`, then the detached fanout:

```bash
BEFORE=$(stat -c %Y "$HD/fanout-result.json" 2>/dev/null || echo 0)
setsid nohup "$PY" "$CWF/casper_fanout.py" --handover-dir "$HD" \
  --model opus --stopwatch 7200 --max-context-tokens 470000 \
  >> "$HD/logs/fanout.log" 2>&1 & disown
```

Then start the background watcher on `fanout-result.json` exactly as the **detached fanout + tracked watcher** pattern in `$CWF/casper.md` shows, substituting `$BEFORE` with its literal value.

**Expected NEEDS-USER pauses** (not failures): ambiguous protection policy — for dead-code also ambiguous dynamic-reference evidence; CI red for causes unrelated to the removals; merge blocked on a required human review. Relay to the user, record the answer in the plan, rerun fanout with a fresh watcher.

## Shared constraints

Both workflows bind these verbatim, in addition to their own payload-specific constraints:

- Approval gate: present the vetted inventory to the user as a table (delete vs flag-only, with id, path/symbol/script, category, confidence, evidence), then show `$HD/goal.md` and STOP — no planning or execution until the user approves it (the **goal approval gate** in `$CWF/casper.md`).
- If no protection policy was found anywhere and a candidate is a whole directory, subsystem, suite, or tier, ask the user before goal authoring.
- The plan objective MUST require verbatim: fresh disposable worktree/branch per the repo convention; independent re-verification of every candidate via the detection-guide checklist before removing it; co-change edits (docs/specs/gherkin) in the same PR; each flag-only finding filed per the repo convention (via its parking remedy if the convention blocks pushes); full local gate before push; the complete PR chain — push, open PR, watch CI, merge when green (authorized by the approved goal), sync main, remove worktree + branch; if the stopwatch nears while waiting on CI/merge, checkpoint the PR number and exact next action, then stop — a pause, never a fail. The calling workflow's own constraints add its payload-specific verbatim requirements to this objective.
- Merging on green CI is authorized by the approved goal; a required human review approval is not — never self-approve; pause with NEEDS-USER.

## Verify / repair / cleanup

```bash
"$PY" "$CWF/casper_verify.py" --handover-dir "$HD" --cwd "$REPO"
```

Criteria check `origin/<BASE>` and the synced main checkout only — never the executor's worktree (deleted post-merge). Substitute the executor-reported PR number into the criteria first (parameter fill, not a contract change — the calling workflow's `goal-template.md`). On a failed criterion, put the exact repair note in the checkpoint, then:

```bash
"$PY" "$CWF/casper_status.py" --set "plan-01-$SLUG.md" failed --handover-dir "$HD"
```

rerun fanout, and verify again. Only after all-pass and reporting the result:

```bash
"$PY" "$CWF/casper_cleanup.py" --handover-dir "$HD"
```
