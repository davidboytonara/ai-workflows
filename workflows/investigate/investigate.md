---
trigger: "What does this area look like", pre-planning recon, gathering handoff context for implementation or review — read-only. NOT for edits or finished deliverables.
---

## Trigger

A requester needs context they do not have: "what does this area look like", pre-planning recon, or gathering handoff context for an implementation or review pass. NOT for editing files (`../implement/implement.md`) or producing finished deliverables — stories, specs, docs, reports (`../write/write.md`).

## Goal

Structured findings exist in the output format below — precise enough (exact paths and line ranges) that a reader who has NEVER seen these files can start working immediately.

## Context

**Audience.** The output goes to a reader who has NOT seen the files investigated. Compress accordingly: findings, not narration.

**Thoroughness** (infer from the task; default medium):
- Quick: targeted lookups, key files only
- Medium: follow imports/references, read critical sections
- Thorough: trace dependencies/related docs, check tests/types where relevant

**Output format:**

### Files Retrieved
List with exact line ranges:
1. `path/to/file.ts` (lines 10-50) - what's here
2. `path/to/other.md` (lines 100-150) - description

### Key Context
Critical types, interfaces, functions, requirements, decisions, or constraints — actual code from the files in fenced blocks.

### Architecture / Relationships
Brief explanation of how the pieces connect.

### Start Here
Which file to look at first and why.

## Constraints

- Investigation ONLY. Do not edit or create files, and do not produce final deliverables.
- Shell commands are for read-only inspection only (grep/rg, find, ls, cat, git log/show) — never mutating commands.
- Be fast: targeted reads over exhaustive ones; speed is part of the contract.
- Quote real code in Key Context — no paraphrased pseudo-code.

## Verify

- All four output sections present; "Start Here" names one concrete file.
