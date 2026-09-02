# Extraction guide — record to Acceptance Criteria

Helper for [`goal-authoring.md`](goal-authoring.md). How to turn one external record's prose into numbered, independently-verifiable acceptance criteria — before touching [`goal-draft-template.md`](goal-draft-template.md).

## General method

1. **Explicit done-when / definition-of-done statements first.** If the record states "done when X" or has a "Definition of Done" / "Acceptance Criteria" section, use it near-verbatim — one criterion per distinct statement. Do not rephrase away specificity (a date, a number, a named recipient).
2. **Checklist items next.** A `- [ ]` list in the record is almost always already acceptance-criteria-shaped; one checklist item → one criterion, in the record's own order.
3. **Plain narrative last.** For a record that is just a request sentence or paragraph with no explicit DoD, derive the smallest set of externally-observable end-states that make "this is done" true — one per distinct claim in the ask. Never add a criterion the record doesn't support just to make the goal feel more complete; a thin but accurate goal beats a padded one.
4. **Constraints are not criteria.** A record's "don't touch X" or "must ship by Friday" is a constraint in `## Goal`, not a numbered, separately-verified acceptance criterion — fold it into the Goal prose or a Constraints bullet instead of inventing a verification method for it.
5. **Ambiguous or missing DoD → pause, don't guess.** If step 1–3 leave real doubt about what "done" means, that is a stop-and-ask to the user before drafting `goal.md`, not a judgment call to resolve alone — an incorrect guess here becomes a wrong contract the user approves without noticing.

## Per-source-type notes

**ClickUp task** (see [`../clickup-workflow/clickup-workflow.md`](../clickup-workflow/clickup-workflow.md)). A "product story" task already carries `# Context`, `# Objectives`, `# Acceptance Criteria`, `# Constraints` headings — when present, its `# Acceptance Criteria` section IS your source list; use it directly rather than re-deriving from `# Context`. Read the comments too: they often carry scope changes or the real DoD added after the description was written, and can supersede it. A "plain task" (ops/IT items) has no template — fall back to the general method above on its freeform description.

**Gmail message / thread** (see [`../gmail-workflow/gmail-workflow.md`](../gmail-workflow/gmail-workflow.md)). The ask is almost always implicit in a request sentence, not a checklist. Read the full thread, not just the latest message — an earlier message often carries context a later one assumes; a later message can also narrow or change the ask entirely. When the thread's request has changed over time, the record you save to `record.md` and draft from is the ask as it stands in the LATEST message, with earlier messages kept only as supporting context.

**Freeform user ask.** A one-line ask ("look into the renewal ticket") is a pointer to work, not a definition of done, and is not enough by itself to draft acceptance criteria from — paraphrase your understanding of "done" back to the user and get it confirmed before drafting when the ask is under a sentence or two. A multi-sentence ask that already states its own end-state can go straight to step 3 of the general method.

## Sizing verification methods

Prefer `command` over `judgment` for every criterion: a repo test/lint/build command, a file-existence or content check, a `git log`/`git diff` check, an API call whose response proves the state. Use `judgment: <inspection instruction>` only when no deterministic check can decide the criterion (e.g., "the reply reads professionally") — and remember the goal-wide cap of 2 judgment items from `../casper/templates.md`'s contract, carried into [`goal-draft-template.md`](goal-draft-template.md).

## Worked example

Record (ClickUp task, plain freeform description): *"Renewal reminder for the Acme contract needs to go out before it lapses on the 30th. Confirm with legal that the new terms are unchanged before sending."*

Extracted criteria:

1. A renewal reminder referencing the Acme contract's 30th expiry has been sent to the intended recipient.
2. Legal confirmed the new terms are unchanged, and that confirmation is recorded before the reminder was sent.

Criterion 1 verification: `command` — check the sent-mail record (or drafts, if the workflow never auto-sends) for the message. Criterion 2 verification: likely `judgment` (no deterministic check for "legal confirmed X" unless there's a ticket/email to point at) — one of the goal's two allowed judgment items.
