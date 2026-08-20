#!/usr/bin/env bash
# Pre-PR gate: read-only checks that must pass before `gh pr create` (and again
# before worktree teardown, for the follow-up-drain half). Run from inside the
# worktree.
#
# Usage: pre-pr-gate.sh <base-branch>
#
# Checks (both always run, so one invocation reports everything):
#   sync      git fetch origin, then `git rev-list --count HEAD..origin/<base>`
#             must print 0 — otherwise the base moved and a rebase is required.
#   handovers `.agents/handovers/` at the repo top-level must be empty modulo
#             .gitignore/.gitkeep — the follow-up drain (worktree.md). This is the
#             conventional location; a repo that keeps no such directory passes
#             this half trivially. The doc lifecycle (what goes in one, where it
#             may be parked, when it is deleted) belongs to the hosting repo's
#             own issue-tracking/handover workflow, not to this script.
#
# Exit codes:
#   0  all gates pass — clear to open the PR
#   1  sync gate failed: branch is behind origin/<base> — rebase, re-run the
#      pre-push gate, re-push, then re-run this script
#   2  usage/environment error: missing/bad args, not a git repo, fetch failed,
#      or origin/<base> does not exist
#   3  follow-up drain failed: .agents/handovers/ contains docs this branch owes
#   4  both gates failed
#
# Read-only: never pushes, rebases, or touches the working tree. The only
# remote interaction is `git fetch origin` (updates remote-tracking refs only),
# which the sync check requires to be meaningful.

set -u -o pipefail

usage() {
    echo "Usage: pre-pr-gate.sh <base-branch>"
    echo "Run from inside the worktree. See header comment for exit codes."
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    usage
    exit 0
fi

if [ $# -ne 1 ] || [ -z "$1" ]; then
    usage >&2
    exit 2
fi
base="$1"

top=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$top" ]; then
    echo "error: not inside a git repository" >&2
    exit 2
fi

if ! git fetch origin --quiet; then
    echo "error: git fetch origin failed" >&2
    exit 2
fi

if ! git rev-parse --verify --quiet "origin/$base" >/dev/null; then
    echo "error: origin/$base does not exist" >&2
    exit 2
fi

sync_failed=0
handover_failed=0

count=$(git rev-list --count "HEAD..origin/$base")
if [ "$count" -eq 0 ]; then
    echo "sync: OK — 0 commits behind origin/$base"
else
    sync_failed=1
    echo "sync: STALE — $count commit(s) behind origin/$base; rebase, re-run the pre-push gate, re-push"
fi

handover_dir="$top/.agents/handovers"
leftovers=$(ls -A "$handover_dir" 2>/dev/null | grep -v -e '^\.gitignore$' -e '^\.gitkeep$')
if [ -z "$leftovers" ]; then
    echo "handovers: OK — .agents/handovers/ is empty"
else
    handover_failed=1
    echo "handovers: BLOCKED — follow-up docs this branch still owes; discharge them per this repo's issue-tracking/handover workflow:"
    printf '%s\n' "$leftovers" | sed 's/^/  - /'
fi

if [ "$sync_failed" -eq 1 ] && [ "$handover_failed" -eq 1 ]; then
    exit 4
elif [ "$handover_failed" -eq 1 ]; then
    exit 3
elif [ "$sync_failed" -eq 1 ]; then
    exit 1
fi
exit 0
