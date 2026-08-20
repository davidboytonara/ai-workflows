#!/usr/bin/env python3
"""Per-harness transcript profiles for the specs-optimization workflow.

`harvest_nav.py` is harness-agnostic: it only ever sees the canonical call
stream produced here. Each backend profile knows four things about its CLI:

  * where transcripts live (`roots()`) and how to enumerate them (`discover()`),
  * how to read the FIRST user message (`first_user_text()`) — used to locate a
    probe's transcript by its run token,
  * how to turn its own JSONL records into canonical calls (`normalize()`),
  * what its transcripts can and cannot tell us (`capabilities`).

Canonical call record (one dict per tool invocation, file order preserved):

    {"tool": "read"|"search"|"command"|"spawn"|"other",
     "name": <raw backend tool name>,
     "path": str|None,        # for read/search
     "command": str|None,     # for command (shell) calls
     "cwd": str|None,         # per-record cwd, else the session-level fallback
     "ts": datetime|None,
     "is_error": bool|None,   # None == unknowable on this backend
     "child_id": str|None}    # spawned sub-transcript id, when recoverable

`normalize()` returns a Normalized bundle: calls + session_cwd + ts range +
`tool_results_seen` (whether this file actually carried tool results).

Capabilities:
  tool_results — tool results are persisted, so `is_error` is real. When false,
                 failed_reads / failed_searches are NOT zero, they are unknown,
                 and every consumer must report them as unavailable.
  nesting      — a spawned subagent's transcript can be linked to its parent.

Claude Code declares both true. Pi declares both false by default: subagent
results carry no session pointer (nesting is genuinely unrecoverable), but tool
results ARE persisted by pi >= 0.84 session format v3, so `tool_results` is
UPGRADED to true when the located transcripts actually contain toolResult
records (see `observed_capabilities`). Detection never downgrades a declared
capability and never invents one — no evidence means "unavailable", not zero.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

# probe_backends.py -> specs-optimization/ -> workflows/ -> repo
REPO_ROOT = Path(__file__).resolve().parents[2]

HARNESSES = ("claude", "pi")
AGENTID_RE = re.compile(r"agentId:\s*([0-9a-fA-F]{6,})")


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def flatten_content(content) -> str:
    """Join the text of a content list/str, ignoring non-text blocks."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if isinstance(b.get("text"), str):
                    parts.append(b["text"])
                elif isinstance(b.get("content"), str):
                    parts.append(b["content"])
            elif isinstance(b, str):
                parts.append(b)
    return "\n".join(parts)


def iter_records(path: Path) -> Iterator[dict]:
    try:
        fh = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield obj


class Normalized:
    __slots__ = ("calls", "session_cwd", "ts_min", "ts_max", "tool_results_seen",
                 "agent_type", "description")

    def __init__(self):
        self.calls: list[dict] = []
        self.session_cwd: str | None = None
        self.ts_min: datetime | None = None
        self.ts_max: datetime | None = None
        self.tool_results_seen = False
        self.agent_type = ""
        self.description = ""

    def _stamp(self, ts):
        if ts is None:
            return
        self.ts_min = ts if self.ts_min is None or ts < self.ts_min else self.ts_min
        self.ts_max = ts if self.ts_max is None or ts > self.ts_max else self.ts_max


class Backend:
    """Base profile. Subclasses fill in root/discovery/normalisation."""

    name = ""
    capabilities: dict = {"tool_results": False, "nesting": False}

    def roots(self) -> list[Path]:
        raise NotImplementedError

    def discover(self, since: float = 0.0) -> Iterator[Path]:
        """Candidate top-level transcripts modified at/after `since` (epoch s)."""
        for root in self.roots():
            if not root.is_dir():
                continue
            for p in root.rglob("*.jsonl"):
                if not self._is_toplevel(p):
                    continue
                try:
                    if p.stat().st_mtime + 1e-6 < since:
                        continue
                except OSError:
                    continue
                yield p

    def _is_toplevel(self, path: Path) -> bool:
        return True

    def first_user_text(self, path: Path) -> str:
        raise NotImplementedError

    def normalize(self, path: Path) -> Normalized:
        raise NotImplementedError

    def child_transcript(self, child_id: str, sibling: Path) -> Path | None:
        return None

    def observed_capabilities(self, normalized: Iterable[Normalized]) -> dict:
        return dict(self.capabilities)


class ClaudeBackend(Backend):
    """Claude Code: ~/.claude/projects/<cwd-slug>/<uuid>.jsonl (+ agent-<hex>.jsonl).

    Records are {"type": "assistant"|"user", "cwd": ..., "timestamp": ...,
    "message": {"content": [blocks]}}; blocks are `tool_use` / `tool_result`.
    Tool results are persisted (is_error is real) and a spawn's tool_result text
    carries `agentId: <hex>`, so nested subagents are linkable.
    """

    name = "claude"
    capabilities = {"tool_results": True, "nesting": True}
    SPAWN_TOOLS = {"Agent", "Task"}

    def __init__(self, projects_root: Path | None = None):
        self.projects_root = Path(projects_root or (Path.home() / ".claude" / "projects")).expanduser()

    def roots(self) -> list[Path]:
        return [self.projects_root]

    def _is_toplevel(self, path: Path) -> bool:
        # agent-*.jsonl are nested subagent transcripts, never a probe root.
        return not path.name.startswith("agent-")

    def first_user_text(self, path: Path) -> str:
        for obj in iter_records(path):
            if obj.get("type") != "user":
                continue
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            text = flatten_content(msg.get("content")).strip()
            if text:
                return text
        return ""

    def normalize(self, path: Path) -> Normalized:
        norm = Normalized()
        meta = path.with_name(path.stem + ".meta.json")
        if meta.exists():
            try:
                md = json.loads(meta.read_text(encoding="utf-8"))
                norm.agent_type = md.get("agentType", "") or ""
                norm.description = md.get("description", "") or ""
            except (OSError, ValueError):
                pass

        pending: list[dict] = []          # canonical calls, in file order
        by_uid: dict[str, dict] = {}      # tool_use id -> canonical call
        for obj in iter_records(path):
            ts = parse_ts(obj.get("timestamp"))
            norm._stamp(ts)
            cwd = obj.get("cwd")
            if cwd and norm.session_cwd is None:
                norm.session_cwd = cwd
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            otype = obj.get("type")
            if otype == "assistant":
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    call = self._call(b.get("name", ""), b.get("input") or {}, cwd, ts)
                    uid = b.get("id", "")
                    if uid:
                        by_uid[uid] = call
                    pending.append(call)
            elif otype == "user":
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    norm.tool_results_seen = True
                    call = by_uid.get(b.get("tool_use_id", ""))
                    if call is None:
                        continue
                    call["is_error"] = bool(b.get("is_error"))
                    if call["tool"] == "spawn":
                        m = AGENTID_RE.search(flatten_content(b.get("content")))
                        if m:
                            call["child_id"] = m.group(1)
        norm.calls = pending
        return norm

    def _call(self, name: str, inp: dict, cwd, ts) -> dict:
        call = {"tool": "other", "name": name, "path": None, "command": None,
                "cwd": cwd, "ts": ts, "is_error": None, "child_id": None}
        if name == "Read":
            call["tool"] = "read"
            call["path"] = inp.get("file_path", "")
        elif name == "Bash":
            call["tool"] = "command"
            call["command"] = inp.get("command", "")
        elif name in ("Grep", "Glob"):
            call["tool"] = "search"
            call["path"] = inp.get("path", "") or inp.get("file_path", "")
        elif name in self.SPAWN_TOOLS:
            call["tool"] = "spawn"
        return call

    def child_transcript(self, child_id: str, sibling: Path) -> Path | None:
        direct = sibling.with_name(f"agent-{child_id}.jsonl")
        if direct.is_file():
            return direct
        for p in self.projects_root.rglob(f"agent-{child_id}.jsonl"):
            return p
        return None


class PiBackend(Backend):
    """pi: ~/.pi/agent/sessions/<cwd-slug>/<ISO-ts>_<uuid>.jsonl.

    Records are {"type":"message","message":{"role":..., "content":[blocks]}};
    tool calls are blocks {"type":"toolCall","name":...,"arguments":{...}} with
    lowercase tool names. `cwd` appears only on the leading
    {"type":"session",...} record, so it is a session-level fallback.

    Nesting is unrecoverable: a `subagent` call's result carries no session
    pointer. Tool results are persisted by session format v3 (pi >= 0.84) as
    {"message":{"role":"toolResult","toolCallId":...,"isError":bool}} — when
    present they are used; when absent `is_error` stays None (unknown).
    """

    name = "pi"
    capabilities = {"tool_results": False, "nesting": False}
    READ_TOOLS = {"read"}
    SEARCH_TOOLS = {"grep", "find", "ls", "glob"}
    COMMAND_TOOLS = {"bash", "shell"}
    SPAWN_TOOLS = {"subagent", "task", "agent"}

    def __init__(self, sessions_root: Path | None = None):
        self.sessions_root = Path(sessions_root or (Path.home() / ".pi" / "agent" / "sessions")).expanduser()

    def roots(self) -> list[Path]:
        return [self.sessions_root]

    def first_user_text(self, path: Path) -> str:
        for obj in iter_records(path):
            if obj.get("type") != "message":
                continue
            msg = obj.get("message")
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            text = flatten_content(msg.get("content")).strip()
            if text:
                return text
        return ""

    def normalize(self, path: Path) -> Normalized:
        norm = Normalized()
        by_uid: dict[str, dict] = {}
        for obj in iter_records(path):
            ts = parse_ts(obj.get("timestamp"))
            norm._stamp(ts)
            if obj.get("type") == "session":
                if isinstance(obj.get("cwd"), str):
                    norm.session_cwd = obj["cwd"]
                continue
            if obj.get("type") != "message":
                continue
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role == "toolResult":
                norm.tool_results_seen = True
                call = by_uid.get(msg.get("toolCallId", ""))
                if call is not None:
                    call["is_error"] = bool(msg.get("isError"))
                continue
            if role != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "toolCall":
                    continue
                call = self._call(b.get("name", "") or "", b.get("arguments") or {}, ts)
                uid = b.get("id", "")
                if uid:
                    by_uid[uid] = call
                norm.calls.append(call)
        # cwd is session-level on pi: back-fill every call.
        for call in norm.calls:
            if not call["cwd"]:
                call["cwd"] = norm.session_cwd
        return norm

    def _call(self, name: str, args: dict, ts) -> dict:
        low = name.lower()
        call = {"tool": "other", "name": name, "path": None, "command": None,
                "cwd": None, "ts": ts, "is_error": None, "child_id": None}
        if low in self.READ_TOOLS:
            call["tool"] = "read"
            call["path"] = args.get("path") or args.get("file_path") or ""
        elif low in self.COMMAND_TOOLS:
            call["tool"] = "command"
            call["command"] = args.get("command", "")
        elif low in self.SEARCH_TOOLS:
            call["tool"] = "search"
            call["path"] = args.get("path") or args.get("dir") or args.get("cwd") or ""
        elif low in self.SPAWN_TOOLS:
            call["tool"] = "spawn"
        return call

    def observed_capabilities(self, normalized: Iterable[Normalized]) -> dict:
        caps = dict(self.capabilities)
        if any(getattr(n, "tool_results_seen", False) for n in normalized):
            caps["tool_results"] = True
        return caps


def get_backend(name: str, **kwargs) -> Backend:
    if name == "claude":
        return ClaudeBackend(kwargs.get("projects_root"))
    if name == "pi":
        return PiBackend(kwargs.get("sessions_root"))
    raise ValueError(f"unknown harness: {name!r} (expected one of {', '.join(HARNESSES)})")


def harness_for_model(model: str) -> str:
    """Mirror of LLM_harness.sh routing: unqualified lowercase claude* -> claude.

    Aliases are resolved the same way the harness does; anything else (bare id
    or provider/id) goes to pi. Keep in sync with LLM_harness.sh resolve_model().
    """
    aliases = {
        "fable": "claude-fable-5", "fable-5": "claude-fable-5", "fable5": "claude-fable-5",
        "opus": "claude-opus-5", "opus-5": "claude-opus-5", "opus5": "claude-opus-5",
        "sonnet": "claude-sonnet-5", "sonnet-5": "claude-sonnet-5", "sonnet5": "claude-sonnet-5",
        "haiku": "claude-haiku-4-5-20251001", "haiku-4.5": "claude-haiku-4-5-20251001",
        "haiku-4-5": "claude-haiku-4-5-20251001",
        "gpt": "gpt-5", "gpt5": "gpt-5", "gpt-5": "gpt-5",
    }
    m = (model or "").strip().lower().replace(" ", "-")
    m = aliases.get(m, m)
    if "/" in m:
        return "pi"
    return "claude" if m.startswith("claude") else "pi"


def harness_for_transcript(path: str | os.PathLike) -> str | None:
    """Infer the backend from a transcript path (claude vs pi tree)."""
    parts = Path(path).expanduser().resolve().parts
    if ".claude" in parts:
        return "claude"
    if ".pi" in parts:
        return "pi"
    return None
