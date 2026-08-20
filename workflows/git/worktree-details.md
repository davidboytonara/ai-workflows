# Worktree details — raw commands, machine enforcement, teardown mechanics, stacked merges

Helper for `worktree.md` (intentionally no `description:` frontmatter — not a discovery entry).

## Creating without the script (raw forms)

The raw `git worktree add` forms skip any `setup-worktree.sh`-style seeding (a repo whose local CI runner scopes the DB at runtime still gets isolation):

```bash
git fetch origin
git worktree add -b feature/<slug> worktrees/<slug> origin/main    # Pattern A — root at origin/main
git worktree add -b feature/<B> worktrees/<B> feature/<A>          # Pattern B — root at the parent branch
git worktree add worktrees/<slug> feature/<slug>                   # branch already exists: drop -b
```

## Pulling `main` updates into a worktree branch

The main checkout owns `main`: update it there with `git pull --ff-only origin main`, then in the worktree `git rebase main` (local-only branch) or `git merge main` (already pushed and shared). A branch can be checked out in only one place at a time — if `main` is busy, rebase onto `origin/main` directly (`git fetch origin && git rebase origin/main`). Never bare `git pull` on a drifted worktree: with `pull.rebase=true` it replays orphaned squash commits and conflicts. Use fetch + rebase, or — for a fully-merged drifted branch — `git reset --hard origin/main` after the safety check in **Recover a drifted worktree**, `worktree-hygiene.md`.

## Sync-gate machine enforcement

The rebased-ness check is the *first* pre-push job — it fails fast before the multi-minute suites, and its fetch refreshes `origin/main` for the later gates:

| Repo | Job | Script |
| --- | --- | --- |
| `<repo-a>` | `check-rebased` | `scripts/check-rebased.sh` (fix with `scripts/sync-worktree.sh`) |
| `<repo-b>` | `<sync-job-name>` | `<script>` |

Both use `git merge-base --is-ancestor <base> HEAD`, which is stricter than the `rev-list --count` proof: it also fails a **diverged** branch, not just a behind one. Base is overridable for Pattern B stacks via the repo's own env vars, e.g. `<REPO>_PRE_PUSH_BASE` / `<REPO>_CO_CHANGE_BASE`.

A typical gate is a hook runner's cheap diff checks plus an affected-scoped local CI command; a well-shaped one has NO local docker image build in it — image compile is verified right-of-push by a CI `build-verify` job. Pushing from several worktrees at once is safe and parallel: per-worktree DBs and ports don't serialize across worktrees.

## Follow-up-drain machine enforcement

A repo may add its own pre-push job that fails the push while the worktree still holds untracked follow-up docs. Such a gate is local-only by construction — untracked docs never reach the remote, so no CI check can back it up and `--no-verify` escapes it entirely. Job name, script, bypass env vars, and the doc lifecycle live in the hosting repo's issue-tracking/handover workflow, not here.

## Teardown — manual equivalent

From the main checkout (never inside the worktree), all three targets explicitly:

```bash
git worktree remove worktrees/<slug>   # 1. worktree  (--force only to discard a dirty tree)
git branch -D feature/<slug>           # 2. branch    (-D: squash leaves it "unmerged" by SHA)
git fetch --prune origin               # drop the stale origin/<slug> ref
# 3. DBs — if your repo makes per-worktree DBs, drop <db-prefix>_test_<slug>_<hash8> +
#    <db-prefix>_wt_<slug>_<hash8> (see worktree-hygiene.md); a teardown script's
#    `--prune-orphans` mode sweeps any DB whose worktree is already gone.
```

Dir deleted by hand? `git worktree prune` clears the metadata; a teardown script's `--prune-orphans` mode also drops its leftover DBs. To realign a drifted worktree instead of removing it, see **Recover a drifted worktree** in `worktree-hygiene.md`.

## Squash-merging a Pattern B stack — the per-layer rebase

Squash collapses the parent's commits into one new commit on `main` with a fresh SHA, so a child still carrying the parent's old commits re-shows the parent's whole diff (and can throw spurious conflicts) if you only retarget it. After the parent's PR squash-merges:

```bash
cd worktrees/<slug-B>                  # the child worktree
git fetch origin
git rebase origin/main                 # git drops the parent's now-squashed commits; leaves only this layer's
git push --force-with-lease
```

Then retarget the child's PR to `main` and squash-merge it. Repeat for the next layer. Merge-commit / rebase-merge strategies keep the parent's commits on `main`, so a retargeted child shows only its own diff: retarget and merge, no force-push needed — simpler for deep stacks.
