---
description: Pull unprocessed inbox messages, classify them, apply Casper/* Gmail labels, and persist state. Invoked every 15 minutes by the heartbeat daemon (07:00–23:45 your local timezone).
---

## Trigger

Not user-invoked: the heartbeat daemon runs this as the `gmail-ingest` scheduled task every 15 minutes, 07:00–23:45 your local timezone.

## Goal

The shared state file `~/.agents/state/gmail-ingest/state.json` is up to date with the last 30 days of inbox for the **work** account: every new message classified, labeled, and recorded in state.

## Context

**CLI base**: `$HOME/.agents/.venv/bin/python "$HOME/.agents/workflows/gmail-workflow/cli.py"`. Account `work`, max age 30 days. **Per-run cap**: 50 messages, enforced by `list_unprocessed.py`.

**Listing:**

```bash
$HOME/.agents/.venv/bin/python "$HOME/.agents/workflows/gmail-workflow/cli.py" \
  list-unprocessed --account work --max-age-days 30 --json
```

Stdout is JSON `{messages: [...]}`. The script reads the state file and skips Gmail message IDs already in `state.messages`, so already-classified emails are not re-processed. An auth/scope failure shows `insufficient_scope`, `invalid_grant`, or `403`.

**Classification schema** — each message gets all six fields below. LLM needed because categorizing free-text email content cannot be enumerated in code.

Category (pick exactly one):

| Category | Use when |
|---|---|
| **Personal** | Friends, family, non-work humans |
| **Work** | Colleagues, customers, vendors, clients |
| **Project** | Specific named project, side project, or named initiative |
| **Finance** | Banking, invoices, receipts, taxes, payments |
| **Travel** | Bookings, itineraries, boarding passes, hotel/airline confirmations |
| **Calendar** | Calendar invites, reschedules, RSVPs, meeting recaps |
| **Newsletter** | Subscribed periodic content (substack, blog digests, industry newsletters) |
| **Promotion** | Marketing, deals, sales, retargeting |
| **System** | Platform notifications, security alerts, password resets, GitHub/CI auto-emails |
| **Social** | LinkedIn, Twitter, Facebook, social media notifications |
| **Information** | Reference material that isn't a newsletter (docs, KB updates, internal memos) |
| **Other** | Genuine escape hatch — use sparingly |

Urgency and Importance are two **independent** axes (Eisenhower matrix) — pick one value from each, not one combined value:

| Urgency | Use when |
|---|---|
| **urgent** | Needs a response or decision within hours. Signals: explicit deadline language ("today", "EOD", "ASAP", "by Friday"), a directly-addressed ask from a person, a security alert, a customer escalation. |
| **not_urgent** | No same-day time pressure, even if it eventually matters. |

| Importance | Use when |
|---|---|
| **important** | Has real business or personal stakes — worth your attention regardless of timing. |
| **not_important** | Low stakes either way — newsletters, FYI cc's, promos, automated notifications without action. |

The pair collapses into one quadrant, applied as the `Casper/<Quadrant>` label and used for notification routing: `urgent`+`important` → **do_now** (pushed immediately); `urgent`+`not_important` → **delegate** (time-pressured but low-stakes — digest only, never an interrupt); `not_urgent`+`important` → **schedule** (digest); `not_urgent`+`not_important` → **eliminate** (digest, lowest priority). This is the common failure mode of a single "importance" field: an urgent-but-trivial message (delegate) used to get treated the same as a genuinely important one — splitting the axes is what makes `urgent`+`not_important` route to the digest instead of interrupting you.

`needs_action`: boolean — the message demands a reply, decision, or task from the user. Independent of both urgency and importance (a `not_important` message can still need action, e.g. RSVP to a low-stakes invite).

`topic_key`: stable slug `<from_domain>|<topic-slug>`, lowercase kebab (e.g. `q3-budget`, `incident`, `invoice`, `1on1-prep`, `roadmap`, `pr-review`). Empty string if no clear topic.

`summary`: ≤120-char one-line synopsis. Third-person, present tense. No filler.

**Bodies.** The `snippet` field gives ~200 chars. When that is not enough to classify confidently:

```bash
$HOME/.agents/.venv/bin/python "$HOME/.agents/workflows/gmail-workflow/cli.py" \
  fetch-bodies --ids <id1>,<id2> --account work --json
```

**Applying** — pipe a JSON array of entries (original metadata plus the classification fields) into:

```bash
echo '<json-array>' | $HOME/.agents/.venv/bin/python "$HOME/.agents/workflows/gmail-workflow/cli.py" \
  apply-classifications --input -
```

Idempotent: state is keyed by Gmail message id; a successful run adds the `Casper/Processed` Gmail label plus a `state.messages[<id>]` record — the two markers that prevent re-processing on later runs.

**Blocker file.** On a blocker, write `~/.agents/state/clarify/gmail-ingest-<runid>.md` containing exactly two markdown h2 headings: `## Task question`, followed by one sentence describing exactly what is blocking you, then an empty `## User reply:` section — and exit 42. The daemon pauses the task until the user fills in `## User reply:`, then resumes it with the answer appended.

## Constraints

- Empty batch → print `SUMMARY: 0 new messages` and exit 0.
- A blocker (auth/scope error, quota exceeded, ambiguous account state, an unclassifiable oversized message) → write the clarify file and exit 42. Never invent classifications or guess past blockers — halt cleanly rather than corrupt the state file.
- Cap fetched bodies at 10/run to bound runtime.
- If `GMAIL_SUMMARIZER_DRY_RUN=true`, pass `--dry-run` to `apply-classifications` (skips Gmail label calls and state writes).
- Every run ends with one line for the heartbeat history: `SUMMARY: classified N (D do_now, G delegate, S schedule, X eliminate, A needs-action, E errors)`.

## Verify

```bash
# Classified ids are recorded in state (count grows across runs)
$HOME/.agents/.venv/bin/python -c "import json,pathlib; s=json.loads(pathlib.Path.home().joinpath('.agents/state/gmail-ingest/state.json').read_text()); print(len(s['messages']))"

# A re-run lists none of the just-processed ids (empty messages -> SUMMARY: 0 new messages)
$HOME/.agents/.venv/bin/python "$HOME/.agents/workflows/gmail-workflow/cli.py" \
  list-unprocessed --account work --max-age-days 30 --json
```

The `SUMMARY:` line printed matches the counts actually applied.
