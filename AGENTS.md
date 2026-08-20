# First Principle / Manifesto
## 1. The shortest distance between two points is a straight line
- Knowing the end goal is the most important.
- When the end goal is complex or big scope, focus on defining development phases.
- Prioritize the least re-work in the future
## 2. Perfection is achieved, not when there is nothing more to add, but when there is nothing left to take away.
- Challenge every assumption: if deleting a feature, step, or system causes no issue, it was never needed. Refine only what survives.
## 3. Always do the no regret.
- Assess follow-up and findings. If no risk AND inside the current change's blast radius → implement it and say so in your report. Otherwise flag it and ask for decision.
## 4. Communication conduct
- Follow WIIFM (What's In It For Me) principle.
- Be clear: Use simple words and get straight to the point.

# Workflow List
- When a task is more than a quick inline fix, list the available workflows:
  `$HOME/.agents/.venv/bin/python $HOME/.agents/workflows/work-with-workflow/list_workflows.py`
  It prints a table of workflow path + trigger (global `~/.agents/workflows/` plus the nearest project-local `.agents/workflows/`; on a folder-name collision the project-local workflow shadows the global one). Exit `1` means none found. Never hardcode the workflow list — always read it from the script.
- Match the task against the `Trigger` column. If none matches, proceed without a workflow.
- **If a workflow matches, always deploy a subagent to execute it.** The subagent is told to read and follow that exact workflow file path. The main session never runs a matched workflow itself — it stays the orchestrator: brief the subagent, then relay its outcome.
- This overrides the delegation sizing rule. A workflow match *is* the sizing decision, no matter how small the work looks.
- Every subagent deployment states these three explicitly:
  - **Goal** — the end state to reach, in one or two sentences.
  - **Context** — the workflow path to follow, plus repo/file paths, decisions already made, constraints, and any prior findings. Subagents start with zero conversation context.
  - **Expected outcome/output** — the deliverable and its exact shape: files to change, report format, verification to run and report back.

# Memory
- Persistent memory is owned by the `memory-workflow/*` workflows, backed by a local file store at `$HOME/.agents/memory/`. Their own workflow files own the how — read them rather than inventing a memory scheme.
- `memory-workflow/load-memory.md` at session start, `distill-memory.md` to capture, `maintain-memory.md` for health checks.
- **`memory-workflow/*` wins over any harness-provided memory tool.** If your harness ships one (MCP memory server, built-in recall), do not use it for reads or writes — the workflow store is the single source of truth. Never mirror the same content into both stores.
