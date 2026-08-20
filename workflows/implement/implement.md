---
trigger: A concrete engineering task is delegated — feature, plan step, refactor, test repair — and no project-local workflow covers it. Bugs: bug-fix. Read-only: investigate.
---

## Trigger

A concrete engineering task is delegated: implement a feature or plan step, write or repair tests, refactor, or any execution work requiring file changes — and no project-local workflow covers that kind of work (a project's own `.agents/workflows/` wins whenever it does). NOT a reported bug or failure (`../bug-fix/bug-fix.md`), NOT read-only recon (`../investigate/investigate.md`), and NOT primarily a written deliverable — story, spec, ticket, docs, copy, report (`../write/write.md`) — unless the task explicitly asks for code-adjacent edits within an engineering task.

## Goal

The assigned task is complete with focused checks run where available, and the report accounts for every file touched and every verification actually performed.

## Context

**Inputs.** The task with its full context: requirements, target paths, decisions already made, constraints, and expected outputs. If prior investigation findings (`../investigate/investigate.md`) or a plan (`../planning/planning.md`) were provided, follow them verbatim; deviations must be called out in Notes.

**Output format:**

### Completed
What was done.

### Files Changed
- `path/to/file.ts` - what changed

### Notes (if any)
Anything the requester should know.

If the work will be handed to review — open-ended or against explicit criteria (`../review/review.md`) — include the exact file paths changed and a short list of key functions/types touched.

## Constraints

- Ambiguity gate: if any requirement, target, or safe edit path is unclear, do NOT edit files at all — return the question/blocker; the requester will clarify and re-delegate.
- Never claim a check passed without running it; report real outcomes, including failures.
- Do not treat product writing as the deliverable unless the task explicitly says so.

## Verify

- Every created/changed/deleted file is listed in Files Changed — no silent edits.
- Focused checks for the touched area were run where available, or their absence stated.
