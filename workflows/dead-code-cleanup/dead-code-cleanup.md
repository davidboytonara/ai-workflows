---
trigger: "Find dead code", "clean up unused code / exports / dependencies", "prune dead files in <repo>" — production code only; dead tests go to dead-test-cleanup.
---

## Trigger

"Find dead code", "clean up unused code / exports / dependencies", "prune dead files in <repo>", "run a dead-code cleanup" — production code only; dead tests trigger `dead-test-cleanup` instead.

## Goal

Every user-approved candidate — file deletions, export demotions, dependency removals — is removed from the target repo through the repo's own PR-to-merge workflow via the casper harness, every flag-only finding is filed per the repo's findings convention, and verification passes against the merged base branch.

## Context

**Harness skeleton.** The session variables, harness contract, execution pattern (scaffold → detached fanout + `BEFORE` watcher seed), expected NEEDS-USER pauses, shared constraint set, and the verify/repair/cleanup sequence live in [`harness-skeleton.md`](harness-skeleton.md) — read it alongside this file. Every command below assumes its **Session variables** with `<slug-prefix>` = `dead-code-cleanup`.

**Detection.**

```bash
"$PY" "$WF/find_dead_code.py" --repo-root "$REPO" --out "$HD/inventory.json" --summary
```

| Exit | Meaning | Action |
|---|---|---|
| 0 | inventory written, ≥1 candidate | continue |
| 1 | inventory written, zero candidates | report to user; stop |
| 2 | usage error | fix arguments |
| 3 | detector unrunnable/failed (partial report still written) | read `detector.error`; **Exit code 3 remediation** in `detection-guide.md`, then rerun |

The detector prefers the repo's own pinned knip (config + devDependency). When `hints.mode` is `fallback-generated-config`, the entry points were guessed and every confidence is capped low — expect more flag-only. After policy recon, rerun adding `--protected <prefix> ...` per protected tree.

**Repo policy recon** (→ `$HD/repo-policy.md`). Read the target repo's README, CONTRIBUTING, AGENTS.md/CLAUDE.md, and docs for: protected paths/trees (vendored code, assets discovered by runtime glob, files loaded by name at runtime or copied by build scripts); co-change gates (docs/specs/gherkin that must move with code; coverage-floor baselines whose documented regeneration command must run as a co-change when a src file is deleted); governance plans that gate mass pruning (especially of dependencies); the findings convention and whether it interacts with a push gate (if so, record the repo's documented parking remedy); the PR/worktree/merge convention; the full local gate command. LLM needed because deletion and co-change policies live as free-form prose across arbitrary repo docs and cannot be enumerated by a rule.

**Vetting.** Cross-check every item against `$HD/repo-policy.md` and `detection-guide.md` (category semantics, mandatory checklist, edge cases). LLM needed because judging whether evidence truly proves a candidate dead requires reading unstructured file content and docs for dynamic references static analysis cannot enumerate.

**Goal authoring.** Fill `goal-template.md` into `$HD/goal.md` — approved file deletions, export demotions, and dependency removals listed separately; flag-only list; protected paths; full-gate command with its own realistic timeout; tailoring notes applied. LLM needed because folding vetted candidates and prose policies into a binding contract requires judgment over unstructured recon notes.

**Execution.** Run the **Execution** section of `harness-skeleton.md` verbatim: ledger scaffold, detached fanout, tracked watcher, and the expected NEEDS-USER pauses.

**Bundled files.** `find_dead_code.py` is the detector; `detection-guide.md` holds category semantics, the mandatory vetting checklist, flag-only routing, and edge cases; `goal-template.md` is the goal.md skeleton + tailoring notes.

## Constraints

- The **Shared constraints** in `harness-skeleton.md` bind here verbatim: approval gate, whole-directory/subsystem question, plan-objective requirements, merge authorization.
- The plan objective additionally MUST require verbatim: export demotions performed as demotions (remove the `export` keyword or re-export line, keep the symbol), never as deletions; coverage-baseline regeneration as a co-change in the same PR when a src file is deleted.
- Test code is permanently out of scope — route it to the `dead-test-cleanup` workflow.
- The inventory is evidence, not a verdict: nothing is removed on the detector's word alone. Demote dynamically-referenced, env-gated, or governance-gated items to flag-only; demote internally-used exports to export-demotion instead of deletion.
- If the delete list exceeds ~40 items, propose a high-confidence first tranche and defer the rest — the workflow is rerunnable; consistency beats completeness.

## Verify

```bash
"$PY" "$CWF/casper_verify.py" --handover-dir "$HD" --cwd "$REPO"
```

Then follow **Verify / repair / cleanup** in [`harness-skeleton.md`](harness-skeleton.md) exactly: criteria check `origin/<BASE>` and the synced main checkout only; substitute the executor-reported PR number first; on a failed criterion checkpoint the repair note, mark the plan `failed`, rerun fanout, verify again; run `casper_cleanup.py` only after all-pass and reporting the result to the user.
