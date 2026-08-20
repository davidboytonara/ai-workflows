---
description: Operate Google Slides presentations via shared Google OAuth and project-local wrappers
---

## Trigger

"Create a presentation / deck", "add slides", "apply the brand to the deck", "inspect / update the slides", "export the deck as pptx" — any Google Slides operation on a new presentation or an existing id / URL.

## Goal

The requested Slides operation (create, add content, apply brand, inspect, update, export pptx) completes under the chosen account alias and passes Verify.

## Context

Commands run from your workspace root. Shorthand: `SCRIPTS=.agents/workflows/gslides-workflow`.

**Dependencies.** `$HOME/.agents/.venv/bin/python $SCRIPTS/_env.py --bootstrap` installs this workflow's deps into the shared venv. Exit `0` → proceed; non-zero → install blocked.

**Auth.** Preflight through the **Shared entrypoint** in `../google-auth-workflow/google-auth-workflow.md`:

```bash
$HOME/.agents/.venv/bin/python .agents/workflows/google-auth-workflow/cli.py slides [--account <alias>] [--no-browser] [--timeout-seconds <seconds>]
```

Direct equivalent: `$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py auth` with the same flags. The **Exit codes**, credential file locations, and **Scope caveat** live in that same file. Slides-specific hints: exit `2` usually means the Slides / Drive APIs need enabling; exit `1` usually means a missing or wrong `~/.agents/credentials/client_secret.<alias>.json`.

**Command reference.** Account aliases: `default`, `work`, `personal`, or custom; every command accepts `[--account <alias>]`.

```bash
# create presentation (optionally from a Drive template)
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py create --title "<title>" [--template-id "<drive_template_id>"] [--output info.json]
# add content from JSON
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py content --presentation-id "<id-or-url>" --content-file "slides.json"
# apply brand JSON
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py brand --presentation-id "<id-or-url>" --brand-file "brand.json"
# inspect: slide ids, tables, images, object ids
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py inspect --presentation-id "<id-or-url>" [--output deck.json] [--compact]
# update: validated apply — JSON check, then dry-run, then live apply; stops at the first failure
# exit 0 applied · 4 changes JSON invalid · 5 dry-run failed · 6 apply failed (nothing applied on 4/5)
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py update --validated --presentation-id "<id-or-url>" --changes-file "changes.json"
# preview only (no apply): same command with --dry-run instead of --validated
# export to PPTX
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py export --presentation-id "<id-or-url>" --output "./deck.pptx"
```

**Input formats.** Slide content JSON follows [`references/content-schema.md`](references/content-schema.md); update JSON follows [`references/changes-schema.md`](references/changes-schema.md); brand JSON and brand-skill detection are covered in [`references/brand-integration.md`](references/brand-integration.md). Authoring these files is this workflow's LLM step — LLM needed because slide content and changes encode the user's intent.

**API quirks.** `inspect` and `update` require a native Google Slides file, not an uploaded `.pptx`. Heavy request bursts can hit throttling.

## Constraints

- Non-zero bootstrap exit → stop and ask the user; do not work around a blocked install.
- Before acting, confirm: operation, account alias, presentation target (new vs existing id / URL), JSON input files needed (`content`, `brand`, `changes`), and export output path.
- Validate `content` / `brand` JSON before execution: `$HOME/.agents/.venv/bin/python -m json.tool <file>.json >/dev/null` (changes JSON is checked by `update --validated` itself).
- Apply updates only through `update --validated`; on exit 4 fix the JSON, on exit 5 read the dry-run error before retrying — never bypass a failed stage with a plain apply. When the preview itself needs review first (non-trivial updates), run `--dry-run` alone, review, then rerun with `--validated`.
- Reuse the same `--account` on every command; when switching between Docs, Sheets, and Slides, rerun auth for the target workflow first (see the **Scope caveat** in `../google-auth-workflow/google-auth-workflow.md`).
- New local JSON drafts default to `Fleeting Notes/` unless the user named a project; exported `.pptx` files go to the project's `Attachments/`.
- Never commit or expose files under `~/.agents/credentials/`. Nothing under `credentials/` ships with this repository — see [`CREDENTIALS.md`](CREDENTIALS.md) for what you must supply and how to obtain it.
- Report presentation title/id/url, alias used, JSON files consumed, commands run, slide or update counts, export paths, verification checks run, and remaining caveats (sharing, API enablement, throttling).

## Verify

```bash
# after content or update operations: re-inspect
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py inspect --presentation-id "<id-or-url>" --compact [--account <alias>]
# after export: file exists
ls -lh "<output.pptx>"
```
