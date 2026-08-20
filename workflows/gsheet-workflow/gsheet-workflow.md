---
description: Operate Google Sheets spreadsheets via shared Google OAuth and project-local wrappers
---

## Trigger

"Put this in a spreadsheet", "read / update the sheet", "add a tab / chart / formula / dropdown", "format these cells", "conditional formatting", "named range" — any Google Sheets operation on a new spreadsheet or an existing id / URL.

## Goal

The requested Sheets operation (create, read, update, append, clear, manage tabs, format, charts, formulas, validation) completes under the chosen account alias and passes Verify.

## Context

Commands run from your workspace root. Shorthand: `SCRIPTS=.agents/workflows/gsheet-workflow`.

**Dependencies.** `$HOME/.agents/.venv/bin/python $SCRIPTS/_env.py --bootstrap` installs this workflow's deps into the shared venv. Exit `0` → proceed; non-zero → install blocked.

**Auth.** Preflight through the **Shared entrypoint** in `../google-auth-workflow/google-auth-workflow.md`:

```bash
$HOME/.agents/.venv/bin/python .agents/workflows/google-auth-workflow/cli.py sheets [--account <alias>] [--no-browser] [--timeout-seconds <seconds>]
```

Direct equivalent: `$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py auth` with the same flags. The **Exit codes**, credential file locations, and **Scope caveat** live in that same file. Sheets-specific hint: exit `1` usually means a missing or wrong `~/.agents/credentials/client_secret.<alias>.json`.

**Command reference.** Account aliases: `default`, `work`, `personal`, or custom; every command accepts `[--account <alias>]`. Capture `spreadsheetId` from `create` output for later commands.

```bash
# create / inspect
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py create --title "<title>" [--sheets "Data,Summary"] [--output info.json]
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py read --info <spreadsheet-id-or-url>
# read values
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py read --spreadsheet <id-or-url> --range "Sheet1!A1:C10" [--raw] [--output data.json]
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py read --spreadsheet <id-or-url> --ranges "Sheet1!A1:B5,Sheet1!D1:E5"
# update / append / clear values
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py update --spreadsheet <id-or-url> --range "Data!A1" --values '[["Name","Value"],["Item1",100]]'
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py update --spreadsheet <id-or-url> --append --range "Data" --values '[["New","Row"]]'
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py update --spreadsheet <id-or-url> --clear --range "Data!A1:Z100"
# manage tabs
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py sheets --spreadsheet <id-or-url> --create --title "Dashboard" [--rows 2000 --columns 40]
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py sheets --spreadsheet <id-or-url> --rename --old "Sheet1" --new "Data"
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py sheets --spreadsheet <id-or-url> --delete --title "OldSheet"
# format / conditional / alternating colors
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py format --spreadsheet <id-or-url> --range "Data!A1:D1" --bold --bg-color "#4285F4" --text-color "#FFFFFF"
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py format --spreadsheet <id-or-url> --range "Data!B2:B100" --conditional --rule greater_than --value 1000 --highlight-color "#00FF00"
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py format --spreadsheet <id-or-url> --alternating --sheet "Data"
# charts
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py charts --spreadsheet <id-or-url> --sheet "Dashboard" --type column --data-range "Data!A1:B12" --title "Monthly Sales"
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py charts --spreadsheet <id-or-url> --list
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py charts --spreadsheet <id-or-url> --delete --chart-id <chart_id>
# formulas / named ranges
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py formulas --spreadsheet <id-or-url> --cell "Data!E2" --formula "=D2/B2"
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py formulas --spreadsheet <id-or-url> --create-named-range --name "SalesData" --range "Data!A1:D100"
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py formulas --spreadsheet <id-or-url> --fill-down --source "Data!E2" --target "Data!E2:E100"
# validation
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py validation --spreadsheet <id-or-url> --range "Data!C2:C100" --dropdown --values "Approved,Pending,Rejected"
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py validation --spreadsheet <id-or-url> --range "Data!D2:D100" --number --min 0 --max 100
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py validation --spreadsheet <id-or-url> --range "Data!E2:E100" --clear
# post-write verify: re-reads the range and compares cell-by-cell (exit 0 verified, 1 mismatch, 2 usage)
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py verify --spreadsheet <id-or-url> --range "Data!A1:B2" --values '[["Name","Value"],["Item1",100]]'
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py verify --spreadsheet <id-or-url> --range "Data!A1:Z100" --expect-empty
```

**References.** Full chart types and options: [`references/charts.md`](references/charts.md). Full cell / conditional / number-format options: [`references/formatting.md`](references/formatting.md).

## Constraints

- Non-zero bootstrap exit → stop and ask the user; do not work around a blocked install.
- Before acting, confirm: operation, account alias, spreadsheet target (new vs existing id / URL), affected sheets / ranges, values or formulas, and whether a JSON output file is needed.
- Reuse the same `--account` on every command; when switching between Docs, Sheets, and Slides, rerun auth for the target workflow first (see the **Scope caveat** in `../google-auth-workflow/google-auth-workflow.md`).
- Never commit or expose files under `~/.agents/credentials/`. Nothing under `credentials/` ships with this repository — see [`CREDENTIALS.md`](CREDENTIALS.md) for what you must supply and how to obtain it.
- Report spreadsheet title/id/url, alias used, commands run, ranges / tabs / charts / rules changed, verification checks run, output file paths, and remaining caveats (permissions, API enablement, throttling, sharing gaps).

## Verify

```bash
# after a values update / append: scripted compare of the affected range against what was written
# (for append, --range is the updatedRange the append reported). Exit 1 lists differing cells on
# stdout — re-read the range with `read --range` and reconcile before reporting done.
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py verify --spreadsheet <id-or-url> --range "<written-range>" --values '<written-values-json>' [--account <alias>]
# after a clear: the range must be empty
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py verify --spreadsheet <id-or-url> --range "<cleared-range>" --expect-empty [--account <alias>]
# after structural work (tabs, formats, validation): re-read metadata
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py read --info <spreadsheet-id-or-url> [--account <alias>]
# after chart work: confirm via the list command
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py charts --spreadsheet <id-or-url> --list [--account <alias>]
```
