---
trigger: "Plan this", "how should we approach X", decompose a task before work starts. NOT specs/stories or finished prose (write), and NOT implementation (implement).
---

## Trigger

A task needs decomposition or an implementation plan before any work starts: "plan this", "how should we approach X", or a requester delegating large actionable work for planning first. NOT for written deliverables — stories, specs, tickets, docs, copy, reports (`../write/write.md`) — or implementation (`../implement/implement.md`).

## Goal

A minimal, parallel-deployment-ready plan exists in the exact output format below, grounded in the actual current state of the files.

## Context

**Inputs.** The original query or requirements, plus optional prior findings from a recon pass (`../investigate/investigate.md`).

**How to plan.** Inspect current state with read-only tools (read, grep, find, ls) as needed. Split work into independent tasks wherever possible; make ordering explicit only where necessary. Reason deeply before answering — this activity warrants maximum deliberation.

**Output format** — the plan IS the deliverable; an executing agent will follow it verbatim:

### Goal
One sentence summary of what needs to be done.

### Task List / Plan
Numbered steps, each small and actionable. Every task carries these exact fields:
- `Parallel: yes/no` - can run concurrently with other unblocked tasks.
- `Blocked by: none | Task N - reason` - required even if none.
- `Blocks: none | Task N` - required even if none.

1. Task 1 - specific file/function or area to inspect/modify. Parallel: yes. Blocked by: none. Blocks: Task 2.
2. Task 2 - what to add/change/verify. Parallel: no. Blocked by: Task 1 - needs findings first. Blocks: none.

### Files to Modify
- `path/to/file.ts` - what changes

### New Files (if any)
- `path/to/new.ts` - purpose

### Risks
Anything to watch out for.

## Constraints

- READ-ONLY. Do not edit or create files, and do not run any mutating command. Inspection only.
- Do not produce finished deliverables (stories, specs, docs, tickets, copy, reports) — return a plan.

## Verify

- Each file in "Files to Modify" was actually inspected or its existence confirmed.
- The plan is the smallest that satisfies the request — no speculative tasks.
