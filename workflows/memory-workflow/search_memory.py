#!/usr/bin/env python3
"""Search $HOME/.agents/memory/ for relevant atomic memory notes.

Scans selected scope directories, reads frontmatter, filters by type/tags/expiry,
optionally ranks by query token overlap. Outputs a compact brief, JSON, or paths.

Default mode (no scope flags, no filter flags):
    Returns full content for global/ (and ephemeral/ if included), but only a
    per-scope *summary* (scope name + aggregated tags, no bodies) for every
    project/<SLUG>/ and repo/<SLUG>/. Lets callers discover which projects and
    repos have memory without loading every body. Pass --project/--repo to pull
    full content for a named scope, or any filter flag (--memory-type/--tag/
    --query) to force full content across all scopes.

    Summary mode applies to `brief` and `json` output. `paths` always lists
    every matching file (unchanged).

Open / active-task memories are excluded from the default brief to keep
session-start context focused on standing rules/facts/workflows/findings. Pass
`--include-open` to add them, `--memory-type open` to filter to just them, or
the `--active-tasks` shortcut (= `--memory-type open --include-ephemeral`,
sorted by priority then due date).

Scope selection (composable):
    (no flags)              all scopes: global + every project/* + every repo/*
                            (project/repo summarized — see Default mode above)
    --project SLUG          narrow to global + project/<SLUG>/   (repeatable)
    --repo SLUG             narrow to global + repo/<SLUG>/       (repeatable)
    --project X --repo Y    global + project/X/ + repo/Y/
    --no-global             exclude global (rarely useful)
    --include-ephemeral     also scan ephemeral/ (default: excluded)

Filtering:
    --memory-type TYPE      rule | fact | workflow | open  (repeatable; OR)
    --tag TAG               match if tag present  (repeatable; OR)
    --include-expired       include memories past their expires date (default: excluded)

Ranking:
    --query TEXT            rank results by Jaccard overlap with body+tags+keywords tokens
                            (keywords are the broad recall signal — see write_memory.py)
    --limit N               cap returned results (default: no cap)

Output:
    --format brief          (default) grouped Markdown bullets, compact
    --format json           list of {path, scope, memory_type, tags, keywords, created, updated, expires, body, score}
    --format paths          just absolute paths, one per line

Exit codes:
    0   normal (results may be empty)
    1   argument or filesystem error

Examples:
    # Umbrella session — grab everything
    search_memory.py

    # Scoped session
    search_memory.py --project <slug> --repo <slug>

    # Only rules relevant to a query
    search_memory.py --memory-type rule --query "terse responses"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

MEMORY_ROOT = Path.home() / ".agents" / "memory"
MEMORY_TYPES = {"rule", "fact", "workflow", "open", "finding"}

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


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


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


def is_expired(meta: dict[str, Any], today: date) -> bool:
    exp = meta.get("expires")
    if not exp:
        return False
    try:
        return date.fromisoformat(str(exp)) < today
    except ValueError:
        return False


PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}


def task_sort_key(record: dict[str, Any]) -> tuple[int, str, str]:
    """Sort active tasks: priority (high → low), then due (asc, missing last), then path."""
    priority = PRIORITY_ORDER.get(str(record.get("priority") or "normal"), 1)
    due = record.get("due") or "9999-12-31"
    return (priority, str(due), record.get("path", ""))


def get_auto_scope_slug() -> str | None:
    """Infer current scope slug from CWD basename."""
    cwd = Path.cwd()
    slug = slugify(cwd.name)
    return slug if slug else None


def resolve_scopes(
    projects: list[str],
    repos: list[str],
    include_global: bool,
    include_ephemeral: bool,
) -> list[tuple[str, Path]]:
    """Return ordered list of (scope_label, directory) to scan.

    If no projects and no repos given, scan global + every project/* + every repo/*.
    Otherwise scan global (unless disabled) + only the named project/repo scopes.
    """
    scopes: list[tuple[str, Path]] = []

    if include_global:
        scopes.append(("global", MEMORY_ROOT / "global"))

    if not projects and not repos:
        project_root = MEMORY_ROOT / "project"
        if project_root.is_dir():
            for sub in sorted(project_root.iterdir()):
                if sub.is_dir():
                    scopes.append((f"project:{sub.name}", sub))
        repo_root = MEMORY_ROOT / "repo"
        if repo_root.is_dir():
            for sub in sorted(repo_root.iterdir()):
                if sub.is_dir():
                    scopes.append((f"repo:{sub.name}", sub))
    else:
        for slug in projects:
            scopes.append((f"project:{slug}", MEMORY_ROOT / "project" / slug))
        for slug in repos:
            scopes.append((f"repo:{slug}", MEMORY_ROOT / "repo" / slug))

    if include_ephemeral:
        scopes.append(("ephemeral", MEMORY_ROOT / "ephemeral"))

    return scopes


def collect(
    scopes: list[tuple[str, Path]],
    memory_types: set[str] | None,
    tags: set[str] | None,
    include_expired: bool,
    query_tokens: set[str] | None,
) -> list[dict[str, Any]]:
    today = date.today()
    results: list[dict[str, Any]] = []

    for scope_label, directory in scopes:
        if not directory.is_dir():
            continue
        for md in sorted(directory.glob("*.md")):
            meta = read_frontmatter(md)
            if meta.get("type") != "memory":
                continue
            mtype = meta.get("memory_type")
            if memory_types and mtype not in memory_types:
                continue
            mtags = meta.get("tags") or []
            if isinstance(mtags, str):
                mtags = [mtags]
            if tags and not (tags & {t.lower() for t in mtags}):
                continue
            if not include_expired and is_expired(meta, today):
                continue

            mkeywords = meta.get("keywords") or []
            if isinstance(mkeywords, str):
                mkeywords = [mkeywords]

            body = read_body(md)
            score = 0.0
            if query_tokens:
                searchable = body + " " + " ".join(mtags) + " " + " ".join(mkeywords)
                score = jaccard(query_tokens, tokenize(searchable))

            record: dict[str, Any] = {
                "path": str(md),
                "scope": scope_label,
                "memory_type": mtype,
                "tags": mtags,
                "keywords": mkeywords,
                "created": meta.get("created"),
                "updated": meta.get("updated"),
                "expires": meta.get("expires"),
                "body": body,
                "score": round(score, 3),
            }
            if mtype == "open":
                for field in ("status", "priority", "scheduled", "due", "started",
                              "next_action", "blocked_by", "related"):
                    if field in meta:
                        record[field] = meta[field]
            results.append(record)

    if query_tokens:
        results.sort(key=lambda r: (-r["score"], r["scope"], r["path"]))
    return results


def summarize_scope(
    scope_label: str,
    directory: Path,
    include_expired: bool,
    include_open: bool,
) -> dict[str, Any] | None:
    """Return a summary {scope, summary, tags} for a project/repo scope, skipping bodies.

    Reads only frontmatter. Aggregates unique tags across all non-expired memories,
    ordered by frequency desc then alpha. Returns None if the scope has no memories.
    Open memories are excluded unless include_open is True.
    """
    if not directory.is_dir():
        return None
    today = date.today()
    tag_counts: dict[str, int] = {}
    count = 0
    open_count = 0
    for md in directory.glob("*.md"):
        meta = read_frontmatter(md)
        if meta.get("type") != "memory":
            continue
        if not include_expired and is_expired(meta, today):
            continue
        if meta.get("memory_type") == "open":
            open_count += 1
            if not include_open:
                continue
        count += 1
        mtags = meta.get("tags") or []
        if isinstance(mtags, str):
            mtags = [mtags]
        for t in mtags:
            key = t.lower().strip()
            if key:
                tag_counts[key] = tag_counts.get(key, 0) + 1
    if count == 0 and open_count == 0:
        return None
    sorted_tags = sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))
    return {
        "scope": scope_label,
        "summary": True,
        "tags": [t for t, _ in sorted_tags],
        "open_count": open_count,
    }


def format_open_meta(record: dict[str, Any]) -> str:
    parts: list[str] = []
    if record.get("status"):
        parts.append(f"status={record['status']}")
    if record.get("priority"):
        parts.append(f"priority={record['priority']}")
    if record.get("scheduled"):
        parts.append(f"scheduled={record['scheduled']}")
    if record.get("due"):
        parts.append(f"due={record['due']}")
    if record.get("started"):
        parts.append(f"started={record['started']}")
    if record.get("blocked_by"):
        parts.append(f"blocked_by={record['blocked_by']!r}")
    if record.get("next_action"):
        parts.append(f"next_action={record['next_action']!r}")
    if record.get("related"):
        related = record["related"]
        if isinstance(related, list):
            related = ",".join(related)
        parts.append(f"related={related}")
    return f" — {{ {'; '.join(parts)} }}" if parts else ""


def render_brief(results: list[dict[str, Any]], summaries: list[dict[str, Any]] | None = None) -> str:
    summaries = summaries or []
    if not results and not summaries:
        return "# Memory Brief\n\n_(no memories matched)_\n"

    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        grouped.setdefault(r["scope"], []).append(r)

    total = len(results)
    header_suffix = f" + {len(summaries)} summarized scope{'s' if len(summaries) != 1 else ''}" if summaries else ""
    lines = [f"# Memory Brief ({total} items{header_suffix})", ""]
    for scope in sorted(grouped.keys()):
        lines.append(f"## {scope}")
        for r in grouped[scope]:
            tag_suffix = f" _({', '.join(r['tags'])})_" if r["tags"] else ""
            body = r["body"].replace("\n", " ").strip()
            task_suffix = format_open_meta(r) if r["memory_type"] == "open" else ""
            lines.append(f"- [{r['memory_type']}] {body}{tag_suffix}{task_suffix}")
        lines.append("")

    if summaries:
        lines.append("## Available scopes (summary only — pass --project/--repo or a filter flag for contents)")
        for s in sorted(summaries, key=lambda x: x["scope"]):
            tag_str = ", ".join(s["tags"]) if s["tags"] else "(no tags)"
            open_suffix = ""
            if s.get("open_count"):
                open_suffix = f" [+{s['open_count']} open — pass --include-open or --active-tasks]"
            lines.append(f"- {s['scope']} — {tag_str}{open_suffix}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Search $HOME/.agents/memory/ for atomic memory notes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--project", action="append", default=[], metavar="SLUG",
                   help="Include project/<SLUG>/ scope. Repeatable. Omit for all projects.")
    p.add_argument("--repo", action="append", default=[], metavar="SLUG",
                   help="Include repo/<SLUG>/ scope. Repeatable. Omit for all repos.")
    p.add_argument("--no-global", action="store_true", help="Exclude the global/ scope.")
    p.add_argument("--include-ephemeral", action="store_true", help="Also scan ephemeral/.")
    p.add_argument("--no-auto-scope", action="store_true",
                   help="With no other scope/filter/query flags, keep old default: summarize project/repo scopes instead of full-loading current cwd scope.")
    p.add_argument("--memory-type", action="append", default=[], choices=sorted(MEMORY_TYPES),
                   help="Filter by memory_type. Repeatable (OR).")
    p.add_argument("--tag", action="append", default=[], metavar="TAG",
                   help="Filter by tag presence. Repeatable (OR).")
    p.add_argument("--include-expired", action="store_true",
                   help="Include memories past their expires date.")
    p.add_argument("--include-open", action="store_true",
                   help="Include memory_type=open in the default brief (excluded by default).")
    p.add_argument("--active-tasks", action="store_true",
                   help="Shortcut: load only memory_type=open across all scopes (incl. ephemeral), "
                        "sorted by priority then due date. Implies --include-open and --include-ephemeral.")
    p.add_argument("--query", default=None, help="Rank results by token overlap with this text.")
    p.add_argument("--limit", type=int, default=0, help="Cap number of results (0 = no cap).")
    p.add_argument("--format", choices=("brief", "json", "paths"), default="brief",
                   help="Output format (default: brief).")
    return p


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)

    if not MEMORY_ROOT.is_dir():
        print(f"error: memory root not found: {MEMORY_ROOT}", file=sys.stderr)
        return 1

    if args.active_tasks:
        args.include_open = True
        args.include_ephemeral = True

    no_scope_flags = not args.project and not args.repo
    no_filter_flags = not args.memory_type and not args.tag and not args.query
    auto_scope_slug = get_auto_scope_slug() if no_scope_flags and no_filter_flags and not args.no_auto_scope else None
    auto_full_labels: set[str] = set()
    if auto_scope_slug:
        if (MEMORY_ROOT / "project" / auto_scope_slug).is_dir():
            auto_full_labels.add(f"project:{auto_scope_slug}")
        if (MEMORY_ROOT / "repo" / auto_scope_slug).is_dir():
            auto_full_labels.add(f"repo:{auto_scope_slug}")

    scopes = resolve_scopes(
        projects=args.project,
        repos=args.repo,
        include_global=not args.no_global,
        include_ephemeral=args.include_ephemeral,
    )

    if args.active_tasks:
        mtypes: set[str] | None = {"open"}
    elif args.memory_type:
        mtypes = set(args.memory_type)
    elif args.include_open:
        mtypes = None
    else:
        mtypes = MEMORY_TYPES - {"open"}
    tags = {t.lower() for t in args.tag} or None
    qtokens = tokenize(args.query) if args.query else None

    # Default mode: no explicit scope, no filters — summarize project/repo scopes.
    # `paths` format is excluded so scripting callers still get every file path.
    summarize_projects_repos = (
        not args.project
        and not args.repo
        and not args.memory_type
        and not args.tag
        and not args.query
        and not args.active_tasks
        and args.format != "paths"
    )

    if summarize_projects_repos:
        full_scopes = [
            s for s in scopes
            if not s[0].startswith(("project:", "repo:")) or s[0] in auto_full_labels
        ]
        summary_scopes = [
            s for s in scopes
            if s[0].startswith(("project:", "repo:")) and s[0] not in auto_full_labels
        ]
    else:
        full_scopes = scopes
        summary_scopes = []

    results = collect(full_scopes, mtypes, tags, args.include_expired, qtokens)

    if args.active_tasks:
        results.sort(key=task_sort_key)

    if args.limit and args.limit > 0:
        results = results[:args.limit]

    summaries: list[dict[str, Any]] = []
    for label, directory in summary_scopes:
        s = summarize_scope(label, directory, args.include_expired, args.include_open)
        if s:
            summaries.append(s)

    if args.format == "json":
        print(json.dumps(results + summaries, indent=2, ensure_ascii=False))
    elif args.format == "paths":
        for r in results:
            print(r["path"])
    else:
        print(render_brief(results, summaries), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
