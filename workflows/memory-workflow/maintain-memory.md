---
trigger: "Memory maintenance", "clean up memory", "memory health check", "lint memory" — also after a big distillation run or when doctor_memory.py reports problems.
---

## Trigger

"Memory maintenance", "clean up memory", "memory health check", "lint memory". Also: after a large distillation run (especially many `near_dup` outcomes); when `doctor_memory.py` reports errors or warnings the user wants resolved; before pruning review dumps / extraction state.

## Goal

`doctor_memory.py` exits clean — errors fixed, warnings triaged with the user — and any destructive cleanup covers only buckets the user explicitly confirmed.

## Context

Lint pass (read-only):

```bash
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/doctor_memory.py" --format text
```

Narrow with `--scope global --scope project:<slug> --format json`. Finding-path checks across project/repo scopes need `--scope-root` so paths can be resolved:

```bash
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/doctor_memory.py" \
  --scope-root project:<slug>=$HOME/.agents \
  --scope-root repo:<slug>=/path/to/<slug>
```

Doctor codes, meanings, and standard resolutions:

| Severity | Code | Meaning → resolution |
|---|---|---|
| error | schema | frontmatter / type / memory_type / list-types invalid → `Read` + `Edit` the file, fix frontmatter |
| error | date | created/updated/expires malformed or out of order → fix dates |
| error | body | empty body → fill or delete |
| error | duplicate-body | exact-normalized body match within (scope, memory_type) → keep the canonical file (most recent `updated`, richest tags/keywords), delete the other(s) |
| warning | tags-count / keywords-count | outside 2-5 / 5-15 → trim or enrich |
| warning | tag-case / *-whitespace / *-duplicate | hygiene → normalize |
| warning | body-long / body-multiline | atomic-ness drift → split or tighten |
| warning | expired | past `expires` date → prune (user gate) |
| warning | near-duplicate | jaccard >= 0.60 (0.85 for findings) → read both, resolve per Constraints |
| warning | finding-anchor | finding lacks path/symbol anchor → add anchor or delete |
| warning | stale-finding-path | referenced path missing under scope root → path moved/renamed: `Edit` body + keywords to the new path, bump `updated`; code removed: delete the finding |
| warning | unresolved-scope-root | need `--scope-root` to verify finding paths → re-run with `--scope-root SCOPE=/PATH` |
| warning | open-missing-blocker | `status: blocked` but `blocked_by` empty/missing → fill in the blocker or relax the status |
| warning | open-overdue | `due` passed, `status` not `done` → user gate |
| warning | open-scheduled-overdue | `scheduled` passed, `status` still `pending` → reschedule or promote to `active` |
| warning | open-done-stale | `status: done` for more than 90 days → user gate to delete |
| warning | open-long-running | `status: active`, `started` more than 14 days ago → user gate |
| warning | open-broken-link | `related` slug matches no memory file → fix the slug or drop the entry |

Triage stale/overdue open items from:

```bash
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/search_memory.py" \
  --active-tasks --format json
```

**Lessons.** Doctor exits 1 on any error — including `root-missing` when `$HOME/.agents/memory/` does not exist yet (distillation has never run). Manual `Read` + `Edit` of memory files during maintenance is fine as long as the doctor passes afterward — `write_memory.py` enforces schema only for new writes. Completed (`done`) tasks are kept ~90 days so they stay available for "what did I ship?" queries. `pending` items with `updated` older than 30 days are stale even without a doctor code. For `blocked` items, re-read `blocked_by`; if the blocker is resolved, flip to `active`/`done` and bump `updated`.

**Cleanup buckets** (the destructive offer): workflow-local source mirrors under `workflows/memory-workflow/sources/` (raw provider exports staged for extraction); extracted review dumps under `~/.agents/memory/review/<provider>/<folder>/*.md`; distillation/extraction state under `~/.agents/state/memory-distill/` (`distill_memories.json`, `extract_session_history.json`, …). Size the offer with the read-only bucket report — exit `0` = something to clean, `1` = all buckets empty/missing (nothing to offer), `2` = usage error (fall back to `du -sh` on the paths above):

```bash
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/cleanup_report.py" --format text
```

Related: `distill-memory.md` writes new memories from review dumps; `load-memory.md` is the read path for the session-start brief.

## Constraints

- Resolve **errors before warnings** — errors block clean exit.
- **Re-run doctor between non-trivial edits** to catch regressions.
- Near-duplicates: same idea, different phrasing → keep the clearer one, delete the other; superseding (one is a refinement) → delete the older; genuinely distinct nuance → leave both, consider tightening tags/keywords to reduce token overlap.
- **Approval gates — ask the user before acting on any of these:**
  - pruning `expired` memories (deletion is destructive — confirm, delete, re-run doctor);
  - deleting `done` items older than 90 days (`open-done-stale`);
  - stale `pending` items (>30 days without update) — still relevant? bump `updated` (optionally tighten `body`), or delete if abandoned;
  - `open-long-running` — is it actually blocked, or should it be split?
  - `open-overdue` — extend `due`, drop priority, or close as `done`?
- **Cleanup: delete nothing unless the user explicitly confirms the scope.** Show the `cleanup_report.py` counts and total size per bucket first; let the user pick which buckets to drop.
- **Preserve canonical phrasing** when consolidating duplicates — third person, present tense, atomic.
- **Do not bypass `write_memory.py` for new writes.** This workflow only edits/deletes existing memories — writing new ones is `distill-memory.md`.
- End the run by reporting: errors fixed N · near-dups resolved K (kept / deleted) · open items resolved O · expired pruned E · stale finding paths fixed S · cleanup buckets touched (or "none").

## Verify

```bash
# Clean exit: no error lines; remaining warnings only those the user chose to keep
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/doctor_memory.py" --format text; echo "exit=$?"

# Open-item triage reflected in the task store
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/search_memory.py" --active-tasks --format json | head -20
```
