---
trigger: "Distill memories", "process review dumps", "update Casper memory from sessions" — or after extract_session_history.py produces new review notes to process.
---

## Trigger

"Distill memories", "process review dumps", "update Casper memory from sessions" — or after `extract_session_history.py` produces new review notes (pi / Claude / AntiGravity). The heartbeat daemon gates this task with `check_pending.py` (exit 0 = sources pending, exit 1 = nothing to distill).

## Goal

Every unprocessed review dump (up to the per-run cap) is distilled into individual memory notes via `write_memory.py`, every skip is logged with a reason, and the state file reflects the run. LLM needed because deciding what is memory-worthy is judgment the scripts cannot enumerate — you decide, the scripts validate + persist.

## Context

**Paths.** Review dumps: `$HOME/.agents/memory/review/<provider>/<folder>/*.md`. Scripts live in `$HOME/.agents/workflows/memory-workflow/`. `distill_state.py` owns the state file (`$HOME/.agents/state/memory-distill/distill_memories.json`; JSON shape + unprocessed rule: **State-file shape** in [`distill-reference.md`](distill-reference.md)): `list` prints the unprocessed inventory oldest-first, `record` persists one review file's result atomically, `check` verifies consistency. Exit codes: `0` success, `1` nothing-to-distill / check failed, `2` usage or validation error.

**Refresh first.** Before distilling, pull the next batch of oldest session archives into review dumps:

```bash
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/extract_session_history.py" --provider all --limit 100
```

Extraction scans workflow-local mirrors (`sources/`) plus live pi, Claude, and AntiGravity session dirs. The raw 100-file cap applies *before* the state-based skip filter (keeps runtime bounded), oldest-first by mtime so the backlog is chewed through chronologically. Then get the batch to process:

```bash
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/distill_state.py" list --limit 100
```

Exit `1` = nothing to distill — end the run there.

**Review dump anatomy.** Frontmatter gives `source_provider`, `session_id`, `cwd`, `source_folder_name`, `turn_count`, `assistant_block_count`, `extract_version`, `currentDate`. Body has `## Turn N` blocks with `**user:**` and (for `extract_version: 2`+) `**assistant:**` blocks; the assistant block is per-turn LLM synthesis — the primary source for `finding` candidates. If `extract_version` is missing or `< 2`, only user-turn types (`rule | fact | workflow | open`) are available — skip the finding pass.

**Attribute definitions, extraction tables, and writer contract.** The **Memory attributes** (`memory_type`, `scope`, `tags`, `keywords`, `body`, `expires`), **High-signal patterns**, **Type-by-type capture rules**, **Acid test**, **Open-item fields**, exact **Writer invocations**, and **Writer response handling** all live in [`distill-reference.md`](distill-reference.md). Read it before extracting.

**Writer lessons.** Duplicates are detected by jaccard overlap on the body, not by source session — one memory may be distilled from many sessions, and the writer stores no provenance, so don't try to record it. Pre-check obvious dups with `rg -li "<key-term>" $HOME/.agents/memory/<scope-dir>/ 2>/dev/null`; if related-but-different, still try the writer — it does its own similarity check.

**Bundled files.** `write_memory.py` validates + persists one memory and prints a JSON response. `extract_session_history.py` turns raw session archives into review dumps. `distill_state.py` owns the distill state (see **Paths**). `check_pending.py` is the heartbeat precondition gate. `sources/` holds raw provider exports staged for extraction. `search_memory.py`, `doctor_memory.py`, and `cleanup_report.py` belong to `load-memory.md` / `maintain-memory.md`.

**Hand-off.** Lint, dedup resolution, stale-item review, expired pruning, and cleanup of review dumps / extraction state belong to `maintain-memory.md` — suggest running it after a batch, especially after many `near_dup` outcomes or a large write count.

## Constraints

- If `extract_session_history.py` exits non-zero, **abort distillation**: report stderr + exit code to the user and stop.
- Process exactly the batch `distill_state.py list --limit 100` returns (at most **100 review files per run**, oldest mtime first) — keeps LLM context focused and preserves extraction precision.
- **Be conservative — when unsure, skip. Noise is worse than misses.** Apply the **Acid test** (`distill-reference.md`) to every candidate before invoking the writer.
- Never extract: anything derivable from reading code/files or already in `CLAUDE.md`/`AGENTS.md`; shared document/data contents unless the user stakes a position on them; hypotheticals; the assistant's own outputs (valid only as the anchor turn of a correction-then-success pattern); conversation summaries; candidates redundant with existing memory that add no new specificity.
- **One memory per atomic idea** — don't concatenate. Canonical phrasing: third person, present tense, subject "User" (or project/repo name when scope-specific); no verbatim quotes in the body unless the quote *is* the memory.
- Log **every** skipped candidate in `record`'s `--skipped-json` array — shape and closed reason vocabulary in `distill-reference.md`; the script derives `candidates_skipped` from it and rejects unknown reasons/types (exit `2`).
- Findings: scope always `project:<slug>`; if `cwd` is null in the dump frontmatter (e.g. AntiGravity), **skip the finding** — never fall back to `global`. Max **20 per review file** — keep the highest-signal, preferring concrete file/symbol anchors over vague architecture handwaves. Tags from `code-paths | signatures | architecture | root-cause | api | config` plus up to 2 free topic tags. Do **not** pass `--allow-dup` by default.
- Open items: max **10 per review file** (prefer items with a concrete `next_action`). Set task fields only when the user's words support them — do not invent. Resolve relative dates against `currentDate` in the dump frontmatter; if ambiguous, omit the field rather than guess. If `status: blocked` and the body reveals no concrete blocker, skip the memory.
- **Trust the writer.** Never hand-write files under `$HOME/.agents/memory/` — always go through `write_memory.py` for schema enforcement.
- **No destructive actions here.** Never delete review dumps, session archives, or state records — that belongs to `maintain-memory.md`.
- Update state after each review file: `distill_state.py record <review-file> --written N --by-type <type=count,…> --skipped-json '<array>'` (each call persists the full state atomically). Never hand-edit the state JSON. If `record` exits nonzero, fall back for this run to manual state handling (**State-file shape** in `distill-reference.md`, write `.tmp` then rename) and surface the failure in the run report.
- End the run by reporting: review files processed N · memories written M (list paths) · near-dups encountered K · errors E.

## Verify

```bash
PY="$HOME/.agents/.venv/bin/python"

# State reflects the run and skip counts are consistent (exit 0)
"$PY" "$HOME/.agents/workflows/memory-workflow/distill_state.py" check

# Memories written this run exist outside review/ and pass the doctor
find "$HOME/.agents/memory" -name "*.md" -newermt "2 hours ago" -not -path "*/review/*"
"$PY" "$HOME/.agents/workflows/memory-workflow/doctor_memory.py" --format text

# Review dumps were not deleted
ls "$HOME/.agents/memory/review/"*/*/*.md 2>/dev/null | wc -l
```
