---
trigger: "Open a PR", "ship it", "land this", "raise a PR" — or any request to push a branch for review or land a feature; covers the whole chain through merge and cleanup.
---

## Trigger

"Open a PR", "ship it", "land this", "raise a PR" — or any request to push a branch for review or land a feature. The branch/worktree model (**Pattern A**/**Pattern B**, naming, stacked merges) lives in `../git/worktree.md`; the git mental model in `../git/worktree-hygiene.md`.

## Goal

The branch is committed, rebased on its base, green through the pre-push gate, pushed, free of the follow-up debt its repo tracks in the worktree, and merged via a green PR — and the worktree, branch, and per-worktree DBs are cleaned up afterward.

## Context

**The chain**: commit → sync → pre-push gate → push → pre-PR gates (sync + follow-up drain) → open PR → PR gate → merge → cleanup. Commit first: `pull --rebase` refuses a dirty tree, and the pre-push hooks run against committed state. Conventional Commits (`feat`/`fix`/`chore`/`docs`(`scope`)`: …`).

**Sync.** From the worktree: `git fetch origin && git pull --rebase origin <base>` (or `git rebase origin/main`); proof is `git rev-list --count HEAD..origin/<base>` printing `0`. Only the main checkout updates `main`, with `git pull --ff-only`; never bare `git pull` on a drifted worktree (**Pulling `main` updates** in `../git/worktree-details.md`).

**The pre-push gate** is the repo's hook stage — `<your repo's pre-push command>` (e.g. `npx lefthook run pre-push`, `npm test`, `make check`). Its first job is the rebased-ness check (job names per repo: **Sync-gate machine enforcement** in `../git/worktree-details.md`), so a stale or diverged branch cannot be pushed at all. A repo may add further pre-push jobs — including an early follow-up-drain check — which are that repo's to document. Details: the **sync gate** and the **follow-up drain** in `../git/worktree.md`.

**Push**: `git push -u origin <branch>`; add `--force-with-lease` only after rebasing an already-pushed branch.

**Pre-PR gates.** `gh pr create` is not a git operation, so no hook fires — both gates are on you. Run `"$HOME/.agents/workflows/git/pre-pr-gate.sh" <base>` from the worktree (read-only; fetches, then checks both gates): exit `0` = clear; anything else, follow what it prints; `2` = usage/env error — fall back to the manual commands (**Sync** above; the **follow-up drain** in `../git/worktree.md`). Every doc it lists is work this branch owes — discharge it as the hosting repo's issue-tracking/handover workflow prescribes, then commit, re-sync, re-gate, push. Then be idempotent: `gh pr list --head <branch> --state open --json number,url` before `gh pr create --base <base> --title "<type>(<scope>): <summary>" --body "<what + why + test plan>"`.

**The PR gate** is distinct from the local pre-push gate: GitHub's required status checks, required reviews, and any merge queue on the base branch. Watch with `gh pr checks <pr> --watch`. If your repo squash-merges: `gh pr merge <pr> --squash --delete-branch` (removes the remote branch; local cleanup below). Pattern B stacks merge bottom-up with a per-layer rebase — **Merging a Pattern B stack** in `../git/worktree.md`.

**Cleanup.** First re-run the drain check — `pre-pr-gate.sh <base>` again (same check as before the PR: follow-up docs reappear after review feedback or deferred fixes, and they are untracked, so teardown destroys leftovers). Then from the main checkout, `<your teardown script> <slug>` (e.g. `scripts/remove-worktree.sh <slug>`) drops any test + runtime DBs, removes the worktree, deletes the branch, and prunes refs. Manual equivalent and the squash `branch -d` caveat: **Teardown after merge** in `../git/worktree.md`. Pattern B: clean up bottom-up — delete a parent only after its child PR is retargeted.

A repo may add its own generated-artifact rules (e.g. conflicts in derived files that must be regenerated, never hand-merged) — defer to that repo's own PR workflow.

## Constraints

- **"Open a PR" means the full pipeline, not just `gh pr create`** — run the chain end to end. Stop early only for a real human decision (a conflict that is a product call, a red check whose fix is ambiguous, a required review you cannot grant): surface it, then resume once unblocked.
- `pull --rebase` is MANDATORY before every push and again before opening the PR — the count must print `0` each time.
- A failing pre-push gate is a STOP: fix the root cause; push only when green. NEVER `--no-verify`, never lower a threshold, never add `continue-on-error` — `--no-verify` also skips the sync check, which is exactly how a stale branch lands. (A repo may document one narrow exception — e.g. a held-connection fallback permitted *after* the full gate is green; defer to that repo's gate spec.)
- On a conflict that needs a real product decision, ask the user — no blind `--ours`/`--theirs` (`rerere` helps when enabled).
- Never hand-merge a conflict in a generated artifact — take one complete side and regenerate it with the hosting repo's documented chain.
- A leftover follow-up doc at either checkpoint is a STOP — discharge it per the hosting repo's issue-tracking/handover workflow before opening the PR or tearing the worktree down.
- Do not merge around a red required check. A required review you cannot grant is a hand-off — request it and pause; never self-approve around branch protection.
- Cleanup after merge is mandatory — all three leftovers: branch, worktree dir, per-worktree test + runtime DBs.

## Verify

```bash
"$HOME/.agents/workflows/git/pre-pr-gate.sh" <base>            # exit 0 — synced + no follow-up debt (both checkpoints)
<your repo's pre-push command>                                 # exits clean before any push
gh pr checks <pr>                                              # every required check green before merge
gh pr view <pr> --json state                                   # "MERGED"
git worktree list | grep "worktrees/<slug>" || echo "worktree gone"
git branch --list "*<slug>*"                                   # empty — branch gone
```
