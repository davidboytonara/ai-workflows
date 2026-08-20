#!/usr/bin/env python3
"""Generic scheduled-task daemon.

Reads tasks from `tasks.yaml`, runs them on cron schedules in a thread pool,
detects missed runs after downtime, persists per-task history, and pauses
tasks that exit 42 until the user fills in their clarify file.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import uuid
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

_HEARTBEAT_DIR = Path(__file__).resolve().parent
if str(_HEARTBEAT_DIR) not in sys.path:
    sys.path.insert(0, str(_HEARTBEAT_DIR))

from clarify import (  # noqa: E402
    DEFAULT_CLARIFY_DIR,
    RESOLVED_SUBDIR,
    ClarifyFile,
    archive,
    clarify_path,
    is_answered,
    read as read_clarify,
)
from config import TaskConfig, load_tasks  # noqa: E402
from history import DEFAULT_HISTORY_DIR, append as append_history  # noqa: E402
from notify import SlackNotifier  # noqa: E402
from runner import RunResult, build_command, execute  # noqa: E402
from scheduler import compute_due_runs  # noqa: E402
from state import DEFAULT_STATE_DIR, StateStore, utc_now  # noqa: E402

DEFAULT_TASKS_FILE = _HEARTBEAT_DIR / "tasks.yaml"
DEFAULT_STATE_FILE = DEFAULT_STATE_DIR / "tasks.json"
DEFAULT_INTERVAL_SECONDS = 60
CLARIFY_SCAN_INTERVAL_SECONDS = 180
POOL_SIZE = 10

LOG = logging.getLogger("heartbeat")


class Daemon:
    def __init__(
        self,
        tasks: list[TaskConfig],
        state_store: StateStore,
        *,
        history_dir: Path,
        clarify_dir: Path,
        pi_binary: str,
        cwd: Path,
        notifier: SlackNotifier | None = None,
    ) -> None:
        self.tasks = {t.name: t for t in tasks}
        self.state = state_store
        self.history_dir = history_dir
        self.clarify_dir = clarify_dir
        self.resolved_dir = clarify_dir / RESOLVED_SUBDIR
        self.pi_binary = pi_binary
        self.cwd = cwd
        self.notifier = notifier if notifier is not None else SlackNotifier.from_env()

        self.executor = ThreadPoolExecutor(max_workers=POOL_SIZE, thread_name_prefix="hb-task")
        self.task_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self.in_flight_lock = threading.Lock()
        self.in_flight_slots: dict[str, set[datetime]] = defaultdict(set)
        self.shutdown_event = threading.Event()

    def shutdown(self) -> None:
        if self.shutdown_event.is_set():
            return
        LOG.info("shutdown requested; draining pool")
        self.shutdown_event.set()
        self.executor.shutdown(wait=True, cancel_futures=False)

    def tick(self, now: datetime | None = None) -> list[Future[None]]:
        if now is None:
            now = utc_now()
        futures: list[Future[None]] = []

        for name, task in self.tasks.items():
            ts = self.state.get(name)

            if ts.last_run_at is None:
                self.state.update(name, last_run_at=now)
                self.state.save()
                continue

            if ts.blocked_runid:
                continue

            for slot in compute_due_runs(task, ts.last_run_at, now):
                if self._dependencies_running(task):
                    LOG.debug("[%s] waiting for dependencies %s", task.name, list(task.depends_on))
                    continue
                fut = self._submit_run(task, slot, None)
                if fut is not None:
                    futures.append(fut)

        if self._should_scan_clarify(now):
            futures.extend(self._resume_answered(now))
            self.state.last_clarify_scan_at = now
            self.state.save()

        return futures

    def _should_scan_clarify(self, now: datetime) -> bool:
        last = self.state.last_clarify_scan_at
        if last is None:
            return True
        return (now - last).total_seconds() >= CLARIFY_SCAN_INTERVAL_SECONDS

    def _resume_answered(self, now: datetime) -> list[Future[None]]:
        futures: list[Future[None]] = []
        for name, task in self.tasks.items():
            ts = self.state.get(name)
            if not ts.blocked_runid or not ts.blocked_since:
                continue
            path = clarify_path(self.clarify_dir, name, ts.blocked_runid)
            if not is_answered(path, ts.blocked_since):
                continue
            try:
                clarify_obj = read_clarify(path)
            except Exception as exc:
                LOG.error("cannot parse clarify file %s: %s", path, exc)
                continue
            scheduled_for = ts.blocked_scheduled_for or now
            old_runid = ts.blocked_runid
            self.state.update(
                name,
                blocked_runid=None,
                blocked_since=None,
                blocked_scheduled_for=None,
            )
            self.state.save()
            archived = archive(path, self.resolved_dir)
            LOG.info("clarify resolved for %s run=%s; archived to %s", name, old_runid, archived)
            fut = self._submit_run(task, scheduled_for, clarify_obj)
            if fut is not None:
                futures.append(fut)
        return futures

    def _dependencies_running(self, task: TaskConfig) -> bool:
        if not task.depends_on:
            return False
        with self.in_flight_lock:
            return any(bool(self.in_flight_slots[name]) for name in task.depends_on)

    def _submit_run(
        self,
        task: TaskConfig,
        scheduled_for: datetime,
        resume_from: ClarifyFile | None,
    ) -> Future[None] | None:
        with self.in_flight_lock:
            if scheduled_for in self.in_flight_slots[task.name]:
                LOG.debug("[%s] skip duplicate in-flight slot %s", task.name, scheduled_for.isoformat())
                return None
            self.in_flight_slots[task.name].add(scheduled_for)
        return self.executor.submit(self._run_one, task, scheduled_for, resume_from)

    def _run_one(
        self,
        task: TaskConfig,
        scheduled_for: datetime,
        resume_from: ClarifyFile | None,
    ) -> None:
        try:
            with self.task_locks[task.name]:
                if self.shutdown_event.is_set():
                    return
                run_id = uuid.uuid4().hex[:8]
                LOG.info("[%s run=%s] starting (scheduled=%s)", task.name, run_id, scheduled_for.isoformat())
                try:
                    result = execute(
                        task,
                        run_id,
                        scheduled_for,
                        clarify_dir=self.clarify_dir,
                        pi_binary=self.pi_binary,
                        cwd=self.cwd,
                        resume_from=resume_from,
                    )
                except Exception as exc:
                    LOG.exception("[%s run=%s] crashed: %s", task.name, run_id, exc)
                    return

                append_history(self.history_dir, task.name, result.to_history_entry())
                self._update_state_after_run(task.name, result)
                self.notifier.notify_run(task.name, result, self.history_dir)
                LOG.info(
                    "[%s run=%s] finished rc=%s pending=%s",
                    task.name,
                    run_id,
                    result.returncode,
                    result.pending_reason,
                )
        finally:
            with self.in_flight_lock:
                self.in_flight_slots[task.name].discard(scheduled_for)

    def _update_state_after_run(self, task_name: str, result: RunResult) -> None:
        if result.pending_reason == "blocked_on_clarification":
            self.state.update(
                task_name,
                blocked_runid=result.run_id,
                blocked_since=result.started_at,
                blocked_scheduled_for=result.scheduled_for,
            )
        else:
            self.state.update(task_name, last_run_at=result.scheduled_for)
        self.state.save()


def _print_dry_run(tasks: list[TaskConfig], pi_binary: str) -> None:
    for task in tasks:
        cmd = build_command(task, pi_binary=pi_binary)
        print(f"[dry-run] {task.name}: cron={task.cron} tz={task.cron_tz} catchup={task.catchup}")
        if task.precondition:
            print(f"  precondition: {task.precondition}")
        if task.depends_on:
            print(f"  depends_on: {list(task.depends_on)}")
        print(f"  command: {cmd}")


def _filter_tasks(tasks: list[TaskConfig], only: str | None) -> list[TaskConfig]:
    if only is None:
        return tasks
    matched = [t for t in tasks if t.name == only]
    if not matched:
        raise SystemExit(f"no task named {only!r}; available: {[t.name for t in tasks]}")
    return matched


def positive_int(value: str) -> int:
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Heartbeat: generic scheduled-task daemon")
    parser.add_argument("--tasks-file", type=Path, default=DEFAULT_TASKS_FILE)
    parser.add_argument("--task", help="Run only this task name (debug)")
    parser.add_argument("--once", action="store_true", help="Run one tick then exit")
    parser.add_argument("--dry-run", action="store_true", help="Print intended commands; do not execute")
    parser.add_argument("--interval-seconds", type=positive_int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--pi-binary", default="pi")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--history-dir", type=Path, default=DEFAULT_HISTORY_DIR)
    parser.add_argument("--clarify-dir", type=Path, default=DEFAULT_CLARIFY_DIR)
    parser.add_argument("--cwd", type=Path, default=Path.home())
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")

    tasks = _filter_tasks(load_tasks(args.tasks_file), args.task)

    if args.dry_run:
        _print_dry_run(tasks, args.pi_binary)
        return 0

    args.history_dir.mkdir(parents=True, exist_ok=True)
    args.clarify_dir.mkdir(parents=True, exist_ok=True)
    (args.clarify_dir / RESOLVED_SUBDIR).mkdir(parents=True, exist_ok=True)
    args.state_path.parent.mkdir(parents=True, exist_ok=True)

    state = StateStore(args.state_path)
    state.load()

    daemon = Daemon(
        tasks,
        state,
        history_dir=args.history_dir,
        clarify_dir=args.clarify_dir,
        pi_binary=args.pi_binary,
        cwd=args.cwd,
    )

    def _signal_handler(signum, _frame):  # noqa: ANN001
        LOG.info("received signal %s", signum)
        daemon.shutdown()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        if args.once:
            futures = daemon.tick()
            for fut in futures:
                fut.result()
            daemon.shutdown()
            return 0

        while not daemon.shutdown_event.is_set():
            daemon.tick()
            daemon.shutdown_event.wait(timeout=args.interval_seconds)
    finally:
        daemon.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
