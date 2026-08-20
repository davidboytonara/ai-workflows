#!/usr/bin/env python3
"""Write a memory note to $HOME/.agents/memory/<scope>/<filename>.md

Schema-validated, near-duplicate aware. Dumb CLI — the LLM decides content.

Usage:
    write_memory.py --memory-type rule --scope global \\
        --tags "style,communication" \\
        --keywords "concise,terse,short-answers" \\
        --body "User prefers concise answers" \\
        [--expires YYYY-MM-DD] \\
        [--allow-dup] [--force]

Active-task fields (only valid with --memory-type open):
    --status {pending,active,blocked,done}
    --priority {high,normal,low}
    --scheduled YYYY-MM-DD      when work is planned to begin (distinct from --due)
    --due YYYY-MM-DD            hard deadline (distinct from --expires)
    --started YYYY-MM-DD        auto-filled to today when --status active is set
    --next-action TEXT          single short sentence: the next concrete step
    --blocked-by TEXT           single short sentence: the blocker (use with --status blocked)
    --related "slug1,slug2"     comma-separated memory file slugs that give context

Tags vs keywords:
    tags     — 2-5 categorical labels (style, infra, security). Filterable via --tag.
    keywords — 5-15 free-form specific terms (file paths, function names, concepts)
               extracted from the body to boost recall in --query ranking.

Outputs JSON to stdout:
    {"status": "written", "path": "..."}
    {"status": "near_dup", "candidate_path": "...", "matches": [{"path": "...", "similarity": 0.82}, ...]}
    {"status": "conflict", "path": "...", "message": "..."}
    {"status": "error", "message": "..."}

Exit codes:
    0  - written, near_dup, or conflict (non-fatal: LLM inspects and decides)
    1  - error (validation failure)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

MEMORY_ROOT = Path.home() / ".agents" / "memory"
MEMORY_TYPES = {"rule", "fact", "workflow", "open", "finding"}
DUP_SIMILARITY_DEFAULT = 0.6
DUP_SIMILARITY_THRESHOLDS = {"finding": 0.85}

OPEN_STATUSES = ("pending", "active", "blocked", "done")
OPEN_PRIORITIES = ("high", "normal", "low")

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "can", "may", "might", "must", "shall",
    "i", "me", "my", "we", "our", "us", "you", "your", "he", "she", "it",
    "they", "them", "their", "this", "that", "these", "those",
    "of", "to", "in", "on", "at", "for", "with", "by", "from", "as", "into",
    "and", "or", "but", "if", "so", "not", "no", "nor",
    "than", "then", "when", "where", "how", "why", "what", "which", "who",
    "user", "prefers", "prefer", "use", "uses", "using",
}


def slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def parse_scope(scope: str) -> Path:
    """Resolve scope string to directory under MEMORY_ROOT.

    global            → MEMORY_ROOT/global
    ephemeral         → MEMORY_ROOT/ephemeral
    project:<name>    → MEMORY_ROOT/project/<slug>
    repo:<name>       → MEMORY_ROOT/repo/<slug>
    """
    if scope in ("global", "ephemeral"):
        return MEMORY_ROOT / scope
    if ":" in scope:
        kind, name = scope.split(":", 1)
        if kind in ("project", "repo") and name.strip():
            return MEMORY_ROOT / kind / slugify(name)
    raise ValueError(
        f"Invalid scope {scope!r}. Expected: global | ephemeral | project:<name> | repo:<name>"
    )


def validate_date(text: str | None) -> str | None:
    if not text:
        return None
    return date.fromisoformat(text).isoformat()


def read_frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    block = text[4:end]
    meta: dict[str, Any] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            meta[key.strip()] = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
        else:
            meta[key.strip()] = val.strip("'\"")
    return meta


def read_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            return text[end + 5:].strip()
    return text.strip()


def dup_threshold_for(memory_type: str) -> float:
    return DUP_SIMILARITY_THRESHOLDS.get(memory_type, DUP_SIMILARITY_DEFAULT)


def find_near_duplicates(
    target_dir: Path,
    memory_type: str,
    body_tokens: set[str],
    threshold: float | None = None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if not target_dir.exists():
        return matches
    effective_threshold = dup_threshold_for(memory_type) if threshold is None else threshold
    for md in target_dir.glob("*.md"):
        meta = read_frontmatter(md)
        if meta.get("memory_type") != memory_type:
            continue
        sim = jaccard(body_tokens, tokenize(read_body(md)))
        if sim >= effective_threshold:
            matches.append({"path": str(md), "similarity": round(sim, 3)})
    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return matches


def render_frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if value is None:
            continue
        if isinstance(value, list):
            joined = ", ".join(json.dumps(item, ensure_ascii=False) for item in value)
            lines.append(f"{key}: [{joined}]")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        else:
            lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def write_memory(
    *,
    memory_type: str,
    scope: str,
    body: str,
    tags: list[str] | None = None,
    keywords: list[str] | None = None,
    expires: str | None = None,
    allow_dup: bool = False,
    force: bool = False,
    status: str | None = None,
    priority: str | None = None,
    scheduled: str | None = None,
    due: str | None = None,
    started: str | None = None,
    next_action: str | None = None,
    blocked_by: str | None = None,
    related: list[str] | None = None,
) -> dict[str, Any]:
    if memory_type not in MEMORY_TYPES:
        return {"status": "error", "message": f"memory_type must be one of {sorted(MEMORY_TYPES)}"}
    body = body.strip()
    if not body:
        return {"status": "error", "message": "body is empty"}

    task_fields = {
        "status": status,
        "priority": priority,
        "scheduled": scheduled,
        "due": due,
        "started": started,
        "next_action": next_action,
        "blocked_by": blocked_by,
        "related": related,
    }
    set_task_fields = {k for k, v in task_fields.items() if v not in (None, "", [])}
    if memory_type != "open" and set_task_fields:
        return {
            "status": "error",
            "message": (
                f"task fields {sorted(set_task_fields)} are only valid for memory_type=open"
            ),
        }

    if status is not None and status not in OPEN_STATUSES:
        return {"status": "error", "message": f"--status must be one of {list(OPEN_STATUSES)}"}
    if priority is not None and priority not in OPEN_PRIORITIES:
        return {"status": "error", "message": f"--priority must be one of {list(OPEN_PRIORITIES)}"}

    target_dir = parse_scope(scope)
    expires_iso = validate_date(expires)
    scheduled_iso = validate_date(scheduled)
    due_iso = validate_date(due)
    started_iso = validate_date(started)
    if scheduled_iso and due_iso and date.fromisoformat(due_iso) < date.fromisoformat(scheduled_iso):
        return {
            "status": "error",
            "message": "due must be on or after scheduled",
        }
    if memory_type == "open" and status == "active" and not started_iso:
        started_iso = datetime.now().date().isoformat()
    if memory_type == "open" and status == "blocked" and not (blocked_by or "").strip():
        print(
            "warning: status=blocked without --blocked-by; doctor will flag this",
            file=sys.stderr,
        )

    body_tokens = tokenize(body)
    body_hash = hashlib.sha1(body.encode()).hexdigest()
    slug = slugify(body) or body_hash[:12]
    if memory_type == "finding":
        filename = f"finding-{slug}-{body_hash[:6]}.md"
    else:
        filename = f"{memory_type}-{slug}.md"
    path = target_dir / filename

    if not allow_dup:
        matches = find_near_duplicates(target_dir, memory_type, body_tokens)
        if matches:
            return {
                "status": "near_dup",
                "candidate_path": str(path),
                "matches": matches,
            }

    if path.exists() and not force:
        return {
            "status": "conflict",
            "path": str(path),
            "message": "File exists at target path. Inspect then re-run with --force to overwrite.",
        }

    now_iso = datetime.now().date().isoformat()
    created_iso = now_iso
    if path.exists():
        created_iso = read_frontmatter(path).get("created", now_iso)

    meta: dict[str, Any] = {
        "type": "memory",
        "memory_type": memory_type,
        "tags": tags or [],
        "keywords": keywords or [],
        "created": created_iso,
        "updated": now_iso,
    }
    if expires_iso:
        meta["expires"] = expires_iso
    if memory_type == "open":
        if status:
            meta["status"] = status
        if priority:
            meta["priority"] = priority
        if scheduled_iso:
            meta["scheduled"] = scheduled_iso
        if due_iso:
            meta["due"] = due_iso
        if started_iso:
            meta["started"] = started_iso
        if next_action and next_action.strip():
            meta["next_action"] = next_action.strip()
        if blocked_by and blocked_by.strip():
            meta["blocked_by"] = blocked_by.strip()
        if related:
            meta["related"] = related

    content = render_frontmatter(meta) + "\n\n" + body + "\n"
    target_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    return {"status": "written", "path": str(path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write a memory note under $HOME/.agents/memory/")
    parser.add_argument("--memory-type", required=True, choices=sorted(MEMORY_TYPES))
    parser.add_argument(
        "--scope",
        required=True,
        help="global | ephemeral | project:<name> | repo:<name>",
    )
    parser.add_argument("--body", required=True, help="Canonical memory statement")
    parser.add_argument("--tags", default="", help="Comma-separated categorical tags (2-5)")
    parser.add_argument(
        "--keywords",
        default="",
        help="Comma-separated free-form terms (5-15) for --query recall — file paths, symbols, concepts",
    )
    parser.add_argument("--expires", default=None, help="ISO date; omit for stable memory")
    parser.add_argument("--allow-dup", action="store_true", help="Skip near-duplicate check")
    parser.add_argument("--force", action="store_true", help="Overwrite if file exists at target path")
    parser.add_argument(
        "--status",
        default=None,
        choices=OPEN_STATUSES,
        help="Active-task state. Only valid with --memory-type open.",
    )
    parser.add_argument(
        "--priority",
        default=None,
        choices=OPEN_PRIORITIES,
        help="Task priority. Only valid with --memory-type open.",
    )
    parser.add_argument(
        "--scheduled",
        default=None,
        help="ISO date when work is planned to begin. Only valid with --memory-type open.",
    )
    parser.add_argument(
        "--due",
        default=None,
        help="ISO date hard deadline for the task. Only valid with --memory-type open.",
    )
    parser.add_argument(
        "--started",
        default=None,
        help="ISO date the task became active. Auto-filled when --status active is set.",
    )
    parser.add_argument(
        "--next-action",
        default=None,
        help="Single short sentence describing the next concrete step.",
    )
    parser.add_argument(
        "--blocked-by",
        default=None,
        help="Single short sentence describing the blocker. Use with --status blocked.",
    )
    parser.add_argument(
        "--related",
        default="",
        help="Comma-separated memory file slugs that give context for the task.",
    )
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    related = [r.strip() for r in args.related.split(",") if r.strip()]
    try:
        result = write_memory(
            memory_type=args.memory_type,
            scope=args.scope,
            body=args.body,
            tags=tags,
            keywords=keywords,
            expires=args.expires,
            allow_dup=args.allow_dup,
            force=args.force,
            status=args.status,
            priority=args.priority,
            scheduled=args.scheduled,
            due=args.due,
            started=args.started,
            next_action=args.next_action,
            blocked_by=args.blocked_by,
            related=related or None,
        )
    except ValueError as exc:
        result = {"status": "error", "message": str(exc)}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
