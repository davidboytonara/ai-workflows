---
trigger: Session start, before the first reply. Also "load memory", "what do you remember", "show memory brief"; and active tasks, current work, todos, blockers, deadlines.
---

## Trigger

Session start, before responding to the first user request. Also: "load memory", "what do you remember", "show memory brief" — or before answering anything that may already be answered by captured rules/facts. Re-invoke with `--active-tasks` whenever the user asks about ongoing work: active tasks, current/outstanding work, todos, what's in progress, blockers, deadlines, what's due.

## Goal

The memory brief lands in active main-session context, so future turns treat captured preferences and unresolved follow-ups as standing instructions.

## Context

Default invocation (umbrella sessions):

```bash
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/search_memory.py"
```

Default mode is context-efficient: `global/` loads full bodies; `project/<slug>` and `repo/<slug>` load summary only (scope label + aggregated tags); auto-scope full-loads any project/repo whose slug matches the cwd basename. `memory_type: open` is excluded by default — active-task chatter is not loaded at session start; each scope summary shows an `[+N open]` hint when items exist. Pull bodies for a specific scope with `--project SLUG` / `--repo SLUG`, e.g.:

```bash
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/search_memory.py" --project <slug>
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/search_memory.py" \
  --project <slug> --memory-type rule --query "terse responses"
```

`--active-tasks` is equivalent to `--memory-type open --include-ephemeral` plus auto-sort by `priority` (high → low) then `due` ascending (missing-due last); narrow further with `--project` / `--repo` / `--tag` / `--query`. To include open items in the regular brief without filtering, pass `--include-open`.

Filtering and ranking flags: `--memory-type rule|fact|workflow|open|finding` (repeatable, OR) · `--tag TAG` (repeatable, OR) · `--query TEXT` (Jaccard rank against body+tags+keywords) · `--limit N` · `--include-ephemeral` / `--include-expired` / `--include-open` · `--no-global` (rarely useful) · `--format brief` (default, grouped Markdown bullets) | `json` (full records) | `paths` (absolute paths, one per line, no summary fold).

An `open` memory may carry `status` (`pending|active|blocked|done`), `priority`, `scheduled`, `due`, `started`, `next_action`, `blocked_by`, `related` — defined in the **Open-item fields** table in `distill-reference.md`.

Related: `distill-memory.md` writes new memories from session review dumps; `maintain-memory.md` lints, dedups, and prunes.

## Constraints

- Run **in the main session, never via sub-agent** — the output must land in active context.
- Treat returned memories as standing instructions for the session: preferences, rules, workflows, unresolved follow-ups, findings. Do not ask the user to restate anything already in the brief.
- Treat `open` task fields as **authoritative** when answering "what's next on X?" — do not re-derive from session history when the field is set.
- If a memory references a specific file, function, or flag and the user is about to act on it, verify it still exists before recommending — memories can drift.

## Verify

```bash
# Store resolves and memories are found (exit 0; non-empty when memories exist)
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/search_memory.py" --format paths | head -5

# Active tasks load on demand
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/search_memory.py" --active-tasks --limit 5
```

The run succeeded if the default brief's Markdown output is present in the main-session transcript itself — not folded away inside a sub-agent report.
