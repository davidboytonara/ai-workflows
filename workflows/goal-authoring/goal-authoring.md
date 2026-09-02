---
trigger: "Turn this ticket into a goal", "write goal.md for this", "draft a casper goal from this email/ticket/record" — any external record (ClickUp task, Gmail message/thread, issue, freeform ask) that needs translating into an approvable casper goal.md before execution.
---

## Trigger

"Turn this ticket into a goal", "write goal.md for this", "draft a casper goal from this email/ticket/record", "what would the acceptance criteria be for this" — any external record that needs to become an approvable `$HD/goal.md` before a `casper` run, or any other workflow's own "goal authoring" step that wants a shared implementation instead of reinventing one.

## Goal

Given one external record, `$HD/goal.md` exists, conforms to the goal contract in [`../casper/templates.md`](../casper/templates.md), and has been shown to the user for the **goal approval gate** in [`../casper/casper.md`](../casper/casper.md) — nothing plans or executes before that approval.

## Context

**Why this exists.** Every casper-driven workflow needs an approved `$HD/goal.md`, but nothing upstream of casper turns an external record — a ClickUp task, a Gmail thread, a freeform ask — into one. Each workflow was left to solve that translation ad hoc; `dead-code-cleanup/goal-template.md` is the one existing example, and it is built from a detector's inventory rather than a prose record. This workflow is the shared middle step — record in, approved goal.md out — that any workflow can call instead of rebuilding it.

**Session variables** (same shape as other workflows' handover setup):

```bash
PY="$HOME/.agents/.venv/bin/python"
CWF="$HOME/.agents/workflows/casper"
SLUG="<kebab-case-goal>"
HD="$HOME/.agents/handovers/$SLUG"
mkdir -p "$HD"
```

**Step 1 — capture the record verbatim.** Save the source record's full text — ClickUp task title + description + comments, Gmail message + thread context, or the user's freeform ask — to `$HD/record.md` before drafting anything. The goal must trace back to it, and whoever approves `goal.md` should be able to diff it against `record.md`. LLM needed because the record is unstructured prose, not a fixed schema.

**Step 2 — extract Objective / Acceptance Criteria / Verification.** Follow [`extraction-guide.md`](extraction-guide.md): pull explicit done-when / definition-of-done statements, checklist items, and stated constraints out of the record; turn each into one numbered, independently-verifiable acceptance criterion. LLM needed because judging what "done" means from prose requires reading intent, not pattern-matching a fixed field.

**Step 3 — draft `$HD/goal.md`.** Fill [`goal-draft-template.md`](goal-draft-template.md): Goal / Acceptance Criteria / Verification, numbered and paired per `../casper/templates.md`'s contract. Keep the template's contract rules (command/judgment labeling, the judgment cap, no heredocs in verification commands, realistic timeouts) — they are casper's parser constraints, not this workflow's opinion, and violating them fails silently at verify time rather than at drafting time.

**Step 4 — goal approval gate.** Show the user `record.md` alongside the drafted `goal.md` and STOP. This workflow never plans or executes; it hands an approved `goal.md` to `casper` ([`../casper/casper.md`](../casper/casper.md)) once the user approves it. Any later change to the goal's outcome or constraints needs renewed approval, same as casper's own rule.

## Constraints

- Never invent an acceptance criterion the record and the user's own words don't support — an ambiguous or missing done-condition is a pause-and-ask, not a guess.
- Never widen the goal beyond what the record actually asks for; a record that bundles unrelated asks gets split into separate goals (separate `$HD` handovers), not one goal with unrelated criteria.
- `record.md` is written once, verbatim, before drafting — the goal is derived from it, never edited after the fact to match a goal drafted first.
- Judgment verification items are capped at 2 per `../casper/templates.md`'s contract; prefer a command wherever a file check, git check, or exit-status check can decide the criterion instead.
- This workflow ends at the approval gate. It never calls `casper_fanout.py` itself — dispatch and execution are casper's job once `goal.md` is approved.

## Verify

- `$HD/record.md` exists and is non-empty.
- `$HD/goal.md` parses under casper's own contract — reuse its parser rather than re-implementing the pairing rule:

```bash
"$PY" -c "
import sys, pathlib
sys.path.insert(0, '$CWF')
from casper_verify import parse_goal
checks = parse_goal(pathlib.Path('$HD/goal.md'))
print(f'{len(checks)} paired criteria/verification items parsed OK')
"
```

- The user has explicitly approved `goal.md` (recorded in the conversation) before any `casper` call is made on it.
