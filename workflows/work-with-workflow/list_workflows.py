#!/usr/bin/env python3
"""List repo workflows using file path and trigger frontmatter.

Scans for Markdown files whose frontmatter contains `trigger`, both directly
inside a workflow dir and one level deep (`*.md` and `*/*.md`), so one
workflow folder may hold several discoverable files:
- Global:        `~/.agents/workflows/` (this repo)
- Project-local: the nearest `.agents/workflows/` found by walking up from
  the current working directory (skipped when it resolves to the global dir).

A file without a `trigger` value is not a discovery entry; `description` is
no longer read at all. Optional `model` and `effort` are read when present.

Project-over-global shadowing: when a project-local workflow *folder* name
equals a global workflow folder name, the project-local entries win and the
global folder's entries are not listed.

Outputs a Markdown table with 4 columns:
- Path
- Trigger
- Model  (optional frontmatter; empty = harness default)
- Effort (optional frontmatter; empty = harness default)

Display rules:
- Global workflows -> path relative to `~/.agents` (e.g. `workflows/...`)
- Project-local    -> path relative to the project root (e.g.
  `.agents/workflows/...`)

Exit codes:
  0  success
  1  no workflow files found
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_WORKFLOW_DIR = REPO_ROOT / "workflows"

# Project-local workflow locations, searched by walking up from the cwd.
PROJECT_WORKFLOW_SUBDIRS = (Path(".agents") / "workflows",)


def find_project_workflow_dirs(start: Path) -> list[tuple[Path, Path]]:
    """Nearest project-local workflow dirs walking up from `start`.

    For each entry in PROJECT_WORKFLOW_SUBDIRS, return the nearest match as
    `(workflow_dir, project_root)`. The global dir is excluded so it is never
    reported twice.
    """
    global_resolved = GLOBAL_WORKFLOW_DIR.resolve()
    found: list[tuple[Path, Path]] = []
    for sub in PROJECT_WORKFLOW_SUBDIRS:
        for base in (start, *start.parents):
            candidate = base / sub
            if candidate.is_dir() and candidate.resolve() != global_resolved:
                found.append((candidate, base))
                break
    return found


FRONTMATTER_KEYS = ("trigger", "model", "effort")


def extract_frontmatter(path: Path) -> dict[str, str]:
    """Read known frontmatter keys. Empty dict when there is no frontmatter."""
    fields: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            first = handle.readline()
            if first.startswith("﻿"):
                first = first.lstrip("﻿")

            if first.strip() != "---":
                return {}

            for line in handle:
                stripped = line.rstrip("\n")
                if stripped in {"---", "..."}:
                    break
                for key in FRONTMATTER_KEYS:
                    if stripped.startswith(f"{key}:"):
                        value = stripped.split(":", 1)[1].strip()
                        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                            value = value[1:-1]
                        fields[key] = value
                        break
    except OSError:
        return {}

    return fields


def escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


def collect(dir_path: Path) -> list[Path]:
    if not dir_path.is_dir():
        return []
    paths = set(dir_path.glob("*.md")) | set(dir_path.glob("*/*.md"))
    return sorted(p for p in paths if extract_frontmatter(p).get("trigger"))


def workflow_folder(path: Path, base: Path) -> str | None:
    """Workflow folder name of an entry, or None for a file directly in `base`."""
    try:
        rel = path.resolve().relative_to(base.resolve())
    except ValueError:
        return None
    return rel.parts[0] if len(rel.parts) > 1 else None


def drop_shadowed(entries: list[Path], base: Path, shadow_names: set[str]) -> list[Path]:
    """Drop entries whose workflow folder name is claimed by a project-local folder."""
    return [p for p in entries if workflow_folder(p, base) not in shadow_names]


def display_path(path: Path, project_roots: list[Path]) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        pass
    for root in project_roots:
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            pass
    return str(resolved)


def main() -> int:
    project_dirs = find_project_workflow_dirs(Path.cwd())
    project_roots = [root for _, root in project_dirs]

    project_entries: list[Path] = []
    shadow_names: set[str] = set()
    for workflow_dir, _ in project_dirs:
        found = collect(workflow_dir)
        project_entries += found
        shadow_names |= {
            name for p in found if (name := workflow_folder(p, workflow_dir)) is not None
        }

    entries = drop_shadowed(collect(GLOBAL_WORKFLOW_DIR), GLOBAL_WORKFLOW_DIR, shadow_names)
    entries += project_entries

    if not entries:
        return 1

    print("| Path | Trigger | Model | Effort |")
    print("| ---- | ------- | ----- | ------ |")
    for path in entries:
        rel = display_path(path, project_roots)
        fields = extract_frontmatter(path)
        trigger = escape_markdown_cell(fields.get("trigger", ""))
        model = escape_markdown_cell(fields.get("model", ""))
        effort = escape_markdown_cell(fields.get("effort", ""))
        print(f"| `{rel}` | {trigger} | {model} | {effort} |")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
