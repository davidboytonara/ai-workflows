---
trigger: Create, add, edit, update, rename, or delete a workflow, or convert one to the five-field format — any change to files under a workflows/<folder>/.
---

## Trigger

"Create a workflow for X", "add / update / edit a workflow", "rename that workflow", "delete / remove a workflow", "convert a workflow to the new format" — any change to files under a `workflows/<folder>/`.

## Goal

The workflow folder reaches the requested state (created, edited, renamed, or deleted), conforms to the five-field standard and the conventions below, and passes every check in Verify.

## Context

**The five-field standard.** Every workflow file is exactly five sections; this file is the reference example.

1. **Trigger** — when the workflow applies, in the user's own words and phrases; the frontmatter `trigger` is a <=170-char distillation of it, and together they feed discovery.
2. **Goal** — the end state, one or two sentences.
3. **Context** — only non-derivable knowledge: environment quirks, hard-won lessons, what each bundled file does. No mechanical how-to steps — the model derives those.
4. **Constraints** — prohibitions, unskippable process rules, scope limits, and approval gates (decisions that belong to the user).
5. **Verify** — how to prove it worked, as exact commands.

When converting or editing an older step-based workflow, sort rather than delete: mechanical how → drop; lesson or institutional knowledge → Context; policy or rule → Constraints; verification → Verify.

**Agent invocation.** Two routes, both harness-agnostic. In-session delegation uses the hosting harness's own subagent tool, so the same workflow works under any harness. Everything else — headless or programmatic model calls — goes through `workflows/casper/LLM_harness.sh`: it takes a model alias plus effort/stopwatch/context budgets and routes to whichever CLI backs that model (`claude -p`, `pi -p`, guards). Naming a provider CLI directly hard-wires a workflow to one harness and loses the timeout, context, and stall guards.

**Model and effort.** Frontmatter may optionally carry `model` and `effort`: the model alias (per `LLM_harness.sh --list-models`) and effort level to use for the workflow's LLM steps. Omitted means the harness defaults apply (driver-derived model; `medium` effort, `high` for GPT 5.6 Sol — see `workflows/casper/models-and-guards.md`). The create gate asks for them; leaving them unset is the normal answer.

**Discovery.** Each workflow owns `workflows/<folder>/`; the primary `.md` may be named differently from the folder, and one folder may hold several discoverable files (`*.md` and `*/*.md`). Discovery (`list_workflows.py`, bundled here) lists `.md` files carrying a `trigger` frontmatter key — `description` is no longer read — from the global `~/.agents/workflows/` plus the nearest project-local `.agents/workflows/` found by walking up from the working directory (`.casper/workflows/` is no longer scanned). Project beats global: when a project-local workflow *folder* name equals a global folder name, the project-local entries win and the global folder is not listed. Helper `.md` files omit `trigger` unless they should appear in discovery.

**Shared runtimes.** Python runs via `$HOME/.agents/.venv/bin/python`; TypeScript via `$HOME/.agents/node_modules/.bin/tsx` (single root `package.json`, `tsx` pinned). Bootstrap snippets and the migration path away from stray local environments: [`runtimes.md`](runtimes.md).

**Scripts.** A script used by one workflow lives in that workflow's folder; scripts shared by several live in `workflows/scripts/`. Both resolve `REPO_ROOT` two levels up (`Path(__file__).resolve().parents[2]` / `path.resolve(__dirname, "..", "..")`). Document exit codes; convention: `0` success, `1` nothing to do / no matches, `2` usage error.

**Rename lesson.** After a rename, hard-coded paths inside scripts break silently — update every reference to the old folder and file names, scripts included.

## Constraints

- Every workflow you create or edit ends up in the five-field format above. Frontmatter contains `trigger` (required, <=170 characters) plus optionally `model` and `effort`; nothing else.
- Prefer deterministic scripts. Decision order per step: Python script → one-line shell → LLM step. If you can articulate the rule in code, the step is deterministic — script it. Every surviving LLM step carries a one-line `LLM needed because <X>` rationale in the workflow file; when editing, convert existing LLM steps to scripts wherever the rule can now be enumerated.
- Once an LLM step is genuinely needed, delegate research, scans, and verbose output to a subagent; keep small edits and values the next step needs inline.
- In-session delegation runs through the subagent tool of whichever harness is hosting the session — name the tool generically ("delegate to a subagent"), never a harness-specific tool name or CLI.
- Every other deployment of an AI agent — any headless or programmatic model call in a workflow step or a workflow script — goes through `$HOME/.agents/workflows/casper/LLM_harness.sh`. Never invoke `claude -p`, `pi -p`, another provider CLI, or a provider SDK directly.
- Never create workflow-local `.venv` or `node_modules`; use the shared runtimes only.
- Create gate: ask clarifying questions and do not start building until goal, trigger, and the script-vs-LLM split are clear; also ask whether the workflow needs a specific `model`/`effort` (default: unset).
- Delete a workflow only on explicit user request.
- Primary workflow file stays under 8000 characters; split helper files if needed. Do not register workflows in AGENTS.md.

## Verify

```bash
PY="$HOME/.agents/.venv/bin/python"
[ -x "$PY" ] || python3 -m venv "$HOME/.agents/.venv"

# Discovery reflects the change (created/edited appears; deleted is gone)
"$PY" "$HOME/.agents/workflows/work-with-workflow/list_workflows.py"

# Frontmatter holds trigger (required) and at most optional model/effort
awk '/^---$/{n++; next} n==1' "$HOME/.agents/workflows/<folder>/<workflow>.md" | grep -vE '^(trigger|model|effort):' && echo "UNEXPECTED FRONTMATTER KEY" || true

# trigger is at most 170 characters
awk '/^---$/{n++; next} n==1 && /^trigger:/ {sub(/^trigger:[[:space:]]*/, ""); gsub(/^["'"'"']|["'"'"']$/, ""); if (length($0) > 170) print "TRIGGER TOO LONG: " length($0)}' "$HOME/.agents/workflows/<folder>/<workflow>.md"

# Any created or modified script still runs
"$PY" "$HOME/.agents/workflows/<folder>/<script>.py" --help
"$HOME/.agents/node_modules/.bin/tsx" --version   # if a .ts script changed

# No scattered deps under workflows/ (shared venv/node_modules live in $HOME/.agents)
find "$HOME/.agents/workflows" -type d \( -name .venv -o -name node_modules \) -print

# Every LLM/subagent mention sits near an "LLM needed because ..." rationale
grep -nE "subagent|claude --print|sub-agent|LLM" "$HOME/.agents/workflows/<folder>/<workflow>.md" || true

# No agent deployed outside the harness (expect no hits)
grep -rnE '(^|[^_/[:alnum:]])(claude|pi)[[:space:]]+(-p|--print)([[:space:]]|$)' "$HOME/.agents/workflows/<folder>/" || true
```
