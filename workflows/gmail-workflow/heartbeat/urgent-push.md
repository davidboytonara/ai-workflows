---
description: Push urgent, not-yet-notified gmail work items to Slack. Invoked every 30 minutes by the heartbeat daemon (07:00–23:30 your local timezone only — quiet-hours-aware).
---

## Trigger

Not user-invoked: the heartbeat daemon runs this as the `gmail-urgent-push` scheduled task every 30 minutes, 07:00–23:30 your local timezone only (quiet-hours-aware).

## Goal

Urgent work-item deltas whose notification decision is `push_urgent` are pushed to Slack (capped at 5 per run), and notification state is stamped only after a successful push.

## Context

State lives at `~/.agents/state/gmail-ingest/state.json`, written by the **gmail-ingest** task (`ingest.md`), whose **Classification schema** supplies each item's `Category`. Selection, sort, the 5-item cap with overflow line, formatting, and the stamp payload are fully scripted by `compose` (`scripts/compose_notification.py`); the manual rules it implements are preserved in [`manual-compose.md`](manual-compose.md) for fallback. LLM needed because the heartbeat daemon executes tasks as agent turns; the agent only wires the commands below and applies the fallback rule.

**Run** — with `CLI="$HOME/.agents/.venv/bin/python $HOME/.agents/workflows/gmail-workflow/cli.py"` and `TMP=$(mktemp -d)`:

```bash
$CLI build-attention --json --channel urgent --only-actionable \
  --enrich-replies --own-address <you@example.com> --max-thread-fetch 25 \
  --use-memory --memory-project <project-slug> > "$TMP/attention.json"

$CLI compose --kind urgent --input "$TMP/attention.json" \
  --stamp-out "$TMP/stamp.json" > "$TMP/message.txt"
```

`compose` selects the `push_urgent` work-item deltas (reply- and memory-aware suppression is already baked into each item's `notification` by `build-attention`), sorts by `last_seen_ms` descending, caps at 5 (`--cap`) with the `+ K more urgent in inbox` overflow line, writes the exact `stamp-notifications` payload for the pushed (capped) set to `--stamp-out`, and always prints the run's `SUMMARY:` line on stderr. Exit 0 → message ready; exit 1 → nothing to push; exit 2 → invalid input or wiring.

**Push, then stamp** (order is mandatory):

```bash
$CLI push-slack --kind urgent < "$TMP/message.txt" \
  && $CLI stamp-notifications --input "$TMP/stamp.json"
```

**Push env behavior:** `GMAIL_SUMMARIZER_DRY_RUN=true` → `push-slack` no-ops and returns 0: treat as success, stamp normally. `CASPER_SLACK_WEBHOOK_URL` unset → logs a warning and returns 0: still stamp, since the user's choice was no Slack delivery. Webhook 5xx/timeout → nonzero exit.

**Failure semantics:** missing state → `build-attention` returns empty items and `compose` exits 1 with `SUMMARY: 0 urgent`. Thread-fetch failure → `build-attention` logs a warning, leaves `reply_state=unknown`, keeps Phase 2 notification behavior. Unstamped overflow items get pushed on the next run or by the **gmail-digest** fallback (`digest.md`).

## Constraints

- Never call the LLM for classification, never list inbox messages, never mutate Gmail labels or Casper memory files. `build-attention --enrich-replies` may fetch candidate thread metadata only to infer reply status; `--use-memory` only reads Casper open-task memory for suppression/reopen decisions.
- Never replay already-communicated fingerprints; this task does not run backfill. Cap at 5 work items per run with the overflow line. `compose` enforces both — do not hand-edit its message body or stamp payload.
- Stamp exactly the pushed work-item objects (`$TMP/stamp.json` — `compose` writes only the capped set), and only on `push-slack` exit 0. Nonzero exit → do not stamp; the next run picks up the same work items idempotently.
- `compose` exit 1 → do not push; end the run with `SUMMARY: 0 urgent`.
- Fallback (a broken compose must degrade, not kill the push): `compose` exit 2 or crash → do NOT drop the run; select, format, and stamp manually for this run per [`manual-compose.md`](manual-compose.md), and surface the compose failure (exit code + stderr) in the run's report.
- Do not add the `:rotating_light: [GMAIL] Urgent` prefix — `push-slack` adds it.

## Verify

- `push-slack` exit code was captured and was 0 before any stamping, and `$TMP/message.txt` is exactly what was pushed.
- The stamp landed for each pushed item:

```bash
$HOME/.agents/.venv/bin/python -c "import json,pathlib; s=json.loads(pathlib.Path.home().joinpath('.agents/state/gmail-ingest/state.json').read_text()); print(json.dumps(s.get('notification_ledger', {}).get('<item_key>'), indent=2))"
```

- The run's last line is the `SUMMARY:` line `compose` printed on stderr — `SUMMARY: pushed N urgent (cap=5)`, or `SUMMARY: 0 urgent` on an empty run.
