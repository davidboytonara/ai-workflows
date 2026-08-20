---
trigger: Git looks confusing or wrong: status says clean but work seems unpushed, "ahead X, behind Y" after a merged PR, `git branch -d` refuses, is `reset --hard` safe.
---

## Trigger

Git looks confusing or wrong: `git status` says clean but you suspect unpushed work; a worktree shows "ahead X, behind Y" after its PR merged; `git branch -d` refuses to delete a merged branch; a drifted worktree and you're unsure whether `reset --hard` is safe; branch create/delete fails from a worktree; a worktree's tests seem to hit the wrong database.

## Goal

You read the repo's real state correctly (what is truly unpushed, what is truly merged), recover a drifted worktree without losing work, and keep every worktree isolated with its own `node_modules`, test DB, and runtime DB.

## Context

**Two facts cause every confusing "divergence" here.** This repo **squash-merges** every PR (one commit per PR on `main`) and uses **one disposable worktree per feature** at `worktrees/<slug>` (`worktree.md`).

**`git status` is silent about unpushed commits.** Feature branches here usually have **no upstream** (`git push` set one, then the remote branch was deleted at merge), so a clean `git status` proves nothing about unpushed work. The real state:

```bash
git fetch origin
git log --oneline origin/main..HEAD   # source of truth: commits you have that main does NOT
git branch -vv                        # every local branch + its upstream + tracking state
git worktree list                     # every worktree and the commit it sits on
```

`origin/main` is only a cache from your last `git fetch` — fetch first or the answer is stale.

**Why a reused worktree shows false "ahead/behind".** Squash-merge lands one fresh-SHA commit on `main`, so a fully-merged branch still looks diverged and a reused worktree drifts further every cycle — hence one fresh worktree per feature (create and teardown: `worktree.md`).

**Recover a drifted worktree.** `git fetch origin --prune`, then the safety check `git log --oneline origin/main..HEAD` FIRST. Empty output → all prior work is merged and `git reset --hard origin/main` is safe. Non-empty → local-only commits; see Constraints.

**Branch bookkeeping lives in the main checkout** (the `git worktree list` line NOT under `worktrees/`); inside a worktree you only commit, push, rebase, merge. Git refuses to delete a branch checked out in another worktree, and a local `reference-transaction` hook (untracked, in `.git/hooks/`) blocks branch create/delete from a linked worktree outright — its error says "create" even when you are deleting. Create: if your repo provides one, e.g. `scripts/setup-worktree.sh <type>/<slug>` (runs in the main checkout for you). Delete: if your repo provides one, e.g. `scripts/remove-worktree.sh <slug>` from the main checkout (or `git -C <main-checkout> branch -D <branch>`).

**Each worktree gets its own node_modules, test DB, and runtime DB** — the model is repo-specific. Per-worktree database isolation means each worktree's test and runtime databases carry a name derived from the worktree slug (e.g. `<db-prefix>_test_<slug>_<hash8>`), so parallel worktrees never share state and teardown must drop those databases as well as the worktree and branch. Never assume a repo implements this: read its own worktree scripts first, because a script that only removes the worktree and branch will leave orphaned databases behind.

**Recommended one-time setup.** If your repo provides a git-config bootstrap (e.g. `scripts/setup-git-config.sh`, or an `npm run setup:git` that also runs on `npm install`), it typically applies `fetch.prune`, `pull.rebase`, `merge.conflictstyle=zdiff3`, `rerere.enabled`, `push.autoSetupRemote` to the one shared `.git/config`, so a single run covers the main checkout and every worktree. Without `fetch.prune`, refs for branches GitHub already deleted linger and look like a remote branch that was never deleted.

## Constraints

- Never trust `git status` for what is unpushed — the source of truth is `origin/main..HEAD` after a fresh fetch.
- Do not keep working in a worktree after its PR merges — one fresh worktree per feature; after merge remove all three: worktree, branch, per-worktree DBs (**Teardown after merge** in `worktree.md`).
- Run the safety check FIRST, before any `git reset --hard origin/main`. Non-empty `origin/main..HEAD` → do NOT reset: land the commits, or ask the user before discarding anything.
- Delete a squash-merged branch only after confirming the work landed (empty `origin/main..HEAD`, or the PR shows "Merged") — then `git branch -D <name>`.
- Create and delete branches from the main checkout, never from a worktree.
- Before relying on the DB half of a repo's worktree scripts, verify it exists: `grep -c psql scripts/remove-worktree.sh`.

## Verify

```bash
git fetch origin
git log --oneline origin/main..HEAD       # empty = everything is on main; non-empty = real unpushed work
git branch -vv                            # tracking state matches what you concluded
git worktree list                         # worktrees sit where you think they do
[ -f scripts/remove-worktree.sh ] && grep -c psql scripts/remove-worktree.sh || echo "no teardown script in this repo"
```
