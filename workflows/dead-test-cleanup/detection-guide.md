# Detection guide — dead-test-cleanup

Helper for `dead-test-cleanup.md`. Category semantics for `find_dead_tests.py` output, the mandatory pre-deletion vetting checklist, flag-only routing, and edge cases. The inventory is candidate EVIDENCE, not a verdict: nothing may be deleted on the scanner's word alone.

## Category semantics

| Category | Means | Path to deletion |
|---|---|---|
| orphan-helper | file under a test root: no runner glob matches it, and no code/config file references it (docs, markdown, lockfiles, build outputs excluded from the reference scan) | vetting checklist |
| orphan-test-file | test-named file (`*.test.*`, `*.spec.*`, `test_*.py`, `*_test.py`, `*.feature`) matching no extracted or supplied runner glob | vetting checklist |
| orphan-dir | test-root subdir: no glob match, no runner config points at it, no external reference to it or its contents | vetting checklist per contained file |
| uninvoked-suite | script invoking a runner binary with zero inbound edges from any CI file, git hook, npm lifecycle script, or their chased plumbing | vetting checklist, esp. item 5 |
| vacuous-scenario | ONLY the repo's own detector output (`--vacuous-list`) | per that detector's own contract |

**Out of scope — flag, never remove: conditionally-skipped or env-gated tests** (`@skip` tags, `it.skip`, env-var opt-ins, escape-hatch scripts). A test someone can still switch on is alive. Example: a `tests/regression/` tier that CI never invokes but the repo's own testing policy marks "never deleted" — always flag-only, enforced via `--protected tests/regression/`. Contrast a test script that no CI workflow, git hook, or gate invokes and no policy protects — a genuine deletable candidate.

## Mandatory vetting checklist (executor, before each deletion)

LLM needed because judging whether evidence truly proves a candidate dead requires reading unstructured file content and docs for dynamic references static scanning cannot enumerate.

For every approved id, in order:

1. **Open the file/script.** Confirm it is what the inventory claims.
2. **Search dynamic/string-built references** — path fragments, template strings, config-driven or reflective loading the scanner cannot see.
3. **Check docs/specs/gherkin mentions** — every mention is co-change surface that must be amended in the same PR.
4. **Confirm no env flag or conditional resurrects it** — grep its name and any env vars near its call sites.
5. **For a suite: script and globs die together.** Verify nothing (CI, hooks, plumbing) exercises the same test files through raw runner commands before deleting either the script or the files its globs cover.
6. **In doubt → flag-only**, with the reason recorded. Doubt is cheap; restoring a deleted gate is not.

## Flag-only routing

File each flag-only finding per the repo's findings convention (recorded in `$HD/repo-policy.md`). WARNING: if the findings convention interacts with a push gate (e.g. an unresolved-findings hook that blocks pushes while docs sit in the worktree), use the repo's documented parking remedy — never bypass or weaken the gate itself.

## Edge cases

- **No vacuous detector in the repo:** category 3 is skipped entirely (`hints.vacuous_status` says so). Never hand-roll vacuousness judgment.
- **No CI files:** confidence is capped low and category 2 evidence is weak — vet invocation by hand. Delivery still follows the repo's own convention.
- **No documented protected paths:** grep the repo docs for tier/never-delete language; if the repo is silent and a candidate is a whole suite/tier, raise `NEEDS-USER:` before deleting anything in it.
- **Monorepo / task runner detected (turbo, nx, lerna):** confidence capped low — pipelines can invoke scripts in ways the scanner does not parse; confirm invocation manually before trusting any uninvoked-suite item.
- **Unparsed runner configs** (`extraction.unparsed_configs`): the executor closes the gap — read each config, derive its include patterns by hand, and re-check every candidate under the affected tree before deletion.

## Exit code 3 remediation

The detector extracted no runner globs and none were supplied. Find them by hand: read the runner's config and docs, the CI files, and script bodies for include patterns, then rerun with `--extra-globs '<glob>' ...`. If the repo genuinely has no discoverable runner, treat every candidate as flag-only and ask the user how tests are run.
