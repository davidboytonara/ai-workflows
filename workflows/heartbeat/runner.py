"""Single-task execution: precondition, subprocess, clarify detection."""

from __future__ import annotations

import collections
import logging
import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clarify import ClarifyFile, clarify_path, read as read_clarify, write_stub
from config import TaskConfig
from state import utc_now

LOG = logging.getLogger(__name__)

SUMMARY_LINES = 40
PRECONDITION_TIMEOUT_SECONDS = 30
KILL_GRACE_SECONDS = 10
RETURNCODE_NEEDS_CLARIFY = 42
TLDR_PREFIX = "SUMMARY:"

PENDING_PRECONDITION_SKIP = "precondition_skip"
PENDING_BLOCKED = "blocked_on_clarification"
PENDING_FAILED = "failed"
PENDING_TIMEOUT = "timeout"


@dataclass
class RunResult:
    run_id: str
    scheduled_for: datetime
    started_at: datetime
    finished_at: datetime
    returncode: int
    pending_reason: str | None
    summary: str
    tldr: str | None
    command: list[str]
    clarify: ClarifyFile | None = None

    def to_history_entry(self) -> dict[str, Any]:
        def iso(dt: datetime) -> str:
            return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        return {
            "run_id": self.run_id,
            "scheduled_for": iso(self.scheduled_for),
            "started_at": iso(self.started_at),
            "finished_at": iso(self.finished_at),
            "returncode": self.returncode,
            "pending_reason": self.pending_reason,
            "summary": self.summary,
            "tldr": self.tldr,
            "command": self.command,
        }


def build_command(task: TaskConfig, prompt: str | None = None, pi_binary: str = "pi") -> list[str]:
    """Build argv for a task. `prompt` overrides task.prompt (used on clarify resume)."""
    if task.type == "pi_workflow":
        effective_prompt = prompt if prompt is not None else task.prompt
        if effective_prompt is None or task.workflow is None:
            raise ValueError(f"task {task.name}: pi_workflow missing workflow/prompt")
        return [pi_binary, "--print", f"@{task.workflow}", effective_prompt]
    if task.command is None:
        raise ValueError(f"task {task.name}: shell missing command")
    return list(task.command)


def build_resume_prompt(original_prompt: str, question: str, reply: str) -> str:
    return (
        f"{original_prompt.rstrip()}\n\n"
        "---\n"
        "Previous question:\n"
        f"{question.strip()}\n\n"
        "User reply:\n"
        f"{reply.strip()}\n"
    )


def _run_precondition(precondition: str, cwd: Path) -> int:
    try:
        completed = subprocess.run(
            precondition,
            shell=True,
            cwd=cwd,
            check=False,
            timeout=PRECONDITION_TIMEOUT_SECONDS,
            capture_output=True,
        )
        return completed.returncode
    except subprocess.TimeoutExpired:
        LOG.warning("precondition timed out: %s", precondition)
        return 124


def _run_command(
    command: list[str],
    cwd: Path,
    timeout: int,
    buffer: collections.deque[str],
    tldr_holder: list[str | None],
) -> tuple[int, bool]:
    """Run command; stream combined stdout/stderr into buffer (last N lines).

    Returns (returncode, timed_out). Children run in a new session so we can
    SIGTERM/SIGKILL the full process group on timeout or shutdown.
    """
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            stripped = line.rstrip("\n")
            buffer.append(stripped)
            if stripped.strip().startswith(TLDR_PREFIX):
                tldr_holder[0] = stripped.strip()[len(TLDR_PREFIX):].strip()

    pump_thread = threading.Thread(target=pump, daemon=True)
    pump_thread.start()

    try:
        proc.wait(timeout=timeout)
        pump_thread.join(timeout=5)
        return proc.returncode, False
    except subprocess.TimeoutExpired:
        pgid = os.getpgid(proc.pid)
        LOG.warning("task timed out after %ss; killing pgid=%s", timeout, pgid)
        try:
            os.killpg(pgid, signal.SIGTERM)
            proc.wait(timeout=KILL_GRACE_SECONDS)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        pump_thread.join(timeout=5)
        return proc.returncode, True


def execute(
    task: TaskConfig,
    run_id: str,
    scheduled_for: datetime,
    *,
    clarify_dir: Path,
    pi_binary: str = "pi",
    cwd: Path | None = None,
    resume_from: ClarifyFile | None = None,
) -> RunResult:
    """Execute one task invocation. Writes clarify stub on exit 42 if missing."""
    if cwd is None:
        cwd = Path.home()
    started_at = utc_now()

    if resume_from is not None and task.type == "pi_workflow" and task.prompt is not None:
        prompt = build_resume_prompt(task.prompt, resume_from.question, resume_from.reply)
    else:
        prompt = task.prompt

    command = build_command(task, prompt=prompt, pi_binary=pi_binary)

    if task.precondition:
        rc = _run_precondition(task.precondition, cwd)
        if rc != 0:
            return RunResult(
                run_id=run_id,
                scheduled_for=scheduled_for,
                started_at=started_at,
                finished_at=utc_now(),
                returncode=rc,
                pending_reason=PENDING_PRECONDITION_SKIP,
                summary=f"precondition exited {rc}: {task.precondition}",
                tldr=None,
                command=command,
            )

    buffer: collections.deque[str] = collections.deque(maxlen=SUMMARY_LINES)
    tldr_holder: list[str | None] = [None]
    rc, timed_out = _run_command(command, cwd, task.timeout_seconds, buffer, tldr_holder)
    finished_at = utc_now()
    summary = "\n".join(buffer)

    clarify_obj: ClarifyFile | None = None
    if timed_out:
        pending_reason: str | None = PENDING_TIMEOUT
    elif rc == 0:
        pending_reason = None
    elif rc == RETURNCODE_NEEDS_CLARIFY:
        pending_reason = PENDING_BLOCKED
        path = clarify_path(clarify_dir, task.name, run_id)
        if not path.exists():
            LOG.warning("task %s exited 42 without clarify file; writing empty stub", task.name)
            write_stub(clarify_dir, task.name, run_id, started_at, question="")
        try:
            clarify_obj = read_clarify(path)
        except ValueError as exc:
            LOG.error("clarify file unparseable (%s); rewriting stub", exc)
            write_stub(clarify_dir, task.name, run_id, started_at, question="")
            clarify_obj = read_clarify(path)
    else:
        pending_reason = PENDING_FAILED

    return RunResult(
        run_id=run_id,
        scheduled_for=scheduled_for,
        started_at=started_at,
        finished_at=finished_at,
        returncode=rc,
        pending_reason=pending_reason,
        summary=summary,
        tldr=tldr_holder[0],
        command=command,
        clarify=clarify_obj,
    )
