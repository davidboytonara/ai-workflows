#!/usr/bin/env python3
"""Extract broad user-turn review notes from pi / Claude / AntiGravity session archives.

Writes one markdown file per source session under:
    $HOME/.agents/memory/review/

Tracks processed source files in:
    $HOME/.agents/state/memory-distill/extract_session_history.json

v2 behavior (extract_version: 2):
- broad / noisy capture: keep every real user message
- attach every substantive assistant text block as `assistant_blocks` on the
  user turn it follows (enables finding extraction by the distiller)
- drop short narration-filler blocks (e.g. "Let me check the auth module.")
- per-block cap 1500 chars, per-turn aggregate cap 6000 chars, with marker
- version bump triggers automatic reprocess when state records an older version
- skip obvious junk only:
  - Claude subagent files under `subagents/`
  - sidechain records (`isSidechain: true`)
  - tool_result pseudo-user messages
  - empty / non-text messages

AntiGravity note:
- local conversation archives are opaque `.pb` blobs — no assistant text is
  recoverable, so findings-extraction will produce an empty `assistant_blocks`
  list for these sessions
- extractor uses trajectory summaries from
  `~/.config/Antigravity/User/globalStorage/state.vscdb`
- when available, it enriches the synthetic review turn with local brain artifact
  metadata from `~/.gemini/antigravity/brain/<session_id>/`
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

WORKFLOW_DIR = Path(__file__).resolve().parent
SUPPORTED_PROVIDERS = ("pi", "claude", "antigravity")
SOURCE_ROOTS = {
    "pi": WORKFLOW_DIR / "sources" / "pi",
    "claude": WORKFLOW_DIR / "sources" / "claude",
    "antigravity": WORKFLOW_DIR / "sources" / "antigravity",
}
LIVE_SOURCE_ROOTS = {
    "pi": (Path.home() / ".pi" / "agent" / "sessions",),
    "claude": (Path.home() / ".claude" / "projects",),
    "antigravity": (
        Path.home() / ".gemini" / "antigravity" / "conversations",
        Path.home() / ".gemini" / "antigravity" / "implicit",
    ),
}
DEFAULT_SOURCE_ROOTS = {
    provider: (SOURCE_ROOTS[provider], *LIVE_SOURCE_ROOTS[provider]) for provider in SUPPORTED_PROVIDERS
}
ANTIGRAVITY_ROOT = SOURCE_ROOTS["antigravity"]
ANTIGRAVITY_BRAIN_ROOT = Path.home() / ".gemini" / "antigravity" / "brain"
ANTIGRAVITY_STATE_DB = Path.home() / ".config" / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
REVIEW_ROOT = Path.home() / ".agents" / "memory" / "review"
STATE_PATH = Path.home() / ".agents" / "state" / "memory-distill" / "extract_session_history.json"
STATE_VERSION = 1
EXTRACT_VERSION = 2
ASSISTANT_BLOCK_CHAR_CAP = 1500
TURN_AGGREGATE_CHAR_CAP = 6000
NARRATION_PATTERN = re.compile(
    r"^\s*(let me|i'?ll|i will|now i|next,?\s*i|first,?\s*i|i'?m going to)\b",
    re.IGNORECASE,
)


@dataclass
class ExtractedTurn:
    index: int
    timestamp: str | None
    assistant_blocks: list[str]
    user_message: str


@dataclass
class SessionExtract:
    provider: str
    source_path: Path
    session_id: str
    session_timestamp: str | None
    source_folder_name: str
    cwd: str | None
    turns: list[ExtractedTurn]
    extra_frontmatter: dict[str, Any] | None = None


@dataclass
class ProtoField:
    number: int
    wire_type: int
    value: int | bytes


@dataclass
class AntigravitySummary:
    session_id: str
    title: str | None
    mode: int | None
    created_at: str | None
    updated_at: str | None
    workspace_uri: str | None
    cwd: str | None
    branch: str | None


def warn(message: str) -> None:
    print(message, file=sys.stderr)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        while timestamp > 10_000_000_000:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
    return None


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def join_text_parts(parts: Iterable[str]) -> str:
    cleaned = [part for part in (normalize_text(part) for part in parts) if part]
    return "\n\n".join(cleaned)


def extract_text_content(content: Any) -> str:
    parts: list[str] = []

    if isinstance(content, str):
        return normalize_text(content)

    if isinstance(content, dict):
        if content.get("type") == "text":
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
        return join_text_parts(parts)

    if isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        return join_text_parts(parts)

    return ""


def compact_assistant_context(text: str | None, max_chars: int = 400) -> str | None:
    if not text:
        return None
    flat = " ".join(text.split())
    if len(flat) <= max_chars:
        return flat
    return flat[:max_chars].rstrip() + "…"


def is_narration_filler(text: str) -> bool:
    """Drop short assistant blocks that are purely announcing intent."""
    stripped = text.strip()
    if len(stripped) >= 200:
        return False
    return bool(NARRATION_PATTERN.match(stripped))


def truncate_with_marker(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    elided = len(text) - cap
    return text[:cap].rstrip() + f"…[+{elided} chars elided]"


def render_assistant_block(blocks: list[str]) -> str | None:
    """Concatenate per-turn assistant text with per-block + per-turn caps."""
    if not blocks:
        return None
    capped_blocks = [truncate_with_marker(b, ASSISTANT_BLOCK_CHAR_CAP) for b in blocks]
    combined = "\n\n---\n\n".join(capped_blocks)
    return truncate_with_marker(combined, TURN_AGGREGATE_CHAR_CAP)


def render_yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def render_frontmatter(data: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in data.items():
        lines.append(f"{key}: {render_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                warn(f"WARN {path}:{line_number}: invalid JSON skipped ({exc})")
                continue
            if isinstance(payload, dict):
                yield payload


def _read_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if position >= len(data):
            raise ValueError("truncated protobuf varint")
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, position
        shift += 7
        if shift >= 64:
            raise ValueError("protobuf varint too long")


def decode_protobuf_fields(data: bytes) -> list[ProtoField]:
    fields: list[ProtoField] = []
    position = 0

    while position < len(data):
        key, position = _read_varint(data, position)
        field_number = key >> 3
        wire_type = key & 0x07

        if wire_type == 0:
            value, position = _read_varint(data, position)
        elif wire_type == 1:
            end = position + 8
            if end > len(data):
                raise ValueError("truncated protobuf fixed64")
            value = data[position:end]
            position = end
        elif wire_type == 2:
            length, position = _read_varint(data, position)
            end = position + length
            if end > len(data):
                raise ValueError("truncated protobuf length-delimited field")
            value = data[position:end]
            position = end
        elif wire_type == 5:
            end = position + 4
            if end > len(data):
                raise ValueError("truncated protobuf fixed32")
            value = data[position:end]
            position = end
        else:
            raise ValueError(f"unsupported protobuf wire type: {wire_type}")

        fields.append(ProtoField(number=field_number, wire_type=wire_type, value=value))

    return fields


def proto_values(fields: list[ProtoField], number: int, wire_type: int | None = None) -> list[int | bytes]:
    values: list[int | bytes] = []
    for field in fields:
        if field.number != number:
            continue
        if wire_type is not None and field.wire_type != wire_type:
            continue
        values.append(field.value)
    return values


def proto_first_int(fields: list[ProtoField], number: int) -> int | None:
    values = proto_values(fields, number, 0)
    if not values:
        return None
    value = values[0]
    return value if isinstance(value, int) else None


def proto_first_string(fields: list[ProtoField], number: int) -> str | None:
    for value in proto_values(fields, number, 2):
        if not isinstance(value, bytes):
            continue
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def proto_first_message(fields: list[ProtoField], number: int) -> list[ProtoField] | None:
    values = proto_values(fields, number, 2)
    if not values:
        return None
    value = values[0]
    if not isinstance(value, bytes):
        return None
    try:
        return decode_protobuf_fields(value)
    except ValueError:
        return None


def base64_decode_loose(value: str) -> bytes | None:
    value = value.strip()
    if not value:
        return None
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding)
    except Exception:
        return None


def timestamp_message_to_iso(fields: list[ProtoField] | None) -> str | None:
    if not fields:
        return None
    seconds = proto_first_int(fields, 1)
    nanos = proto_first_int(fields, 2) or 0
    if seconds is None:
        return None
    timestamp = seconds + (nanos / 1_000_000_000)
    return normalize_timestamp(timestamp)


def file_uri_to_path(uri: str | None) -> str | None:
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme and parsed.scheme != "file":
        return uri
    path = unquote(parsed.path or "")
    return path or None


def antigravity_mode_name(mode: int | None) -> str | None:
    if mode == 1:
        return "agent"
    if mode == 2:
        return "ask"
    return None


def source_folder_name_from_cwd(cwd: str | None, fallback: str) -> str:
    if cwd:
        name = Path(cwd).name
        if name:
            return name
    return fallback


def read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warn(f"WARN failed to read JSON metadata: {path} ({exc})")
        return None
    return payload if isinstance(payload, dict) else None


@lru_cache(maxsize=1)
def load_antigravity_summary_index() -> dict[str, AntigravitySummary]:
    summaries: dict[str, AntigravitySummary] = {}

    if not ANTIGRAVITY_STATE_DB.exists():
        return summaries

    try:
        connection = sqlite3.connect(str(ANTIGRAVITY_STATE_DB))
    except sqlite3.Error as exc:
        warn(f"WARN failed to open AntiGravity state DB: {ANTIGRAVITY_STATE_DB} ({exc})")
        return summaries

    try:
        row = connection.execute(
            "select value from ItemTable where key = 'antigravityUnifiedStateSync.trajectorySummaries'"
        ).fetchone()
    except sqlite3.Error as exc:
        warn(f"WARN failed to query AntiGravity trajectory summaries: {ANTIGRAVITY_STATE_DB} ({exc})")
        connection.close()
        return summaries
    finally:
        connection.close()

    if not row or not row[0]:
        return summaries

    raw = base64_decode_loose(str(row[0]))
    if raw is None:
        warn("WARN failed to decode AntiGravity trajectory summaries payload")
        return summaries

    try:
        outer_fields = decode_protobuf_fields(raw)
    except ValueError as exc:
        warn(f"WARN failed to parse AntiGravity trajectory summaries protobuf ({exc})")
        return summaries

    for entry_value in proto_values(outer_fields, 1, 2):
        if not isinstance(entry_value, bytes):
            continue
        try:
            entry_fields = decode_protobuf_fields(entry_value)
        except ValueError as exc:
            warn(f"WARN failed to parse AntiGravity trajectory summary entry ({exc})")
            continue

        session_id = proto_first_string(entry_fields, 1)
        wrapper_fields = proto_first_message(entry_fields, 2)
        summary_b64 = proto_first_string(wrapper_fields or [], 1)
        summary_raw = base64_decode_loose(summary_b64 or "") if summary_b64 else None

        if not session_id or summary_raw is None:
            continue

        try:
            summary_fields = decode_protobuf_fields(summary_raw)
        except ValueError as exc:
            warn(f"WARN failed to parse AntiGravity session summary for {session_id} ({exc})")
            continue

        workspace_fields = proto_first_message(summary_fields, 9) or []
        workspace_uri = proto_first_string(workspace_fields, 1) or proto_first_string(workspace_fields, 2)
        cwd = file_uri_to_path(workspace_uri)

        summaries[session_id] = AntigravitySummary(
            session_id=session_id,
            title=normalize_text(proto_first_string(summary_fields, 1) or "") or None,
            mode=proto_first_int(summary_fields, 5),
            created_at=timestamp_message_to_iso(proto_first_message(summary_fields, 3)),
            updated_at=timestamp_message_to_iso(proto_first_message(summary_fields, 10))
            or timestamp_message_to_iso(proto_first_message(summary_fields, 7)),
            workspace_uri=workspace_uri,
            cwd=cwd,
            branch=proto_first_string(workspace_fields, 4),
        )

    return summaries


def load_antigravity_artifact_summary(session_id: str, artifact_name: str) -> str | None:
    session_dir = ANTIGRAVITY_BRAIN_ROOT / session_id
    if not session_dir.exists():
        return None

    metadata_candidates = [
        session_dir / f"{artifact_name}.metadata.json",
        session_dir / "artifacts" / f"{artifact_name}.metadata.json",
    ]
    for metadata_path in metadata_candidates:
        metadata = read_json_file(metadata_path)
        if not metadata:
            continue
        summary = metadata.get("summary")
        if isinstance(summary, str):
            normalized = normalize_text(summary)
            if normalized:
                return normalized

    content_candidates = [
        session_dir / artifact_name,
        session_dir / "artifacts" / artifact_name,
        session_dir / f"{artifact_name}.resolved",
        session_dir / "artifacts" / f"{artifact_name}.resolved",
    ]
    for content_path in content_candidates:
        if not content_path.exists():
            continue
        try:
            text = normalize_text(content_path.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            warn(f"WARN failed to read AntiGravity artifact: {content_path} ({exc})")
            continue
        if not text:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        snippet = " ".join(lines[:8]).strip()
        if snippet:
            return snippet

    return None


def load_antigravity_artifact_heading(session_id: str, artifact_name: str) -> str | None:
    session_dir = ANTIGRAVITY_BRAIN_ROOT / session_id
    if not session_dir.exists():
        return None

    content_candidates = [
        session_dir / artifact_name,
        session_dir / "artifacts" / artifact_name,
        session_dir / f"{artifact_name}.resolved",
        session_dir / "artifacts" / f"{artifact_name}.resolved",
    ]
    for content_path in content_candidates:
        if not content_path.exists():
            continue
        try:
            text = normalize_text(content_path.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            warn(f"WARN failed to read AntiGravity artifact heading: {content_path} ({exc})")
            continue
        if not text:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                heading = normalize_text(stripped.lstrip("#").strip())
                if heading:
                    return heading
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if first_line:
            return first_line

    return None


def load_antigravity_assistant_context(session_id: str, prompt_text: str | None) -> str | None:
    parts: list[str] = []

    task_summary = load_antigravity_artifact_summary(session_id, "task.md")
    plan_summary = load_antigravity_artifact_summary(session_id, "implementation_plan.md")

    if task_summary and task_summary != prompt_text:
        parts.append(f"task: {task_summary}")
    if plan_summary and plan_summary != prompt_text:
        parts.append(f"plan: {plan_summary}")

    if not parts:
        return None
    return compact_assistant_context(" | ".join(parts), max_chars=400)


def load_antigravity_prompt_fallback(session_id: str) -> str | None:
    for artifact_name in ("implementation_plan.md", "task.md"):
        heading = load_antigravity_artifact_heading(session_id, artifact_name)
        if heading:
            return heading
    for artifact_name in ("implementation_plan.md", "task.md"):
        summary = load_antigravity_artifact_summary(session_id, artifact_name)
        if summary:
            return summary
    return None


def parse_pi_session(path: Path) -> SessionExtract:
    session_id = path.stem
    session_timestamp: str | None = None
    cwd: str | None = None
    turns: list[ExtractedTurn] = []

    for payload in iter_jsonl(path):
        if payload.get("isSidechain") is True:
            continue

        payload_type = payload.get("type")
        if payload_type == "session":
            session_id = payload.get("id") or session_id
            cwd = payload.get("cwd") or cwd
            session_timestamp = normalize_timestamp(payload.get("timestamp")) or session_timestamp
            continue

        if payload_type != "message":
            if session_timestamp is None:
                session_timestamp = normalize_timestamp(payload.get("timestamp"))
            if cwd is None and isinstance(payload.get("cwd"), str):
                cwd = payload["cwd"]
            continue

        message = payload.get("message")
        if not isinstance(message, dict):
            continue

        if cwd is None and isinstance(payload.get("cwd"), str):
            cwd = payload["cwd"]
        if session_timestamp is None:
            session_timestamp = normalize_timestamp(payload.get("timestamp"))

        role = message.get("role")
        text = extract_text_content(message.get("content"))
        message_timestamp = normalize_timestamp(message.get("timestamp")) or normalize_timestamp(payload.get("timestamp"))

        if role == "assistant":
            if text and not is_narration_filler(text) and turns:
                turns[-1].assistant_blocks.append(text)
            continue

        if role != "user" or not text:
            continue

        turns.append(
            ExtractedTurn(
                index=len(turns) + 1,
                timestamp=message_timestamp,
                assistant_blocks=[],
                user_message=text,
            )
        )

    return SessionExtract(
        provider="pi",
        source_path=path,
        session_id=session_id,
        session_timestamp=session_timestamp,
        source_folder_name=path.parent.name,
        cwd=cwd,
        turns=turns,
    )


def parse_claude_session(path: Path) -> SessionExtract:
    session_id = path.stem
    session_timestamp: str | None = None
    cwd: str | None = None
    turns: list[ExtractedTurn] = []

    for payload in iter_jsonl(path):
        if payload.get("isSidechain") is True:
            continue

        if session_timestamp is None:
            session_timestamp = normalize_timestamp(payload.get("timestamp"))
        if cwd is None and isinstance(payload.get("cwd"), str):
            cwd = payload["cwd"]
        if isinstance(payload.get("sessionId"), str) and payload["sessionId"].strip():
            session_id = payload["sessionId"].strip()

        payload_type = payload.get("type")
        if payload_type not in {"assistant", "user"}:
            continue

        message = payload.get("message")
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        text = extract_text_content(message.get("content"))
        message_timestamp = normalize_timestamp(message.get("timestamp")) or normalize_timestamp(payload.get("timestamp"))

        if payload_type == "assistant" or role == "assistant":
            if text and not is_narration_filler(text) and turns:
                turns[-1].assistant_blocks.append(text)
            continue

        if (payload_type != "user" and role != "user") or not text:
            continue

        turns.append(
            ExtractedTurn(
                index=len(turns) + 1,
                timestamp=message_timestamp,
                assistant_blocks=[],
                user_message=text,
            )
        )

    return SessionExtract(
        provider="claude",
        source_path=path,
        session_id=session_id,
        session_timestamp=session_timestamp,
        source_folder_name=path.parent.name,
        cwd=cwd,
        turns=turns,
    )


def parse_antigravity_session(path: Path) -> SessionExtract:
    session_id = path.stem
    summary = load_antigravity_summary_index().get(session_id)

    prompt_text = summary.title if summary and summary.title else None
    if not prompt_text:
        prompt_text = load_antigravity_prompt_fallback(session_id)

    assistant_context = load_antigravity_assistant_context(session_id, prompt_text)
    timestamp = (
        (summary.created_at if summary else None)
        or (summary.updated_at if summary else None)
        or normalize_timestamp(path.stat().st_mtime)
    )
    cwd = summary.cwd if summary else None
    workspace_uri = summary.workspace_uri if summary else None
    branch = summary.branch if summary else None
    mode_name = antigravity_mode_name(summary.mode if summary else None)

    turns: list[ExtractedTurn] = []
    if prompt_text:
        turns.append(
            ExtractedTurn(
                index=1,
                timestamp=timestamp,
                assistant_blocks=[assistant_context] if assistant_context else [],
                user_message=prompt_text,
            )
        )

    extra_frontmatter: dict[str, Any] = {}
    if workspace_uri:
        extra_frontmatter["source_workspace_uri"] = workspace_uri
    if branch:
        extra_frontmatter["source_branch"] = branch
    if mode_name:
        extra_frontmatter["antigravity_mode"] = mode_name

    return SessionExtract(
        provider="antigravity",
        source_path=path,
        session_id=session_id,
        session_timestamp=timestamp,
        source_folder_name=source_folder_name_from_cwd(cwd, path.parent.name),
        cwd=cwd,
        turns=turns,
        extra_frontmatter=extra_frontmatter or None,
    )


def parse_session(provider: str, path: Path) -> SessionExtract:
    if provider == "pi":
        return parse_pi_session(path)
    if provider == "claude":
        return parse_claude_session(path)
    if provider == "antigravity":
        return parse_antigravity_session(path)
    raise SystemExit(f"Unsupported provider: {provider}")


def infer_provider(path: Path) -> str | None:
    resolved = path.resolve()
    for provider, roots in DEFAULT_SOURCE_ROOTS.items():
        for root in roots:
            if root.exists() and resolved.is_relative_to(root.resolve()):
                return provider
    return None


def should_skip_source_path(path: Path, provider: str) -> bool:
    if provider == "antigravity":
        if path.suffix.lower() != ".pb":
            return True
    else:
        if path.suffix.lower() != ".jsonl":
            return True
        if provider == "claude" and "subagents" in path.parts:
            return True
    if not os.access(path, os.R_OK):
        return True
    return False


def iter_default_roots(provider_filter: str) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    for provider in SUPPORTED_PROVIDERS:
        if provider_filter in {"all", provider}:
            roots.extend((provider, root) for root in DEFAULT_SOURCE_ROOTS[provider])
    return roots


def iter_candidate_files(root: Path, provider: str) -> Iterable[Path]:
    pattern = "*.pb" if provider == "antigravity" else "*.jsonl"
    yield from sorted(root.rglob(pattern))


def collect_source_files(paths: list[str], provider_filter: str) -> list[tuple[str, Path]]:
    collected: list[tuple[str, Path]] = []
    seen: set[tuple[str, str]] = set()

    def add(provider: str, path: Path) -> None:
        resolved = path.resolve()
        key = (provider, str(resolved))
        if key in seen or should_skip_source_path(resolved, provider):
            return
        seen.add(key)
        collected.append((provider, resolved))

    if not paths:
        for provider, root in iter_default_roots(provider_filter):
            if not root.exists():
                warn(f"WARN missing root skipped: {root}")
                continue
            for candidate in iter_candidate_files(root, provider):
                add(provider, candidate)
        return collected

    for raw_path in paths:
        candidate = Path(raw_path).expanduser().resolve()
        if not candidate.exists():
            warn(f"WARN missing path skipped: {candidate}")
            continue

        inferred = infer_provider(candidate)
        if provider_filter == "all":
            provider = inferred
        else:
            provider = provider_filter
            if inferred is not None and inferred != provider:
                warn(f"WARN provider mismatch skipped: {candidate}")
                continue

        if provider not in SUPPORTED_PROVIDERS:
            if candidate.is_dir() and provider_filter == "all":
                added_before = len(collected)
                for child_provider, root in iter_default_roots("all"):
                    if not root.exists():
                        continue
                    if root.is_relative_to(candidate):
                        for child in iter_candidate_files(root, child_provider):
                            add(child_provider, child)
                    elif candidate.is_relative_to(root):
                        for child in iter_candidate_files(candidate, child_provider):
                            add(child_provider, child)
                if len(collected) > added_before:
                    continue
            warn(f"WARN cannot infer provider for path skipped: {candidate}")
            continue

        if candidate.is_file():
            add(provider, candidate)
            continue

        for child in iter_candidate_files(candidate, provider):
            child_provider = provider if provider_filter != "all" else (infer_provider(child) or provider)
            if child_provider in SUPPORTED_PROVIDERS:
                add(child_provider, child)

    return collected


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"version": STATE_VERSION, "processed": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"State file invalid JSON: {STATE_PATH} ({exc})") from exc


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_signature(path: Path) -> tuple[int, int]:
    stat_result = path.stat()
    return stat_result.st_size, stat_result.st_mtime_ns


def is_already_processed(state: dict[str, Any], path: Path) -> bool:
    entry = state.get("processed", {}).get(str(path))
    if not isinstance(entry, dict):
        return False
    size, mtime_ns = file_signature(path)
    return (
        entry.get("size") == size
        and entry.get("mtime_ns") == mtime_ns
        and entry.get("extract_version") == EXTRACT_VERSION
    )


def build_output_path(session: SessionExtract) -> Path:
    return REVIEW_ROOT / session.provider / session.source_folder_name / f"{session.source_path.stem}.md"


def render_session_markdown(session: SessionExtract) -> str:
    assistant_block_count = sum(len(t.assistant_blocks) for t in session.turns)
    frontmatter = {
        "type": "memory_review",
        "extract_version": EXTRACT_VERSION,
        "source_provider": session.provider,
        "session_id": session.session_id,
        "session_timestamp": session.session_timestamp,
        "source_path": str(session.source_path),
        "source_folder_name": session.source_folder_name,
        "cwd": session.cwd,
        "turn_count": len(session.turns),
        "assistant_block_count": assistant_block_count,
    }
    if session.extra_frontmatter:
        frontmatter.update(session.extra_frontmatter)

    lines = [
        render_frontmatter(frontmatter),
        "",
        f"# Session Extract: {session.session_id}",
        "",
    ]

    if not session.turns:
        lines.append("No extractable user turns found.")
        return "\n".join(lines) + "\n"

    for turn in session.turns:
        lines.append(f"## Turn {turn.index} · {turn.timestamp or 'unknown'}")
        lines.append("")
        lines.append("**user:**")
        lines.append("~~~~")
        lines.append(turn.user_message)
        lines.append("~~~~")
        lines.append("")
        assistant_text = render_assistant_block(turn.assistant_blocks)
        if assistant_text:
            lines.append("**assistant:**")
            lines.append("~~~~")
            lines.append(assistant_text)
            lines.append("~~~~")
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines) + "\n"


def process_session(provider: str, source_path: Path, dry_run: bool) -> tuple[Path, int]:
    session = parse_session(provider, source_path)
    output_path = build_output_path(session)
    content = render_session_markdown(session)

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

    return output_path, len(session.turns)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract user-turn review notes from pi / Claude / AntiGravity session archives"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional source file or directory paths. Defaults to workflow-local mirrors plus live pi, Claude, and AntiGravity session dirs.",
    )
    parser.add_argument(
        "--provider",
        choices=("all", "pi", "claude", "antigravity"),
        default="all",
        help="Provider filter. Default: all",
    )
    parser.add_argument("--force", action="store_true", help="Reprocess even if manifest says unchanged")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing notes or manifest")
    parser.add_argument("--limit", type=int, help="Max number of session files to process")
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be >= 0")

    source_files = collect_source_files(args.paths, args.provider)

    state = load_state()
    processed = state.setdefault("processed", {})

    if not args.force:
        source_files = [
            item for item in source_files
            if not is_already_processed(state, item[1])
        ]

    source_files.sort(key=lambda item: item[1].stat().st_mtime_ns)
    if args.limit is not None:
        source_files = source_files[: args.limit]

    if not source_files:
        print("No session files found.")
        return 0
    wrote = 0
    skipped = 0

    for provider, source_path in source_files:
        if not args.force and is_already_processed(state, source_path):
            skipped += 1
            print(f"skip {provider} {source_path}")
            continue

        output_path, turn_count = process_session(provider, source_path, dry_run=args.dry_run)
        size, mtime_ns = file_signature(source_path)
        wrote += 1

        print(f"{'would-write' if args.dry_run else 'wrote'} {provider} {output_path} turns={turn_count}")

        if args.dry_run:
            continue

        processed[str(source_path)] = {
            "provider": provider,
            "output_path": str(output_path),
            "size": size,
            "mtime_ns": mtime_ns,
            "processed_at": utc_now(),
            "turn_count": turn_count,
            "extract_version": EXTRACT_VERSION,
        }

    if not args.dry_run:
        state["version"] = STATE_VERSION
        state["updated"] = utc_now()
        save_state(state)

    print(f"done total={len(source_files)} wrote={wrote} skipped={skipped} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
