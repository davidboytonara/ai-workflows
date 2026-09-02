# goal.md template — dead-code-cleanup

Helper for `dead-code-cleanup.md` **Goal authoring**. This is the detector-driven counterpart to the generic [`../goal-authoring/goal-draft-template.md`](../goal-authoring/goal-draft-template.md) — same goal.md shape and contract rules, but built from `inventory.json` + `repo-policy.md` instead of a prose record. Copy the block below into `$HD/goal.md`, replace every `<...>` placeholder from `$HD/inventory.json` + `$HD/repo-policy.md`, apply the tailoring notes, then show it to the user and pause for approval (the **goal approval gate** in `../casper/casper.md`). Placeholders: `<REPO>` main-checkout path, `<BASE>` base branch, `<BRANCH>`/`<WORKTREE_DIR>` per the repo's worktree convention, `<FULL_GATE_CMD>` the repo's full local gate, `<BASELINE_CMD>` the repo's documented coverage-baseline regeneration command, `<CONVENTION>` its findings convention.

````markdown
## Goal
Remove the dead production code approved below from <REPO>, delivering
through the repo's own PR workflow to merge and post-merge cleanup.

Approved file deletions (vetted ids from inventory.json):
- <dc-id> <path> — <one-line reason>

Approved export demotions (remove the export keyword/re-export, KEEP the symbol):
- <dc-id> <path>#<symbol> — <one-line reason>

Approved dependency removals (zero imports AND zero script/CI/config usage proven):
- <dc-id> <package> from <package.json path> — <one-line reason>

Flag-only findings (never delete; record each per <CONVENTION>):
- <dc-id> <path or symbol> — <why flagged>

Constraints:
- Work only in a fresh disposable worktree/branch created per the repo's
  convention (<WORKTREE_CMD> → <WORKTREE_DIR>, branch <BRANCH>); never edit
  the main checkout directly.
- Never modify protected paths: <PROTECTED_LIST>.
- Re-verify every candidate with the detection-guide.md checklist before
  removing it; any doubt demotes it to flag-only.
- Demotions stay demotions: never delete a file or symbol approved only for
  export demotion.
- Amend every co-change surface (docs/specs/gherkin referencing a removed
  path or symbol) in the same PR; when a src file is deleted, regenerate the
  coverage-floor baseline with <BASELINE_CMD> in the same PR.
- Test code is out of scope; if a removal would orphan a test, pause with
  NEEDS-USER instead of widening the PR.
- Run <FULL_GATE_CMD> locally and pass before pushing.
- Merging when CI is green is authorized by this goal; a required human
  review approval is not — pause with NEEDS-USER if branch protection
  demands one.
- After merge: sync <BASE> in the main checkout, then remove the worktree
  and branch per the repo convention.

## Acceptance Criteria
1. Every deletion-approved path is absent from origin/<BASE>.
2. Every demoted export is no longer exported, and every removed dependency
   is absent from its package.json, on origin/<BASE>.
3. The merged PR diff touches no protected path.
4. The repo full gate passes on the merged state of <BASE>.
5. Every co-change surface referencing a removed path/symbol was amended in
   the PR (coverage baseline included, when applicable).
6. Every flag-only finding is recorded per <CONVENTION>.
7. The PR is MERGED, the worktree dir is absent, and the branch ref is gone.

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
   cd <REPO> && git fetch -q origin <BASE> && rc=0
   while read -r path symbol; do
     git show "origin/<BASE>:$path" | grep -qE "export\b.*\b$symbol\b" \
       && { echo "still exported: $path#$symbol"; rc=1; }
   done <<'EOF'
   <path> <symbol>
   EOF
   for d in <REMOVED_DEPS>; do
     git show "origin/<BASE>:<PKG_JSON_PATH>" | grep -q "\"$d\":" \
       && { echo "still listed: $d"; rc=1; }
   done; exit $rc
   ```
3. command (timeout=300)
   ```bash
   cd <REPO> && gh pr diff <PR_NUMBER> --name-only \
     | grep -E '^(<PROTECTED_REGEX>)' && exit 1 || exit 0
   ```
4. command (timeout=5400)
   ```bash
   cd <REPO> && git fetch -q origin <BASE> \
     && git merge-base --is-ancestor \
        "$(gh pr view <PR_NUMBER> --json mergeCommit -q .mergeCommit.oid)" HEAD \
     && <FULL_GATE_CMD>
   ```
5. command (timeout=600)
   ```bash
   cd <REPO> && <CO_CHANGE_GATE_CMD>
   ```
6. judgment: open the repo findings location (<CONVENTION>) and confirm one
   recorded entry per flag-only id above, each naming its path/symbol and reason.
7. command (timeout=300)
   ```bash
   test "$(gh pr view <PR_NUMBER> -R <OWNER/REPO> --json state -q .state)" = MERGED \
     && ! test -d <WORKTREE_DIR> \
     && ! git -C <REPO> show-ref --verify --quiet refs/heads/<BRANCH>
   ```
````

## Contract rules baked into this template

The generic rules (numbering/pairing, the judgment cap, the heredoc ban, timeout sizing) live in [`../goal-authoring/goal-draft-template.md`](../goal-authoring/goal-draft-template.md)'s "Contract rules baked into this template" — read those alongside the dead-code-cleanup-specific rules below.

- Verification never references the executor's worktree contents — it is deleted post-merge. Absence checks run against `origin/<BASE>` (`git cat-file -e` / `git show`); the full gate runs in the main checkout after the executor's post-merge sync (criterion 4's `merge-base --is-ancestor` proves the sync happened).
- Criterion 4 declares its own realistic timeout (the harness default is 300 s; a full gate needs more — size `timeout=` to the repo's real gate duration). If the repo has a coverage-floor baseline, a stale baseline fails this gate, so criterion 4 also proves the baseline co-change.
- Criterion 6 stays judgment only while the convention is prose; downgrade it to a command when the convention is file-based with predictable naming (e.g. `test -f <findings-dir>/<id>-*.md` per id) — it is one of the goal's two allowed judgment items.
- For per-item verification loops, define an inline function and call it once per item (`chk() { ...; }` then `chk <path> <symbol>` lines) — indentation-immune and equally diffable, and avoids the heredoc ban below.

## Tailoring notes

- **`<PR_NUMBER>` is unknown at approval time.** Criteria reference it symbolically; the executor's checkpoint records the real number; before running verify, the driving session substitutes the literal number. This is parameter fill, explicitly NOT a contract change — no renewed approval needed.
- **No export demotions or no dependency removals approved:** drop the empty half of criterion 2's command (or the whole pair when both are empty) and renumber, keeping criteria and verification paired and in the same order.
- **No coverage-floor baseline in the repo:** drop `<BASELINE_CMD>` from the constraint and the parenthetical from criterion 5.
- **No CI in the target repo:** "green" degenerates to the local full gate; drop the `gh pr checks` expectation but keep criteria 1, 2, 4, 7 (a PR/branch review flow may still be the repo convention). Fallback-mode detector confidence is already capped low — expect more flag-only.
- **No co-change gate:** replace criterion 5's command with: `judgment: for each removed path/symbol, search the repo docs/specs/gherkin for remaining references and confirm none survive unamended.` (This is the second — and last — allowed judgment item.)
- **No protected paths:** drop criterion pair 3 and renumber, keeping criteria and verification paired and in the same order.
