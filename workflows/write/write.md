---
trigger: A non-code deliverable is requested: user story, spec, ticket, acceptance criteria, docs, README, marketing/UI copy, a report or product analysis. NOT code (implement).
---

## Trigger

A non-code deliverable is requested. Two payloads, one activity:

- **Product-definition payload** — a user story, feature spec, ticket, or a set of acceptance criteria.
- **Prose payload** — documentation, README content, marketing or UI copy, a report, or product analysis.

NOT code (`../implement/implement.md`) and NOT bare task decomposition (`../planning/planning.md`), unless the task explicitly asks for the written artifact as the deliverable.

## Goal

A clear, testable, accurate deliverable exists in the requested format and register, grounded in the real sources reviewed, with open assumptions surfaced.

## Context

**Inputs.** The request, plus audience, format/register, and source-of-truth paths when known.

**How to work.** Match the requested register — reference docs, marketing copy, and an executive report read very differently; a story or spec reads differently again. When no format is given, use the simplest conventional one and say so in Notes.

**Output format:**

### Completed
What was delivered.

### Deliverable
The story/spec/ticket/acceptance criteria, or the doc/copy/report/analysis — or the file path if written to file.

### Sources Reviewed
- `path/to/file.md` - relevant context

### Notes (if any)
Assumptions, blockers, or follow-ups.

## Constraints

- Do NOT edit code. Write files only when the task explicitly requests the deliverable at a path; keep such writes focused.
- Clarity gate: if requirements, audience, format, register, or source of truth are unclear, return concise questions INSTEAD of a misleading artifact.
- Every acceptance criterion must be individually binary-checkable — verifiable as pass/fail without judgment calls; no compound or vague criteria.
- Do not duplicate an existing source of truth — link or point to it instead of restating it.

## Verify

- The deliverable matches the requested format, register, and audience.
- Assumptions and open questions are surfaced in Notes, not silently embedded.
