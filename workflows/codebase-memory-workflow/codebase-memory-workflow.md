---
trigger: "Where is X defined", "who calls X", "what would this change impact", "what changed since <ref>" — any structural question on a codebase that has `codebase-memory-mcp` (https://github.com/DeusData/codebase-memory-mcp) available. Not for editing files, and not a substitute for reading the real file before you change it.
---

## Trigger

A structural question about a codebase — "where is X defined", "who calls X" / "what does X call", "what would changing this impact", "what changed since `<ref>`", "give me the shape of this repo" — when `codebase-memory-mcp` is installed and the repo has been indexed. This is `../investigate/investigate.md`'s cheaper first move for exactly these questions, not a replacement for it: still read the actual file/lines before editing anything based on what the graph says.

## Goal

The structural question is answered from the indexed knowledge graph — one or two tool calls, no multi-file Glob/Grep/Read sweep — and, whenever the answer is actually going to be acted on rather than just used to orient, the index has been confirmed to reflect the current working tree before it's trusted.

## Context

**Setup, once per machine.** Install (`npm install -g codebase-memory-mcp`, a platform package manager, or the prebuilt binary — see the project's own install docs); `codebase-memory-mcp install` self-registers it into whichever MCP-compatible harness you're running (Claude Code, Codex CLI, and 40+ others are auto-detected). No daemon required — it runs as an MCP server over stdio, or as a one-shot CLI.

**Setup, once per repo/clone.** Index before first use, and again after pulling changes made outside this session (a background watcher keeps it in sync with edits made *during* a session, but that doesn't survive a fresh clone or a pull):

```
index_repository(repo_path="<absolute path to the repo root>")
```

The path must be absolute — a relative path fails.

**Tool-to-question map** (validated against this repo — `home-user-ai-workflows`, 2750 nodes / 11050 edges on the first index):

| Question | Tool |
|---|---|
| Where is X defined / show me its source | `search_graph` (name/label/file pattern) or `get_code_snippet` (exact source, optionally with neighbors) |
| Who calls X / what does X call | `trace_path` (`direction`: `inbound`=callers, `outbound`=callees, `both`) |
| What would this diff/commit impact | `detect_changes` (`--since <ref>`, `direction inbound` = blast radius of callers) — also the staleness check, see Constraints |
| Shape of the codebase (entry points, hotspots, layers, clusters, package fan-in/out) | `get_architecture` |
| Free-text / fuzzy search across files | `search_code` |
| Anything not covered above | `get_graph_schema` first (real node/edge types), then `query_graph` (read-only Cypher-like) |
| Is the index actually covering this repo | `index_status` / `check_index_coverage` |

**One-off use outside an MCP client.** `codebase-memory-mcp cli <tool> --flag value` (or pipe JSON on stdin) works from a plain shell or a script — run `cli <tool> --help` for its exact flags; passing raw JSON as a single argument still works but is deprecated. As an MCP server: `codebase-memory-mcp` with no arguments (stdio).

## Constraints

- Never trust the graph over the actual file for anything you're about to edit — it's a locator/navigator, not a source of truth for content. Read the real file and lines before writing a change based on what it returned.
- The graph goes stale the moment anyone edits after the last index — including mid-session edits by a teammate or a parallel process. `detect_changes --since <last known-good ref>` (or a re-index) is the staleness check; run it before relying on the graph for anything you're about to act on, not only once at session start.
- Never commit the local graph store to the repo: it's regenerable, environment-specific, and goes stale the moment someone else's commit lands — regenerate per clone/environment instead of syncing it through git. The tool's own optional "commit a compressed `.codebase-memory/graph.db.zst` snapshot so teammates skip reindexing" convenience is declined here for the same reason (`.gitignore` blocks it).
- Falls back silently, never blocks: if the binary isn't installed or the repo isn't indexed, that's not a blocker — fall back to `../investigate/investigate.md`'s normal Grep/Read approach and move on. Never stop a task to install this unprompted.

## Verify

- The answer cites a real qualified name, file path, and line range the graph actually returned — not a paraphrase.
- If the answer was acted on (not just used to orient), a `detect_changes --since <ref>` (or a re-index) confirmed the graph reflected the current `HEAD` before it was trusted.
