# Goal and plan templates

Helper for [`casper.md`](casper.md). Copy these shapes exactly; the pairing, approval, and status rules live in the primary. `casper_status.py --scaffold --handover-dir "$HD"` generates the plan doc and `plans.json` shapes below (idempotently) and seeds the ledger — only `## Objective` remains to fill.

**Checklist and waves.** A plan checklist is optional (executor completes unchecked items in order); no fixed phases or mandatory artifact types exist. Each split plan (see the primary's Constraints) must still be a complete executable work unit with one harness call; independent plans go in wave `0`, later waves only for real dependencies — fanout finishes one wave before dispatching the next.

## `$HD/goal.md`

Use `judgment: <inspection instruction>` only when no command or deterministic file check can decide a criterion. Criteria and verification methods must be numbered, paired, and in the same order; each verification item must begin with `command`/`[command]` or `judgment`/`[judgment]`.

````markdown
## Goal
<the complete desired outcome and constraints>

## Acceptance Criteria
1. <criterion>

## Verification
1. command (timeout=300)
   ```bash
   <command whose exit 0 proves the criterion>
   ```
````

## `$HD/plan-01-<slug>.md`

```markdown
---
status: pending
---

## Objective
<complete the approved goal; include relevant paths, constraints, and focused checks>

## Progress / Handover
```

## `$HD/plans.json`

```json
[
  {"file":"plan-01-<slug>.md","title":"Complete the approved goal","wave":0}
]
```
