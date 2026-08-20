---
description: Automate Google NotebookLM (notebooks, sources, research, artifact generation, downloads) via project-local scripts, with handoff to whatever document workflows your setup provides
---

> **⚠️ Terms-of-Service notice.** This workflow drives a browser against Google
> NotebookLM using a session you log into yourself, via an unofficial client. It is
> intended solely for **your own account and your own data**. Automated access may
> violate Google's terms, which can change at any time. Read the full notice in the
> repository README before use.

## Trigger

"NotebookLM", "make a notebook from these sources", "run deep research on X", "generate an audio overview / slide deck / report / quiz from my sources", "download that NotebookLM artifact" — any NotebookLM automation, including as the research step before a document deliverable.

## Goal

The requested NotebookLM operation (Q&A, research, artifact generation, download) completes via the workflow-local scripts, with outputs saved to the right vault destination and handed off to the matching downstream workflow.

## Context

**Scripts.** All in this folder — thin argv wrappers around `notebooklm-py`, one per domain: `session.py`, `notebook.py`, `source.py`, `chat.py`, `research.py`, `generate.py`, `artifact.py`, `note.py`, `share.py`. Every script accepts `--help`. `README.md` here documents the command surface, exit codes (0 success, 1 business-logic failure, 2 usage, 3 env/bootstrap), and manual login; `references/interop.md` is the downstream handoff cookbook (brand styling, email drafts, issue creation, ...). Shorthand below: `SCRIPTS=.agents/workflows/notebooklm-workflow`.

**Environment.** Bootstrap deps: `$HOME/.agents/.venv/bin/python $SCRIPTS/_env.py --bootstrap` (exit 0 = ready). If it fails: check network / pip access; install `notebooklm-py` into `$HOME/.agents/.venv` manually and retry.

**Auth is out-of-band** — these scripts never launch a browser. Preflight:
```bash
$HOME/.agents/.venv/bin/python $SCRIPTS/session.py auth-check --test
```
Non-zero = cookies expired or missing; the fix is always this manual login guide:
```bash
PY="$HOME/.agents/.venv/bin/python"
"$PY" -m pip install -r .agents/workflows/notebooklm-workflow/requirements.txt "notebooklm-py[browser]"
"$PY" -m playwright install chromium        # + "$PY" -m playwright install-deps chromium on Linux
"$HOME/.agents/.venv/bin/notebooklm" login
"$HOME/.agents/.venv/bin/notebooklm" auth check --test
```

**Command patterns** (non-obvious flags; `$HOME/.agents/.venv/bin/python` before each script):
- Notebook: `$SCRIPTS/notebook.py list` or `$SCRIPTS/notebook.py create "<title>"`, then `$SCRIPTS/session.py use <notebook_id>` — later commands run against the selected notebook.
- Sources: `$SCRIPTS/source.py add "<url-or-path>"`, then `$SCRIPTS/source.py wait <source_id> --timeout 900`. Batches: `$SCRIPTS/source_batch.py <src>... [--from-file list.txt] [--notebook <id>] [--timeout 900]` adds all, waits for each, prints one status line per source (stderr) plus a JSON summary with `ready_ids` (stdout); `--plan` previews the commands without executing.
- Deep research — blocking: `$SCRIPTS/research.py add "<query>" --mode deep --import-all`; non-blocking (long runs): `--no-wait`, then `$SCRIPTS/research.py wait --timeout 900 --import-all`.
- Q&A: `$SCRIPTS/chat.py ask "<prompt>" --json`, or `--save-as-note --note-title "<t>"`.
- Generate: `$SCRIPTS/generate.py <type> [flags] --wait`, `<type>` ∈ `audio`, `video`, `slide-deck`, `report`, `quiz`, `flashcards`, `infographic`, `data-table`, `mind-map`. Examples: `generate.py report --format briefing-doc --wait`, `generate.py slide-deck --format detailed --wait`, `generate.py audio "deep dive on chapter 3" --format deep-dive --wait`. `--wait` already handles transient throttling/polling; if still throttled, lower frequency and retry.
- Download: `$SCRIPTS/artifact.py download <type> <local-path> [--format <fmt>]`, e.g. `download report ./briefing.md`, `download slide-deck ./slides.pptx --format pptx`, `download data-table ./table.csv`. Expired artifact URL → re-list with `$SCRIPTS/artifact.py list --type <type>` and retry.

**Output destinations** (vault rules): markdown → `Fleeting Notes/`; when the user named a project → that project's `Attachments/`.

**Downstream handoff:** hand the downloaded artifact to whatever workflow owns that file type in your setup (`.pptx` → a deck workflow, `.csv` / `.xlsx` → a spreadsheet workflow, `.md` report → further edit/convert as needed). Full cookbook: `references/interop.md`.

**Lesson.** Poor source parse quality on a dynamic site → ingest a saved local file (`.md`, `.pdf`, `.docx`) instead of the URL.

## Constraints

- Never attempt browser automation for login from this workflow — login is manual only. When `auth-check --test` fails, stop and print the login guide above.
- `_env.py --bootstrap` non-zero → installation blocked; stop and ask the user.
- Clarify before acting: goal (`ask` / `research` / `generate` / `download`), notebook target (new vs existing id), source list (URLs, YouTube, local files), output artifact type + destination path, and any downstream handoff (a document, spreadsheet, deck, gmail, or clickup workflow in your setup).
- For more than 3 sources, run `source_batch.py` instead of looping add/wait by hand. Exit 1 → report the failed sources from its summary and continue with `ready_ids`; exit 2 (usage) or 3 (bootstrap) → fix per the rules above before retrying.
- Final report must include: notebook id, ingested source ids, artifact ids, local output paths, downstream workflow triggered (if any), and remaining caveats (throttling, expired artifact URL, source parse quality).

## Verify

```bash
SCRIPTS=.agents/workflows/notebooklm-workflow
$HOME/.agents/.venv/bin/python $SCRIPTS/session.py auth-check --test    # exit 0 = authenticated
$HOME/.agents/.venv/bin/python $SCRIPTS/notebook.py list                # notebook exists
$HOME/.agents/.venv/bin/python $SCRIPTS/artifact.py list --type <type>  # artifact generated
ls -l <local-path>                                                      # downloaded file exists, non-empty
```
