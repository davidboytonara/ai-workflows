---
trigger: All branch work, no exceptions — even a one-line fix gets its own worktree; parallel branches without stash, reviewing a PR locally, stacked branches, post-merge cleanup.
---

## Trigger

All branch work, without exception — even a one-line fix gets its own worktree. Also: parallel branches without `git stash`, long-running work that would block the main checkout, reviewing a PR locally, stacked-branch decisions, post-merge cleanup. New to the model? Read `worktree-hygiene.md` first.

## Goal

A fresh worktree at `worktrees/<slug>` holds the branch, rebased on its base before every push and PR; after merge worktree, branch, and per-worktree DBs are all gone.

## Context

**Worktrees are the only way to branch.** `git checkout -b` is dead: a local `reference-transaction` hook blocks branch create/delete from a linked worktree, and git refuses to delete a branch checked out elsewhere — so branch bookkeeping always runs from the main checkout, which stays on `main`.

**Naming.** Branch `<type>/<slug>`; `<type>` is `feature` (new capability), `fix`, `chore` (tooling/deps/refactor, no behavior change), or `docs`. Slug: lowercase, hyphenated, ≤40 chars, no ticket noise. Worktree dir = the slug alone (branch `feature/auth-rewrite` → `worktrees/auth-rewrite`), 1:1 with the branch. `worktrees/<slug>` (repo root, gitignored via `worktrees/*`) is *your checkout*; `.git/worktrees/` is git's internal per-worktree metadata — never put checkouts there, never hand-edit its files.

**Pattern A vs Pattern B — decide before creating.** **Pattern A (independent)** — needs no code from another in-flight branch; root at `origin/main`; the default. **Pattern B (stacked)** — imports a parent's symbols/types/schemas/migrations, or its tests fail without the parent's commits; root at the parent branch. Decision protocol: for each pair of in-flight scopes ask *"Can X be reviewed and merged before Y, with no edits to Y?"* — Yes for all pairs → A; any No → B, chained in dependency order.

**Create.** Preferred: your repo's worktree bootstrap script, if it provides one (e.g. `scripts/setup-worktree.sh <type>/<slug>`) — it runs `git worktree add` and seeds concurrency-safety: secrets, venvs, real `node_modules`, an isolated env file with distinct ports + per-worktree DBs (see your repo's deployment/env-matrix docs). Raw forms that skip the seeding: **Creating without the script** in `worktree-details.md`.

**The sync gate** — rebase onto the base immediately before **every** `git push` *and* every `gh pr create`. Proof, which must print `0`:

```bash
git fetch origin && git rev-list --count HEAD..origin/main   # Pattern B: substitute the parent — the base is whatever the PR targets
```

Machine-enforced as the first pre-push job — job names, scripts, stack base overrides, and what else the gate runs: **Sync-gate machine enforcement** in `worktree-details.md`. **`gh pr create` has no hook** — git hooks fire on git operations only, so the pre-PR re-sync (the **pre-PR gates** in `../pull-request/pull-request.md`) is yours to run. Pulling `main` updates into a live branch: **Pulling `main` updates** in `worktree-details.md`.

**Follow-up drain — two checkpoints.** A repo may track deferred follow-up work in files that live *inside* the worktree. Such files are typically untracked, so worktree removal destroys them: drain them **before `gh pr create`** and again **before teardown** (they reappear between the two — review feedback, deferred fixes). What counts as a follow-up doc, where it lives, whether it may be parked elsewhere, when it is deleted, and which hook enforces it are the **hosting repo's** issue-tracking/handover workflow's to define — this workflow only reserves the two checkpoints. `pre-pr-gate.sh` checks both (a repo with no such directory passes trivially).

**Teardown after merge** — always all three: worktree, branch, per-worktree test + runtime DBs. (The DB half is repo-specific: some repos' same-named script removes only worktree + branch — see the isolation note in `worktree-hygiene.md`.) From the main checkout: your repo's teardown script, if it provides one (e.g. `scripts/remove-worktree.sh <slug>`) (path also works; `--force` if dirty or unmerged-by-SHA after squash). **`--prune-orphans` is a SEPARATE mode, not an add-on flag** — it does NOT tear down `<slug>`; it only sweeps DBs whose worktree is already gone, then exits: run the two forms separately. Manual equivalent and hand-deleted-dir recovery: **Teardown — manual equivalent** in `worktree-details.md`.

**Merging a Pattern B stack** — bottom-up, parent before child: the parent's merge reshapes history, so each child is realigned before it merges; delete a parent's branch/worktree only after its child is retargeted. Squash-merge needs a per-layer rebase of each child (commands and why: **Squash-merging a Pattern B stack** in `worktree-details.md`); merge-commit / rebase-merge keep the parent's commits on `main` — retarget and merge, no rebase.

## Constraints

- One branch per worktree; **never reuse a worktree** for the next branch — create fresh off `origin/main` (`worktree-hygiene.md` explains the false-divergence trap).
- `pull --rebase` is mandatory before **every** push and before opening a PR — the count proof must print `0`. Non-zero is a STOP: rebase, re-run the gate, then push. Never `--no-verify` — it skips the sync check and every other pre-push job (see the **pre-push gate** in `../pull-request/pull-request.md`).
- Never bare `git pull` on a drifted worktree (**Pulling `main` updates** in `worktree-details.md`).
- Follow-up work the hosting repo tracks inside the worktree must be drained at **both checkpoints** — a leftover is a STOP; the remedies are that repo's workflow's to define.
- A rebase conflict that needs a real product decision → ask the user, never blind-pick (`../pull-request/pull-request.md`).
- Unclear whether one branch needs another's code to compile/test (Pattern A vs B) → ask the user, do not guess.
- After merge, always tear down all three: worktree, branch, per-worktree DBs.
- Path is always `worktrees/<slug>` at the repo root — never inside `.git/`, never `../<repo>-<slug>` or `~/work/<slug>`, never nested in another worktree. Never edit `worktrees/<slug>/.git` (a pointer file). Never `rm -rf` a tracked worktree — `git worktree remove`, then `git worktree prune` if needed.
- **Never let GitHub's auto-retarget merge a stacked child without its per-layer rebase** — the duplicate-diff / conflict trap.

## Verify

```bash
git worktree list                                            # worktree at worktrees/<slug>; main checkout on main
git fetch origin && git rev-list --count HEAD..origin/main   # 0 before any push/PR (Pattern B: parent as base)
"$HOME/.agents/workflows/git/pre-pr-gate.sh" <base>          # exit 0 at both checkpoints (sync + follow-up drain)
# After teardown:
git worktree list | grep "worktrees/<slug>" || echo "worktree gone"
git branch --list "*<slug>*"                                 # empty
psql -lqt | grep -E "<db-prefix>_(test|wt)_<slug>" || echo "DBs gone"   # only if your repo makes per-worktree DBs
```
