# Detection guide — dead-code-cleanup

Helper for `dead-code-cleanup.md`. Category semantics for `find_dead_code.py` output, the mandatory pre-removal vetting checklist, flag-only routing, and edge cases. The inventory is candidate EVIDENCE, not a verdict: nothing may be removed on the detector's word alone. Test code is permanently out of scope here — orphan tests, uninvoked suites, and test helpers route to the `dead-test-cleanup` workflow (the detector already drops test roots and counts them in `hints.excluded_test_items`).

## Category semantics

| Category | Means | Remediation path |
|---|---|---|
| unused-file | knip found no import path from any entry point to the file | vetting checklist → file deletion |
| unused-export | exported symbol never imported elsewhere | vetting checklist → export demotion when used inside its own file; deletion only when the symbol body is also unreferenced in-file |
| unused-type-export | exported type/interface/enum never imported | same as unused-export |
| unused-dependency | package.json dependency never imported | deletable only when vetting proves zero imports AND no script/CI/config usage; otherwise flag-only |
| unused-devdependency | devDependency never imported by tooling knip models | same as unused-dependency — tool configs and npm scripts invoke binaries knip may not model |

knip `unlisted`/`unresolved` issues land under `hints`, never as delete candidates: they signal missing declarations or broken specifiers — repo-health findings to file per the repo's findings convention, not dead code.

## Mandatory vetting checklist (executor, before each removal)

LLM needed because judging whether evidence truly proves a candidate dead requires reading unstructured file content and docs for dynamic references static analysis cannot enumerate.

For every approved id, in order:

1. **Open the file/symbol.** Confirm it is what the inventory claims.
2. **Search dynamic/string-built references** — route registration tables, CLI subcommand dispatch, glob-based discovery, config/reflection loading, build-script copies, template strings assembling the path or symbol name.
3. **Check docs/specs/gherkin mentions** — every mention is co-change surface that must be amended in the same PR.
4. **Confirm no env flag or conditional resurrects it** — grep the name and any env vars near its references. A feature someone can still switch on is alive → flag-only.
5. **Export used only internally → demote, never delete**: remove the `export` keyword (or the re-export line) and keep the symbol. This is a distinct remediation the goal must name per item; deleting a demotion-approved symbol is a contract breach.
6. **Dependency: prove absence beyond imports** — grep package.json scripts, CI files, tool configs, and binary invocations (`npx <bin>`, `<bin>` in script bodies). Any hit → flag-only.
7. **In doubt → flag-only**, with the reason recorded. Doubt is cheap; restoring a deleted module is not.

## Flag-only routing

File each flag-only finding per the repo's findings convention (recorded in `$HD/repo-policy.md`). WARNING: if the findings convention interacts with a push gate (e.g. an unresolved-findings hook that blocks pushes while docs sit in the worktree), use the repo's documented parking remedy — never bypass or weaken the gate itself.

## Edge cases

Worked examples — recurring archetypes in a TypeScript monorepo rooted at `<REPO_ROOT>`:

- **Vendored trees** (e.g. `vendor/**` mapped via tsconfig `paths`): protected, never prune (`--protected vendor`).
- **Runtime-glob-discovered asset dirs** (e.g. a plugin/workflow directory whose members are loaded by `*/*.md` at runtime): invisible to the import graph, so unused-file hits there are false positives → protected/flag-only.
- **Filename-loaded migrations** (e.g. `migrations/`): loaded by filename at runtime; no import edges exist by design.
- **Build-copied assets** (e.g. a prompt or persona `.md` copied by the build script, not imported).
- **Coverage-floor baselines** (e.g. `coverage-per-file-baseline.json`): deleting any src file requires regenerating the baseline per the repo's documented command as a co-change in the same PR, or the gate goes red on main.
- **Findings convention** — flag-only findings are filed through the hosting repo's own issue-tracking workflow, in whatever form and location that workflow mandates.
- **Governance plans** — a repo-level simplification/refactor plan that explicitly "authorizes NO pruning" in a given phase gates mass pruning, and mass dependency pruning belongs to whichever phase that plan assigns it. An unused-dependency finding is deletable only when checklist item 6 fully passes; otherwise flag-only into the plan's backlog.

General:

- **Fallback mode** (`hints.mode` = `fallback-generated-config`): the entry-point list was guessed from package.json `main`/`bin`/`exports` plus `src/index.*` heuristics, so whole subtrees may be falsely orphaned. Confidence is already capped low — expect mostly flag-only, and prefer getting repo-native knip (devDependency + checked-in config) adopted before deleting at scale.
- **File-local linters already gate** (e.g. biome/eslint `recommended` on unused locals): anything surviving them is cross-module evidence — still run the checklist; dynamic references live across modules, exactly where linters cannot see.
- **Monorepos**: knip workspaces only work in repo-native mode; in fallback mode treat every non-root package's findings as flag-only.

## Exit code 3 remediation

The detector could not produce a knip report; `detector.error` in the partial report says why. Common causes: `npx`/Node missing on PATH; repo-native mode chosen but knip is not installed (`npx --no-install` refuses to fetch — run the repo's dependency install first); knip config error; no derivable entry points in fallback mode (add repo-native knip, or ask the user what the entry points are). Fix the cause and rerun the detector. If the repo genuinely cannot run knip, ask the user how dead code is detected in this repo — do not hand-roll an import-graph analysis.
