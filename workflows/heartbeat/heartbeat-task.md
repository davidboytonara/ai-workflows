---
trigger: "Add a heartbeat task", "change the schedule / prompt / timeout of <task>", "rename / delete a heartbeat task" — any change to heartbeat tasks.yaml or a task's files.
---

## Trigger

"Add / create a heartbeat task", "change the schedule / prompt / dependency / timeout of <task>", "rename a heartbeat task", "delete / remove a heartbeat task" — any change to `~/.agents/workflows/heartbeat/tasks.yaml` (the machine-local live config; copy it from the shipped `tasks.yaml.example` on first setup) or to a task's workflow, state, or secrets.

## Goal

The requested lifecycle change is applied consistently across `tasks.yaml` and the task's workflow, state, and secrets locations, the daemon reloads clean, and every check in Verify passes.

## Context

- One name, one identity: `<domain>-<verb>`, regex `^[a-z0-9][a-z0-9-]*$` (e.g. `gmail-ingest`, `memory-distill`), unique in `tasks.yaml` and reused verbatim for the workflow folder, state folder, secrets folder, history filename, and clarify filename pattern. Never diverge these.
- Layout per task: workflow at `~/.agents/workflows/<task-name>/<task-name>.md` (the LLM-facing procedure for `pi_workflow` type; `shell` type needs no `.md` but still gets the folder if helper scripts exist), helper scripts co-located, unit tests in `~/.agents/workflows/<task-name>/tests/`. State in `~/.agents/state/<task-name>/` — `state.json` written atomically via tmp + rename, optional `<task-name>.lock` if concurrent runs are possible.
- Reserved, daemon-owned state: `state/heartbeat/` (`tasks.json`), `state/history/` (`<task>.jsonl` — the only audit trail), `state/clarify/` (clarify protocol).
- Secrets have exactly two channels: env vars appended to `~/.agents/secrets/heartbeat.env` (loaded by `casper-heartbeat.service`, referenced in `tasks.yaml` as `${VAR_NAME}` or `${VAR_NAME:-default}`), and binary credentials / OAuth tokens / cookie jars / key files in `~/.agents/secrets/<task-name>/` (files `0600`, dir `0700`). If task code needs a secret path, expose it through a `heartbeat.env` var (e.g. `GMAIL_OAUTH_DIR=${HOME}/.agents/secrets/gmail-ingest`).
- `workflow`, `precondition`, `command` in `tasks.yaml` expand `${VAR}` and leading `~` at load; unset vars fail loud — they do not default to empty.
- Clarify protocol: a `pi_workflow` run needing user input writes `~/.agents/state/clarify/<task-name>-<runid>.md` with its question under a `## Task question` section and exits 42; the daemon pauses the task until the user fills in `## User reply:`.
- Every `pi_workflow` prompt must carry: a concrete output stamp (`SUMMARY: ...` line) so the daemon's tldr capture works, the clarify clause, and hard volume caps (e.g. "cap 50 messages per run") so a runaway run cannot exhaust quota.
- After a delete or rename, the daemon's `state/heartbeat/tasks.json` keeps the old key; the daemon ignores names absent from `tasks.yaml`, so the default is to leave it and tell the user it is residual.
- The reference sheet [`lifecycle-reference.md`](lifecycle-reference.md) holds the exact `tasks.yaml` entry template, the update risk table (which checks each kind of change requires), and the ordered command sequences for rename, state migration, and delete, and the pi session policy. Sequence order matters — follow them, do not re-derive.

## Constraints

- Do not improvise file locations.
- Create gate: ask all inputs up front in one message, then stop until answered — name, one-sentence purpose, 5-field cron + tz (default UTC), catchup `all|one|none` (default `one`), type `pi_workflow|shell`, dependencies, optional precondition (non-zero exit skips the run), timeout seconds (default 3600), external secrets. Skip only items the user already supplied verbatim.
- Never write a new task's state into the reserved daemon dirs, never create new top-level state files, never commit empty placeholder dirs — create directories in code on first write.
- Secrets go only through the two channels; `secrets/` is gitignored — never check in anything under it, and never read secrets from arbitrary paths.
- Append to `tasks.yaml` without reordering existing entries; keep every edit minimal — do not "tidy" surrounding entries. Copy-paste the clarify clause from the template; do not paraphrase the path.
- A `type` flip (`pi_workflow` ↔ `shell`) is a Delete followed by a Create, not an edit.
- Rename and state migration only with no run in flight: wait for it to land in history or stop the daemon first. Hand-edit `state/heartbeat/tasks.json` only with the daemon stopped. Real folders only — no symlinks.
- Delete gate: before removing anything, confirm with the user the task name, any `depends_on` dependents (do not proceed while one exists without a plan to remove or rewire it), and the fate of state, secrets, and especially `state/history/<task-name>.jsonl` — ask before deleting history. Decide with the user whether open clarify files are archived under `state/clarify/resolved/` or deleted. Drop `heartbeat.env` vars only this task used; keep shared ones (e.g. `CASPER_SLACK_WEBHOOK_URL`).
- Hands-off without explicit user approval: daemon internals (`heartbeat_daemon.py`, `config.py`, `runner.py`, `scheduler.py`, `state.py`, `history.py`, `clarify.py`, `notify.py`), `casper-heartbeat.service`, and the daemon-owned `state/` trees.
- Never add `--no-session` to `runner.py` or to any task's command.
- Non-trivial new task logic gets unit tests under `~/.agents/workflows/<task-name>/tests/` (state schema, precondition, edge inputs); do not add tests for the daemon itself — that suite exists.

## Verify

Run in order; stop on the first failure.

```bash
# 1. Schema + cron + tz + dependency check
~/.agents/.venv/bin/python ~/.agents/workflows/heartbeat/heartbeat_daemon.py --once --dry-run

# 2. Scoped one-shot of just the affected task (skip on Delete)
~/.agents/.venv/bin/python ~/.agents/workflows/heartbeat/heartbeat_daemon.py --once --task <task-name>

# 3. Inspect what landed
tail ~/.agents/state/history/<task-name>.jsonl
ls ~/.agents/state/<task-name>/
ls ~/.agents/state/clarify/   # only expect a file if the run intentionally exited 42

# 4. Tests for the affected workflow, if it has any
~/.agents/.venv/bin/python -m unittest discover -s ~/.agents/workflows/<task-name>/tests -v

# 5. Reload and confirm a clean start / first scheduled fire
systemctl --user restart casper-heartbeat
journalctl --user -u casper-heartbeat -f

# 6. Delete only: residue check (0 clean; 1 residue; 2 usage; --keep-history if audit trail kept)
~/.agents/.venv/bin/python ~/.agents/workflows/heartbeat/validate_delete.py <task-name>
```

Done when: the one-shot produced one history line matching expectation — rc 0 with `pending_reason: null`, or an intentional 42 with a clarify stub (for prompt-only edits, a correct real fire in `journalctl` after restart substitutes); the daemon restarted clean; tests green. Per mode — Create: state landed under `state/<task-name>/`, secrets in the two channels at `0600`/`0700`, `journalctl` shows the task scheduled. Update: no consumer references an old state path; after a rename, `state/heartbeat/tasks.json` and `state/history/` carry the new name with no orphaned dirs. Delete: `validate_delete.py` exits 0 (tasks.yaml + `depends_on`, `workflows/` residue, per-task dirs, history per user choice, open clarify files, `heartbeat.env`). If the script errors rather than printing FAILs, fall back to the manual checklist in `lifecycle-reference.md` and surface the failure. If the task fires frequently, wait for one real fire and confirm the outcome; if rarely, move on. Any box that can't be ticked means the task is not done — surface what's blocked to the user.
