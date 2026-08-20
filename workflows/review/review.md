---
trigger: "Review this", "check my work", "is this done" — judge delivered changes: open-ended quality/security, or PASS/FAIL against explicit criteria. Read-only verdict.
---

## Trigger

"Review this", "check my work", "is this done", "does this meet the acceptance criteria" — delivered work needs an independent, read-only judgement: after implementation, before a PR, when quality or security is in doubt, or when work is claimed complete against a stated list. Two modes, same posture:

- **Open-ended mode** — no fixed criteria list: judge quality, correctness, and security across the changed surface.
- **Criteria mode** — explicit criteria exist (acceptance criteria from a spec (`../write/write.md`), a plan's done-conditions, or a task's stated requirements): check each one individually. If criteria were referenced but not provided, extract them verbatim from the referenced spec/plan — or return a blocker asking for them. Never invent criteria.

The two can run together: criteria mode first, then a short open-ended pass if asked.

## Goal

A PASS/FAIL/BLOCKED verdict exists in the output format for the mode in play, with every must-fix finding — and, in criteria mode, every criterion — backed by concrete `file:line` or command evidence.

## Context

**Inputs.** What to judge: changed file paths, a diff range, or a work summary; plus the intent of the change and any specific concerns. In criteria mode, also the explicit criteria list (or the spec/plan to extract it from).

Reason deeply and skeptically before concluding — this activity warrants maximum deliberation.

**Output format — open-ended mode:**

### Files Reviewed
- `path/to/file.ts` (lines X-Y)

### Result
PASS, FAIL, or BLOCKED. PASS only when no must-fix issues remain; FAIL when critical issues must be fixed; BLOCKED when review cannot be completed (say why).

### Critical (must fix)
- `file.ts:42` - Issue description

### Warnings (should fix)
- `file.ts:100` - Issue description

### Suggestions (consider)
- `file.ts:150` - Improvement idea

### Summary
Overall assessment in 2-3 sentences.

**Output format — criteria mode:**

### Criteria Checked
- PASS/FAIL — Criterion 1: evidence (`file:line` or command + actual outcome)
- PASS/FAIL — Criterion 2: evidence

### Result
PASS (every criterion passes), FAIL (any criterion fails), or BLOCKED (cannot verify — say exactly what is missing).

### Summary
2-3 sentences: what passes, what is missing or failing.

## Constraints

- Review is READ-ONLY. Do not modify files.
- Shell commands must be non-mutating: `git diff`, `git log`, `git show`, `grep`/`rg`, `find`, `ls`, and similar inspection. No builds unless the task explicitly permits that specific command.
- Every Critical and Warning finding must cite `file:line`; no vague findings.
- Verdict honesty: unresolved must-fix = FAIL, never PASS-with-notes.
- Verify against the stated criteria only — do not widen into general review; out-of-scope observations get one line at most. *(criteria mode)*
- Unverifiable ≠ pass: a criterion without evidence is FAIL or BLOCKED, never PASS. *(criteria mode)*
- Evidence must be concrete and reproducible — cite the file:line or the exact command and its actual output. *(criteria mode)*

## Verify

- The verdict is consistent with the findings listed.
- Criteria mode: every provided criterion appears in Criteria Checked with its own PASS/FAIL and evidence — none dropped.
