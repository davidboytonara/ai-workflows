---
description: Manage ClickUp tasks in your configured ClickUp list — create, update (deadline/epic/PIC/status), list, comment, attach
---

## Trigger

"Create a ClickUp task", "assign this to <person>", "move the deadline", "set it to in progress", "what's on <person>'s plate", "comment on / attach this to task <id>" — any create, update, delete, list, comment, or attachment operation on ClickUp tasks.

## Goal

The requested operation lands in the configured list and the user gets the concrete result back: `task_id` + `url` on create, the changed fields on update, the listing on read.

## Context

**Routing.** ClickUp is THE task tracker — everything goes to the single list pinned in `~/.agents/.config` (a folder > list chain resolved once at setup; a guest account may see no spaces, which the resolver handles).

**Script conventions.** All scripts run via `$HOME/.agents/.venv/bin/python` from the vault root; stdlib-only; print one JSON object `{'ok','status','response',...}`; exit `0` = success, `1` = API/network error (report `status` + `response` to the user), `2` = usage error (the JSON `error` explains what's missing and lists valid candidates). Rate limit is 100 req/min; on HTTP 429 wait `retry_after_s` seconds. `clickup_common.py` is the shared library behind all of them (config merge, auth, name→id resolution) — never invoked directly. Config split: the `CLICKUP_API_TOKEN` secret in `~/.agents/.env`, non-secret pinned ids in `~/.agents/.config` (copy `.env.example` / `.config.example` from the repo root on first use); `_shared/agents_config.py` merges both, and a real environment variable overrides either.

**One-time setup** (only if `~/.agents/.config` has an empty `CLICKUP_LIST_ID`) — resolve and pin the workspace → space → list chain, statuses, roster, and epic model:
```bash
$HOME/.agents/.venv/bin/python ".agents/workflows/clickup-workflow/clickup_resolve_ids.py"           # dry-run: inspect
$HOME/.agents/.venv/bin/python ".agents/workflows/clickup-workflow/clickup_resolve_ids.py" --write   # pin into ~/.agents/.config
```
Exit 2 with a `workspaces`/`spaces`/`lists` array means a name didn't match — pass `--team-id` / `--space-name` / `--project-name` / `--list-name` accordingly.

**Drafting the description** (LLM needed because drafting prose from a conversation cannot be encoded as a rule). Two accepted shapes:
- **Product story** — feature/product work. Save to a markdown file in the vault with exactly the headings `# Context`, `# Objectives`, `# Acceptance Criteria`, `# Constraints`.
- **Plain task** — simple ops/IT items: freeform markdown description (or `--description` inline), no template.

**Create:**
```bash
// turbo
$HOME/.agents/.venv/bin/python ".agents/workflows/clickup-workflow/clickup_create_task.py" \
  --title "<Task_Title>" \
  --description-file "<path/to/story.md>" \
  --priority "normal" \
  --target-date "YYYY-MM-DD" \
  --assignee-name "<username or email>" \
  --epic "<epic option name or parent task id>"
```
Only `--title` and a description are required. Priority words: `urgent|high|normal(medium)|low|none`.

**Update** (deadline, epic, PIC/assignee, status, title, description — pass only what changes):
```bash
// turbo
$HOME/.agents/.venv/bin/python ".agents/workflows/clickup-workflow/clickup_update_task.py" \
  --task-id "<task_id>" \
  --status "in progress" \
  --target-date "YYYY-MM-DD" \
  --assignee-name "<add this person>" \
  --remove-assignee-name "<remove this person>" \
  --epic "<epic>" \
  --priority "high"
```
`--priority none` clears priority. An invalid `--status` exits 2 and prints `valid_statuses`. `--delete` deletes the task.

**List / read** (status review, workload check) — all flags optional; default is open tasks in text form (per-assignee workload counts, then tasks grouped by assignee); `--format json` when another workflow consumes the output:
```bash
// turbo
$HOME/.agents/.venv/bin/python ".agents/workflows/clickup-workflow/clickup_list_tasks.py" \
  --assignee-name "<person>" --status "<status>" --include-closed --format json
```

**Comment:**
```bash
// turbo
$HOME/.agents/.venv/bin/python ".agents/workflows/clickup-workflow/clickup_add_comment.py" \
  --task-id "<task_id>" --text "<comment>"
```

**Attach** (repeat per file, max 1 GB each):
```bash
// turbo
$HOME/.agents/.venv/bin/python ".agents/workflows/clickup-workflow/clickup_add_attachment.py" \
  --task-id "<task_id>" --file-path "<path/to/file.pdf>"
```

**Epic**: `--epic` behavior is pinned in `~/.agents/.config` by setup — this list uses the `parent` model: epics are top-level tasks and `--epic` takes the epic task's id (stories become its subtasks). (`custom_field` model would take an option name instead; exit 2 lists `valid_options`.)
**PIC** = assignee. Names resolve case-insensitively against the workspace roster (username or email); unresolved names exit 2 with `valid_members`.
**Statuses** are list-scoped and set by name.
**Dates** are converted to epoch-ms at local noon (ClickUp date-only quirk); pass plain `YYYY-MM-DD`.

## Constraints

- Maximum 3 objectives per product story; more goals → split into multiple stories.
- If the task was drafted from source material (a MoM/note file, shared doc, screenshot, PDF, email), attach that file immediately after creating — citing the source in the description is not enough; the file itself must live on the task so whoever picks it up has full context. No underlying source file (verbal ask, quick idea) → skip. Same rule on update: attach only if new supporting material actually surfaces.
- `--delete` is destructive — only on explicit user request or smoke-test cleanup.
- Never guess statuses — on exit 2 pick from the `valid_statuses` echoed back. Exit 2 generally means fix the invocation from the candidates listed; don't retry blindly.
- `--notify-all` on comments only when the user wants the team pinged.
- Never print or commit `CLICKUP_API_TOKEN`; secrets stay in `~/.agents/.env`, only non-secret ids in `~/.agents/.config`.

## Verify

- Every call: exit code `0` and `"ok": true` in the printed JSON. On create, report the returned `task_id` and `url` to the user.
- Confirm a create/update actually took effect:
```bash
// turbo
$HOME/.agents/.venv/bin/python ".agents/workflows/clickup-workflow/clickup_list_tasks.py" --format json
```
The task appears with the expected status/assignee/date (add `--include-closed` if it was closed).
