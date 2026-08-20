# Heartbeat task lifecycle — reference sheet

Companion to [`heartbeat-task.md`](heartbeat-task.md): templates and ordered command sequences. The order inside each sequence matters — follow it as written.

## tasks.yaml entry template

Append (do not reorder existing entries) to `~/.agents/workflows/heartbeat/tasks.yaml` — the live config, which is machine-local and never committed. If it does not exist yet, create it by copying the shipped template: `cp ~/.agents/workflows/heartbeat/tasks.yaml.example ~/.agents/workflows/heartbeat/tasks.yaml`.

```yaml
  - name: <task-name>
    cron: "<5-field cron>"
    cron_tz: "<zoneinfo key>"           # default UTC; omit if UTC
    catchup: one                        # all | one | none
    precondition: "<shell command>"     # optional
    depends_on: []                      # optional list of task names
    type: pi_workflow                   # or shell
    workflow: ${HOME}/.agents/workflows/<task-name>/<task-name>.md
    timeout_seconds: 3600
    prompt: |
      <one-sentence purpose>.

      <constraints, caps, what NOT to do>.

      If you cannot proceed without user input, write a clarify file at
      `~/.agents/state/clarify/<task-name>-<runid>.md` with your specific
      question under the `## Task question` section, then exit with code 42.
      The daemon will pause this task until the user fills in `## User reply:`.
```

For `shell` type, replace `workflow` + `prompt` with:

```yaml
    command: ["<bin>", "<arg1>", "<arg2>"]
```

Schedule examples: `"0 */6 * * *"` UTC, `"0 11 * * 5"` with `cron_tz` set to your own IANA zone key (e.g. `"Europe/Berlin"`).

## Update risk table

Classify the change first — the bigger the blast radius, the more checks you need. If the change spans multiple rows, take the highest-risk path.

| Change | Risk | Required |
| --- | --- | --- |
| Workflow `.md` body only | low | dry-run + scoped one-shot |
| `prompt` text edit | low | dry-run + scoped one-shot |
| `cron` / `cron_tz` / `catchup` | medium | dry-run (validates cron + tz) |
| `depends_on` add/remove | medium | dry-run + verify dependency name exists |
| `precondition` change | medium | run precondition manually first |
| `type` flip (`pi_workflow` ↔ `shell`) | high | treat as Delete + Create |
| `timeout_seconds` reduction | medium | check recent history for typical run duration |
| State file path change | high | follow the state-migration sequence below |
| Secret rename | high | edit `heartbeat.env` and any consumer code in lockstep |

Edit in this order:

1. `~/.agents/workflows/heartbeat/tasks.yaml` — edit the entry in place, keep ordering.
2. `~/.agents/workflows/<task-name>/<task-name>.md` — workflow body if applicable.
3. `~/.agents/secrets/heartbeat.env` — only when adding/renaming env vars.
4. Consumer code (the workflow's helper scripts) — only when contracts change.

## Rename sequence (riskiest update)

Not undoable mid-flight — if a run is in progress, wait for it to finish or stop the daemon first.

1. Rename `tasks.yaml` `name:`.
2. Rename `workflows/<old>/` → `workflows/<new>/` and the inner `<old>.md` → `<new>.md`.
3. Move state: `mv state/<old>/ state/<new>/`; `mv state/history/<old>.jsonl state/history/<new>.jsonl`; move any open `state/clarify/<old>-<runid>.md` to `state/clarify/<new>-<runid>.md` before resume. The daemon's `state/heartbeat/tasks.json` still holds the old key — hand-edit it only after stopping the daemon.
4. Move secrets if applicable: `mv secrets/<old>/ secrets/<new>/`, and update any env var pointing into it.
5. Update every reference to the old name across `tasks.yaml` `depends_on` lists, workflow bodies, and helper scripts.
6. Restart the daemon.

## State-migration sequence (only if the state path changed)

1. Stop the daemon.
2. `mkdir -p state/<task>/` and move existing state files into it.
3. Update every code path constant that reads/writes the old path.
4. Update every prompt and doc reference (`grep -rn '<old-path>' workflows/`).
5. Restart the daemon. Tail one fire and confirm reads/writes hit the new path.

## Delete sequence

Drain in-flight work first:

```bash
systemctl --user stop casper-heartbeat
journalctl --user -u casper-heartbeat -n 30 --no-pager | grep <task-name>
```

If a run was in flight, wait for it to land in `state/history/<task-name>.jsonl`.

Remove the `tasks.yaml` entry; if any remaining task referenced the removed name in `depends_on`, remove that reference or replace it with a valid task name. Then:

```bash
rm -rf ~/.agents/workflows/<task-name>/     # the task's own workflow folder
rm -rf ~/.agents/state/<task-name>/         # app state
rm -f  ~/.agents/state/history/<task-name>.jsonl   # audit trail — confirm with user first
rm -f  ~/.agents/state/clarify/<task-name>-*.md    # open clarify files (rare)
rm -rf ~/.agents/secrets/<task-name>/       # per-task credential dir
# Env vars: edit ~/.agents/secrets/heartbeat.env and drop keys only this task used.
#           Keep anything shared (e.g. CASPER_SLACK_WEBHOOK_URL).
```

Restart and confirm:

```bash
systemctl --user start casper-heartbeat
journalctl --user -u casper-heartbeat -n 30 --no-pager
```

## Delete validation

Manual fallback (only if `validate_delete.py` itself errors — the normal run is Verify step 6 in `heartbeat-task.md`): no grep hit for the task name across `workflows/` and `tests/` (resolved clarify files may stay); `workflows/<task-name>/`, `state/<task-name>/`, `secrets/<task-name>/` gone — history only if the user chose to keep it; task-unique env vars removed from `heartbeat.env`.

## Pi session policy

Heartbeat runs `pi --print` with sessions enabled on purpose — each run leaves a session under `~/.pi/agent/sessions/` that `extract_session_history.py` walks so `memory-distill` can pull learnings from any task's transcript. Never disable sessions (see the `--no-session` constraint in `heartbeat-task.md`).
