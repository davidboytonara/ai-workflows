---
description: Operate Google Docs documents via shared Google OAuth and project-local wrappers
---

## Trigger

"Create a Google Doc", "write / append this to the doc", "update the document", "read / inspect a Google Doc", "export the doc as docx / pdf" — any Google Docs operation on a new document or an existing id / URL.

## Goal

The requested Docs operation (create, add content, inspect, update, export) completes under the chosen account alias and passes Verify.

## Context

Commands run from your workspace root. Shorthand: `SCRIPTS=.agents/workflows/gdocs-workflow`.

**Dependencies.** `$HOME/.agents/.venv/bin/python $SCRIPTS/_env.py --bootstrap` installs this workflow's deps into the shared venv. Exit `0` → proceed; non-zero → install blocked.

**Auth.** Preflight through the **Shared entrypoint** in `../google-auth-workflow/google-auth-workflow.md`:

```bash
$HOME/.agents/.venv/bin/python .agents/workflows/google-auth-workflow/cli.py docs [--account <alias>] [--no-browser] [--timeout-seconds <seconds>]
```

Direct equivalent: `$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py auth` with the same flags. The **Exit codes**, credential file locations, and **Scope caveat** live in that same file. Docs-specific hints: exit `2` usually means the Docs / Drive APIs need enabling; exit `1` usually means a missing or wrong `~/.agents/credentials/client_secret.<alias>.json`.

**Command reference.** Account aliases: `default`, `work`, `personal`, or custom; every command accepts `[--account <alias>]`.

```bash
# create document
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py create --title "<title>" [--output info.json]
# add or replace content from markdown / text
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py content --document-id "<id-or-url>" --content-file "draft.md" [--mode replace|append] [--format markdown|text]
# inspect: indexes, headings, tables, full text
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py inspect --document-id "<id-or-url>" [--output doc.json] [--compact]
# update: validated apply — JSON check, then dry-run, then live apply; stops at the first failure
# exit 0 applied · 4 changes JSON invalid · 5 dry-run failed · 6 apply failed (nothing applied on 4/5)
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py update --validated --document-id "<id-or-url>" --changes-file "changes.json" [--output result.json]
# preview only (no apply): same command with --dry-run instead of --validated
# export to local file
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py export --document-id "<id-or-url>" --output "./brief.docx" [--format docx|pdf|txt|html|epub]
```

**Input formats.** Content files are `.md` or `.txt`; the supported markdown subset is documented in [`content-format.md`](content-format.md). Update JSON takes friendly ops or raw Docs API requests; shapes in [`changes-schema.md`](changes-schema.md). Authoring these files is this workflow's LLM step — LLM needed because content and changes encode the user's intent.

**API quirks.** `update` and `export` require a native Google Docs file, not an uploaded `.docx`. Markdown support is partial (see [`content-format.md`](content-format.md)). Heavy request bursts can hit throttling.

## Constraints

- Non-zero bootstrap exit → stop and ask the user; do not work around a blocked install.
- Before acting, confirm: operation, account alias, target document (new vs existing id / URL), input files needed, and export output path.
- Apply updates only through `update --validated`; on exit 4 fix the JSON, on exit 5 read the dry-run error before retrying — never bypass a failed stage with a plain apply. When the preview itself needs review first (non-trivial updates), run `--dry-run` alone, review, then rerun with `--validated`.
- Reuse the same `--account` on every command; when switching between Docs, Sheets, and Slides, rerun auth for the target workflow first (see the **Scope caveat** in `../google-auth-workflow/google-auth-workflow.md`).
- New local drafts default to `Fleeting Notes/` unless the user named a project; exported `.docx` / `.pdf` files go to the project's `Attachments/`.
- Never commit or expose files under `~/.agents/credentials/`. Nothing under `credentials/` ships with this repository — see [`CREDENTIALS.md`](CREDENTIALS.md) for what you must supply and how to obtain it.
- Report document title/id/url, alias used, files consumed, commands and checks run, export paths, and remaining caveats (permissions, API enablement, unsupported markdown, throttling).

## Verify

```bash
# after content or update operations: re-inspect
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py inspect --document-id "<id-or-url>" --compact [--account <alias>]
# after export: file exists
ls -lh "<output-file>"
```
