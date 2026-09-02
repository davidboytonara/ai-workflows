---
description: Compose and push a Slack digest of gmail work-item deltas. Runs at 10:00, 13:00, and 18:00 your local timezone. The 10:00 run also includes a topic-frequency anomaly section.
---

## Trigger

Not user-invoked: the heartbeat daemon runs this as the `gmail-digest` scheduled task at 10:00, 13:00, and 18:00 your local timezone. The current your local timezone slot (`10:00`, `13:00`, or `18:00`) labels the message header; only the 10:00 slot runs the anomaly section.

## Goal

A category-grouped Slack digest of the work-item deltas whose notification decision is `include_digest` — plus, at 10:00, any topic spikes — is pushed, and notification state is stamped only after a successful push.

## Context

State lives at `~/.agents/state/gmail-ingest/state.json`, written by the **gmail-ingest** task (`ingest.md`), whose **Classification schema** supplies each item's `category` and its urgency/importance axes (collapsed into one Eisenhower quadrant). Selection, grouping, formatting, anomaly rendering, and the stamp payload are fully scripted by `compose` (`scripts/compose_notification.py`); the manual rules it implements are preserved in [`manual-compose.md`](manual-compose.md) for fallback. LLM needed because the heartbeat daemon executes tasks as agent turns; the agent only wires the commands below and applies the fallback rule.

**Run** — with `CLI="$HOME/.agents/.venv/bin/python $HOME/.agents/workflows/gmail-workflow/cli.py"` and `TMP=$(mktemp -d)`:

```bash
$CLI build-attention --json --channel digest \
  --enrich-replies --own-address <you@example.com> --max-thread-fetch 25 \
  --use-memory --memory-project <project-slug> > "$TMP/attention.json"

$CLI detect-anomalies --json > "$TMP/anomalies.json"   # 10:00 slot only

$CLI compose --kind digest --slot <HH:MM> --input "$TMP/attention.json" \
  --stamp-out "$TMP/stamp.json" > "$TMP/message.txt"   # add --anomalies "$TMP/anomalies.json" at 10:00
```

`compose` selects the `include_digest` work-item deltas (reply- and memory-aware suppression is already baked into each item's `notification` by `build-attention`), writes the exact `stamp-notifications` payload to `--stamp-out` (empty `items` for an anomaly-only digest), and always prints the run's `SUMMARY:` line on stderr. Exit 0 → message ready; exit 1 → nothing to send this slot; exit 2 → invalid input or wiring.

**Push, then stamp** (order is mandatory):

```bash
$CLI push-slack --kind digest < "$TMP/message.txt" \
  && $CLI stamp-notifications --input "$TMP/stamp.json"
```

**Failure semantics:** missing state → `build-attention` returns empty items and `compose` exits 1 with `SUMMARY: no state yet`. Thread-fetch failure → `build-attention` logs a warning, leaves `reply_state=unknown`, keeps Phase 2 notification behavior. `detect-anomalies` failure or an unusable anomalies file → `compose` warns and treats it as no anomalies and continues.

## Constraints

- Never call the LLM for classification, never list inbox messages, never mutate Gmail labels or Casper memory files. `build-attention --enrich-replies` may fetch candidate thread metadata only to infer reply status; `--use-memory` only reads Casper open-task memory for suppression/reopen decisions.
- Never replay already-communicated fingerprints; this task does not run backfill. Count work items, not constituent messages. `compose` enforces both — do not hand-edit its message body or stamp payload.
- Stamp only after `push-slack` exits 0, with exactly the `--stamp-out` payload. Webhook failure → do not stamp; the next slot retries unchanged work items plus any new changes. An anomaly-only digest pushes the anomaly section and stamps the empty item list on success.
- `compose` exit 1 → do not push; end the run with the `SUMMARY:` line it printed (`empty digest`, or `no state yet`); never push an empty message.
- Fallback (a broken compose must degrade, not kill the digest): `compose` exit 2 or crash → do NOT drop the slot; select, format, and stamp manually for this run per [`manual-compose.md`](manual-compose.md), and surface the compose failure (exit code + stderr) in the run's report.
- Do not add the `:envelope_with_arrow: [GMAIL] Digest` prefix — `push-slack` adds it.

## Verify

- `push-slack` exited 0 before any stamping, and `$TMP/message.txt` is exactly what was pushed.
- The stamp landed for each included item:

```bash
$HOME/.agents/.venv/bin/python -c "import json,pathlib; s=json.loads(pathlib.Path.home().joinpath('.agents/state/gmail-ingest/state.json').read_text()); print(json.dumps(s.get('notification_ledger', {}).get('<item_key>'), indent=2))"
```

- The run's last line is the `SUMMARY:` line `compose` printed on stderr — `SUMMARY: digested N work items (cat=Work:3,Finance:2; anomalies=K)`, or one of the empty-run summaries above.
