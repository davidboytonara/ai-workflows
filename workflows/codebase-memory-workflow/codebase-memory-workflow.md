---
trigger: "Where is X defined", "who calls X", "what would this change impact", "what changed since <ref>" — any structural question on a codebase that has `codebase-memory-mcp` (https://github.com/DeusData/codebase-memory-mcp) available. Not for editing files, and not a substitute for reading the real file before you change it.
---

## Trigger

A structural question about a codebase — "where is X defined", "who calls X" / "what does X call", "what would changing this impact", "what changed since `<ref>`", "give me the shape of this repo" — when `codebase-memory-mcp` is installed and the repo has been indexed. This is `../investigate/investigate.md`'s cheaper first move for exactly these questions, not a replacement for it: still read the actual file/lines before editing anything based on what the graph says.

## Goal

The structural question is answered from the indexed knowledge graph — one or two tool calls, no multi-file Glob/Grep/Read sweep — and, whenever the answer is actually going to be acted on rather than just used to orient, the index has been confirmed to reflect the current working tree before it's trusted.

## Context

**Setup, once per machine.** Install (`npm install -g codebase-memory-mcp`, a platform package manager, or the prebuilt binary — see the project's own install docs); `codebase-memory-mcp install` self-registers it into whichever MCP-compatible harness you're running (Claude Code, Codex CLI, and 40+ others are auto-detected). No daemon required — it runs as an MCP server over stdio, or as a one-shot CLI.

**Setup, once per repo/clone.** Check for a committed `.codebase-memory/graph.db.zst` first (this repo ships one — see below); if there isn't one, index before first use, and re-index again after pulling changes made outside this session (a background watcher keeps it in sync with edits made *during* a session, but that doesn't survive a fresh clone or a pull):

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

## Committed graph for this repo

This repo commits its own graph at `.codebase-memory/` (`graph.db.zst` + `artifact.json` + `.gitattributes`) so a fresh clone or a fresh cloud session skips the initial index — read it before doing a broad Glob/Grep/Read pass on this repo, and edit only the files the graph says are actually involved.

- **Staleness check, always first.** `.codebase-memory/artifact.json`'s `commit` field is the exact commit the graph was built from. Compare it to the current `HEAD`:
  ```bash
  git -C <repo> log -1 --format=%H   # current HEAD
  cat <repo>/.codebase-memory/artifact.json   # .commit field
  ```
  Equal → trust the graph as-is. Different → run `detect_changes --since <artifact.json's commit>` first; its `impacted` set is what the graph doesn't yet know about — treat those files/symbols as ungraphed and fall back to Read/Grep for them specifically, rather than distrusting the whole graph.
- **Refresh after a non-trivial edit.** Before committing a change that alters structure (new/renamed/deleted functions, files, or call relationships — not a doc-only or comment-only edit), re-index and re-commit the artifact in the same change:
  ```bash
  codebase-memory-mcp cli index_repository --repo-path <repo> --persistence true
  git -C <repo> add .codebase-memory/
  ```
  A stale committed graph is worse than none — it answers confidently and wrongly. Don't leave one behind on purpose.

## Constraints

- Never trust the graph over the actual file for anything you're about to edit — it's a locator/navigator, not a source of truth for content. Read the real file and lines before writing a change based on what it returned.
- The committed graph can still go stale mid-session (your own uncommitted edits, or a teammate's parallel work) even when `artifact.json` matched `HEAD` at the start — the staleness check above is a start-of-task gate, not a one-time fact. Re-run it before relying on the graph for anything you're about to act on if real time has passed or edits have landed since.
- Falls back silently, never blocks: if the binary isn't installed, `.codebase-memory/` is missing, or a target repo other than this one isn't indexed, that's not a blocker — fall back to `../investigate/investigate.md`'s normal Grep/Read approach and move on. Never stop a task to install this unprompted.

## Verify

- The answer cites a real qualified name, file path, and line range the graph actually returned — not a paraphrase.
- If the answer was acted on (not just used to orient), the staleness check above ran and either confirmed a match or resolved the diff via `detect_changes` before the answer was trusted.
- If the task changed this repo's structure, `.codebase-memory/artifact.json`'s `commit` field is refreshed to the new `HEAD` (or a follow-up commit that refreshes it) — never leave a structural change unreflected in the committed graph.
