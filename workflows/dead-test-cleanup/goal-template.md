# goal.md template — dead-test-cleanup

Helper for `dead-test-cleanup.md` **Goal authoring**. Copy the block below into `$HD/goal.md`, replace every `<...>` placeholder from `$HD/inventory.json` + `$HD/repo-policy.md`, apply the tailoring notes, then show it to the user and pause for approval (the **goal approval gate** in `../casper/casper.md`). Placeholders: `<REPO>` main-checkout path, `<BASE>` base branch, `<BRANCH>`/`<WORKTREE_DIR>` per the repo's worktree convention, `<FULL_GATE_CMD>` the repo's full local gate, `<CONVENTION>` its findings convention.

````markdown
## Goal
Remove the dead automation-test code approved below from <REPO>, delivering
through the repo's own PR workflow to merge and post-merge cleanup.

Approved deletions (vetted ids from inventory.json):
- <dt-id> <path or script> — <one-line reason>

Flag-only findings (never delete; record each per <CONVENTION>):
- <dt-id> <path or script> — <why flagged>

Constraints:
- Work only in a fresh disposable worktree/branch created per the repo's
  convention (<WORKTREE_CMD> → <WORKTREE_DIR>, branch <BRANCH>); never edit
  the main checkout directly.
- Never modify protected paths: <PROTECTED_LIST>.
- Re-verify every candidate with the detection-guide.md checklist before
  deleting; any doubt demotes it to flag-only.
- Amend every co-change surface (docs/specs/gherkin/baselines referencing a
  deleted path) with co-change edits in the same PR.
- Never remove conditionally-skipped or env-gated tests; they are flag-only.
- Run <FULL_GATE_CMD> locally and pass before pushing.
- Merging when CI is green is authorized by this goal; a required human
  review approval is not — pause with NEEDS-USER if branch protection
  demands one.
- After merge: sync <BASE> in the main checkout, then remove the worktree
  and branch per the repo convention.

## Acceptance Criteria
1. Every deletion-approved path is absent from origin/<BASE>.
2. The merged PR diff touches no protected path.
3. The repo full test gate passes on the merged state of <BASE>.
4. Every co-change surface referencing a deleted path was amended in the PR.
5. Every flag-only finding is recorded per <CONVENTION>.
6. The PR is MERGED, the worktree dir is absent, and the branch ref is gone.

## Verification
1. command (timeout=300)
   ```bash
   cd <REPO> && git fetch -q origin <BASE> && rc=0
   for p in <DELETED_PATHS>; do
     git cat-file -e "origin/<BASE>:$p" 2>/dev/null && { echo "present: $p"; rc=1; }
   done; exit $rc
   ```
2. command (timeout=300)
   ```bash
   cd <REPO> && gh pr diff <PR_NUMBER> --name-only \
     | grep -E '^(<PROTECTED_REGEX>)' && exit 1 || exit 0
   ```
3. command (timeout=5400)
   ```bash
   cd <REPO> && git fetch -q origin <BASE> \
     && git merge-base --is-ancestor \
        "$(gh pr view <PR_NUMBER> --json mergeCommit -q .mergeCommit.oid)" HEAD \
     && <FULL_GATE_CMD>
   ```
4. command (timeout=600)
   ```bash
   cd <REPO> && <CO_CHANGE_GATE_CMD>
   ```
5. judgment: open the repo findings location (<CONVENTION>) and confirm one
   recorded entry per flag-only id above, each naming its path and reason.
6. command (timeout=300)
   ```bash
   test "$(gh pr view <PR_NUMBER> -R <OWNER/REPO> --json state -q .state)" = MERGED \
     && ! test -d <WORKTREE_DIR> \
     && ! git -C <REPO> show-ref --verify --quiet refs/heads/<BRANCH>
   ```
````

## Contract rules baked into this template

- Verification never references the executor's worktree contents — it is deleted post-merge. Path-absence checks run against `origin/<BASE>` (`git cat-file -e`); the full gate runs in the main checkout after the executor's post-merge sync (criterion 3's `merge-base --is-ancestor` proves the sync happened).
- Criterion 3 declares its own realistic timeout (the harness default is 300 s; a full gate needs more — size `timeout=` to the repo's real gate duration).
- Keep judgment items ≤ 2. Criterion 5 stays judgment only while the convention is prose; downgrade it to a command when the convention is file-based with predictable naming (e.g. `test -f <findings-dir>/<id>-*.md` per id).

## Tailoring notes

- **`<PR_NUMBER>` is unknown at approval time.** Criteria reference it symbolically; the executor's checkpoint records the real number; before running verify, the driving session substitutes the literal number. This is parameter fill, explicitly NOT a contract change — no renewed approval needed.
- **No CI in the target repo:** "green" degenerates to the local full gate; drop the `gh pr checks` expectation but keep criteria 1, 3, 6 (a PR/branch review flow may still be the repo convention). Detector confidence is already capped low — expect more flag-only.
- **No co-change gate:** replace criterion 4's command with: `judgment: for each deleted path, search the repo docs/specs/gherkin for remaining references and confirm none survive unamended.` (This is the second — and last — allowed judgment item.)
- **No vacuous detector in the repo:** category 3 is out of scope; omit its ids entirely.
- **No protected paths:** drop criterion pair 2 and renumber, keeping criteria and verification paired and in the same order.
