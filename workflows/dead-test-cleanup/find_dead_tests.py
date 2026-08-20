#!/usr/bin/env python3
"""Detect candidate dead automation-test code in a target repo.

This is a bounded recon aid producing candidate EVIDENCE, not an oracle:
every item is a lead with recorded evidence for later human/LLM vetting
(see detection-guide.md). Nothing here proves a deletion is safe.

Categories emitted:
  orphan-helper     under a test root, matches no runner glob, and no
                    import/require/from/path-string reference to it exists
                    across the repo's code/config files (docs trees,
                    markdown, lockfiles and build outputs are excluded from
                    the reference corpus: prose catalogues do not execute
                    code, and counting them would hide true orphans).
  orphan-test-file  test-named (*.test.*, *.spec.*, test_*.py, *_test.py,
                    *.feature) under a test root, matches no extracted or
                    supplied runner glob.
  orphan-dir        immediate subdir of a test root: no glob matches any
                    file under it, no runner config points at it, and no
                    outside file references the dir or any candidate in it
                    (dirs kept alive purely by imports are helpers, not
                    orphans — the extra reference test suppresses those).
  uninvoked-suite   npm script whose body invokes a runner binary
                    (node/tsx --test, playwright, cucumber-js, pytest,
                    jest, vitest, mocha, c8, nyc) with zero inbound edges
                    from any CI file, hook config, npm lifecycle script, or
                    their transitively chased in-repo shell/JS/TS files
                    (chase bounded to invocation plumbing: root-level files
                    and script/tool/CI dirs, each in-repo and < 200 KB).
                    Comment and echo lines are stripped before edge
                    extraction so prose mentions do not count as calls, and
                    shell blocks behind opt-in env guards (first test
                    decidably false under default env, e.g.
                    `[ "${CI_FULL:-0}" = "1" ]`) are treated as manual
                    escape hatches, not CI invocations.
  vacuous-scenario  ONLY from --vacuous-list (the repo's OWN detector
                    output); otherwise the category is recorded skipped and
                    hints.vacuous_detector_candidates lists scripts whose
                    name/body mentions "vacuous".

Monorepo-aware: every package.json outside node_modules/vendor/build dirs
is parsed; scripts are namespaced <pkg-dir>#<name> (bare name for the root
package). Best-effort extraction with provenance: configs it cannot parse
land in extraction.unparsed_configs and cap affected confidence at low.
Confidence is high only with complete relevant extraction; capped low when
unparsed configs cover the tree, a task runner (turbo/nx/lerna) is
detected, or zero CI files exist (vacuous items stay high — they come from
the repo's own detector).

Exit codes:
  0  inventory written, >=1 candidate
  1  inventory written, zero candidates
  2  usage error (bad flags, --repo-root not a git repo root)
  3  extraction too incomplete: no runner globs extracted and none supplied
     via --extra-globs (a partial extraction report is still written)
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import posixpath
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

# find_dead_tests.py -> dead-test-cleanup/ -> workflows/ -> ~/.agents
REPO_ROOT = Path(__file__).resolve().parents[2]

EXCLUDE_DIRS = {
    "node_modules", ".git", "dist", "build", "out", "coverage", "vendor",
    "var", ".venv", "venv", "site-packages", "__pycache__", ".next",
    ".nuxt", ".cache", "target", "secrets",
}
KEEP_DOTDIRS = {".github", ".circleci", ".husky"}
DOC_DIRS = {"docs", "doc"}
LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock",
    "poetry.lock", "uv.lock", "composer.lock", "Gemfile.lock",
}
CODE_EXTS = {
    ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".py",
    ".sh", ".bash", ".zsh", ".json", ".yml", ".yaml", ".toml", ".cfg",
    ".ini", ".feature", ".rb", ".go", ".rs", ".java",
}
BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip",
    ".gz", ".tar", ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4",
    ".wasm", ".sqlite", ".db", ".exe", ".bin", ".jar",
}
TEST_NAME_PATTERNS = ("*.test.*", "*.spec.*", "test_*.py", "*_test.py", "*.feature")
NEVER_FLAG = {"conftest.py", "__init__.py", "README.md", ".gitignore", ".gitkeep", ".DS_Store"}
LIFECYCLE = {
    "preinstall", "install", "postinstall", "prepare", "prepack",
    "postpack", "prepublish", "prepublishOnly", "preversion", "version",
    "postversion", "dependencies",
}
CHASE_EXTS = {".sh", ".bash", ".js", ".mjs", ".ts"}
# Chase only invocation plumbing: root-level files and files under
# script/tool/CI dirs. Application and test sources are never chased —
# their npm-command mentions are typically help text, not invocations.
CHASE_DIRS = {"scripts", "script", "tools", "tool", "ci", "bin", "hooks",
              ".github", ".circleci", ".husky"}
CHASE_MAX_FILES = 500
CHASE_MAX_BYTES = 200 * 1024
SCAN_MAX_BYTES = 1024 * 1024
CATEGORY_ORDER = ["uninvoked-suite", "orphan-dir", "orphan-test-file", "orphan-helper", "vacuous-scenario"]

NPM_RUN_RE = re.compile(r"\bnpm\s+(?:run|run-script)\s+([A-Za-z0-9:._-]+)")
NPM_TEST_RE = re.compile(r"\bnpm\s+(?:test|t)\b")
YARN_PNPM_RE = re.compile(r"\b(?:yarn|pnpm)\s+(?:run\s+)?([A-Za-z0-9:._-]+)")
RUN_SP_RE = re.compile(r"\b(?:run-s|run-p|npm-run-all)\b((?:\s+[A-Za-z0-9:*._'\"-]+)*)")
FILE_MENTION_RE = re.compile(r"[A-Za-z0-9_@./-]+\.(?:sh|bash|mjs|ts|js)\b")
QUOTED_TOKEN_RE = re.compile(r"['\"]([^'\"\s]+)['\"]")
RUNNER_BIN_RE = re.compile(r"(?<![\w./-])(playwright|cucumber-js|pytest|py\.test|jest|vitest|mocha|c8|nyc)(?![\w.-])")
NODE_TEST_RE = re.compile(r"\b(?:node|tsx)\b[^;&|]*?--test\b")


def norm_rel(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return posixpath.normpath(p) if p else p


def glob_to_regex(g: str) -> re.Pattern:
    g = norm_rel(g)
    i, out = 0, []
    while i < len(g):
        if g.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif g.startswith("**", i):
            out.append(".*")
            i += 2
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        elif g[i] == "?":
            out.append("[^/]")
            i += 1
        elif g[i] == "[":
            j = g.find("]", i + 2)  # +2: "[]" starts a literal-] class
            if j == -1:
                out.append(re.escape(g[i]))
                i += 1
            else:
                body = g[i + 1:j]
                neg = body.startswith(("!", "^"))
                if neg:
                    body = body[1:]
                body = body.replace("\\", "\\\\").replace("]", "\\]")
                out.append("[" + ("^" if neg else "") + body + "]")
                i = j + 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def static_prefix(g: str) -> str:
    m = re.search(r"[*?\[]", g)
    p = g if not m else g[: m.start()]
    return p.rsplit("/", 1)[0] if "/" in p else ""


def is_test_named(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in TEST_NAME_PATTERNS)


def strip_prose(text: str) -> str:
    """Drop full-line comments and echo lines before edge extraction."""
    kept = []
    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("#") or s.startswith("echo ") or s == "echo":
            continue
        kept.append(line)
    return "\n".join(kept)


# Matches [ "${VAR:-default}" = "literal" ] (also == / !=).
DECIDABLE_TEST_RE = re.compile(
    r'\[\s*"?\$\{(\w+):-([^}]*)\}"?\s*(!?==?)\s*"?([^\s"\]]*)"?')


def opt_in_guard_false(line: str) -> bool:
    """True when the first [ test ] on an if/elif line is decidably FALSE
    under default env (an opt-in escape hatch, e.g. `${CI_FULL:-0}` = "1").
    Compound `&&` chains with a false first test are false; `||` chains and
    unrecognized shapes are conservatively treated as runnable."""
    if "||" in line:
        return False
    m = DECIDABLE_TEST_RE.search(line)
    if not m:
        return False
    default, op, lit = m.group(2), m.group(3), m.group(4)
    true_by_default = (default != lit) if op == "!=" else (default == lit)
    return not true_by_default


def strip_gated(text: str) -> str:
    """Drop shell blocks behind opt-in env guards: they are manual escape
    hatches (e.g. CASPER_CI_FULL=1), not invocations CI performs."""
    out: list[str] = []
    stack: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("if ") or s.startswith("if["):
            suppress = opt_in_guard_false(s)
            if s.endswith("; fi") or s.endswith(";fi"):
                if not suppress and "suppress" not in stack:
                    out.append(line)
                continue
            stack.append("suppress" if suppress else "keep")
            continue
        if s.startswith("elif ") and stack:
            stack[-1] = "suppress" if opt_in_guard_false(s) else "keep"
            continue
        if (s == "else" or s.startswith("else ")) and stack:
            if stack[-1] == "suppress":
                stack[-1] = "keep"
            continue
        if s == "fi" or s.startswith(("fi ", "fi;", "fi#")):
            if stack:
                stack.pop()
            continue
        if "suppress" in stack:
            continue
        out.append(line)
    return "\n".join(out)


def read_text(path: Path, cap: int = SCAN_MAX_BYTES) -> str | None:
    try:
        if path.suffix.lower() in BINARY_EXTS:
            return None
        with open(path, "rb") as fh:
            raw = fh.read(cap)
        if b"\x00" in raw[:2048]:
            return None
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return None


class Repo:
    def __init__(self, root: Path):
        self.root = root
        self.files: list[str] = []
        self.sizes: dict[str, int] = {}
        self.walk()

    def walk(self) -> None:
        for fr in self._universe():
            fp = self.root / fr
            if fp.is_symlink():
                continue
            try:
                self.sizes[fr] = fp.stat().st_size
            except OSError:
                continue
            self.files.append(fr)
        self.files.sort()
        self.fileset = set(self.files)

    def _universe(self):
        # Tracked files only: linked git worktrees nested under the root,
        # generated trees, and other untracked content are invisible to the
        # repo's runners yet pollute both the candidate list and the
        # reference corpus (duplicate basenames suppress real orphans).
        try:
            out = subprocess.run(
                ["git", "-C", str(self.root), "ls-files", "-z"],
                capture_output=True, check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            yield from self._fs_walk()
            return
        for raw in out.split(b"\0"):
            if not raw:
                continue
            fr = norm_rel(raw.decode("utf-8", "replace"))
            parts = fr.split("/")
            if any(
                c in EXCLUDE_DIRS or (c.startswith(".") and c not in KEEP_DOTDIRS)
                for c in parts[:-1]
            ):
                continue
            yield fr

    def _fs_walk(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel = norm_rel(os.path.relpath(dirpath, self.root))
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in EXCLUDE_DIRS and (not d.startswith(".") or d in KEEP_DOTDIRS)
            )
            for f in sorted(filenames):
                yield f if rel == "." else f"{rel}/{f}"

    def read(self, rel: str, cap: int = SCAN_MAX_BYTES) -> str | None:
        return read_text(self.root / rel, cap)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Detect candidate dead automation-test code (recon aid, not an oracle)."
    )
    ap.add_argument("--repo-root", required=True, help="absolute path to target git repo root")
    ap.add_argument("--out", required=True, help="path for the JSON inventory")
    ap.add_argument("--test-dirs", default="tests,test,spec,__tests__,e2e",
                    help="CSV of test-root dir names (or relative paths containing '/')")
    ap.add_argument("--extra-globs", nargs="+", action="extend", default=[],
                    help="additional runner include globs")
    ap.add_argument("--protected", nargs="+", action="extend", default=[],
                    help="path prefixes; matching items become flag_only")
    ap.add_argument("--vacuous-list", help="newline-separated output of the repo's OWN vacuous-scenario detector")
    ap.add_argument("--summary", action="store_true", help="print a markdown summary table")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    if not root.is_dir() or not (root / ".git").exists():
        print(f"error: --repo-root {root} is not a git repo root", file=sys.stderr)
        return 2
    if args.vacuous_list and not Path(args.vacuous_list).is_file():
        print(f"error: --vacuous-list {args.vacuous_list} not found", file=sys.stderr)
        return 2

    repo = Repo(root)
    unparsed: list[dict] = []
    runner_globs: list[dict] = []

    # ---- classify discovered files -------------------------------------
    pkg_jsons = [f for f in repo.files if posixpath.basename(f) == "package.json"]
    ci_files = [f for f in repo.files
                if (f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml")))
                or f in (".gitlab-ci.yml", ".circleci/config.yml")
                or posixpath.basename(f) == "Jenkinsfile"]
    hook_files = [f for f in repo.files
                  if posixpath.basename(f) in ("lefthook.yml", "lefthook.yaml", ".lefthook.yml")
                  or f == ".pre-commit-config.yaml"
                  or (f.startswith(".husky/") and "/_" not in f)]
    playwright_cfgs = [f for f in repo.files if posixpath.basename(f).startswith("playwright.config.")]
    cucumber_cfgs = [f for f in repo.files
                     if posixpath.basename(f).startswith("cucumber")
                     and f.endswith((".json", ".js", ".cjs", ".mjs", ".yaml", ".yml"))]
    pytest_cfgs = [f for f in repo.files
                   if posixpath.basename(f) in ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml")]
    for f in repo.files:
        b = posixpath.basename(f)
        if b.startswith(("jest.config.", "vitest.config.")):
            unparsed.append({"path": f, "reason": "jest/vitest config is code; not parsed"})

    # ---- package.json scripts + glob extraction ------------------------
    scripts: dict[str, str] = {}          # ns -> body
    script_globs: dict[str, list[str]] = {}
    parse_failures = False
    for pj in pkg_jsons:
        try:
            data = json.loads(repo.read(pj) or "")
        except (json.JSONDecodeError, TypeError):
            unparsed.append({"path": pj, "reason": "package.json parse failure"})
            parse_failures = True
            continue
        pkgdir = posixpath.dirname(pj) or "."
        for name, body in (data.get("scripts") or {}).items():
            if not isinstance(body, str):
                continue
            ns = name if pkgdir == "." else f"{pkgdir}#{name}"
            scripts[ns] = body
            globs = []
            for tok in QUOTED_TOKEN_RE.findall(body):
                if "*" in tok and ("/" in tok or tok.startswith("*")) and not tok.startswith("-"):
                    globs.append(norm_rel(tok) if pkgdir == "." else norm_rel(posixpath.join(pkgdir, tok)))
            if globs:
                script_globs[ns] = globs
                runner_globs.append({"source": f"{pj}#{name}", "globs": globs})
        jest_cfg = data.get("jest")
        if isinstance(jest_cfg, dict):
            jm = [g for g in (jest_cfg.get("testMatch") or []) if isinstance(g, str)]
            if jm:
                runner_globs.append({"source": f"{pj}#jest", "globs": [norm_rel(g.replace("<rootDir>/", "")) for g in jm]})
            else:
                unparsed.append({"path": pj, "reason": "jest section without literal testMatch"})

    # ---- playwright configs --------------------------------------------
    pw_globs: list[str] = []
    for cfg in playwright_cfgs:
        text = repo.read(cfg) or ""
        cfgdir = posixpath.dirname(cfg)
        dirs = re.findall(r"testDir\s*[:=]\s*[\"']([^\"']+)[\"']", text)
        matches = re.findall(r"testMatch\s*[:=]\s*\[?\s*[\"']([^\"']+)[\"']", text)
        globs = []
        for d in dirs:
            d = norm_rel(posixpath.join(cfgdir, d)) if cfgdir else norm_rel(d)
            globs.append(f"{d}/**")
        for m in matches:
            base = norm_rel(posixpath.join(cfgdir, dirs[0])) if dirs else cfgdir
            globs.append(norm_rel(posixpath.join(base, m)) if base else norm_rel(m))
        if globs:
            pw_globs.extend(globs)
            runner_globs.append({"source": cfg, "globs": globs})
        else:
            unparsed.append({"path": cfg, "reason": "no literal testDir/testMatch found (computed config)"})

    # ---- cucumber configs ----------------------------------------------
    cu_globs: list[str] = []
    for cfg in cucumber_cfgs:
        text = repo.read(cfg) or ""
        cfgdir = posixpath.dirname(cfg)
        globs: list[str] = []
        parsed = None
        if cfg.endswith(".json"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        if isinstance(parsed, dict):
            for profile in parsed.values():
                if isinstance(profile, dict):
                    for key in ("paths", "import", "require"):
                        globs += [g for g in (profile.get(key) or []) if isinstance(g, str)]
        else:
            m = re.search(r"paths\s*[:=]\s*\[([^\]]*)\]", text)
            if m:
                globs += QUOTED_TOKEN_RE.findall(m.group(1))
            elif cfg.endswith((".js", ".cjs", ".mjs")):
                unparsed.append({"path": cfg, "reason": "cucumber config is code; no literal paths found"})
        fixed = []
        for g in globs:
            g = norm_rel(g)
            sp = static_prefix(g)
            if sp and not (root / sp).exists() and cfgdir and (root / cfgdir / sp).exists():
                g = norm_rel(posixpath.join(cfgdir, g))
            fixed.append(g)
        if fixed:
            cu_globs.extend(fixed)
            runner_globs.append({"source": cfg, "globs": fixed})

    # ---- pytest configs -------------------------------------------------
    py_globs: list[str] = []
    for cfg in pytest_cfgs:
        cfgdir = posixpath.dirname(cfg)
        testpaths: list[str] = []
        pyfiles: list[str] = []
        text = repo.read(cfg) or ""
        try:
            if cfg.endswith("pyproject.toml"):
                if "pytest" not in text:
                    continue
                if tomllib is None:
                    unparsed.append({"path": cfg, "reason": "tomllib unavailable"})
                    continue
                opts = (tomllib.loads(text).get("tool", {}).get("pytest", {}).get("ini_options", {}))
                testpaths = list(opts.get("testpaths") or [])
                pyfiles = list(opts.get("python_files") or [])
                if not opts:
                    continue
            else:
                import configparser
                cp = configparser.ConfigParser()
                cp.read_string(text)
                sec = next((s for s in ("pytest", "tool:pytest") if cp.has_section(s)), None)
                if sec is None:
                    continue
                testpaths = (cp.get(sec, "testpaths", fallback="") or "").split()
                pyfiles = (cp.get(sec, "python_files", fallback="") or "").split()
        except Exception as exc:  # noqa: BLE001 — best-effort extraction with provenance
            unparsed.append({"path": cfg, "reason": f"pytest config parse failure: {exc}"})
            parse_failures = True
            continue
        pyfiles = pyfiles or ["test_*.py", "*_test.py"]
        globs = [norm_rel(posixpath.join(cfgdir, tp, "**", pf))
                 for tp in (testpaths or ["."]) for pf in pyfiles]
        py_globs.extend(globs)
        runner_globs.append({"source": cfg, "globs": globs})

    if args.extra_globs:
        runner_globs.append({"source": "cli:--extra-globs", "globs": [norm_rel(g) for g in args.extra_globs]})

    all_globs: list[str] = []
    for entry in runner_globs:
        all_globs += entry["globs"]
    all_globs = sorted(set(all_globs))
    compiled = [(g, glob_to_regex(g)) for g in all_globs]

    def glob_match(rel: str) -> bool:
        return any(rx.match(rel) for _, rx in compiled)

    # ---- invocation graph (category 2) ---------------------------------
    name_index: dict[str, list[str]] = {}
    for ns in scripts:
        name_index.setdefault(ns.rsplit("#", 1)[-1], []).append(ns)

    invoked: set[str] = set()
    chased: set[str] = set()
    queue: list[tuple[str, str]] = []
    lifecycle_roots = [ns for ns in scripts if ns.rsplit("#", 1)[-1] in LIFECYCLE]
    for f in ci_files + hook_files:
        queue.append(("file", f))
    for ns in lifecycle_roots:
        queue.append(("script", ns))

    origins: dict[str, str] = {}
    current_node = "?"

    def invoke_name(bare: str) -> None:
        for ns in name_index.get(bare, []):
            if ns not in invoked:
                invoked.add(ns)
                origins.setdefault(ns, current_node)
                queue.append(("script", ns))
            base = ns.rsplit("#", 1)[-1]
            prefix = ns[: -len(base)]
            for pp in (f"{prefix}pre{base}", f"{prefix}post{base}"):
                if pp in scripts and pp not in invoked:
                    invoked.add(pp)
                    origins.setdefault(pp, f"lifecycle:{ns}")
                    queue.append(("script", pp))

    def scan_edges(text: str) -> None:
        for m in NPM_RUN_RE.finditer(text):
            invoke_name(m.group(1))
        if NPM_TEST_RE.search(text):
            invoke_name("test")
        for m in YARN_PNPM_RE.finditer(text):
            if m.group(1) in name_index:
                invoke_name(m.group(1))
        for m in RUN_SP_RE.finditer(text):
            for tok in m.group(1).split():
                tok = tok.strip("'\"")
                if "*" in tok:
                    for bare in name_index:
                        if fnmatch.fnmatch(bare, tok):
                            invoke_name(bare)
                elif tok in name_index:
                    invoke_name(tok)
        for m in FILE_MENTION_RE.finditer(text):
            cand = norm_rel(m.group(0))
            # Resolve variable-prefixed paths ($ROOT/scripts/x.sh) by
            # longest suffix that exists in the repo.
            rel = None
            while True:
                if cand in repo.fileset:
                    rel = cand
                    break
                if "/" not in cand:
                    break
                cand = cand.split("/", 1)[1]
            if (rel and posixpath.splitext(rel)[1] in CHASE_EXTS
                    and ("/" not in rel or rel.split("/", 1)[0] in CHASE_DIRS)
                    and repo.sizes.get(rel, 0) < CHASE_MAX_BYTES
                    and rel not in chased and len(chased) < CHASE_MAX_FILES):
                chased.add(rel)
                queue.append(("file", rel))

    processed: set[tuple[str, str]] = set()
    while queue:
        kind, key = queue.pop()
        if (kind, key) in processed:
            continue
        processed.add((kind, key))
        current_node = f"{kind}:{key}"
        if kind == "file":
            text = repo.read(key, CHASE_MAX_BYTES)
            if text:
                scan_edges(strip_gated(strip_prose(text)))
        else:
            invoked.add(key)
            origins.setdefault(key, "root")
            scan_edges(scripts.get(key, ""))
    if os.environ.get("DT_DEBUG"):
        for ns in sorted(invoked):
            print(f"[debug] invoked {ns} <- {origins.get(ns, '?')}", file=sys.stderr)

    items: list[dict] = []
    for ns in sorted(scripts):
        if ns in invoked:
            continue
        body = scripts[ns]
        runners = sorted(set(RUNNER_BIN_RE.findall(body)))
        if NODE_TEST_RE.search(body):
            runners.append("node --test")
        if not runners:
            continue
        targets = list(script_globs.get(ns, []))
        if not targets:
            if "playwright" in runners:
                targets = pw_globs[:]
            elif "cucumber-js" in runners:
                targets = cu_globs[:]
            elif any(r in ("pytest", "py.test") for r in runners):
                targets = py_globs[:]
        pj = "package.json" if "#" not in ns else f"{ns.rsplit('#', 1)[0]}/package.json"
        items.append({
            "path": pj, "category": "uninvoked-suite", "kind": "npm-script",
            "script": ns, "targets": targets,
            "evidence": [
                f"script '{ns}' invokes runner(s): {', '.join(runners)}",
                f"zero inbound edges from {len(ci_files)} CI file(s), {len(hook_files)} hook file(s), "
                f"{len(lifecycle_roots)} lifecycle script(s), or their transitive chain ({len(chased)} chased files)",
                f"targets: {', '.join(targets) if targets else '(none extracted)'}",
            ],
        })

    # ---- test roots + per-file categories ------------------------------
    pkgdirs = sorted({posixpath.dirname(pj) or "." for pj in pkg_jsons})
    root_names = [t.strip() for t in args.test_dirs.split(",") if t.strip()]
    test_roots: list[str] = []
    for entry in root_names:
        if "/" in entry:
            if (root / entry).is_dir():
                test_roots.append(norm_rel(entry))
            continue
        for base in ["."] + pkgdirs:
            cand = entry if base == "." else f"{base}/{entry}"
            if (root / cand).is_dir():
                test_roots.append(norm_rel(cand))
    test_roots = sorted(set(test_roots))

    helper_cands: list[str] = []
    for tr in test_roots:
        for f in repo.files:
            if not f.startswith(tr + "/"):
                continue
            base = posixpath.basename(f)
            if base in NEVER_FLAG or glob_match(f):
                continue
            if is_test_named(base):
                near = [g for g in all_globs if static_prefix(g).startswith(tr)][:8]
                items.append({
                    "path": f, "category": "orphan-test-file", "kind": "file",
                    "script": None,
                    "evidence": [
                        "test-named file matching no extracted or supplied runner glob",
                        f"globs checked: {len(all_globs)} total; under {tr}/: {near or '(none)'}",
                    ],
                })
            else:
                helper_cands.append(f)

    # ---- reference scan -------------------------------------------------
    tokens: dict[str, list[str]] = {}
    for f in helper_cands:
        stem = Path(f).stem
        tok = stem if len(stem) >= 4 else posixpath.basename(f)
        tokens.setdefault(tok, []).append(f)
    subdirs = sorted({f"{tr}/{seg}" for tr in test_roots
                      for seg in {p[len(tr) + 1:].split("/", 1)[0]
                                  for p in repo.files if p.startswith(tr + "/") and "/" in p[len(tr) + 1:]}
                      if not seg.startswith(".")})
    for d in subdirs:
        tokens.setdefault(d, [])

    corpus = [f for f in repo.files
              if posixpath.splitext(f)[1] in CODE_EXTS
              and posixpath.basename(f) not in LOCKFILES
              and not any(part in DOC_DIRS for part in f.split("/"))
              and repo.sizes.get(f, 0) <= SCAN_MAX_BYTES]
    tok_list = sorted(tokens, key=len, reverse=True)
    chunk_res = [re.compile("|".join(re.escape(t) for t in tok_list[i:i + 60]))
                 for i in range(0, len(tok_list), 60)]
    hits: dict[str, set[str]] = {t: set() for t in tokens}
    n_scanned = 0
    for f in corpus:
        text = repo.read(f)
        if text is None:
            continue
        n_scanned += 1
        for rx in chunk_res:
            for m in set(rx.findall(text)):
                hits[m].add(f)

    for tok, cands in tokens.items():
        for f in cands:
            if hits[tok] - {f}:
                continue
            items.append({
                "path": f, "category": "orphan-helper", "kind": "file",
                "script": None,
                "evidence": [
                    f"under test root, matches none of {len(all_globs)} runner globs",
                    f"zero import/require/from/path-string references to '{tok}' across "
                    f"{n_scanned} code/config files scanned (docs, markdown, lockfiles, build outputs excluded)",
                ],
            })

    for d in subdirs:
        under = [f for f in repo.files if f.startswith(d + "/")]
        if not under or any(glob_match(f) for f in under):
            continue
        if hits[d] - set(under):
            continue
        externally_referenced = [f for f in under
                                 for tok, cs in tokens.items()
                                 if f in cs and (hits[tok] - set(under))]
        if externally_referenced:
            continue
        items.append({
            "path": d, "category": "orphan-dir", "kind": "dir", "script": None,
            "evidence": [
                f"immediate subdir of a test root; none of its {len(under)} files match any of "
                f"{len(all_globs)} runner globs",
                "no runner config points at it and no outside file references the dir or its contents",
            ],
        })

    # ---- vacuous scenarios ----------------------------------------------
    vac_cands = sorted(ns for ns, body in scripts.items()
                       if "vacuous" in ns.lower() or "vacuous" in body.lower())
    if args.vacuous_list:
        lines = [ln.strip() for ln in Path(args.vacuous_list).read_text(errors="replace").splitlines() if ln.strip()]
        for ln in lines:
            items.append({
                "path": ln, "category": "vacuous-scenario", "kind": "scenario",
                "script": None,
                "evidence": [f"repo-detector-output: {args.vacuous_list}"],
            })
        vacuous_status = f"included: {len(lines)} entries from {args.vacuous_list}"
    else:
        vacuous_status = "skipped: no --vacuous-list supplied (delete nothing in this category without the repo's own detector)"

    # ---- protected / flag_only ------------------------------------------
    prefixes = [norm_rel(p).rstrip("/") for p in args.protected]

    def is_protected(item: dict) -> bool:
        for p in prefixes:
            if item["path"] == p or item["path"].startswith(p + "/") or p in item["path"]:
                return True
            for t in item.get("targets", []):
                sp = static_prefix(t)
                if sp and (sp == p or sp.startswith(p + "/") or p.startswith(sp + "/") or p == sp):
                    return True
        return False

    # ---- confidence ------------------------------------------------------
    task_runner = any((root / f).exists() for f in ("turbo.json", "nx.json", "lerna.json"))
    if not task_runner:
        for pj in pkg_jsons:
            try:
                d = json.loads(repo.read(pj) or "{}")
            except json.JSONDecodeError:
                continue
            deps = {**(d.get("dependencies") or {}), **(d.get("devDependencies") or {})}
            if {"turbo", "nx", "lerna"} & set(deps):
                task_runner = True
    unparsed_dirs = [posixpath.dirname(u["path"]) or "." for u in unparsed]
    global_low = task_runner or not ci_files

    for item in items:
        if item["category"] == "vacuous-scenario":
            item["confidence"] = "high"
        elif global_low:
            item["confidence"] = "low"
        elif any(ud == "." or item["path"].startswith(ud + "/") for ud in unparsed_dirs):
            item["confidence"] = "low"
        elif unparsed or parse_failures:
            item["confidence"] = "medium"
        else:
            item["confidence"] = "high"
        item["flag_only"] = is_protected(item)

    items.sort(key=lambda i: (CATEGORY_ORDER.index(i["category"]), i["path"], i.get("script") or ""))
    for n, item in enumerate(items, 1):
        item["id"] = f"dt-{n:03d}"

    counts = {c: sum(1 for i in items if i["category"] == c) for c in CATEGORY_ORDER}
    counts["flag_only"] = sum(1 for i in items if i["flag_only"])

    inventory = {
        "schema": "dead-test-inventory/v1",
        "repo_root": str(root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "extraction": {
            "package_json_files": pkg_jsons,
            "runner_globs": runner_globs,
            "unparsed_configs": unparsed,
            "ci_files": ci_files,
            "hook_files": hook_files,
            "invocation_roots": ci_files + hook_files + sorted(lifecycle_roots),
        },
        "hints": {
            "vacuous_detector_candidates": vac_cands,
            "vacuous_status": vacuous_status,
            "task_runner_detected": task_runner,
            "protected_paths_used": prefixes,
        },
        "items": [{k: i[k] for k in
                   ("id", "path", "category", "kind", "script", "evidence", "confidence", "flag_only")
                   } | ({"targets": i["targets"]} if "targets" in i else {})
                  for i in items],
        "counts": counts,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inventory, indent=2) + "\n")

    if not all_globs:
        print("error: no runner globs extracted and none supplied via --extra-globs; "
              f"partial extraction report written to {out}", file=sys.stderr)
        return 3

    if args.summary:
        print(f"# dead-test inventory — {len(items)} candidate(s), {counts['flag_only']} flag-only")
        print("| path | category | confidence | flag_only | evidence |")
        print("|---|---|---|---|---|")
        for i in items:
            ev = i["evidence"][0][:100].replace("|", "\\|")
            path = i["script"] or i["path"]
            print(f"| {path} | {i['category']} | {i['confidence']} | {str(i['flag_only']).lower()} | {ev} |")

    return 0 if items else 1


if __name__ == "__main__":
    raise SystemExit(main())
