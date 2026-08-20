#!/usr/bin/env python3
"""Scaffold and retire bug-fix implementation plans under <project>/.agents/handovers/.

Two deterministic ends of the bug-fix workflow live here; the judgment work
(investigate, repro, write tests, implement fix) stays with the LLM.

  scaffold  Create .agents/handovers/<slug>.md from the standard bug-fix template.
  complete  Gate deletion of a plan on every Done-criteria checkbox being checked.

The plan lives in the *user's current project*, not in ~/.agents. The project
root is resolved from --repo-root, else `git rev-parse --show-toplevel`, else cwd.

Exit codes:
  0  success
  1  plan incomplete (boxes remain) / nothing to do
  2  usage error or plan file not found
  3  scaffold conflict (plan already exists)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Matches a markdown task checkbox line: "- [ ] ..." or "- [x] ...".
CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<label>.*)$")

HANDOVERS_SUBDIR = Path(".agents") / "handovers"

TEMPLATE = """# Bug Fix Plan: {title}

> slug: `{slug}` · created: {date}
> Retire this file via `bug_fix_plan.py complete --slug {slug}` once every box
> under **Done Criteria** is checked. Do not delete it by hand.

## 1. Symptom / Report
<What the user reported: the observed wrong behavior, error text, or breakage.
Quote the exact message/log. Note where it surfaced and who/what hit it.>

## 2. Reproduction Steps
<Exact, ordered, minimal steps to reproduce. Include environment, inputs, data,
and the precise expected-vs-actual divergence.>

1.
2.

- Expected:
- Actual:

## 3. Root Cause
<The underlying cause with `file:line` references and a causal explanation of
why it produces the symptom. Not "where it's caught" — why it happens.>

## 4. Automation Test Plan  (write these BEFORE touching the fix)
List every test to add/modify that FAILS before the fix and PASSES after. Never
start the fix until these exist and are confirmed red. Pick the layers that fit
the bug; for any layer you skip, state why it does not apply.

- [ ] Unit test — `<path>` · asserts: <...>
- [ ] Integration test — `<path>` · asserts: <...>
- [ ] Browser / e2e test — `<path>` · asserts: <...>  (skip only if no UI surface — say why)

## 5. Implementation Steps
<Ordered fix steps with `file:line` targets. Reuse existing utilities; match the
surrounding code's style and altitude.>

1.

## 6. Verification
<Exact commands to run the tests above and confirm green, plus any manual check.
Show the command lines so the next session can re-run them verbatim.>

```
```

## Done Criteria
- [ ] Root cause identified and documented in §3
- [ ] Reproduction steps in §2 confirmed to actually reproduce the bug
- [ ] Automation tests written and confirmed FAILING before the fix (unit / integration / browser as applicable)
- [ ] Fix implemented per §5
- [ ] All automation tests now PASS
- [ ] Verification commands in §6 run and green
"""


def project_root(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        top = out.stdout.strip()
        if top:
            return Path(top).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return Path.cwd().resolve()


def plan_path(root: Path, slug: str) -> Path:
    return root / HANDOVERS_SUBDIR / f"{slug}.md"


def title_from_slug(slug: str) -> str:
    return slug.replace("-", " ").strip().capitalize()


def cmd_scaffold(args: argparse.Namespace) -> int:
    slug = args.slug.strip()
    if not SLUG_RE.match(slug):
        print(f"error: --slug must be kebab-case (got {slug!r})")
        return 2
    root = project_root(args.repo_root)
    path = plan_path(root, slug)
    if path.exists():
        print(f"error: plan already exists: {path}")
        print("edit it, or pick a different --slug.")
        return 3
    title = args.title.strip() if args.title else title_from_slug(slug)
    date = args.date.strip() if args.date else _dt.date.today().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(title=title, slug=slug, date=date), encoding="utf-8")
    print(path)
    return 0


def _resolve_plan(args: argparse.Namespace) -> Path | None:
    if args.path:
        return Path(args.path).expanduser().resolve()
    if not args.slug:
        return None
    return plan_path(project_root(args.repo_root), args.slug.strip())


def cmd_complete(args: argparse.Namespace) -> int:
    path = _resolve_plan(args)
    if path is None:
        print("error: pass --slug <slug> or --path <file>")
        return 2
    if not path.is_file():
        print(f"error: plan not found: {path}")
        return 2

    unchecked: list[str] = []
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        m = CHECKBOX_RE.match(line)
        if not m:
            continue
        total += 1
        if m.group("mark") == " ":
            unchecked.append(m.group("label").strip() or "(unlabeled)")

    if total == 0:
        print(f"warning: no checkboxes found in {path}")

    if unchecked and not args.force:
        print(f"plan INCOMPLETE — {len(unchecked)}/{total} box(es) still open in {path}:")
        for label in unchecked:
            print(f"  [ ] {label}")
        print("finish the work (or pass --force to delete anyway).")
        return 1

    if args.check:
        done = total - len(unchecked)
        print(f"plan COMPLETE ({done}/{total}) — ready to delete: {path}")
        return 0

    path.unlink()
    print(f"deleted completed plan: {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scaffold", help="create .agents/handovers/<slug>.md from the template")
    sc.add_argument("--slug", required=True, help="kebab-case plan slug, e.g. login-500-on-empty-email")
    sc.add_argument("--title", help="human title (default: derived from slug)")
    sc.add_argument("--repo-root", help="project root (default: git toplevel, else cwd)")
    sc.add_argument("--date", help="created date (default: today, ISO)")
    sc.set_defaults(func=cmd_scaffold)

    cp = sub.add_parser("complete", help="delete the plan only if every Done box is checked")
    cp.add_argument("--slug", help="plan slug (resolves to .agents/handovers/<slug>.md)")
    cp.add_argument("--path", help="explicit path to the plan file (overrides --slug)")
    cp.add_argument("--repo-root", help="project root (default: git toplevel, else cwd)")
    cp.add_argument("--check", action="store_true", help="report status only; do not delete")
    cp.add_argument("--force", action="store_true", help="delete even if boxes remain")
    cp.set_defaults(func=cmd_complete)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
