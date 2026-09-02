# goal.md draft template — goal-authoring

Helper for [`goal-authoring.md`](goal-authoring.md). Copy the block below into `$HD/goal.md`, replace every `<...>` placeholder from `$HD/record.md` and the [`extraction-guide.md`](extraction-guide.md) pass, then show it to the user and pause for approval (the **goal approval gate** in [`../casper/casper.md`](../casper/casper.md)).

````markdown
## Goal
<the complete desired outcome, derived from record.md, plus any constraints
the record or the user stated>

## Acceptance Criteria
1. <criterion derived from an explicit DoD/checklist item, or the smallest
   observable end-state the record supports>

## Verification
1. command (timeout=300)
   ```bash
   <command whose exit 0 proves the criterion>
   ```
````

## Contract rules baked into this template

These come from `casper_verify.py`'s parser, not from this workflow's opinion — violating them fails silently at verify time instead of at drafting time:

- Acceptance Criteria and Verification are both numbered lists, must be the same length, and are matched by position — criterion *N* is proved by verification item *N*.
- Every verification item must start with `command`/`[command]` or `judgment`/`[judgment]`; anything else fails to parse.
- Keep judgment items to at most 2 per goal — use `judgment: <inspection instruction>` only when no command or deterministic file/state check can decide the criterion (see `extraction-guide.md`'s sizing section).
- Verification commands must NOT use heredocs (`<<'EOF'`): the verifier's command extraction is indentation-hostile and a mangled terminator makes the criterion fail without ever running. For a per-item loop, define an inline function and call it once per item (`chk() { ...; }` then `chk <arg>` lines) instead.
- Give each `command` a `timeout=` sized to what it actually does — the harness default is 300 seconds; a real build/test/deploy check needs more, stated explicitly on that item.

## Tailoring notes

- **No natural command exists for a criterion** (e.g. "the reply reads professionally", "legal's confirmation is genuine") → `judgment: <inspection instruction>`, within the goal-wide cap of 2.
- **The record bundles more than one distinct ask** → split into multiple goals (separate `$HD` handovers), not one goal with unrelated criteria stapled together.
- **The record's done-condition is genuinely absent or contradictory** → this is a pause-and-ask to the user before drafting continues (`goal-authoring.md`'s Constraints), not a guess folded into the goal.
- **The downstream workflow has its own detector/inventory instead of a prose record** (e.g. `dead-code-cleanup`) → this template still governs the goal.md *shape* and the contract rules above; the workflow's own template supplies the payload-specific placeholders (ids, protected paths, gate commands) this generic one has no way to know.
