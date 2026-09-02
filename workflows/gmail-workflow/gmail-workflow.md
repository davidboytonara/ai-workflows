---
description: Operate Gmail safely — read, triage, attachment download, draft-only replies, and reversible cleanup — via shared Google OAuth and workflow-local scripts
---

## Trigger

"Check my email", "summarize / triage my inbox", "download the attachment from …", "draft a reply to …", "clean up these emails" — any interactive Gmail read, triage, attachment, draft, or reversible-cleanup request. Scheduled counterparts live in `heartbeat/` (`ingest.md`, `digest.md`, `urgent-push.md`).

## Goal

The requested operation completes through the workflow-local CLI: triage is deduped and resolution-checked, attachments land where agreed, drafts (never sent) are created or updated in place, and reversible mutations are previewed, applied, and reported.

## Context

Shorthand `SCRIPTS=.agents/workflows/gmail-workflow`; interpreter `$HOME/.agents/.venv/bin/python`.

**Turning an email into a casper goal.** This workflow only reads, triages, drafts, and reversibly cleans up — it never plans or executes work. When an email should turn into an approved `casper` run (e.g. "handle what this thread is asking for"), use [`../goal-authoring/goal-authoring.md`](../goal-authoring/goal-authoring.md) to draft `$HD/goal.md` from the message/thread, then hand off to `../casper/casper.md`.

**Bootstrap** (exit 0 → proceed; non-zero → install blocked, stop and ask):

```bash
$HOME/.agents/.venv/bin/python $SCRIPTS/_env.py --bootstrap
```

**Auth preflight** — aliases `default`, `work`, `personal`, or custom; reuse the same `--account` everywhere after:

```bash
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py auth [--account <alias>] [--no-browser]
```

Exit 0 → proceed. Exit 2 → token exists but verification incomplete: fix Gmail API / scopes / Cloud config, rerun. Exit 1 → auth error; common cause: missing/wrong `credentials/client_secret.<alias>.json`; inspect stderr. Nothing under `credentials/` ships with this repository — see [`CREDENTIALS.md`](CREDENTIALS.md) for what you must supply and how to obtain it.

**Read** (full bodies, capped at 10 results):

```bash
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py read --subject "Invoice" --from "billing@example.com" --body "overdue" --attachment-name "invoice.pdf" --max-results 10 [--account <alias>]
```

**Triage** (read-only, metadata only — use instead of `read` for the whole inbox, not just 10). LLM needed because bucketing free-text mail into action/information/noise takes judgment. Scope to unread and raise the ceiling to get the full set:

```bash
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py list-unprocessed --account <alias> --max-age-days 30 --unread-only --max-results 500 --dry-run --json
```

Flags (on `list_unprocessed.py`, passed through by `cli.py`):

- `--max-results N` (default 50) paginates on `nextPageToken` up to N. Default stays 50 so the heartbeat's batch + processed-state dedupe (the **Per-run cap** in `heartbeat/ingest.md`) is unchanged — raise it here instead of editing `BATCH_CAP`.
- `--unread-only` scopes to `in:inbox is:unread`. The default `in:inbox` is all mail regardless of read state — the heartbeat's "not yet in processed-state" notion, a *different* set than "currently unread".
- Hitting the ceiling with mail remaining sets `"truncated": true` + `"remaining_estimate": N` in the JSON and warns on stderr — truncation is never silent.

Cross-check the true unread count (`utils` lives under `scripts/`, hence the path):

```bash
$HOME/.agents/.venv/bin/python -c "
import sys; sys.path.insert(0, '$SCRIPTS/scripts')
from utils.auth_helper import build_gmail_service
svc = build_gmail_service(account='<alias>')
print(svc.users().labels().get(userId='me', id='UNREAD').execute()['messagesUnread'])
"
```

**Dedupe before classifying:** group by `thread_id` AND normalized subject (strip `Re:`/`RE:`/`Fwd:`, collapse whitespace) — the same notice often arrives 2–3× (direct + via a Google Group like it@/finance@, or repeated dunning). Classify once per group; apply to every id in the group.

Fetch bodies only for needed ids:

```bash
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py fetch-bodies --account <alias> --ids "<id1>,<id2>" --max-chars 4000 --json
```

Resolution check on action candidates (cheap):

```bash
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py check-resolution --account <alias> --ids "<action_id1>,<action_id2>" --json
```

**Attachments:**

```bash
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py attachments --message-id "<gmail_message_id>" --output-dir "<output_dir>" [--account <alias>]
```

**Drafts.** New message:

```bash
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py draft --to "user@example.com" --subject "Follow-up" --body "Just checking in on this." --from "<your-identity@domain>" [--cc "team@example.com"] [--bcc "audit@example.com"] [--account <alias>]
```

Reply in-thread (copies `threadId`, sets `In-Reply-To`/`References`; keep subject `Re: <original>` so Gmail threads reliably):

```bash
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py draft --account <alias> \
  --reply-to-message-id "<original_gmail_message_id>" \
  --from "<identity the original was sent TO>" \
  --to "<original sender>" --subject "Re: <original subject>" --body "<reply text>"
```

Correct/replace an existing draft in place:

```bash
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py draft --account <alias> --update-draft-id "<draft_id>" --from "..." --to "..." --subject "..." --body "..." [--reply-to-message-id "..."]
```

**Cleanup** (reversible only — see Constraints):

```bash
# preview first (no changes)
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py modify --account <alias> --ids "<id1>,<id2>" --trash --dry-run
# then apply
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py modify --account <alias> --ids "<id1>,<id2>" --trash
$HOME/.agents/.venv/bin/python $SCRIPTS/cli.py modify --account <alias> --ids "<id3>,<id4>" --mark-read
```

**Playbooks.** Drafting rules, per-email-type draft routing, per-sender resolution heuristics that `check-resolution` cannot infer, and recurring recipients are all deployment-specific. They are intentionally not shipped here — keep your own `playbooks.md` next to this file (it is yours, not part of this repository) and read it before composing any draft or downgrading an action item.

## Constraints

- Never send email. Never permanently delete a message (no `messages.delete`) and never alter message content.
- Reversible changes (trash — recoverable ~30 days — and mark read/unread) only via `cli.py modify`, only on explicit user request; always `--dry-run` first and report the preview before applying.
- Standing exception, pre-authorized — do not ask again: after classifying a triage run, `modify --mark-read` every message bucketed Low-priority/Optional, Information (no action), or Noise — dry-run, apply, report the count. Never auto-mark a message whose thread_id has an Action-needed message; those stay unread until the user acts or says to clear them.
- Drafts are always safe (never sent). Prefer `--update-draft-id` in place; never delete a draft to recreate it.
- Resolution cross-check is MANDATORY before reporting anything action-needed — unread is a weak proxy for unresolved. Verdicts: `likely_resolved` → report "likely resolved — verify" with evidence, NOT action-needed; `verify` → "possibly handled elsewhere — verify"; `open` → action-needed. Then apply your own per-sender resolution heuristics, if you keep any.
- Enumerate the full unread set: while `"truncated": true`, raise `--max-results` (or narrow / `--unread-only`) and re-run until `false` — never stop at the newest 50.
- When triage matches one of your own draft-routing rules, prepare the routed (unsent) draft proactively and report its draft id + `[ISI ...]` placeholders.
- Never invent commitments (prices, dates, approvals); user-only facts become clearly-marked `[ISI ...]` placeholders, listed back to the user.
- Confirm goal, account alias, filters/message id, recipients, and output directory before acting; prefer project `Attachments/` when the user named a project.

## Verify

- Reads/triage: returned ids and headers match the requested filters; an `--unread-only --max-results 500` run with `"truncated": false` enumerates the full unread set and tallies with the UNREAD cross-check above.
- Attachments: `find "<output_dir>" -maxdepth 1 -type f | sort`
- Drafts: capture the printed draft id + message id; UI check: Gmail Drafts on the same account.
- Report: account alias, filters or draft metadata, message ids touched, file paths, checks run, remaining caveats (permissions, API enablement, org policy).
