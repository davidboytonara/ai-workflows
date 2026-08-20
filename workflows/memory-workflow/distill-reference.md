# Distill reference — extraction patterns, writer contract, state shape

Companion to [`distill-memory.md`](distill-memory.md): the binding policy (caps, skip rules, canonical phrasing, abort rules) lives there under **Constraints**; this file holds the attribute definitions, extraction tables, the exact writer invocations, and the JSON shapes.

## Memory attributes

`memory_type`: `rule | fact | workflow | open | finding`. `scope`: `global` (applies across all work), `project:<slug>` (lowercase kebab, infer from `cwd` basename or conversation topic), `repo:<slug>`, or `ephemeral` (pair with `--expires`). `tags`: 2–5 lowercase categorical labels (filterable via `--tag`). `keywords`: 5–15 free-form specific terms from the body — file paths, symbols, domain concepts, alt-spellings (boost `--query` ranking only; not filterable). `body`: canonical third-person sentence (`"I hate long preambles"` → `User dislikes long preambles in assistant responses`). `expires`: ISO date, volatile memories only. `open` memories also carry optional task fields (`status`, `priority`, `scheduled`, `due`, `started`, `next_action`, `blocked_by`, `related`) — see **Open-item fields**.

## High-signal patterns

Sweep each review file for these five patterns before reaching for the type table — they are the most reliable sources of memory-worthy content.

| Pattern | Maps to | Scan trigger in review dump |
|---|---|---|
| **Correction-then-success** (highest signal — the corrective content reveals a constraint the user never stated upfront, so treat it as stronger than an explicit "I prefer X", which can be a one-off) | usually `rule`, sometimes `fact` | User turn rejects/corrects an assistant output, assistant revises, and a later user turn accepts without further correction. Extract the *corrective content*, generalized into a durable preference/constraint. |
| **Clarification response** | usually `fact`, sometimes `rule` | Assistant asks a clarifying question, user reveals stable environment/tooling/team context. Extract only if durable across sessions — skip session-specific answers ("the file from yesterday's email"). |
| **Explicit preference / constraint** | `rule` | Direct user statements: "I always X", "don't suggest Y — we can't use it", "we've decided to go with Z", "use metric units". |
| **Stable user-world fact** | `fact` | Durable role/org/team/tooling identity, stated as ongoing not transient. |
| **Methodology / mental model** | `rule` or `workflow` | User names a framework or decision process they apply: "I use OKRs for planning", "we follow trunk-based development", "my approach to incidents is the 5-whys". |

## Type-by-type capture rules

| Type | Capture | Skip |
|---|---|---|
| **rule** | Stated preferences, prohibitions, anti-patterns ("never X", "I prefer Y") — from **user** blocks. Also **silent confirmations**: assistant proposed a non-obvious approach (unusual choice, judgment call, deviation from default) and the next user turn accepts without pushback (affirmation, "ok", topic shift, follow-up that builds on it). Body: third-person rule + **Why:** "validated by user acceptance after assistant proposed it." | One-off stylistic asks inside a single task. Trivial/obvious approaches accepted by default — bar: would another reasonable assistant have made a different choice? If no, skip. |
| **fact** | Durable facts about user/projects/setup ("we use X", "team size is N") — from **user** blocks | Ephemeral numbers, task-specific context |
| **workflow** | Process habits, collaboration patterns ("always squash-merge") — from **user** blocks | Single-use commands |
| **open** | Active tasks / unresolved follow-ups / scheduled work — from **user** blocks. Capture status, priority, scheduled date, deadline (`due`), next concrete step, blocker, and links to related findings, so a later session can answer "what am I working on?" without re-reading the session. Fields: **Open-item fields** below. | Things already resolved in that session; one-off subtasks inside a single workstream |
| **finding** | LLM-synthesized facts about code/infra surfaced during exploration — from **assistant** blocks. Capture file paths, function signatures, architecture notes, bug root causes, API contracts, config locations. Third-person, concrete, anchored to a file/symbol when possible. | Raw tool output pasted verbatim; narration ("let me check X"); task-progress statements; elided `…[+N chars elided]` fragments |

Anchor findings: prefer bodies referencing a real path or symbol (`"write_memory.py exposes write_memory() returning {status, path} JSON"` over `"the writer uses JSON"`).

Keywords example for a finding about `services/backend-api/src/portfolio_price_updater.py`: `portfolio_price_updater, price-updater, services/backend-api, portfolio, price, updater, backend, snapshot`.

## Acid test (binding-essential)

Applied silently to each candidate **before** invoking the writer. If the candidate sentence could appear in a Wikipedia article *without naming the user, their project, or their entities*, **skip it**. The valuable unit is the *binding* between the user/entity and the fact — not the fact alone. Removing the entity reference should make the sentence meaningless or generic; that loss of meaning is the signal to capture.

- `Python uses indentation for block structure.` → fail (no binding).
- `User's <project-slug> project uses 4-space indentation enforced by ruff.` → pass (binding to `<project-slug>` is load-bearing).
- `User prefers merge over rebase for the <repo-slug> repo to preserve audit trail.` → pass (binding + reason).

Then confirm all three: **future usefulness** (still useful surfaced 3+ months out), **non-redundant with training** (not already known to the consuming LLM), **non-transient** (not session-specific or one-off). Any false → skip.

For `finding` candidates, swap the binding subject from "user" to the project/repo in the scope — a finding about `services/backend-api/src/database.py` binds to `<project-slug>`, not to a generic Python codebase.

A candidate that fails is skipped — log a `skipped_reasons` entry with `reason: "failed-acid-test-or-calibration"` plus a one-phrase note (e.g. `acid: too-generic`, `calibration: transient`).

## Open-item fields

`open` memories are the personal-assistant task store. All fields below are optional — set only when the user's words support them; do not invent.

| Field | Values | Extract when |
|---|---|---|
| `status` | `pending` (default if absent) \| `active` \| `blocked` \| `done` | `active` if user says "I'm currently working on X", "in the middle of Y". `blocked` if user reports a blocker ("waiting on Z", "stuck because W"). `done` if user closes the loop ("finished", "shipped", "merged"). Otherwise omit. |
| `priority` | `high` \| `normal` (default) \| `low` | `high` from explicit urgency: "P0", "ASAP", "blocking release", "before Friday demo". `low` from de-prioritization: "nice to have", "eventually", "when there's time". |
| `scheduled` | ISO `YYYY-MM-DD` | User states a planned start: "I'll tackle this Monday", "starting next sprint". Resolve relative dates against `currentDate` from session frontmatter. Omit if vague. |
| `due` | ISO `YYYY-MM-DD` | Hard deadline. "by Thursday", "EOM" → absolute ISO date. **Must be ≥ `scheduled` if both set.** Distinct from `expires` (memory archival). |
| `started` | ISO `YYYY-MM-DD` | User says they began ("started on Monday"). Auto-filled to today by the writer when `--status active` is passed without `--started`. |
| `next_action` | one short sentence | Concrete next step, third person. From "next I need to Y". Critical for resume-without-re-deriving. |
| `blocked_by` | one short sentence | Required when `status: blocked`. The actual blocker, not a generic "waiting". |
| `related` | list of memory file slugs | Cross-link to findings/rules from the same session that give context. Slug = filename without `.md`. The doctor lints these for resolvability. |

Scope for open items: project-scoped when tied to a codebase/domain (`project:<cwd-basename-slug>`), repo-scoped for repo-only tasks, ephemeral when expiring soon, global only for cross-project personal todos.

## Writer invocations

Non-finding, non-open memories:

```bash
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/write_memory.py" \
  --memory-type <rule|fact|workflow> \
  --scope <scope> \
  --tags "<categorical csv>" \
  --keywords "<free-form csv>" \
  --body "<canonical statement>" \
  [--expires YYYY-MM-DD]
```

Open / active-task memories (pass any subset of the **Open-item fields** above):

```bash
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/write_memory.py" \
  --memory-type open \
  --scope "project:<slug>" \
  --tags "infra,security" \
  --keywords "slack-webhook,rotation,credentials" \
  --status active \
  --priority high \
  --scheduled 2026-04-28 \
  --due 2026-05-02 \
  --next-action "Generate new webhook URL in Slack admin and update <APP>_SLACK_WEBHOOK_URL env" \
  --related "finding-slack-webhook-leak-abc123" \
  --body "User is rotating the Slack incoming webhook after the URL leaked into chat logs"
```

Finding memories (do **not** pass `--allow-dup` — the writer's 0.85 `finding` threshold handles append-with-dedup automatically):

```bash
"$HOME/.agents/.venv/bin/python" "$HOME/.agents/workflows/memory-workflow/write_memory.py" \
  --memory-type finding \
  --scope "project:<cwd-basename-slug>" \
  --tags "<csv from fixed vocab>" \
  --keywords "<file paths, symbols, concepts csv>" \
  --body "<canonical, file/symbol-anchored statement>"
```

Parse the JSON response.

## Writer response handling

| status | Action |
|---|---|
| `written` | Log path, continue |
| `near_dup` | Read each match path. If same idea → skip (add `near-dup same idea` or `obvious duplicate` to `skipped_reasons`). If superseded → delete the old file, re-run with `--force`. If distinct nuance worth keeping → re-run with `--allow-dup`. **Finding-specific:** if any match shares the same file/symbol anchor AND says essentially the same thing, skip; re-run with `--allow-dup` only if the distinction is concrete and named. |
| `conflict` | File exists at target path with different body. Read it, then either rename (tweak `body` wording → new slug) or `--force` overwrite. If skipped, add `writer error/conflict` to `skipped_reasons`. (Findings use a hash-suffixed filename, so true conflicts are rare.) |
| `error` | Log candidate + error, skip; add `writer error/conflict` to `skipped_reasons` |

## skipped_reasons entries

For every skipped candidate, append one item for that review file:

```json
{"type":"finding","candidate":"short candidate text or anchor","reason":"near-dup same idea"}
```

Keep `candidate` concise but auditable (candidate text, type, and file/symbol anchor when relevant). Closed `reason` vocabulary: `obvious duplicate`, `near-dup same idea`, `not durable/task-specific`, `stale/resolved open item`, `derivable/documented elsewhere`, `unsupported/unsafe/uncertain candidate`, `writer error/conflict`, `failed-acid-test-or-calibration` (see **Acid test**).

## State-file shape

`$HOME/.agents/state/memory-distill/distill_memories.json`:

```json
{
  "$HOME/.agents/memory/review/pi/.../abc.md": {
    "size": 12345,
    "mtime_ns": 1713300000000000000,
    "processed_at": "2026-04-17T10:00:00Z",
    "candidates_written": 3,
    "candidates_skipped": 2,
    "skipped_reasons": [
      {
        "type": "finding",
        "candidate": "write_memory.py duplicate threshold behavior",
        "reason": "near-dup same idea"
      },
      {
        "type": "open",
        "candidate": "revisit temporary debugging task",
        "reason": "not durable/task-specific"
      }
    ],
    "candidates_written_by_type": {
      "rule": 1,
      "fact": 0,
      "workflow": 0,
      "open": 0,
      "finding": 2
    }
  }
}
```

A review file is **unprocessed** if its path is not in state or its `size`/`mtime_ns` differ. `candidates_skipped` must equal `len(skipped_reasons)` for the review entry, and every state write must be atomic (write to `.tmp`, rename). `distill_state.py` owns all of this; hand-edit the state only as the fallback when the script itself fails.
