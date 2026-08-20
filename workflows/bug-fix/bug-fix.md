---
trigger: "This is broken", a reported bug, a failure, "fix this bug" — diagnose → fix → prove; also resuming a bug-fix plan already in a project's .agents/handovers/.
---

## Trigger

The user reports a bug, a failure, or "this is broken" — anything where the work is diagnose → fix → prove. Also resuming an existing bug-fix plan found in a project's `.agents/handovers/`.

## Goal

The bug is fixed with tests that were confirmed red before the fix and green after, the original repro no longer reproduces, and the plan file is retired through `bug_fix_plan.py complete` with every checkbox done.

## Context

**Where the plan lives.** In the **user's current project**, not in `~/.agents`: `.agents/handovers/<slug>.md`. Root resolves from `--repo-root`, else `git rev-parse --show-toplevel`, else cwd. The plan is the unit of tracking: it carries the root cause, the test plan, and the done criteria.

**Setup.**

```bash
PY="$HOME/.agents/.venv/bin/python"
BF="$HOME/.agents/workflows/bug-fix/bug_fix_plan.py"
```

**Scaffold.** `"$PY" "$BF" scaffold --slug <kebab-slug> [--title "<human title>"]` — exit `0` prints the plan path; exit `2` means the slug is not kebab-case; exit `3` means a plan for this slug already exists. The slug names the symptom, not the suspected cause (`login-500-on-empty-email`, not `fix-validator`).

**Plan sections.** §1 Symptom: quote the exact error text or log, note where it surfaced. §2 Reproduction: minimal, ordered repro with explicit expected-vs-actual — an unreproduced bug means you are about to fix a guess. §3 Root cause (*LLM needed because:* locating a causal chain across unfamiliar code from a symptom cannot be enumerated as a rule — it requires reading the code and forming a hypothesis): record `file:line` references and *why* the code produces the symptom; "where the error is caught/thrown" is not a root cause; if the evidence supports two competing causes, note both and pick the one the repro discriminates. §4 Tests: ships with unit / integration / browser rows — pick the layers that fit, and paste the confirmed failure output here or in §6. §5 Fix: ordered steps with `file:line` targets. §6 Verification: record the exact command lines so the next session can re-run them verbatim.

**Checkbox accounting lesson.** `complete` counts *every* checkbox in the file, not just the Done Criteria ones. For a test layer that does not apply, replace its line with a checked box stating why (`- [x] Browser test — n/a, no UI surface`) — a leftover unchecked row blocks retirement.

**Retire.** `"$PY" "$BF" complete --slug <kebab-slug> --check` is the dry run listing what is still open; without `--check`, exit `0` deletes the plan, exit `1` lists the unchecked boxes, exit `2` means wrong slug or plan not found.

**Drain-check interaction.** A repo that drains `.agents/handovers/` before a PR or a worktree teardown (the **follow-up drain** in [`../git/worktree.md`](../git/worktree.md), rules per that repo's own issue-tracking/handover workflow) will be blocked by a live plan file — intended: it means the fix is not finished. Retire the plan via `complete` before opening the PR.

## Constraints

- **Test-first is the point.** Tests confirmed red BEFORE the fix, green after; do not touch the fix until they are red — a test written after the fix proves nothing about the bug, and a fix landed without a failing-first test is not done, regardless of how obvious it looks.
- Confirm the repro actually fails before going further. If you cannot reproduce it, say so and ask the user for the missing environment, input, or data rather than proceeding.
- Fix the cause found in §3 — if the fix drifts somewhere else, the root cause was wrong: go back and update §3.
- On scaffold exit `3` (plan already exists), read it and resume from wherever its boxes stop; do not re-scaffold under a new slug.
- One plan per bug: two symptoms with one root cause = one plan; one symptom with two causes = two plans.
- The plan is the handover: keep §3–§6 current as you learn; a fresh session must be able to resume from the file alone.
- Never delete the plan by hand — only via `complete`. On exit `1`, finish the listed work; do not pass `--force`. `--force` exists only for a plan the user has explicitly abandoned: deleting a plan with open boxes silently drops tracked work, so it needs the user to say so.

## Verify

```bash
# Re-run the exact command lines recorded in §6: new tests green,
# plus the project's own suite/lint for the touched area.
# Re-run the §2 repro: it must no longer reproduce.

"$PY" "$BF" complete --slug <kebab-slug> --check   # exit 0: nothing open
"$PY" "$BF" complete --slug <kebab-slug>           # exit 0: plan deleted
```
