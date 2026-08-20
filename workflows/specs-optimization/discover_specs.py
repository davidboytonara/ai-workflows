#!/usr/bin/env python3
"""Discover a repo's spec/doc corpus and infer its current categorization.

Generic across repos (no hardcoded paths). Probes common spec roots, treats the
root's top-level folders as categories, detects navigation-aid files, parses a
declared domain map if present, and inventories every markdown file. Writes a
manifest.json consumed by harvest_nav.py and by the workflow's prompt-generation
and report steps.

Exit codes:
  0  spec/doc corpus found, manifest written
  1  no spec/doc corpus found
  2  usage error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml  # PyYAML lives in the shared $HOME/.agents/.venv
except Exception:  # pragma: no cover - yaml is expected but degrade gracefully
    yaml = None

# discover_specs.py -> specs-optimization/ -> workflows/ -> repo
REPO_ROOT = Path(__file__).resolve().parents[2]

# Candidate spec roots, highest priority first.
CANDIDATE_ROOTS = (
    "docs/specs",
    "docs/spec",
    "specs",
    "spec",
    "docs",
    "doc",
    "documentation",
    ".agents/specs",
    "architecture",
)

# Dirs never worth scanning for a markdown corpus.
IGNORE_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", ".venv", "venv",
    "__pycache__", ".cache", ".next", ".turbo", "coverage", ".pytest_cache",
    ".mypy_cache", "target", ".idea", ".vscode",
}

# (role, regex on the basename) — first match wins.
NAV_AID_RULES = (
    ("index", re.compile(r"^_?index\.md$", re.I)),
    ("overview", re.compile(r"^overview\.md$", re.I)),
    ("glossary", re.compile(r"^glossary\.md$", re.I)),
    ("readme", re.compile(r"^readme\.md$", re.I)),
    ("current-state", re.compile(r"^current[-_]state\.md$", re.I)),
    ("domain-map", re.compile(r"^domain[-_]map\.(ya?ml|json)$", re.I)),
    ("domain-map", re.compile(r".*map.*\.(ya?ml|json)$", re.I)),
)

NUMBERED_RE = re.compile(r"^(\d{1,3})[-_]")
HEADING_RE = re.compile(r"^#{1,6}\s")


def nav_aid_role(name: str) -> str | None:
    for role, rx in NAV_AID_RULES:
        if rx.match(name):
            return role
    return None


def iter_md(root: Path):
    """Yield every *.md path under root, pruning ignored dirs."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".git")]
        for fn in filenames:
            if fn.lower().endswith(".md"):
                yield Path(dirpath) / fn


def count_md(root: Path) -> int:
    n = 0
    for _ in iter_md(root):
        n += 1
        if n >= 10000:  # plenty; avoid pathological trees
            break
    return n


def pick_specs_root(repo_root: Path, min_md: int) -> tuple[Path | None, str]:
    """Return (specs_root, discovered_by) or (None, reason)."""
    for rel in CANDIDATE_ROOTS:
        cand = repo_root / rel
        if cand.is_dir() and count_md(cand) >= min_md:
            return cand, f"probe:{rel}"

    # Fallback: densest top-level subdir by recursive md count.
    best: tuple[int, Path] | None = None
    for child in sorted(repo_root.iterdir() if repo_root.is_dir() else []):
        if not child.is_dir() or child.name in IGNORE_DIRS or child.name.startswith("."):
            continue
        c = count_md(child)
        if c >= min_md and (best is None or c > best[0]):
            best = (c, child)
    if best is not None:
        return best[1], f"fallback:densest:{best[1].name}"

    # Last resort: loose markdown directly in the repo root.
    if count_md(repo_root) >= min_md:
        return repo_root, "fallback:repo-root"

    return None, "no-corpus"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def title_and_headings(text: str) -> tuple[str, int, bool]:
    lines = text.splitlines()
    fm = bool(lines) and lines[0].strip() == "---"
    start = 0
    if fm:
        for j in range(1, min(len(lines), 200)):
            if lines[j].strip() in {"---", "..."}:
                start = j + 1
                break
    title = ""
    for line in lines[start:start + 80]:
        s = line.strip()
        if s.startswith("# "):
            title = s[2:].strip()
            break
    headings = sum(1 for l in lines if HEADING_RE.match(l))
    return title, headings, fm


def parse_declared(path: Path) -> tuple[list[dict], str | None]:
    try:
        raw = read_text(path)
        if path.suffix.lower() == ".json":
            data = json.loads(raw)
        elif yaml is not None:
            data = yaml.safe_load(raw)
        else:
            return [], "pyyaml-missing"
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        return [], f"parse-error: {exc}"

    domains = None
    if isinstance(data, dict):
        for key in ("domains", "categories", "sections", "areas", "specs"):
            if isinstance(data.get(key), list):
                domains = data[key]
                break
    elif isinstance(data, list):
        domains = data
    if domains is None:
        return [], None

    declared: list[dict] = []
    for d in domains:
        if isinstance(d, dict):
            declared.append({
                "id": d.get("id") or d.get("number") or d.get("order") or d.get("prefix"),
                "name": d.get("name") or d.get("title") or d.get("slug") or d.get("dir"),
                "src_prefixes": d.get("src_prefixes") or d.get("paths") or d.get("globs") or [],
            })
        elif isinstance(d, str):
            declared.append({"id": None, "name": d, "src_prefixes": []})
    return declared, None


def category_of(rel_parts: tuple[str, ...]) -> str:
    return rel_parts[0] if len(rel_parts) > 1 else "(root)"


def build_manifest(repo_root: Path, specs_root: Path, discovered_by: str) -> dict:
    files: list[dict] = []
    cat_stats: dict[str, dict] = {}
    fm_yes = fm_no = 0

    for md in iter_md(specs_root):
        rel = md.relative_to(specs_root)
        parts = rel.parts
        cat = category_of(parts)
        text = read_text(md)
        title, headings, fm = title_and_headings(text)
        fm_yes += int(fm)
        fm_no += int(not fm)
        try:
            size = md.stat().st_size
            mtime = int(md.stat().st_mtime)
        except OSError:
            size = len(text.encode("utf-8"))
            mtime = 0
        files.append({
            "path": str(md),
            "rel": rel.as_posix(),
            "category": cat,
            "bytes": size,
            "title": title,
            "heading_count": headings,
            "mtime": mtime,
        })
        st = cat_stats.setdefault(cat, {"md_count": 0, "bytes_total": 0})
        st["md_count"] += 1
        st["bytes_total"] += size

    # Category metadata from the directory layout.
    categories: list[dict] = []
    for child in sorted(p for p in specs_root.iterdir() if p.is_dir() and p.name not in IGNORE_DIRS and not p.name.startswith(".")):
        name = child.name
        st = cat_stats.get(name, {"md_count": 0, "bytes_total": 0})
        m = NUMBERED_RE.match(name)
        subdirs = sum(1 for x in child.iterdir() if x.is_dir())
        categories.append({
            "name": name,
            "is_numbered": bool(m),
            "order": int(m.group(1)) if m else None,
            "md_count": st["md_count"],
            "bytes_total": st["bytes_total"],
            "subdir_count": subdirs,
            "nav_aids": nav_aids_in(child, depth_one=True),
        })
    if "(root)" in cat_stats:
        st = cat_stats["(root)"]
        categories.append({
            "name": "(root)", "is_numbered": False, "order": None,
            "md_count": st["md_count"], "bytes_total": st["bytes_total"],
            "subdir_count": 0, "nav_aids": [],
        })
    categories.sort(key=lambda c: (c["order"] is None, c["order"] if c["order"] is not None else 0, c["name"]))

    nav_aids_root = nav_aids_in(specs_root, depth_one=True)

    # Declared domain map, if any (search root-level nav-aids of role domain-map).
    declared: list[dict] = []
    domain_map_path = None
    domain_map_error = None
    for na in nav_aids_root:
        if na["role"] == "domain-map":
            domain_map_path = na["path"]
            declared, domain_map_error = parse_declared(Path(na["path"]))
            break

    if fm_yes and fm_no:
        fm_style = "mixed"
    elif fm_yes:
        fm_style = "yaml"
    else:
        fm_style = "none"

    return {
        "repo_root": str(repo_root),
        "specs_root": str(specs_root),
        "discovered_by": discovered_by,
        "style": {
            "numbered_folders": any(c["is_numbered"] for c in categories),
            "frontmatter": fm_style,
        },
        "categories": categories,
        "nav_aids_root": nav_aids_root,
        "declared_categories": declared,
        "domain_map_path": domain_map_path,
        "domain_map_error": domain_map_error,
        "files": files,
        "totals": {
            "categories": len([c for c in categories if c["name"] != "(root)"]),
            "files": len(files),
            "bytes": sum(f["bytes"] for f in files),
        },
    }


def nav_aids_in(directory: Path, depth_one: bool) -> list[dict]:
    """Detect nav-aid files directly inside `directory` (non-recursive)."""
    out: list[dict] = []
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return out
    for p in entries:
        if not p.is_file():
            continue
        role = nav_aid_role(p.name)
        if role:
            out.append({"role": role, "path": str(p), "name": p.name})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover a repo's spec/doc corpus and infer its categorization.")
    parser.add_argument("--repo-root", default=os.getcwd(), help="Repo to inspect (default: cwd).")
    parser.add_argument("--out", default="-", help="Write manifest JSON here (default: stdout).")
    parser.add_argument("--min-md", type=int, default=3, help="Min markdown files for a dir to qualify (default: 3).")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser()
    if not repo_root.is_dir():
        print(f"error: repo-root not a directory: {repo_root}", file=sys.stderr)
        return 2

    specs_root, discovered_by = pick_specs_root(repo_root.resolve(), args.min_md)
    if specs_root is None:
        print(f"no spec/doc corpus found under {repo_root} (min-md={args.min_md})", file=sys.stderr)
        return 1

    manifest = build_manifest(repo_root.resolve(), specs_root.resolve(), discovered_by)

    payload = json.dumps(manifest, indent=2)
    if args.out == "-":
        print(payload)
    else:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        t = manifest["totals"]
        print(
            f"manifest: {out} | specs_root={manifest['specs_root']} "
            f"({discovered_by}) | categories={t['categories']} files={t['files']} "
            f"declared={len(manifest['declared_categories'])}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
