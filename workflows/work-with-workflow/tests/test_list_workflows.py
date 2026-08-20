"""Frontmatter parsing tests for list_workflows.py."""

from __future__ import annotations

from pathlib import Path

from list_workflows import collect, drop_shadowed, extract_frontmatter, workflow_folder


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_trigger_only(tmp_path: Path) -> None:
    path = write(tmp_path, "a.md", "---\ntrigger: Just a trigger.\n---\nbody\n")
    assert extract_frontmatter(path) == {"trigger": "Just a trigger."}


def test_model_and_effort(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "b.md",
        "---\ntrigger: With settings.\nmodel: gpt-5.6-sol\neffort: high\n---\n",
    )
    assert extract_frontmatter(path) == {
        "trigger": "With settings.",
        "model": "gpt-5.6-sol",
        "effort": "high",
    }


def test_quoted_values_are_unquoted(tmp_path: Path) -> None:
    path = write(tmp_path, "c.md", '---\ntrigger: "Quoted."\nmodel: \'opus\'\n---\n')
    assert extract_frontmatter(path) == {"trigger": "Quoted.", "model": "opus"}


def test_no_frontmatter(tmp_path: Path) -> None:
    path = write(tmp_path, "d.md", "# heading\ntrigger: not frontmatter\n")
    assert extract_frontmatter(path) == {}


def test_unknown_keys_ignored(tmp_path: Path) -> None:
    path = write(tmp_path, "e.md", "---\ntrigger: Ok.\ndescription: legacy\nauthor: bob\n---\n")
    assert extract_frontmatter(path) == {"trigger": "Ok."}


def test_collect_requires_trigger(tmp_path: Path) -> None:
    write(tmp_path, "listed.md", "---\ntrigger: Listed.\n---\n")
    write(tmp_path, "helper.md", "---\nmodel: opus\n---\n")  # no trigger
    write(tmp_path, "legacy.md", "---\ndescription: Old key.\n---\n")  # no trigger
    write(tmp_path, "plain.md", "no frontmatter\n")
    assert [p.name for p in collect(tmp_path)] == ["listed.md"]


def test_project_local_folder_shadows_global(tmp_path: Path) -> None:
    """A project-local folder name hides the same-named global folder's entries."""
    global_dir = tmp_path / "global"
    project_dir = tmp_path / "project" / ".agents" / "workflows"
    for base, name in ((global_dir, "Global"), (project_dir, "Project")):
        (base / "shared").mkdir(parents=True)
        write(base / "shared", "shared.md", f"---\ntrigger: {name} shared.\n---\n")
    (global_dir / "global-only").mkdir()
    write(global_dir / "global-only", "solo.md", "---\ntrigger: Global only.\n---\n")
    write(global_dir, "top-level.md", "---\ntrigger: Top level global.\n---\n")

    project_entries = collect(project_dir)
    shadow_names = {workflow_folder(p, project_dir) for p in project_entries}
    assert shadow_names == {"shared"}

    kept = drop_shadowed(collect(global_dir), global_dir, shadow_names)
    assert [p.relative_to(global_dir).as_posix() for p in kept] == [
        "global-only/solo.md",
        "top-level.md",
    ]
    assert [p.relative_to(project_dir).as_posix() for p in project_entries] == [
        "shared/shared.md"
    ]


def test_workflow_folder_of_top_level_file_is_none(tmp_path: Path) -> None:
    path = write(tmp_path, "top.md", "---\ntrigger: Top.\n---\n")
    assert workflow_folder(path, tmp_path) is None
