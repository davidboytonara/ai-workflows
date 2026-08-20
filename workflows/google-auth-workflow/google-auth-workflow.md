---
description: Verify Google OAuth for Google Docs, Sheets, and Slides via one workflow entrypoint
---

## Trigger

"Authenticate Google", "re-auth", "log in for Docs / Sheets / Slides", "fix Google OAuth" — or any gdocs / gsheet / gslides command failing with an auth exit code. Shared auth dependency of `../gdocs-workflow/gdocs-workflow.md`, `../gsheet-workflow/gsheet-workflow.md`, and `../gslides-workflow/gslides-workflow.md`.

## Goal

Auth for the target service (`docs`, `sheets`, or `slides`) verifies with exit `0` for the chosen account alias, so the calling workflow can proceed.

## Context

Commands run from your workspace root (quote the path if it contains spaces).

**Shared entrypoint.** One CLI fronts all three services:

```bash
SCRIPTS=.agents/workflows/google-auth-workflow
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py docs [--account <alias>] [--no-browser] [--timeout-seconds <seconds>]
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py sheets [--account <alias>] [--no-browser] [--timeout-seconds <seconds>]
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py slides [--account <alias>] [--no-browser] [--timeout-seconds <seconds>]
```

It dispatches to the workflow-local auth commands:

- Docs → `.agents/workflows/gdocs-workflow/cli.py auth`
- Sheets → `.agents/workflows/gsheet-workflow/cli.py auth`
- Slides → `.agents/workflows/gslides-workflow/cli.py auth`

`--no-browser` suppresses the browser launch for headless runs.

**Account aliases and credential files.** Aliases: `default`, `work`, `personal`, or custom. All four service workflows share ONE credentials directory — `GOOGLE_CREDENTIALS_DIR` in `~/.agents/.env`, default `~/.agents/credentials/` — holding `client_secret.<alias>.json` (OAuth client) and `token.<alias>.json` (stored token), one token file per account alias. Nothing under `credentials/` ships with this repository; each workflow's `CREDENTIALS.md` explains which files you must supply and how to obtain them.

**Exit codes.**

- `0` → auth verified; proceed with target workflow
- `2` → OAuth token exists but verification is incomplete; enable required Google API(s) or fix scopes, then rerun target auth
- `1` → auth error; inspect stderr, then fix the missing / wrong credentials file in `~/.agents/credentials/`
- `3` → target workflow env bootstrap failed; install blocked or venv issue

**Scope caveat.** Required OAuth scopes differ between Docs, Sheets, and Slides. When switching services, rerun auth for the target workflow before first use — an existing token for the alias may lack the new service's scopes.

## Constraints

- Confirm target service, account alias, and whether `--no-browser` is required before running. LLM needed because service and alias come from the user's intent, not from any file.
- Never commit, print, or paste the contents of any `credentials/` file (client secrets, tokens). Fix auth problems by placing the correct `client_secret.<alias>.json`, never by hand-editing token files.
- Reuse the same `--account` alias on all later Docs / Sheets / Slides commands in the session.
- Report target service, account alias, command run, exit code, authenticated email when available, and any remaining API-enablement or credential issues.

## Verify

```bash
cd "<workspace-root>"
$HOME/.agents/.venv/bin/python .agents/workflows/google-auth-workflow/cli.py <docs|sheets|slides> --account <alias>; echo "exit=$?"
# exit=0 proves auth; the alias token exists in the target workflow:
ls ~/.agents/credentials/token.<alias>.json
```
