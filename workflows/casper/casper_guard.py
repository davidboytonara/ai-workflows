#!/usr/bin/env python3
"""Context-token budget guard for one headless `claude -p` resolver session.

Wraps a single claude CLI call in stream-json mode so the session is bounded by
BOTH budgets, with a graceful wind-down before each hard stop:

  tokens : wind-down notice injected at (max-context-tokens - context-grace);
           hard stop (SIGTERM, SIGKILL 10s later) at max-context-tokens
  time   : wind-down notice injected at (stopwatch - grace);
           hard stop at stopwatch

The wind-down is a mid-run user message (steering) telling the resolver to
refresh its "## Progress / Handover" checkpoint, mark the plan done only if
complete, and end its turn. The context gauge counts only main-chain assistant
events (sidechains have their own windows) and always uses the latest value —
session compaction can shrink the window, so a running max would overshoot.

Stdout is a compact human log (assistant text, ">> Tool {input}" lines, and
"[guard] ..." gauge/lifecycle lines), not raw stream-json, so fanout's
logs/<plan>.log stays readable and small.

With --resume-session, the claude call re-enters that prior session (--resume) so a
paused plan continues with its warm context instead of a cold rebuild; if the session
cannot be resumed (evicted/unknown id: exit != 0 with no stream events), the guard
falls back to one cold start automatically. With --state-file, the guard atomically
writes {"session","reason","gauge","exit","usage_events","result_seen","resumed",
"first_call_over_budget"} on completion so the dispatcher can decide whether the NEXT
run may warm-resume (sessions near the token budget must restart cold — resuming them
would immediately re-trip the hard limit) and whether the run made zero progress
(first_call_over_budget: the token budget killed the very first model call, i.e. the
plan's inputs alone may not fit the budget).

Usage:
  casper_guard.py --model MODEL [--effort EFFORT] [--stopwatch S] [--grace S]
                  [--max-context-tokens N] [--context-grace N]
                  [--gauge-log-step N] [--claude-bin BIN]
                  [--resume-session ID] [--state-file PATH] [--] PROMPT

Exit codes:
  <child>  passed through from claude (128+signum if it died to a signal)
  124      budget stop — token hard limit or wall-clock stopwatch (treat as paused)
  2        usage error
"""

from __future__ import annotations

import argparse
import ctypes
import dataclasses
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

_USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens",
                 "cache_read_input_tokens", "output_tokens")

_WIND_DOWN_BODY = """\
and you WILL be hard-stopped at the limit. Stop starting new work immediately and wrap up:
1. Safely finish or abandon only the step already in progress — nothing new.
2. Replace the "## Progress / Handover" section of the plan document with a fresh bounded
   checkpoint (completed work, current evidence, remaining work, exact next action), exactly
   as your original instructions describe.
3. ONLY if the whole plan is genuinely complete, run the exact casper_status.py
   "--set <plan> done" command given in your original instructions.
4. End your turn with a brief summary. Do not start any new task, edit, or investigation
   beyond the checkpoint update."""


@dataclasses.dataclass(frozen=True)
class Budget:
    stopwatch: int
    grace: int
    max_context_tokens: int
    context_grace: int


# --------------------------------------------------------------- pure helpers

def parse_event(line: str) -> dict | None:
    """One stream-json line -> event dict, or None for blank/non-JSON lines."""
    line = line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def is_main_chain(event: dict) -> bool:
    """Sidechain (subagent) events carry parent_tool_use_id and have their own window."""
    return event.get("parent_tool_use_id") in (None, "")


def context_tokens(event: dict) -> int | None:
    """Context occupancy of one main-chain assistant API call.

    input + cache_creation + cache_read is the window content of THIS call;
    output_tokens is added because this call's output is irrevocably in-window
    for the next call — the conservative number a kill decision should use.
    """
    if event.get("type") != "assistant" or not is_main_chain(event):
        return None
    usage = (event.get("message") or {}).get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        return sum(int(usage.get(field) or 0) for field in _USAGE_FIELDS)
    except (TypeError, ValueError):
        return None


def compact_log_lines(event: dict, tool_input_chars: int = 200) -> list[str]:
    """Human log lines for one event: text verbatim, tool calls one per line."""
    if event.get("type") != "assistant" or not is_main_chain(event):
        return []
    lines: list[str] = []
    for block in (event.get("message") or {}).get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            lines.append(block["text"])
        elif block.get("type") == "tool_use":
            raw = json.dumps(block.get("input", {}), ensure_ascii=False)
            if len(raw) > tool_input_chars:
                raw = raw[:tool_input_chars] + "…"
            lines.append(f">> {block.get('name', '?')} {raw}")
    return lines


def should_wind_down(gauge: int, elapsed: float, budget: Budget,
                     already_sent: bool, result_seen: bool) -> str | None:
    """Which budget (if any) warrants the one-shot wind-down notice now."""
    if already_sent or result_seen:
        return None
    if (budget.max_context_tokens > 0
            and gauge >= budget.max_context_tokens - budget.context_grace):
        return "token"
    # Cap grace at half the stopwatch so a short stopwatch (e.g. fanout's default
    # --grace 300 with --stopwatch 300) never fires the notice at t=0.
    if elapsed >= budget.stopwatch - min(budget.grace, budget.stopwatch // 2):
        return "time"
    return None


def should_hard_stop(gauge: int, elapsed: float, budget: Budget) -> str | None:
    """Which budget (if any) warrants killing the child now."""
    if budget.max_context_tokens > 0 and gauge >= budget.max_context_tokens:
        return "token"
    if elapsed >= budget.stopwatch:
        return "time"
    return None


def wind_down_text(reason: str, used: int, budget_tokens: int, seconds_left: float) -> str:
    if reason == "token":
        first = (f"Your context budget is nearly exhausted: about {used:,} of "
                 f"{budget_tokens:,} tokens are used,")
    else:
        first = (f"Your wall-clock budget is nearly exhausted: about {int(seconds_left)} "
                 f"seconds remain before the hard stop,")
    return f"[CASPER GUARD — WIND-DOWN NOTICE]\n{first}\n{_WIND_DOWN_BODY}"


def user_message_line(text: str) -> bytes:
    """The exact stream-json stdin shape the claude CLI accepts mid-run."""
    message = {"type": "user",
               "message": {"role": "user",
                           "content": [{"type": "text", "text": text}]}}
    return (json.dumps(message, ensure_ascii=False) + "\n").encode()


def final_exit_code(hard_fired: bool, child_rc: int | None) -> int:
    """124 for any budget stop; otherwise pass the child through (128+signum)."""
    if hard_fired or child_rc is None:
        return 124
    return 128 - child_rc if child_rc < 0 else child_rc


# ---------------------------------------------------------- process plumbing

_SHUTDOWN = False


def _request_shutdown(signum, frame) -> None:
    global _SHUTDOWN
    _SHUTDOWN = True


def _set_pdeathsig() -> None:
    """Best-effort: kill the child if the guard itself is SIGKILLed (Linux)."""
    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
    except Exception:
        pass


def _log(msg: str) -> None:
    print(msg, flush=True)


def _write_stdin(child: subprocess.Popen, data: bytes) -> bool:
    try:
        child.stdin.write(data)
        child.stdin.flush()
        return True
    except (BrokenPipeError, OSError, ValueError):
        return False  # child gone or stdin closed; the loop will observe it


def _close_stdin(child: subprocess.Popen) -> None:
    try:
        if child.stdin and not child.stdin.closed:
            child.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass


def _signal_group(child: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(child.pid, sig)  # start_new_session=True makes pid the pgid
    except (ProcessLookupError, PermissionError, OSError):
        try:
            child.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass


def _write_state(path: Path, state: dict) -> None:
    """Advisory sidecar for the dispatcher; never fail the run over it."""
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state) + "\n")
        os.replace(tmp, path)
    except OSError:
        pass


# ------------------------------------------------------------------ run loop

def _supervise(args: argparse.Namespace, resume_session: str | None) -> tuple[int, dict]:
    budget = Budget(args.stopwatch, args.grace, args.max_context_tokens, args.context_grace)
    cmd = [args.claude_bin, "-p", "--dangerously-skip-permissions"]
    if resume_session:
        cmd += ["--resume", resume_session]
    cmd += ["--model", args.model, "--effort", args.effort,
            "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
    try:
        child = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
            start_new_session=True, preexec_fn=_set_pdeathsig,
            env={**os.environ, "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"})
    except OSError as exc:
        print(f"casper_guard.py: cannot launch {args.claude_bin}: {exc}", file=sys.stderr)
        return 2, {"session": None, "reason": "spawn-error", "gauge": 0, "exit": 2,
                   "usage_events": 0, "result_seen": False, "resumed": bool(resume_session),
                   "first_call_over_budget": False}

    ctx_desc = (f"ctx={budget.max_context_tokens:,} "
                f"wind-down={budget.max_context_tokens - budget.context_grace:,}"
                if budget.max_context_tokens else "ctx=off")
    resume_desc = f" resume={resume_session}" if resume_session else ""
    _log(f"[guard] start model={args.model} effort={args.effort} "
         f"stopwatch={budget.stopwatch}s grace={budget.grace}s {ctx_desc}{resume_desc}")
    _write_stdin(child, user_message_line(args.prompt))
    start = time.monotonic()

    sel = selectors.DefaultSelector()
    fd = child.stdout.fileno()
    os.set_blocking(fd, False)
    sel.register(fd, selectors.EVENT_READ)

    buf = bytearray()
    gauge = 0
    usage_events = 0
    sidechain_events = 0
    gauge_bucket = 0
    session_id: str | None = None
    soft_sent = False
    hard_fired = False
    hard_reason: str | None = None
    first_call_over_budget = False
    result_seen = False
    kill_at: float | None = None
    eof = False

    def gauge_line() -> None:
        if budget.max_context_tokens:
            pct = 100 * gauge // budget.max_context_tokens
            _log(f"[guard] ctx {gauge:,}/{budget.max_context_tokens:,} ({pct}%)")
        else:
            _log(f"[guard] ctx {gauge:,}")

    def drain() -> None:
        nonlocal eof
        while not eof:
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                return
            except OSError:
                chunk = b""
            if not chunk:
                eof = True
                sel.unregister(fd)
                return
            buf.extend(chunk)

    def handle(line: bytes) -> None:
        nonlocal gauge, usage_events, sidechain_events, gauge_bucket, result_seen, session_id
        event = parse_event(line.decode("utf-8", "replace"))
        if event is None:
            text = line.decode("utf-8", "replace").strip()
            if text:
                _log(f"[raw] {text[:200]}")
            return
        if event.get("session_id"):
            session_id = event["session_id"]  # stable across --resume (verified)
        if not is_main_chain(event):
            sidechain_events += 1
            return
        tokens = context_tokens(event)
        if tokens is not None:
            gauge = tokens  # latest wins: compaction can shrink the window
            usage_events += 1
            bucket = gauge // args.gauge_log_step
            if bucket != gauge_bucket:
                gauge_bucket = bucket
                gauge_line()
        for entry in compact_log_lines(event):
            _log(entry)
        if event.get("type") == "result":
            result_seen = True
            gauge_line()
            _log(f"[guard] result num_turns={event.get('num_turns')} "
                 f"is_error={event.get('is_error')}")
            if event.get("result"):
                _log(str(event["result"]))
            _close_stdin(child)  # verified: the CLI then exits cleanly

    def pump() -> None:
        drain()
        while True:
            nl = buf.find(b"\n")
            if nl < 0:
                return
            line = bytes(buf[:nl])
            del buf[:nl + 1]
            handle(line)

    while True:
        if eof:
            time.sleep(0.25)
        else:
            sel.select(0.25)
        pump()

        elapsed = time.monotonic() - start
        if _SHUTDOWN and not hard_fired:
            hard_fired, hard_reason = True, "signal"
            _log("[guard] termination signal received — stopping the resolver")
            _close_stdin(child)
            _signal_group(child, signal.SIGTERM)
            kill_at = time.monotonic() + 10
        if not soft_sent and not hard_fired:
            reason = should_wind_down(gauge, elapsed, budget, soft_sent, result_seen)
            if reason:
                soft_sent = True
                left = max(budget.stopwatch - elapsed, 0)
                gauge_line()
                _log(f"[guard] wind-down injected ({reason}) at ctx {gauge:,}, "
                     f"{int(left)}s left")
                _write_stdin(child, user_message_line(
                    wind_down_text(reason, gauge, budget.max_context_tokens, left)))
        if not hard_fired:
            reason = should_hard_stop(gauge, elapsed, budget)
            if reason:
                hard_fired, hard_reason = True, reason
                if reason == "token" and usage_events <= 1:
                    first_call_over_budget = True  # zero progress: dispatcher escalates
                    _log("[guard] context over budget on FIRST call — the plan input may "
                         "exceed the budget; consider splitting the plan")
                gauge_line()
                _log(f"[guard] HARD {reason} limit — SIGTERM")
                _close_stdin(child)
                _signal_group(child, signal.SIGTERM)
                kill_at = time.monotonic() + 10
        if kill_at is not None and child.poll() is None and time.monotonic() >= kill_at:
            _log("[guard] SIGKILL")
            _signal_group(child, signal.SIGKILL)
            kill_at = None
        if child.poll() is not None:
            pump()
            if buf.strip():
                handle(bytes(buf))  # trailing line without a final newline
            break

    _close_stdin(child)
    try:
        child.stdout.close()
    except OSError:
        pass
    if budget.max_context_tokens and not usage_events:
        _log("[guard] WARNING: no usage events seen — token budget was not enforced "
             "(stream format drift?)")
    _log(f"[guard] done: exit={child.returncode} ctx={gauge:,} "
         f"sidechain_events={sidechain_events} reason={hard_reason or 'child-exit'}")
    code = final_exit_code(hard_fired, child.returncode)
    return code, {"session": session_id, "reason": hard_reason or "child-exit",
                  "gauge": gauge, "exit": code, "usage_events": usage_events,
                  "result_seen": result_seen, "resumed": bool(resume_session),
                  "first_call_over_budget": first_call_over_budget}


def _run(args: argparse.Namespace) -> int:
    code, state = _supervise(args, args.resume_session)
    if (args.resume_session and code not in (0,) and not _SHUTDOWN
            and state["reason"] == "child-exit"
            and not state["usage_events"] and not state["result_seen"]):
        # Session evicted/unknown: the CLI dies before emitting any stream event
        # (verified: exit 1 + "No conversation found..."). Degrade to a cold start.
        _log(f"[guard] resume of session {args.resume_session} failed (exit {code}, "
             "no events) — falling back to a cold start")
        code, state = _supervise(args, None)
    if args.state_file:
        _write_state(args.state_file, state)
    return code


# ----------------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser(description="Token+time budget guard for one claude -p call.")
    ap.add_argument("--model", required=True, help="Full model id (already alias-resolved)")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--stopwatch", type=int, default=7200, help="Hard wall-clock budget (s)")
    ap.add_argument("--grace", type=int, default=300,
                    help="Time wind-down notice at stopwatch-grace seconds "
                         "(grace is capped at half the stopwatch)")
    ap.add_argument("--max-context-tokens", type=int, default=470000,
                    help="Hard context-token budget; 0 disables token checks")
    ap.add_argument("--context-grace", type=int, default=40000,
                    help="Token wind-down notice at max-context-tokens minus this")
    ap.add_argument("--gauge-log-step", type=int, default=25000,
                    help="Log a context gauge line at each multiple of this")
    ap.add_argument("--claude-bin", default="claude", help="Executable to launch")
    ap.add_argument("--resume-session", default=None,
                    help="Prior claude session id to warm-resume (falls back to a "
                         "cold start if the session cannot be resumed)")
    ap.add_argument("--state-file", type=Path, default=None,
                    help="Write {session, reason, gauge, exit, resumed} JSON here on "
                         "completion for the dispatcher's warm-resume decision")
    ap.add_argument("prompt", help="Initial user message (sent over stdin)")
    args = ap.parse_args()
    if args.stopwatch <= 0 or args.grace < 0:
        ap.error("stopwatch must be positive and grace non-negative")
    if args.max_context_tokens < 0:
        ap.error("max-context-tokens must be >= 0")
    if args.max_context_tokens and not 0 <= args.context_grace < args.max_context_tokens:
        ap.error("context-grace must satisfy 0 <= context-grace < max-context-tokens")
    if args.gauge_log_step <= 0:
        ap.error("gauge-log-step must be positive")
    if not args.prompt.strip():
        ap.error("empty PROMPT")
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
