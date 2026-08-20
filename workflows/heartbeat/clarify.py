"""Clarification file I/O.

A task exits 42 when it needs user input, writing a clarify file at
`state/clarify/<task>-<runid>.md`. The daemon considers the file "answered"
when its mtime is newer than `submitted_at` *and* the user has written
non-whitespace content under the `## User reply:` marker.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

DEFAULT_CLARIFY_DIR = Path.home() / ".agents" / "state" / "clarify"
RESOLVED_SUBDIR = "resolved"

QUESTION_RE = re.compile(r"^## Task question\s*\n(.*?)(?=^## User reply:|\Z)", re.MULTILINE | re.DOTALL)
REPLY_RE = re.compile(r"^## User reply:\s*\n(.*)$", re.MULTILINE | re.DOTALL)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class ClarifyFile:
    path: Path
    task: str
    run_id: str
    submitted_at: datetime
    question: str
    reply: str


def clarify_path(clarify_dir: Path, task: str, run_id: str) -> Path:
    return clarify_dir / f"{task}-{run_id}.md"


def write_stub(
    clarify_dir: Path,
    task: str,
    run_id: str,
    submitted_at: datetime,
    question: str = "",
) -> Path:
    """Write an empty clarify file. Used when a task exits 42 without writing one itself."""
    clarify_dir.mkdir(parents=True, exist_ok=True)
    path = clarify_path(clarify_dir, task, run_id)
    submitted_iso = submitted_at.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    content = (
        "---\n"
        f"task: {task}\n"
        f"run_id: {run_id}\n"
        f"submitted_at: {submitted_iso}\n"
        "---\n"
        "\n"
        "## Task question\n"
        f"{question.strip() or '(task exited 42 without writing a question; check history.jsonl for context)'}\n"
        "\n"
        "## User reply:\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def read(path: Path) -> ClarifyFile:
    text = path.read_text(encoding="utf-8")
    fm_match = FRONTMATTER_RE.match(text)
    if not fm_match:
        raise ValueError(f"{path}: missing YAML frontmatter")
    fm_raw = yaml.safe_load(fm_match.group(1)) or {}
    if not isinstance(fm_raw, dict):
        raise ValueError(f"{path}: frontmatter must be a mapping")
    try:
        task = str(fm_raw["task"])
        run_id = str(fm_raw["run_id"])
        submitted_at_raw = fm_raw["submitted_at"]
    except KeyError as exc:
        raise ValueError(f"{path}: frontmatter missing {exc}") from exc

    if isinstance(submitted_at_raw, datetime):
        submitted_at = submitted_at_raw.astimezone(timezone.utc) if submitted_at_raw.tzinfo else submitted_at_raw.replace(tzinfo=timezone.utc)
    else:
        submitted_at = datetime.fromisoformat(str(submitted_at_raw)).astimezone(timezone.utc)

    body = fm_match.group(2)
    q_match = QUESTION_RE.search(body)
    r_match = REPLY_RE.search(body)
    question = q_match.group(1).strip() if q_match else ""
    reply = r_match.group(1).strip() if r_match else ""

    return ClarifyFile(
        path=path,
        task=task,
        run_id=run_id,
        submitted_at=submitted_at,
        question=question,
        reply=reply,
    )


def is_answered(path: Path, submitted_at: datetime) -> bool:
    """True iff file mtime > submitted_at and the reply body is non-empty after strip()."""
    if not path.exists():
        return False
    mtime_utc = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    if mtime_utc <= submitted_at:
        return False
    try:
        parsed = read(path)
    except (ValueError, yaml.YAMLError):
        return False
    return bool(parsed.reply.strip())


def archive(path: Path, resolved_dir: Path) -> Path:
    resolved_dir.mkdir(parents=True, exist_ok=True)
    target = resolved_dir / path.name
    os.replace(path, target)
    return target
