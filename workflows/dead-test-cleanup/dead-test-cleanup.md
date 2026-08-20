---
trigger: "Find dead tests", "clean up orphan / unused tests", "remove uninvoked suites or vacuous scenarios" — test code only; dead production code goes to dead-code-cleanup.
---

## Trigger

"Find dead tests", "clean up orphan / unused tests", "remove uninvoked test suites", "prune vacuous scenarios in <repo>" — automation-test code only; dead production code triggers `dead-code-cleanup` instead.

## Goal

Every user-approved candidate — orphan test files and helpers, uninvoked suites, vacuous scenarios — is deleted from the target repo through the repo's own PR-to-merge workflow via the casper harness, every flag-only finding is filed per the repo's findings convention, and verification passes against the merged base branch.

## Context

**Harness skeleton.** The session variables, harness contract, execution pattern (scaffold → detached fanout + `BEFORE` watcher seed), expected NEEDS-USER pauses, shared constraint set, and the verify/repair/cleanup sequence live in [`../dead-code-cleanup/harness-skeleton.md`](../dead-code-cleanup/harness-skeleton.md) — read it alongside this file. Every command below assumes its **Session variables** with `<slug-prefix>` = `dead-test-cleanup`.

**Detection.**

```bash
"$PY" "$WF/find_dead_tests.py" --repo-root "$REPO" --out "$HD/inventory.json" --summary
```

| Exit | Meaning | Action |
|---|---|---|
| 0 | inventory written, ≥1 candidate | continue |
| 1 | inventory written, zero candidates | report to user; stop |
| 2 | usage error | fix arguments |
| 3 | extraction too incomplete (partial report still written) | **Exit code 3 remediation** in `detection-guide.md`; rerun with `--extra-globs` |

If `hints.vacuous_detector_candidates` is non-empty, run the repo's own detector, save its output to `$HD/vacuous.txt`, and rerun with `--vacuous-list "$HD/vacuous.txt"`. After policy recon, rerun adding `--protected <prefix> ...` per protected tier.

**Repo policy recon** (→ `$HD/repo-policy.md`). Read the target repo's README, CONTRIBUTING, AGENTS.md/CLAUDE.md, and docs for: never-delete/protected test tiers; co-change gates (docs/specs/gherkin that must move with tests); the findings convention and whether it interacts with a push gate (if so, record the repo's documented parking remedy); the PR/worktree/merge convention; the full local gate command. LLM needed because deletion and co-change policies live as free-form prose across arbitrary repo docs and cannot be enumerated by a rule.

**Vetting.** Cross-check every item against `$HD/repo-policy.md` and `detection-guide.md` (category semantics, mandatory checklist, edge cases). LLM needed because judging whether evidence truly proves a candidate dead requires reading unstructured file content and docs for dynamic references static scanning cannot enumerate.

**Goal authoring.** Fill `goal-template.md` into `$HD/goal.md` — approved deletions, flag-only list, protected paths, full-gate command with its own realistic timeout, tailoring notes applied. LLM needed because folding vetted candidates and prose policies into a binding contract requires judgment over unstructured recon notes.

**Execution.** Run the **Execution** section of `../dead-code-cleanup/harness-skeleton.md` verbatim: ledger scaffold, detached fanout, tracked watcher, and the expected NEEDS-USER pauses.

**Bundled files.** `find_dead_tests.py` is the scanner; `detection-guide.md` holds category semantics, the mandatory vetting checklist, flag-only routing, and edge cases; `goal-template.md` is the goal.md skeleton + tailoring notes.

## Constraints

- The **Shared constraints** in `../dead-code-cleanup/harness-skeleton.md` bind here verbatim: approval gate, whole-suite/tier question, plan-objective requirements, merge authorization.
- The inventory is evidence, not a verdict: nothing is deleted on the scanner's word alone. Demote policy-protected or env-gated items to flag-only.

## Verify

```bash
"$PY" "$CWF/casper_verify.py" --handover-dir "$HD" --cwd "$REPO"
```

Then follow **Verify / repair / cleanup** in [`../dead-code-cleanup/harness-skeleton.md`](../dead-code-cleanup/harness-skeleton.md) exactly: criteria check `origin/<BASE>` and the synced main checkout only; substitute the executor-reported PR number first; on a failed criterion checkpoint the repair note, mark the plan `failed`, rerun fanout, verify again; run `casper_cleanup.py` only after all-pass and reporting the result to the user.
