# NotebookLM Scripts

Project-local wrappers around the `notebooklm-py` CLI. Used by
`.agents/workflows/notebooklm-workflow/notebooklm-workflow.md`. Self-contained
with workflow-local docs and references.

## Layout

- `requirements.txt` — pins `notebooklm-py`
- `_env.py` — venv bootstrap + CLI proxy (`run_cli()`); also runnable:
  `$HOME/.agents/.venv/bin/python _env.py --bootstrap`, `--paths`
- Domain scripts (thin argv forwarders):
  - `session.py` — `status`, `use`, `clear`, `auth-check`, `language ...`, `login`
  - `notebook.py` — `list`, `create`, `rename`, `delete`, `summary`, `metadata`
  - `source.py` — full `source` group (add, add-research, list, wait, …)
  - `source_batch.py` — batch `add` + `wait` over many sources; one status
    line per source + JSON summary (`--plan` previews; exit 0 all ready,
    1 some failed, 2 usage, 3 env)
  - `chat.py` — `ask`, `configure`, `history`
  - `research.py` — `status`, `wait`; alias `add` → `source add-research`
  - `generate.py` — all `generate <type>` subcommands
  - `artifact.py` — `artifact` group + `download <type>` in one entry
  - `note.py` — full `note` group
  - `share.py` — full `share` group

## Auth

Authentication is **out-of-band**. These scripts never launch a browser.
Perform a one-time manual login using the shared Casper venv:

```bash
PY="$HOME/.agents/.venv/bin/python"
"$PY" -m pip install -r .agents/workflows/notebooklm-workflow/requirements.txt "notebooklm-py[browser]"
"$PY" -m playwright install chromium
# Linux hosts may also need: "$PY" -m playwright install-deps chromium
"$HOME/.agents/.venv/bin/notebooklm" login
"$HOME/.agents/.venv/bin/notebooklm" auth check --test
```

Cookies land at `~/.notebooklm/storage_state.json` and are read by every script here.

If the cookie file is missing, scripts exit `1` with a pointer to the
login guide. If login expires, run `session.py auth-check --test` and
re-login manually.

## Quick start

```bash
SCRIPTS=.agents/workflows/notebooklm-workflow

$HOME/.agents/.venv/bin/python $SCRIPTS/session.py auth-check --test
$HOME/.agents/.venv/bin/python $SCRIPTS/notebook.py create "Research 2026-Q2"
$HOME/.agents/.venv/bin/python $SCRIPTS/session.py use <notebook_id>
$HOME/.agents/.venv/bin/python $SCRIPTS/source.py add "https://example.com/article"
$HOME/.agents/.venv/bin/python $SCRIPTS/source.py wait <source_id> --timeout 600
$HOME/.agents/.venv/bin/python $SCRIPTS/chat.py ask "Summarize" --save-as-note --note-title "Summary"
$HOME/.agents/.venv/bin/python $SCRIPTS/generate.py report --format briefing-doc --wait
$HOME/.agents/.venv/bin/python $SCRIPTS/artifact.py download report ./briefing.md
```

## Exit codes

- `0` — success
- `1` — business-logic failure (auth missing, not found, generation error)
- `2` — usage / unknown subcommand
- `3` — environment / venv bootstrap failure

## Flag reference

Each script accepts `--help` and (where it delegates to a group) forwards
to the underlying group's help output. This README plus `references/interop.md`
cover the local command surface and downstream handoff patterns.
