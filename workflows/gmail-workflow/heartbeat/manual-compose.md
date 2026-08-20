# Manual compose fallback (digest & urgent-push)

Helper for [`digest.md`](digest.md) and [`urgent-push.md`](urgent-push.md); no `description` frontmatter, so it stays out of discovery. These are the exact selection/format rules `cli.py compose` (`scripts/compose_notification.py`) implements. Use them ONLY when `compose` exits 2 or crashes — compose manually for that run and surface the compose failure (exit code + stderr) in the run's report.

## Selection (both channels)

Parse build-attention `{items: [...]}`:

- **digest**: select items with `notification.action == "include_digest"`.
- **urgent**: select items with `notification.action == "push_urgent"`.

These are work-item deltas, not raw messages. Reply- and memory-aware status is already reflected in `notification` by `build-attention`: include `awaiting_user` / `reopened` items, suppress `awaiting_other_party` / `likely_resolved`. Memory `done` suppresses unless the latest email is newer than the memory update (then it pushes once as reopened with `reason=new_email_after_memory_done`); memory `blocked` suppresses unless urgency escalates, inbound arrives after a user reply, or text explicitly unblocks/approves/adds a deadline; memory `active`/`pending` suppresses static reminders and exposes `memory.next_action` when included.

## Digest message

Group by `category` (ingest-schema order: Personal, Work, Project, Finance, Travel, Calendar, Newsletter, Promotion, System, Social, Information, Other; empty → Other); within a category sort by `importance_current` (urgent fallback first, then important, then low), then `last_seen_ms` descending:

```text
*Digest <HH:MM>* — N work items
:chart_with_upwards_trend: *example.com|q3-budget* — 7 today vs avg 1.4/day      ← only at 10:00 if any

*Work* (3, 1 needs action)
  • *important* — <From display> — <Subject>
    _<latest_summary>_ — 2 msgs in thread, new since last digest
  • *low* — <From display> — <Subject>
    _<latest_summary>_

*Finance* (2)
  • *important* — <From display> — <Subject>
    _<latest_summary>_
```

Bullet rules: one bullet per selected work item, from `latest_from`, `latest_subject`, `latest_summary`. Append ` — <message_count> msgs in thread, new since last digest` when `message_count > 1`; omit when 1. Append ` — memory next: <next_action>` when `memory.next_action` is present. When `notification.reason == "new_email_after_memory_done"`, label the bullet `*reopened?*` / mention `new email after completed memory`. When an included blocked memory has `memory.blocked_by`, mention `was blocked by <blocked_by>; new email may change blocker`. Category headers read `(N, M needs action)`, dropping `, M needs action` when M = 0.

Anomalies (10:00 slot only): parse `detect-anomalies --json` `{flagged: [...]}`; render each entry as `:chart_with_upwards_trend: *<topic_key>* — <today> today vs avg <mean>/day` directly under the header line.

## Urgent message

Sort by `last_seen_ms` descending; cap at 5 work items; keep the uncapped count for the overflow line. One bullet per work item:

```text
*N urgent in inbox*
• *<Category>* — <From display> — <Subject>
  _<latest_summary>_
• *<Category>* — <From display> — <Subject>
  _<latest_summary>_
…
+ K more urgent in inbox       ← only if selected list was capped
```

`<From display>`: prefer the human-readable portion of `latest_from` (`Boss <boss@example.com>` → `Boss`); fall back to the bare address. Append ` — memory next: <next_action>` when `memory.next_action` is present. When `notification.reason == "new_email_after_memory_done"`, call it `reopened urgent` / mention `new email after completed memory`.

## Stamp payload

Pipe exactly the included (digest) / pushed, i.e. capped (urgent) work-item objects into `stamp-notifications --input -`:

```json
{
  "channel": "digest",
  "items": [
    {
      "item_key": "thread:work:...",
      "current_fingerprint": "sha1:...",
      "importance_current": "important",
      "status": "open",
      "last_seen_ms": 1776936543000,
      "message_ids": ["msg1", "msg2"]
    }
  ]
}
```

An anomaly-only digest stamps an empty `items` list on push success. The helper updates `notification_ledger[item_key]` and fills empty `messages[mid].pushed.<channel>` markers, preserving existing marker values. The ledger may have been seeded from legacy `pushed.digest` / `pushed.urgent` markers by `backfill-notifications` (`cli.py backfill-notifications --dry-run --json` is a rollout diagnostic only).

## Run summaries

- digest: `SUMMARY: digested N work items (cat=Work:3,Finance:2; anomalies=K)`; empty selection and no anomalies → `SUMMARY: empty digest`; missing state → `SUMMARY: no state yet`.
- urgent: `SUMMARY: pushed N urgent (cap=5)`; empty selection → `SUMMARY: 0 urgent`.
