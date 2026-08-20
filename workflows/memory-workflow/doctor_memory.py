#!/usr/bin/env python3
"""Deterministically lint $HOME/.agents/memory notes.

Reports schema issues, weak tags/keywords, duplicate memories, and stale
finding file references. Read-only: never edits or deletes memories.

Exit codes:
  0  no errors (warnings allowed unless --fail-on-warning)
  1  errors found, or warnings found with --fail-on-warning
  2  usage/config error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

MEMORY_ROOT = Path.home() / ".agents" / "memory"
MEMORY_TYPES = {"rule", "fact", "workflow", "open", "finding"}
DUP_SIMILARITY_DEFAULT = 0.60
DUP_SIMILARITY_THRESHOLDS = {"finding": 0.85}
BODY_WARN_CHARS = 1200
OPEN_STATUSES = {"pending", "active", "blocked", "done"}
OPEN_PRIORITIES = {"high", "normal", "low"}
OPEN_DATE_FIELDS = ("scheduled", "due", "started")
OPEN_DONE_STALE_DAYS = 90
OPEN_LONG_RUNNING_DAYS = 14
CODE_SUFFIXES = (
    "py", "md", "yaml", "yml", "json", "jsonl", "toml", "ini", "cfg", "sql",
    "ts", "tsx", "js", "jsx", "go", "rs", "java", "kt", "sh", "html", "css", "service",
)
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

ABS_PATH_RE = re.compile(r"(?<![A-Za-z0-9_.@$+~-])(?:~|\$HOME)?/[^\s`'\"<>()\[\]{},;]+")
REL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_:/.-])(?:[A-Za-z0-9_.@$+~-]+/)+[A-Za-z0-9_.@$+~-]+\.(?:"
    + "|".join(CODE_SUFFIXES)
    + r")\b"
)
BARE_CODE_RE = re.compile(r"(?<![A-Za-z0-9_./-])[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:" + "|".join(CODE_SUFFIXES) + r")\b")


@dataclass(frozen=True)
class Issue:
    severity: str  # error | warning
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class Note:
    path: Path
    scope: str
    memory_type: str
    body: str
    tags: list[str]
    keywords: list[str]
    tokens: set[str]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def parse_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    inner = value[1:-1].strip()
    return [x.strip().strip("'\"") for x in inner.split(",")]


def read_frontmatter(path: Path) -> tuple[dict[str, Any], str, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, "", str(exc)

    if not text.startswith("---\n"):
        return {}, text.strip(), "missing frontmatter"
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text.strip(), "unterminated frontmatter"

    meta: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            return meta, text[end + 5:].strip(), f"invalid frontmatter line: {line}"
        key, _, raw_val = line.partition(":")
        key = key.strip()
        raw_val = raw_val.strip()
        if raw_val.startswith("[") and raw_val.endswith("]"):
            meta[key] = parse_list(raw_val)
        else:
            meta[key] = raw_val.strip("'\"")
    return meta, text[end + 5:].strip(), None


def scope_for(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    parts = rel.parts
    if not parts:
        return "unknown"
    if parts[0] in {"global", "ephemeral", "review"}:
        return parts[0]
    if len(parts) >= 3 and parts[0] in {"project", "repo"}:
        return f"{parts[0]}:{parts[1]}"
    return parts[0]


def iter_memory_files(root: Path, scopes: set[str] | None, include_review: bool) -> list[Path]:
    allowed_top = {"global", "ephemeral", "project", "repo"}
    if include_review:
        allowed_top.add("review")

    files: list[Path] = []
    for path in root.rglob("*.md"):
        rel_parts = path.relative_to(root).parts
        if not rel_parts or rel_parts[0] not in allowed_top:
            continue
        scope = scope_for(path, root)
        if scopes and scope not in scopes:
            continue
        files.append(path)
    return sorted(files, key=lambda p: str(p))


def parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return date.fromisoformat(value)


def normalize_body(body: str) -> str:
    return re.sub(r"\s+", " ", body.strip().lower())


def parse_scope_roots(items: list[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"invalid --scope-root {item!r}; expected scope=/path")
        scope, raw_path = item.split("=", 1)
        scope = scope.strip()
        raw_path = raw_path.strip()
        if not scope or not raw_path:
            raise ValueError(f"invalid --scope-root {item!r}; expected scope=/path")
        roots[scope] = Path(raw_path).expanduser().resolve()

    cwd = Path.cwd().resolve()
    cwd_slug = slugify(cwd.name)
    if cwd_slug:
        roots.setdefault(f"project:{cwd_slug}", cwd)
        roots.setdefault(f"repo:{cwd_slug}", cwd)
    return roots


def clean_path_ref(value: str) -> str | None:
    # lstrip only opener/quote chars; preserve leading "." so .agents/, .casper/, .git/ survive
    ref = value.strip().lstrip("`'\"<>([{").rstrip("`'\"<>)]}.,;:")
    if not ref or "://" in ref or "*" in ref or "…" in ref or "..." in ref:
        return None
    if ref.startswith("//") or ref.startswith("-") or ref.startswith(","):
        return None
    if ref.startswith("/skill:") or ref.startswith("skill:"):
        return None
    if ref.startswith("./"):
        ref = ref[2:]
    # Single-segment absolute fragments (e.g. /cli.py, /data.md, /6) are typically
    # extraction artifacts from text like "…/parent/cli.py" — skip them.
    if ref.startswith("/") and "/" not in ref[1:]:
        return None
    return ref or None


def extract_path_refs(body: str, keywords: list[str]) -> list[str]:
    text = re.sub(r"https?://\S+", " ", body + "\n" + "\n".join(keywords))
    refs: set[str] = set()
    for regex in (ABS_PATH_RE, REL_PATH_RE, BARE_CODE_RE):
        for match in regex.findall(text):
            ref = clean_path_ref(match)
            if ref:
                refs.add(ref)
    return sorted(refs)


def has_symbol_anchor(body: str, keywords: list[str], path_refs: list[str]) -> bool:
    if path_refs:
        return True
    text = body + "\n" + "\n".join(keywords)
    if re.search(r"[A-Za-z_][A-Za-z0-9_]*(?:\(\)|\.[A-Za-z_][A-Za-z0-9_]*|::[A-Za-z_][A-Za-z0-9_]*)", text):
        return True
    # CamelCase identifiers (e.g. FlashAIChat, RBAC, OAuth)
    if re.search(r"\b[A-Z][a-z]+(?:[A-Z][a-z]*)+\b", text) or re.search(r"\b[A-Z]{2,}[a-z]?[A-Z]*\b", text):
        return True
    # Keywords carrying structural anchors: path segment, kebab identifier, snake/hash
    for kw in keywords:
        if not kw:
            continue
        if "/" in kw or "-" in kw or "_" in kw or "#" in kw:
            return True
    return False


def expand_absolute_ref(ref: str) -> Path:
    if ref.startswith("$HOME/"):
        return Path.home() / ref[len("$HOME/"):]
    return Path(ref).expanduser()


_URL_ENDPOINT_RE = re.compile(r"^/[a-z][a-z0-9_-]*(/[a-z0-9_:.-]+)*/?$")
_RUNTIME_PREFIXES = ("/app/", "/srv/", "/var/", "/tmp/", "/run/", "/opt/", "/etc/")


def _is_url_or_runtime_ref(ref: str) -> bool:
    """Heuristic: absolute ref is likely a URL endpoint or runtime path the doctor cannot verify.

    Skip when the ref has no file extension AND (matches URL-slug shape OR sits under a runtime
    prefix like /app/, /var/). Real filesystem paths almost always have an extension or live under
    /home, /mnt, /usr/local — they will not match this guard.
    """
    if any(seg.startswith(".") and "." in seg[1:] for seg in ref.split("/")):
        return False  # hidden file with extension, e.g. /foo/.env.local
    last = ref.rsplit("/", 1)[-1]
    if "." in last:
        return False  # has file extension → treat as real path
    if ref.startswith(_RUNTIME_PREFIXES):
        return True
    return bool(_URL_ENDPOINT_RE.match(ref))


def ref_exists(root: Path, ref: str) -> bool:
    candidate = root / ref
    if candidate.exists():
        return True
    # For both single-name and multi-segment refs, recursively search by basename and
    # verify the candidate path's tail matches the full ref. Handles cases where a
    # finding records a partial path (e.g. "scripts/build_attention_view.py") whose
    # full location lives a few directories deeper.
    basename = Path(ref).name
    try:
        for match in root.rglob(basename):
            if str(match).endswith("/" + ref) or str(match) == str(root / ref):
                return True
            if "/" not in ref:
                return True
        return False
    except OSError:
        return False


def lint_open_fields(
    path: Path,
    meta: dict[str, Any],
    updated: date | None,
    today: date,
    known_slugs: set[str],
) -> list[Issue]:
    issues: list[Issue] = []
    spath = str(path)

    status = meta.get("status")
    if status is not None and status not in OPEN_STATUSES:
        issues.append(Issue("error", "schema", spath, f"status must be one of {sorted(OPEN_STATUSES)}"))
        status = None

    priority = meta.get("priority")
    if priority is not None and priority not in OPEN_PRIORITIES:
        issues.append(Issue("error", "schema", spath, f"priority must be one of {sorted(OPEN_PRIORITIES)}"))

    parsed: dict[str, date | None] = {}
    for field in OPEN_DATE_FIELDS:
        if field not in meta:
            continue
        try:
            parsed[field] = parse_iso_date(meta.get(field))
            if parsed[field] is None:
                issues.append(Issue("error", "date", spath, f"{field} must be ISO date"))
        except ValueError:
            issues.append(Issue("error", "date", spath, f"{field} must be ISO date"))
            parsed[field] = None

    scheduled = parsed.get("scheduled")
    due = parsed.get("due")
    if scheduled and due and due < scheduled:
        issues.append(Issue("error", "date", spath, "due before scheduled"))

    blocked_by_raw = meta.get("blocked_by")
    blocked_by = str(blocked_by_raw).strip() if isinstance(blocked_by_raw, str) else ""
    if status == "blocked" and not blocked_by:
        issues.append(Issue("warning", "open-missing-blocker", spath, "status=blocked but blocked_by is empty"))
    if status == "done" and updated and (today - updated).days > OPEN_DONE_STALE_DAYS:
        issues.append(Issue(
            "warning",
            "open-done-stale",
            spath,
            f"status=done for more than {OPEN_DONE_STALE_DAYS} days; consider deleting",
        ))
    if due and due < today and status != "done":
        issues.append(Issue("warning", "open-overdue", spath, f"due {due.isoformat()} passed and status is {status or 'unset'}"))
    if scheduled and scheduled < today and status in (None, "pending"):
        issues.append(Issue(
            "warning",
            "open-scheduled-overdue",
            spath,
            f"scheduled {scheduled.isoformat()} passed but status is {status or 'unset'}",
        ))
    started = parsed.get("started")
    if started and status == "active" and (today - started).days > OPEN_LONG_RUNNING_DAYS:
        issues.append(Issue(
            "warning",
            "open-long-running",
            spath,
            f"task active for {(today - started).days} days since {started.isoformat()}",
        ))

    related_raw = meta.get("related")
    if related_raw is not None:
        if not isinstance(related_raw, list):
            issues.append(Issue("error", "schema", spath, "related must be list"))
        else:
            for entry in related_raw:
                slug = str(entry).strip()
                if not slug:
                    issues.append(Issue("warning", "open-broken-link", spath, "related contains empty entry"))
                    continue
                if slug.endswith(".md"):
                    slug = slug[:-3]
                if slug not in known_slugs:
                    issues.append(Issue("warning", "open-broken-link", spath, f"related slug {slug!r} does not match any memory file"))

    return issues


def lint_finding_paths(note: Note, roots: dict[str, Path]) -> list[Issue]:
    issues: list[Issue] = []
    refs = extract_path_refs(note.body, note.keywords)
    if not has_symbol_anchor(note.body, note.keywords, refs):
        issues.append(Issue("warning", "finding-anchor", str(note.path), "finding should include path or symbol anchor"))

    root = roots.get(note.scope)
    unresolved_reported = False
    for ref in refs:
        if ref.startswith("/") or ref.startswith("~/") or ref.startswith("$HOME/"):
            if not expand_absolute_ref(ref).exists():
                if _is_url_or_runtime_ref(ref):
                    continue
                issues.append(Issue("warning", "stale-finding-path", str(note.path), f"referenced path missing: {ref}"))
            continue

        if root is None:
            if not unresolved_reported:
                issues.append(Issue(
                    "warning",
                    "unresolved-scope-root",
                    note.scope,
                    f"cannot verify relative finding paths; pass --scope-root {note.scope}=/path",
                ))
                unresolved_reported = True
            continue

        if not ref_exists(root, ref):
            issues.append(Issue("warning", "stale-finding-path", str(note.path), f"path missing under {root}: {ref}"))
    return issues


def check_list_items(path: Path, field: str, items: list[str], low: int, high: int) -> list[Issue]:
    issues: list[Issue] = []
    spath = str(path)
    if len(items) < low or len(items) > high:
        issues.append(Issue("warning", f"{field}-count", spath, f"{field} should contain {low}-{high} items"))

    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str) or not item.strip():
            issues.append(Issue("warning", f"{field}-empty", spath, f"{field} contains empty item"))
            continue
        if item != item.strip():
            issues.append(Issue("warning", f"{field}-whitespace", spath, f"{field} item has surrounding whitespace: {item!r}"))
        normalized = item.strip().lower()
        if field == "tags" and item.strip() != normalized:
            issues.append(Issue("warning", "tag-case", spath, f"tag should be lowercase: {item}"))
        if normalized in seen:
            issues.append(Issue("warning", f"{field}-duplicate", spath, f"duplicate {field[:-1]}: {item}"))
        seen.add(normalized)
    return issues


def lint(root: Path, scopes: set[str] | None, include_review: bool, roots: dict[str, Path]) -> tuple[list[Issue], int]:
    if not root.is_dir():
        return [Issue("error", "root-missing", str(root), "memory root not found")], 0

    issues: list[Issue] = []
    notes: list[Note] = []
    files = iter_memory_files(root, scopes, include_review)
    today = date.today()
    known_slugs: set[str] = {p.stem for p in root.rglob("*.md")}

    for path in files:
        meta, body, parse_error = read_frontmatter(path)
        scope = scope_for(path, root)
        spath = str(path)

        if parse_error:
            issues.append(Issue("error", "schema", spath, parse_error))

        if meta.get("type") != "memory":
            issues.append(Issue("error", "schema", spath, "type must be memory"))

        memory_type = meta.get("memory_type")
        if memory_type not in MEMORY_TYPES:
            issues.append(Issue("error", "schema", spath, f"memory_type must be one of {sorted(MEMORY_TYPES)}"))
            memory_type = str(memory_type or "")

        tags_raw = meta.get("tags", [])
        keywords_raw = meta.get("keywords", [])
        if not isinstance(tags_raw, list):
            issues.append(Issue("error", "schema", spath, "tags must be list"))
            tags: list[str] = []
        else:
            tags = [str(t) for t in tags_raw]
        if not isinstance(keywords_raw, list):
            issues.append(Issue("error", "schema", spath, "keywords must be list"))
            keywords: list[str] = []
        else:
            keywords = [str(k) for k in keywords_raw]

        issues.extend(check_list_items(path, "tags", tags, 2, 5))
        # Rule and workflow memories are often short preference statements with
        # nothing meaningful to add as keywords; relax their lower bound to 1.
        kw_low = 1 if memory_type in {"rule", "workflow"} else 5
        issues.extend(check_list_items(path, "keywords", keywords, kw_low, 15))

        parsed_dates: dict[str, date | None] = {}
        for field in ("created", "updated", "expires"):
            if field not in meta:
                if field in {"created", "updated"}:
                    issues.append(Issue("error", "date", spath, f"{field} is required"))
                continue
            try:
                parsed_dates[field] = parse_iso_date(meta.get(field))
                if parsed_dates[field] is None:
                    issues.append(Issue("error", "date", spath, f"{field} must be ISO date"))
            except ValueError:
                issues.append(Issue("error", "date", spath, f"{field} must be ISO date"))
                parsed_dates[field] = None

        created = parsed_dates.get("created")
        updated = parsed_dates.get("updated")
        expires = parsed_dates.get("expires")
        if created and updated and updated < created:
            issues.append(Issue("error", "date", spath, "updated before created"))
        if expires and expires < today:
            issues.append(Issue("warning", "expired", spath, f"memory expired on {expires.isoformat()}"))

        stripped_body = body.strip()
        if not stripped_body:
            issues.append(Issue("error", "body", spath, "body is empty"))
        elif len(stripped_body) > BODY_WARN_CHARS:
            issues.append(Issue("warning", "body-long", spath, f"body longer than {BODY_WARN_CHARS} chars"))
        if "\n" in stripped_body:
            issues.append(Issue("warning", "body-multiline", spath, "atomic memory body should usually be one sentence/paragraph"))

        note = Note(
            path=path,
            scope=scope,
            memory_type=memory_type,
            body=stripped_body,
            tags=tags,
            keywords=keywords,
            tokens=tokenize(stripped_body),
        )
        notes.append(note)
        if note.memory_type == "finding":
            issues.extend(lint_finding_paths(note, roots))
        if note.memory_type == "open":
            issues.extend(lint_open_fields(path, meta, updated, today, known_slugs))

    by_body: dict[tuple[str, str, str], Path] = {}
    for note in notes:
        normalized = normalize_body(note.body)
        if not normalized:
            continue
        key = (note.scope, note.memory_type, normalized)
        if key in by_body:
            issues.append(Issue("error", "duplicate-body", str(note.path), f"duplicate body: {by_body[key]}"))
        else:
            by_body[key] = note.path

    for i, left in enumerate(notes):
        if not left.body or not left.tokens:
            continue
        for right in notes[i + 1:]:
            if left.scope != right.scope or left.memory_type != right.memory_type:
                continue
            if not right.body or not right.tokens:
                continue
            if normalize_body(left.body) == normalize_body(right.body):
                continue
            threshold = DUP_SIMILARITY_THRESHOLDS.get(left.memory_type, DUP_SIMILARITY_DEFAULT)
            similarity = jaccard(left.tokens, right.tokens)
            if similarity >= threshold:
                issues.append(Issue(
                    "warning",
                    "near-duplicate",
                    str(right.path),
                    f"similarity {similarity:.3f} with {left.path}",
                ))

    issues.sort(key=lambda x: (x.severity != "error", x.code, x.path, x.message))
    return issues, len(files)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint $HOME/.agents/memory notes")
    parser.add_argument("--scope", action="append", default=[], help="Scope label to scan, e.g. global, project:<slug>, repo:<slug>. Repeatable.")
    parser.add_argument("--include-review", action="store_true", help="Include review/ files (excluded by default).")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--fail-on-warning", action="store_true", help="Exit 1 when warnings exist.")
    parser.add_argument("--scope-root", action="append", default=[], metavar="SCOPE=/PATH", help="Project/repo root for stale finding checks. Repeatable.")
    return parser


def render_text(scanned: int, errors: list[Issue], warnings: list[Issue]) -> str:
    lines = [
        "# Memory Doctor",
        "",
        f"Scanned: {scanned}",
        f"Errors: {len(errors)}",
        f"Warnings: {len(warnings)}",
        "",
        "## Errors",
    ]
    if errors:
        lines.extend(f"- {i.path}: [{i.code}] {i.message}" for i in errors)
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings"])
    if warnings:
        lines.extend(f"- {i.path}: [{i.code}] {i.message}" for i in warnings)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        roots = parse_scope_roots(args.scope_root)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    issues, scanned = lint(MEMORY_ROOT, set(args.scope) or None, args.include_review, roots)
    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]

    if args.format == "json":
        print(json.dumps({
            "summary": {"scanned": scanned, "errors": len(errors), "warnings": len(warnings)},
            "issues": [asdict(issue) for issue in issues],
        }, indent=2, ensure_ascii=False))
    else:
        print(render_text(scanned, errors, warnings), end="")

    if errors or (args.fail_on_warning and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
