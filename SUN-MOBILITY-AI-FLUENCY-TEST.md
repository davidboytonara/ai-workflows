# SUN Mobility AI-Native Fluency Test — Findings

**Candidate:** David Boy Tonara
**Repo under test:** [`frgunawan82/ai-workflows`](https://github.com/frgunawan82/ai-workflows)
**Prompt:** clone the repo, find use cases for professional & personal life, suggest improvements. No fixed spec — the exercise evaluates AI fluency and creative problem-solving, not a specific deliverable.

---

## 1. What the repo actually is

`ai-workflows` is a library of reusable, harness-agnostic Markdown workflow files (installed to `~/.agents/workflows/`) that any AI CLI (Claude Code, Codex, Pi, OpenCode) can read and follow. Each workflow defines a **trigger**, a **goal / end-state**, and a **verification method** — and is kept cheap on context because only the one matching workflow file is loaded per task (via `list_workflows.py`), never the whole library.

Notable workflows inspected:

| Workflow | Purpose |
|---|---|
| `casper` | Autonomous coding-agent orchestration: plan → execute → verify, gated by human approval |
| `clickup-workflow` | Pull open/assigned ClickUp tasks |
| `gmail-workflow` | Ingest, classify, digest, and draft-reply to Gmail |
| `gsheet` / `gdocs` / `gslides-workflow` | Google Workspace automation |
| `heartbeat` | systemd-based recurring scheduler (Linux only) |
| `notebooklm-workflow` | Document ingestion + report/mind-map/data-table generation via an unofficial NotebookLM client |
| `dead-code-cleanup` / `dead-test-cleanup` | Detect and (with vetting) remove unused code/tests |
| `specs-optimization` | Read-only "probe" agents audit a doc corpus for AI-navigability |
| `memory-workflow` | Distill session transcripts into durable, tagged memory notes |
| `playwright` / `kernel-browser` | Browser automation |

## 2. Security review (completed before use)

Inspected `install.sh`, every Python/shell/TS script, `.env.example` / `.config.example`, and `.gitignore`. Result: **clean**.

- No remote code execution, no `curl \| bash`, no obfuscated payloads.
- No hardcoded secrets; templates ship empty.
- No unexpected outbound URLs (only Google APIs + test fixtures).
- `.gitignore` thoroughly blocks credentials/tokens/sessions/logs.
- `CREDENTIALS.md` files are setup docs only, not real secrets.
- **Caveat:** `casper_verify.py` and `heartbeat/runner.py` use `subprocess(shell=True)` — this runs user/agent-defined shell commands with full user permissions. Be deliberate about what commands are allowed on scheduled/autonomous paths, since `heartbeat` runs unattended.

## 3. Use cases

### Professional

1. **Ticket-to-PR pipeline (SWE / Technical PM)**
   `heartbeat` (schedule) → `clickup-workflow` (pull open/assigned tasks) → user authors `goal.md` → `casper` (plan / execute / verify, human-approval gate before execution) → `pull-request` (branch + PR).
   *Gap found:* nothing auto-converts a ticket into `goal.md` — that translation is manual/agent-assisted every time (see improvement #1).

2. **Email triage + drafting**
   `heartbeat` runs `gmail-ingest` (every 15 min, classifies by category incl. Finance / `needs_action` / importance) → `gmail-digest` / `gmail-urgent-push` post Slack summaries on schedule (pure read/format/push, no LLM call, no drafting). Drafting replies is a separate, interactive-only capability (`cli.py draft --reply-to-message-id ...`), guided by ad hoc instructions or a user-authored `playbooks.md` (not shipped). Drafts are **never** auto-sent — they land in Gmail Drafts for manual review/send.
   *Caveat found:* `importance` is a single collapsed field (urgent/important/low), not a true independent urgent×important matrix, even though `needs_action` is explicitly modeled as independent (see improvement #2).

3. **Regulatory document synthesis (Auditor use case — directly maps to my Bank Maluku Malut ITGC engagement)**
   Ingest public regulator PDFs (OJK / POJK / SLIK circulars) via `source_batch.py` → generate a `report` (`briefing-doc` format, downloads as Markdown) or `mind-map` / `data-table` via `generate.py` → convert to PDF as a separate manual step (no native PDF output exists).
   *Explicitly scoped to PUBLIC regulatory text only* — never confidential audit evidence or bank data, which should not route through a third-party/cloud tool (`notebooklm-py` is an unofficial client).

4. **Job-search tracker + cover letters** (personal-professional, relevant to my current transition)
   `gsheet-workflow` (application tracker) + `gdocs-workflow` (tailored cover letters) + `gmail-workflow` (auto-surface recruiter replies).

5. **Engineering hygiene sweep**
   `dead-code-cleanup` / `dead-test-cleanup` — finds unused files/exports/deps, routes through `casper` + the repo's own PR flow. Treats detector output as *evidence only*, requiring explicit vetting before removal.

6. **Meta-audit of internal docs' AI-readiness**
   `specs-optimization` — runs read-only "probe" agents against a doc corpus, mines transcripts for navigation friction, produces a report recommending re-categorization. Directly relevant to SUN Mobility's stated "AI-Native transformation" mission: it audits the documentation substrate the whole transformation depends on.

### Personal

7. **Cross-venture knowledge continuity**
   `memory-workflow` distills session transcripts into durable, tagged memory notes (rules / facts / open items) — useful across many concurrent projects (ZeInvitation, Hermes, mahjong-table venture, palm-oil smallholder services) without re-explaining context each time.

## 4. Improvement suggestions

1. **Missing ticket/record → `goal.md` bridge (highest priority).** There is no generalized way to turn an external record (ticket, email, regulatory finding) into a well-formed `goal.md` with paired acceptance criteria and verification steps. `dead-code-cleanup` already has its own `goal-template.md` — generalize this into a shared "goal-authoring" helper other workflows can call, instead of every workflow re-solving the same translation problem ad hoc.

2. **Gmail importance schema conflates urgency and importance.** Today `importance` is one collapsed field (urgent/important/low). Split it into two independent axes — mirroring how `needs_action` is already modeled independently — to support genuine Eisenhower-matrix triage instead of a single ordinal scale.

3. **No native PDF output anywhere in the doc-generation path.** `notebooklm-workflow`'s `generate.py` only emits md/pptx/csv. This is a real gap for audit/regulatory-style deliverables that expect PDF as the artifact of record.

4. **`heartbeat` scheduling is Linux/systemd-only.** No Windows/macOS equivalent, which blocks the entire scheduled layer (digests, ingests, sweeps) for non-Linux users.

5. **`playbooks.md` (drafting rules) is BYO and barely documented.** Ship an example template so people discover the capability exists and know the expected shape.

6. **Data-sensitivity guidance is generic / one-size-fits-all.** The ToS notice doesn't distinguish "personal data, low stakes" from "regulated-industry data, high stakes." A short decision note (e.g., a checklist: public vs. confidential, regulated vs. not, third-party-tool-eligible vs. not) would help regulated-industry users avoid real compliance mistakes — directly relevant to the `notebooklm-workflow` scoping caveat above.

7. **Casper's approval gate has no structured review surface.** It's currently "show the file, wait" with no diff view or structured accept/reject/edit loop — a real risk of rubber-stamping on repeated use. A structured review step (diff summary + explicit accept/reject/edit per change) would reduce that risk without removing the human gate.

## 5. Why these findings, not others

The exercise asked for AI fluency and creative problem-solving rather than a fixed deliverable, so the approach taken was: (a) actually read the code and scripts rather than the README's marketing description, (b) do an unprompted security pass before recommending any use case involving credentials or scheduled/autonomous execution, and (c) map use cases to genuine current work (audit engagement, job search, personal ventures) rather than generic examples, so the gaps found are gaps that would actually block adoption.
