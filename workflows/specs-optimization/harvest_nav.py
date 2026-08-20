#!/usr/bin/env python3
"""Harvest probe transcripts and compute spec-navigation-friction metrics.

Harness-agnostic: every backend-specific detail (transcript layout, record
schema, tool names, whether tool results exist) lives in `probe_backends.py`.
Given `probes.json` from `run_probes.py`, this:
  1. Loads each probe's located transcript and resolves the backend profile
     (from --harness, else inferred from the transcript paths).
  2. Reconstructs nested descendants where the backend supports it (Claude Code
     links subagents by agentId; pi cannot, and says so).
  3. Normalises each transcript into canonical calls and extracts spec-file
     navigation events from `read` calls, `search` calls and parsed shell
     commands.
  4. Computes per-probe and per-domain navigation-inefficiency metrics, plus a
     co-navigation matrix and global aggregates.
  5. Emits metrics.json (full, including the resolved backend `capabilities`),
     nav_traces.md (condensed per-probe traces), and digest.md (a budget-bounded,
     LLM-facing summary — the ONLY file the session should read; raw transcripts
     are far too large for context).

Capability gating: when the backend does not persist tool results, `is_error` is
UNKNOWN, not false. Failed-read/search counts are reported as null, the `failed`
term is DROPPED from the friction sum (not summed as zero), and the digest says
so in words. Never report a silent 0.

Exit codes:
  0  success
  1  no transcripts located, OR zero spec navigation across all probes
  2  usage error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from collections import Counter, deque
from pathlib import Path

from probe_backends import HARNESSES, get_backend, harness_for_transcript

# harvest_nav.py -> specs-optimization/ -> workflows/ -> repo
REPO_ROOT = Path(__file__).resolve().parents[2]

# Friction weights (positive = friction, nav-aid-first usage is a discoverability credit).
W = {"sbf": 2.0, "hops": 2.0, "rereads": 1.0, "dead_ends": 1.5, "failed": 1.5, "navaid": 1.0}

SEARCH_PROGS = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "find", "fd", "fdfind", "ls", "tree"}
READ_PROGS = {"cat", "head", "tail", "less", "more", "bat", "sed", "awk", "nl", "tac",
              "wc", "file", "stat", "xxd", "od", "md5sum", "sha1sum", "sha256sum"}
WRAPPER_PROGS = {"sudo", "command", "time", "nice", "env", "xargs", "stdbuf"}
# Flags whose following token is a pattern/count, never a path to navigate.
VALUE_FLAGS = {"-name", "-iname", "-path", "-ipath", "-wholename", "-regex", "-iregex",
               "-e", "--regexp", "--include", "--exclude", "--exclude-dir",
               "-A", "-B", "-C", "-m", "--max-count", "-n"}
PATH_EXTS = (".md", ".markdown", ".mdx", ".yaml", ".yml", ".json", ".txt", ".rst")

NAV_AID_RE = re.compile(
    r"^(_?index\.md|overview\.md|glossary\.md|readme\.md|current[-_]state\.md|domain[-_]map\.(ya?ml|json))$",
    re.I,
)
SUBCMD_SPLIT = re.compile(r"\|\||&&|[|;\n]")
OP_SPLIT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")  # leading FOO=bar env assignment


def is_nav_aid(name: str) -> bool:
    return bool(NAV_AID_RE.match(name))


class SpecResolver:
    """Maps absolute/relative paths to (category, is_nav_aid, rel, depth) under specs_root."""

    def __init__(self, specs_root: str):
        norm = os.path.normpath(os.path.abspath(specs_root))
        self.specs_parts = Path(norm).parts
        self.anchor = self.specs_parts[-min(2, len(self.specs_parts)):]

    def _rel_parts(self, p_parts: tuple[str, ...]):
        n = len(self.specs_parts)
        if p_parts[:n] == self.specs_parts:
            return p_parts[n:]
        k = len(self.anchor)
        for i in range(len(p_parts) - k + 1):
            if tuple(p_parts[i:i + k]) == self.anchor:
                return p_parts[i + k:]
        return None

    def classify(self, path_str: str, cwd: str | None):
        if not path_str:
            return None
        p = path_str.strip().strip("'\"")
        if p.startswith("~"):
            return None
        if not p.startswith("/"):
            if not cwd:
                return None
            p = os.path.join(cwd, p)
        norm = Path(os.path.normpath(p))
        rel = self._rel_parts(norm.parts)
        if rel is None:
            return None
        # Drop trailing glob segments (e.g. `docs/specs/*` or `06/*.md`) so a
        # wildcard never becomes a spurious category.
        rel = list(rel)
        while rel and any(ch in rel[-1] for ch in "*?[]{}"):
            rel.pop()
        rel = tuple(rel)
        if not rel:
            return {"category": "(specs-root)", "is_nav_aid": False, "rel": "", "depth": 0}
        name = rel[-1]
        looks_file = name.lower().endswith(PATH_EXTS)
        nav = looks_file and is_nav_aid(name)
        if looks_file:
            category = rel[0] if len(rel) >= 2 else "(root)"
        else:
            category = rel[0] if rel else "(specs-root)"
        return {"category": category, "is_nav_aid": nav, "rel": "/".join(rel), "depth": len(rel)}


def path_like(token: str) -> bool:
    t = token.strip().strip("'\"")
    if not t or t.startswith("-"):
        return False
    return "/" in t or t.lower().endswith(PATH_EXTS)


def parse_bash(command: str, cwd: str | None, resolver: SpecResolver) -> list[dict]:
    """Yield spec-nav events from a shell command string (best-effort)."""
    events: list[dict] = []
    for sub in SUBCMD_SPLIT.split(command or ""):
        sub = sub.strip()
        if not sub:
            continue
        try:
            tokens = shlex.split(sub, posix=True)
        except ValueError:
            tokens = sub.split()
        # Strip leading env assignments and wrapper programs.
        while tokens and (OP_SPLIT.match(tokens[0]) or os.path.basename(tokens[0]) in WRAPPER_PROGS):
            tokens = tokens[1:]
        if not tokens:
            continue
        prog = os.path.basename(tokens[0])
        if prog in SEARCH_PROGS:
            kind = "search"
        elif prog in READ_PROGS:
            kind = "read"
        else:
            continue
        toks = tokens[1:]
        i = 0
        while i < len(toks):
            tok = toks[i]
            if tok in VALUE_FLAGS:
                i += 2  # skip the flag and its pattern/count value
                continue
            if tok.startswith(("--include=", "--exclude=", "--exclude-dir=", "--regexp=")):
                i += 1
                continue
            if path_like(tok):
                hit = resolver.classify(tok, cwd)
                if hit:
                    events.append({**hit, "kind": kind, "src": prog})
            i += 1
    return events


class Parsed:
    __slots__ = ("events", "child_ids", "total_tool_calls", "nested_spawns",
                 "ts_min", "ts_max", "agent_type", "description", "path",
                 "tool_results_seen")

    def __init__(self):
        self.events: list[dict] = []
        self.child_ids: list[str] = []
        self.total_tool_calls = 0
        self.nested_spawns = 0
        self.ts_min = None
        self.ts_max = None
        self.agent_type = ""
        self.description = ""
        self.path = ""
        self.tool_results_seen = False


def parse_transcript(jsonl: Path, backend, resolver: SpecResolver) -> Parsed:
    """Backend-normalised transcript -> spec-navigation events.

    The backend profile turns its own records into canonical calls; everything
    below is harness-independent. `is_error` may be None (backend does not
    persist tool results) and stays None on the event — never coerced to False.
    """
    pr = Parsed()
    pr.path = str(jsonl)
    norm = backend.normalize(jsonl)
    pr.ts_min, pr.ts_max = norm.ts_min, norm.ts_max
    pr.agent_type = norm.agent_type
    pr.description = norm.description
    pr.tool_results_seen = norm.tool_results_seen

    for call in norm.calls:
        pr.total_tool_calls += 1
        cwd = call.get("cwd") or norm.session_cwd
        tool = call.get("tool")
        new: list[dict] = []
        if tool == "spawn":
            pr.nested_spawns += 1
            if call.get("child_id"):
                pr.child_ids.append(call["child_id"])
            continue
        if tool == "read":
            hit = resolver.classify(call.get("path") or "", cwd)
            if hit:
                new.append({**hit, "kind": "read", "src": call.get("name") or "read"})
        elif tool == "command":
            new.extend(parse_bash(call.get("command") or "", cwd, resolver))
        elif tool == "search":
            hit = resolver.classify(call.get("path") or "", cwd)
            if hit:
                new.append({**hit, "kind": "search", "src": (call.get("name") or "search").lower()})
        for ev in new:
            ev["is_error"] = call.get("is_error")
            pr.events.append(ev)
    return pr


def load_probes(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("probes.json must be a non-empty JSON array")
    out = []
    for i, e in enumerate(data, start=1):
        if not isinstance(e, dict):
            raise ValueError(f"probes.json entry {i} is not an object")
        out.append(e)
    return out


def resolve_harness(choice: str, probes: list[dict]) -> str:
    """Explicit --harness wins; otherwise infer from the transcript paths.

    A run must use exactly one backend (mixed backends make metrics
    incomparable), so a mixed inference is a usage error.
    """
    if choice != "auto":
        return choice
    seen = {h for h in (harness_for_transcript(e["transcript"])
                        for e in probes if e.get("transcript")) if h}
    if len(seen) == 1:
        return seen.pop()
    if not seen:
        raise ValueError("cannot infer --harness from probes.json transcript paths; pass --harness")
    raise ValueError(f"probes.json mixes harnesses ({', '.join(sorted(seen))}); one backend per run")


def is_domain(category: str, is_nav_aid_flag: bool) -> bool:
    return not is_nav_aid_flag and category not in {"(root)", "(specs-root)", "(nav-aid)"}


def agent_metrics(pr: Parsed, depth: int, caps: dict) -> dict:
    """Per-probe metrics. `caps['tool_results']` false => failure counts are None."""
    has_errs = bool(caps.get("tool_results"))
    events = pr.events
    ok_reads = [e for e in events if e["kind"] == "read" and not e["is_error"]]
    domain_reads = [e for e in ok_reads if is_domain(e["category"], e["is_nav_aid"])]
    searches = [e for e in events if e["kind"] == "search"]

    # Totals count every spec read (incl. nav-aid "map" files); domain math below
    # uses domain_reads only so the map isn't mistaken for content.
    all_counts = Counter(e["rel"] for e in ok_reads)
    distinct = len(all_counts)
    rereads = sum(c - 1 for c in all_counts.values())
    domain_counts = Counter(e["rel"] for e in domain_reads)

    # searches issued before the first successful spec read (incl. nav-aid files)
    sbf = 0
    for e in events:
        if e["kind"] == "search":
            sbf += 1
        elif e["kind"] == "read" and not e["is_error"]:
            break

    cat_seq = [e["category"] for e in domain_reads]
    collapsed = [c for i, c in enumerate(cat_seq) if i == 0 or c != cat_seq[i - 1]]
    hops = max(0, len(collapsed) - 1)
    hop_touch: Counter = Counter()
    for i in range(1, len(collapsed)):
        hop_touch[collapsed[i - 1]] += 1
        hop_touch[collapsed[i]] += 1

    nav_aid_reads = sum(1 for e in ok_reads if e["is_nav_aid"])
    used_map_first = bool(ok_reads) and ok_reads[0]["is_nav_aid"]

    # dead ends: domain file read once whose next domain read is a different category
    dead_ends = 0
    dead_end_files: list[str] = []
    for i, e in enumerate(domain_reads):
        if domain_counts[e["rel"]] != 1:
            continue
        nxt = domain_reads[i + 1] if i + 1 < len(domain_reads) else None
        if nxt is not None and nxt["category"] != e["category"]:
            dead_ends += 1
            dead_end_files.append(e["rel"])

    # per-category breakdown
    cats = {e["category"] for e in domain_reads} | {e["category"] for e in searches if is_domain(e["category"], e["is_nav_aid"])}
    first_read_idx: dict[str, int] = {}
    for idx, e in enumerate(events):
        if e["kind"] == "read" and not e["is_error"] and is_domain(e["category"], e["is_nav_aid"]):
            first_read_idx.setdefault(e["category"], idx)
    first_navaid_idx = next((idx for idx, e in enumerate(events)
                             if e["kind"] == "read" and not e["is_error"] and e["is_nav_aid"]), None)

    per_cat: dict[str, dict] = {}
    for cat in cats:
        c_reads = [e for e in domain_reads if e["category"] == cat]
        c_rel = Counter(e["rel"] for e in c_reads)
        fr = first_read_idx.get(cat)
        sbf_cat = sum(1 for idx, e in enumerate(events)
                      if e["kind"] == "search" and e["category"] == cat and (fr is None or idx < fr))
        per_cat[cat] = {
            "reads": len(c_reads),
            "distinct": len(c_rel),
            "rereads": sum(v - 1 for v in c_rel.values()),
            "searches": sum(1 for e in searches if e["category"] == cat),
            "searches_before_first_read": sbf_cat,
            "dead_ends": sum(1 for f in dead_end_files if f.split("/")[0] == cat or (("/" not in f) and cat == "(root)")),
            "failed_reads": (sum(1 for e in events if e["kind"] == "read" and e["is_error"] and e["category"] == cat)
                             if has_errs else None),
            "hop_touch": hop_touch.get(cat, 0),
            "navaid_first": bool(first_navaid_idx is not None and (fr is None or first_navaid_idx <= fr)),
            "engaged": True,
        }

    return {
        "agent_type": pr.agent_type,
        "description": pr.description,
        "depth": depth,
        "spec_reads_total": len(ok_reads),
        "spec_reads_distinct": distinct,
        "spec_rereads": rereads,
        "domain_reads": len(domain_reads),
        "nav_aid_reads": nav_aid_reads,
        "used_map_first": used_map_first,
        "searches_total": len(searches),
        "non_domain_searches": sum(1 for e in searches if not is_domain(e["category"], e["is_nav_aid"])),
        "searches_before_first_spec_read": sbf,
        "cross_domain_hops": hops,
        "distinct_domains_touched": len({e["category"] for e in domain_reads}),
        "dead_end_reads": dead_ends,
        "max_nesting_depth_to_spec": max((e["depth"] for e in ok_reads), default=0),
        "failed_reads": (sum(1 for e in events if e["kind"] == "read" and e["is_error"]) if has_errs else None),
        "failed_searches": (sum(1 for e in searches if e["is_error"]) if has_errs else None),
        "nested_spawns": pr.nested_spawns,
        "total_tool_calls": pr.total_tool_calls,
        "transcript": pr.path,
        "time_span_s": round((pr.ts_max - pr.ts_min).total_seconds(), 1) if pr.ts_min and pr.ts_max else None,
        "per_cat": per_cat,
        "domains": sorted({e["category"] for e in domain_reads}),
    }


def condense_trace(events: list[dict], keep_head: int = 8, keep_tail: int = 8) -> str:
    if not events:
        return "(no spec navigation)"
    keep = set(range(min(keep_head, len(events))))
    keep |= set(range(max(0, len(events) - keep_tail), len(events)))
    prev_cat = None
    for i, e in enumerate(events):
        if e["is_error"]:
            keep.add(i)
        if e["kind"] == "read" and is_domain(e["category"], e["is_nav_aid"]):
            if prev_cat is not None and e["category"] != prev_cat:
                keep.add(i)
                keep.add(i - 1)
            prev_cat = e["category"]
    seen: set[str] = set()
    out: list[str] = []
    last_kept = -1
    for i, e in enumerate(events):
        if i not in keep:
            continue
        if i - last_kept > 1:
            out.append(f"…(+{i - last_kept - 1})")
        last_kept = i
        rel = e["rel"] or "*"
        short = "/".join(rel.split("/")[-2:]) if rel != "*" else "*"
        if e["kind"] == "search":
            tok = f"[{e['src']}:{e['category']}]"
        else:
            mark = "~" if e["is_nav_aid"] else ""
            reread = "(re)" if rel in seen else ""
            seen.add(rel)
            tok = f"{mark}{short}{reread}"
        if e["is_error"]:
            tok = "✗" + tok
        out.append(tok)
    return " → ".join(out)


def enforce_budget(sections: list[str], traces: list[str], budget: int) -> str:
    core = "\n".join(sections)
    if len(core.encode("utf-8")) >= budget:
        marker = "\n\n…digest truncated (core over budget)…\n"
        keep = max(0, budget - len(marker.encode("utf-8")))
        return core.encode("utf-8")[:keep].decode("utf-8", "ignore") + marker
    out = core
    for t in traces:
        candidate = out + "\n" + t
        if len(candidate.encode("utf-8")) > budget:
            out += "\n\n…remaining agent traces omitted to fit digest budget…\n"
            break
        out = candidate
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Harvest probe transcripts -> spec navigation metrics.")
    ap.add_argument("--probes", required=True, help="probes.json written by run_probes.py.")
    ap.add_argument("--harness", default="auto", choices=("auto",) + HARNESSES,
                    help="Backend profile (default: auto, inferred from transcript paths).")
    ap.add_argument("--specs-root", required=True, help="Absolute path to the spec corpus root.")
    ap.add_argument("--manifest", default="", help="Optional manifest.json from discover_specs.py.")
    ap.add_argument("--out-dir", required=True, help="Run directory for outputs.")
    ap.add_argument("--digest-budget-bytes", type=int, default=24000)
    args = ap.parse_args()

    try:
        probes = load_probes(Path(args.probes).expanduser())
    except OSError as exc:
        print(f"error: cannot read --probes: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: bad --probes: {exc}", file=sys.stderr)
        return 2
    try:
        harness = resolve_harness(args.harness, probes)
        backend = get_backend(harness)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    resolver = SpecResolver(args.specs_root)

    manifest_cats: dict[str, int] = {}
    cats_with_navaid: set[str] = set()
    if args.manifest:
        try:
            man = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            for c in man.get("categories", []):
                manifest_cats[c["name"]] = c.get("md_count", 0)
                if c.get("nav_aids"):
                    cats_with_navaid.add(c["name"])
        except (OSError, ValueError, KeyError):
            pass

    # Walk the probe roots, then any nested descendants the backend can link.
    parsed: dict[str, Parsed] = {}
    depth: dict[str, int] = {}
    order: list[str] = []
    missing_roots: list[int] = []
    unresolved_children = 0
    seen_files: set[str] = set()
    q: deque[tuple[str, Path, int, Path]] = deque()
    for e in probes:
        tpath = str(e.get("transcript") or "")
        label = f"probe-{int(e.get('index', 0) or 0):02d}" if e.get("index") else Path(tpath).stem
        if not tpath or not Path(tpath).is_file():
            missing_roots.append(e.get("index"))
            continue
        q.append((label, Path(tpath), 0, Path(tpath)))
    while q:
        label, jsonl, d, sibling = q.popleft()
        key = str(jsonl.resolve())
        if key in seen_files:
            continue
        seen_files.add(key)
        pr = parse_transcript(jsonl, backend, resolver)
        parsed[label] = pr
        depth[label] = d
        order.append(label)
        for child in pr.child_ids:
            child_path = backend.child_transcript(child, sibling)
            if child_path is None:
                unresolved_children += 1
                continue
            q.append((f"{label}/{child[:8]}", child_path, d + 1, child_path))

    located = list(order)
    if not located:
        msg = (f"no transcripts located from {args.probes} "
               f"(harness={harness}); every probe entry was empty or missing on disk")
        print(msg, file=sys.stderr)
        (out_dir / "digest.md").write_text(f"# specs-optimization digest\n\n**{msg}**\n", encoding="utf-8")
        return 1

    caps = backend.observed_capabilities([parsed[a] for a in located])
    per_agent = {a: agent_metrics(parsed[a], depth.get(a, 0), caps) for a in located}
    total_spec_events = sum(len(parsed[a].events) for a in located)

    # Per-domain aggregation.
    all_cats = set(manifest_cats) | {c for m in per_agent.values() for c in m["per_cat"]}
    per_domain: dict[str, dict] = {}
    for cat in all_cats:
        comp = Counter()
        engaged = 0
        navaid_first = 0
        for m in per_agent.values():
            pc = m["per_cat"].get(cat)
            if not pc:
                continue
            engaged += 1
            navaid_first += int(pc["navaid_first"])
            comp["sbf"] += pc["searches_before_first_read"]
            comp["hops"] += pc["hop_touch"]
            comp["rereads"] += pc["rereads"]
            comp["dead_ends"] += pc["dead_ends"]
            if caps["tool_results"]:
                comp["failed"] += pc["failed_reads"] or 0
        navaid_rate = (navaid_first / engaged) if engaged else 0.0
        # No tool results on this backend => the `failed` term is DROPPED from the
        # sum, not summed as zero: an unmeasurable signal must not look clean.
        raw = (W["sbf"] * comp["sbf"] + W["hops"] * comp["hops"] + W["rereads"] * comp["rereads"]
               + W["dead_ends"] * comp["dead_ends"]
               - W["navaid"] * navaid_rate * engaged)
        if caps["tool_results"]:
            raw += W["failed"] * comp["failed"]
        per_domain[cat] = {
            "files": manifest_cats.get(cat),
            "engaged_agents": engaged,
            "navaid_first_rate": round(navaid_rate, 2),
            "friction_raw": round(raw, 2),
            "friction_norm": round(raw / engaged, 2) if engaged else 0.0,
            "components": dict(comp),
        }

    # Co-navigation matrix.
    co = Counter()
    for m in per_agent.values():
        ds = sorted(set(m["domains"]))
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                co[(ds[i], ds[j])] += 1

    # Globals.
    reread_files = Counter()
    deadend_files = Counter()
    for a in located:
        pr = parsed[a]
        dom = [e for e in pr.events if e["kind"] == "read" and not e["is_error"] and is_domain(e["category"], e["is_nav_aid"])]
        rc = Counter(e["rel"] for e in dom)
        for rel, c in rc.items():
            reread_files[rel] += c
    zero_agents = [a for a in located if per_agent[a]["spec_reads_total"] == 0]
    readers = [m for m in per_agent.values() if m["spec_reads_total"] > 0]
    globals_ = {
        "probes_requested": len(probes),
        "probes_located": sum(1 for a in located if depth.get(a, 0) == 0),
        "agents_located": len(located),
        "agents_missing": len(missing_roots),
        "probes_without_transcript": missing_roots,
        "nested_spawns_seen": sum(m["nested_spawns"] for m in per_agent.values()),
        "nested_transcripts_unresolved": unresolved_children,
        "agents_zero_spec_reads": len(zero_agents),
        "total_spec_reads": sum(m["spec_reads_total"] for m in per_agent.values()),
        "total_domain_reads": sum(m["domain_reads"] for m in per_agent.values()),
        "total_searches": sum(m["searches_total"] for m in per_agent.values()),
        "non_domain_searches": sum(m["non_domain_searches"] for m in per_agent.values()),
        "total_cross_domain_hops": sum(m["cross_domain_hops"] for m in per_agent.values()),
        "avg_searches_before_first_read": round(sum(m["searches_before_first_spec_read"] for m in readers) / len(readers), 2) if readers else None,
        "domains_never_navigated": sorted(c for c in manifest_cats if per_domain.get(c, {}).get("engaged_agents", 0) == 0),
        "max_agent_depth": max(depth.values()) if depth else 0,
        "failed_reads_total": (sum(m["failed_reads"] or 0 for m in per_agent.values())
                               if caps["tool_results"] else None),
    }

    # Only the weights actually applied are reported: on a backend without tool
    # results the `failed` term is dropped from the sum, so advertising its weight
    # would misstate how friction was computed.
    applied_weights = {k: v for k, v in W.items() if k != "failed" or caps["tool_results"]}

    metrics = {
        "specs_root": str(Path(os.path.normpath(os.path.abspath(args.specs_root)))),
        "harness": harness,
        "capabilities": caps,
        "weights": applied_weights,
        "globals": globals_,
        "per_domain": per_domain,
        "co_navigation": [{"pair": f"{a} + {b}", "count": n} for (a, b), n in co.most_common(30)],
        "per_agent": per_agent,
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    # nav_traces.md
    trace_lines = ["# Per-probe navigation traces", "",
                   f"harness: {harness} · capabilities: {caps}", ""]
    ranked = sorted(located, key=lambda a: -(per_agent[a]["searches_before_first_spec_read"]
                                             + per_agent[a]["cross_domain_hops"]
                                             + (per_agent[a]["failed_reads"] or 0)))
    for a in ranked:
        m = per_agent[a]
        trace_lines.append(
            f"### {a} (depth {m['depth']}, {m['agent_type'] or '?'}) — "
            f"reads {m['spec_reads_total']} / hops {m['cross_domain_hops']} / "
            f"sbf {m['searches_before_first_spec_read']} / dead-ends {m['dead_end_reads']}")
        if m["description"]:
            trace_lines.append(f"_{m['description']}_")
        trace_lines.append("`" + condense_trace(parsed[a].events) + "`")
        trace_lines.append("")
    (out_dir / "nav_traces.md").write_text("\n".join(trace_lines), encoding="utf-8")

    # digest.md (budget-bounded)
    pseudo = {"(specs-root)", "(root)", "(nav-aid)"}
    dom_rows = sorted(((k, v) for k, v in per_domain.items() if k not in pseudo),
                      key=lambda kv: -kv[1]["friction_norm"])
    no_errs = not caps["tool_results"]
    sec: list[str] = ["# specs-optimization digest", "",
                      f"specs_root: `{metrics['specs_root']}`  ",
                      f"harness: `{harness}` · capabilities: tool_results={str(caps['tool_results']).lower()}, "
                      f"nesting={str(caps['nesting']).lower()}  ",
                      f"weights applied: {applied_weights}", ""]
    if no_errs:
        sec.append(f"> **failed-read signal unavailable on {harness}** — this backend does not persist "
                   f"tool results, so failed reads/searches are UNKNOWN (not zero) and the `failed` term "
                   f"is dropped from the friction sum. Do not read `n/a` as clean.")
        sec.append("")
    if not caps["nesting"] and globals_["nested_spawns_seen"]:
        sec.append(f"> **nested-subagent navigation unavailable on {harness}** — "
                   f"{globals_['nested_spawns_seen']} nested spawn(s) observed but their transcripts "
                   f"cannot be linked, so their navigation is not counted below.")
        sec.append("")
    sec.append("## Global aggregates")
    g = globals_
    sec.append(f"- probes located: **{g['probes_located']}**/{g['probes_requested']} · transcripts mined "
               f"(incl. nested): {g['agents_located']} · zero spec reads: {g['agents_zero_spec_reads']} · "
               f"max depth {g['max_agent_depth']}")
    sec.append(f"- spec reads: {g['total_spec_reads']} (domain {g['total_domain_reads']}) · "
               f"searches: {g['total_searches']} (whole-corpus {g['non_domain_searches']}) · "
               f"cross-domain hops: {g['total_cross_domain_hops']}")
    sec.append(f"- avg searches before first spec read: **{g['avg_searches_before_first_read']}**")
    if g["domains_never_navigated"]:
        sec.append(f"- domains never navigated: {', '.join(g['domains_never_navigated'])}")
    sec.append("")
    sec.append("## Per-domain navigation friction (higher = worse)")
    sec.append("| domain | files | agents | friction | sbf | hops | rereads | dead | failed | map-first |")
    sec.append("| --- | --: | --: | --: | --: | --: | --: | --: | --: | --: |")
    for name, d in dom_rows[:40]:
        c = d["components"]
        failed_cell = "n/a" if no_errs else c.get("failed", 0)
        sec.append(f"| {name} | {d['files'] if d['files'] is not None else '-'} | {d['engaged_agents']} | "
                   f"{d['friction_norm']} | {c.get('sbf',0)} | {c.get('hops',0)} | {c.get('rereads',0)} | "
                   f"{c.get('dead_ends',0)} | {failed_cell} | {d['navaid_first_rate']} |")
    sec.append("")
    if reread_files:
        sec.append("## Most re-read files")
        for rel, n in reread_files.most_common(8):
            sec.append(f"- `{rel}` — {n} reads")
        sec.append("")
    if metrics["co_navigation"]:
        sec.append("## Top co-navigated domain pairs")
        for item in metrics["co_navigation"][:10]:
            sec.append(f"- {item['pair']} — {item['count']} agents")
        sec.append("")
    sec.append("## Worst-probe traces (read in full from nav_traces.md if needed)")

    traces = []
    for a in ranked[:6]:
        m = per_agent[a]
        traces.append(f"- **{a}** (d{m['depth']}, sbf {m['searches_before_first_spec_read']}, hops {m['cross_domain_hops']}): "
                      f"`{condense_trace(parsed[a].events)}`")

    digest = enforce_budget(sec, traces, args.digest_budget_bytes)
    (out_dir / "digest.md").write_text(digest, encoding="utf-8")

    print(f"harness={harness} caps={caps} located={len(located)} spec_events={total_spec_events} "
          f"digest_bytes={len(digest.encode('utf-8'))} -> {out_dir}", file=sys.stderr)
    if total_spec_events == 0:
        print("no spec navigation detected across any located probe "
              "(check --specs-root or whether probe prompts exercised the specs)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
