#!/usr/bin/env python3
"""Prepare the runtime and launch the Playwright daemon.

Uses the shared Casper virtualenv at ~/.agents/.venv (managed outside this
workflow), verifies its requirements, and installs Chromium into a
workflow-local .browsers directory before starting the daemon. Browser
binaries stay under this folder; the Python runtime is shared.

Default mode execs the daemon in the foreground (background it yourself).
With --ensure the script instead runs the full daemon-availability sequence
itself: health-check port --port, start the daemon in the background (output
to --log) only if the check fails, then re-check until healthy or --wait
seconds pass.

Exit codes:
  0  success (--ensure: daemon healthy — already running or freshly started)
  1  setup failure (--ensure: daemon failed to start or never became healthy;
     read the --log file)
  2  usage error
  3  --ensure only: a headless daemon is already running but --headed was
     requested; shut it down (playwright_client.py action shutdown) and re-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
# Shared Casper virtualenv, provisioned and maintained outside this workflow.
VENV_DIR = Path.home() / ".agents" / ".venv"
BROWSERS_ROOT = SCRIPT_DIR / ".browsers"
REQUIREMENTS_PATH = SCRIPT_DIR / "requirements.txt"
# Keep workflow state markers local (alongside the browsers we own) so the
# shared venv stays pristine. .browsers is git/chezmoi-ignored.
REQUIREMENTS_HASH_PATH = BROWSERS_ROOT / ".playwright.requirements.sha256"
BROWSER_MARKER_PATH = BROWSERS_ROOT / ".playwright.chromium.ready"
AUTH_ROOT = SCRIPT_DIR / ".auth"
ARTIFACT_ROOT = SCRIPT_DIR / "artifacts"
DEFAULT_PORT = 17337
DEFAULT_LOG = SCRIPT_DIR / "logs" / "daemon.log"
DEFAULT_WAIT_SECONDS = 20.0


def venv_python() -> Path:
    return VENV_DIR / "bin" / "python"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str]) -> None:
    subprocess.check_call(command)


def ensure_venv() -> Path:
    python_path = venv_python()
    if not python_path.exists():
        raise OSError(
            f"Shared Casper virtualenv not found at {VENV_DIR}. "
            f"Create it (python3 -m venv {VENV_DIR}) before launching this workflow."
        )
    return python_path


def ensure_requirements(python_path: Path) -> None:
    wanted = sha256(REQUIREMENTS_PATH)
    current = REQUIREMENTS_HASH_PATH.read_text(encoding="utf-8").strip() if REQUIREMENTS_HASH_PATH.exists() else ""
    if current == wanted:
        return
    run([str(python_path), "-m", "pip", "install", "-q", "-r", str(REQUIREMENTS_PATH)])
    REQUIREMENTS_HASH_PATH.write_text(wanted + "\n", encoding="utf-8")
    if BROWSER_MARKER_PATH.exists():
        BROWSER_MARKER_PATH.unlink()


def ensure_browser(python_path: Path) -> None:
    if BROWSER_MARKER_PATH.exists():
        return
    run([str(python_path), "-m", "playwright", "install", "chromium"])
    BROWSER_MARKER_PATH.write_text("chromium\n", encoding="utf-8")


def prepare_runtime() -> Path:
    """Create workflow dirs, pin the browsers path, and verify the shared venv."""
    AUTH_ROOT.mkdir(parents=True, exist_ok=True)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    BROWSERS_ROOT.mkdir(parents=True, exist_ok=True)
    # Keep browser binaries inside this folder so the workflow stays self-contained.
    # `playwright install` and the daemon (child process) both honour this env var.
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BROWSERS_ROOT))
    python_path = ensure_venv()
    ensure_requirements(python_path)
    ensure_browser(python_path)
    return python_path


def check_health(port: int, timeout: float = 3.0) -> dict[str, Any] | None:
    """Return the daemon's /health payload if it responds ok, else None."""
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) and payload.get("ok") else None


def health_summary(status: str, port: int, health: dict[str, Any]) -> str:
    return json.dumps(
        {
            "ok": True,
            "status": status,
            "port": port,
            "pid": health.get("pid"),
            "headless": health.get("headless"),
            "channel": health.get("channel"),
        }
    )


def build_ensure_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="playwright_launch.py --ensure",
        description=(
            "Ensure the Playwright daemon is up: health-check the port, start the daemon\n"
            "in the background (output to --log) only if the check fails, then re-check\n"
            "until healthy or --wait seconds pass."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Exit codes:\n"
            "  0  daemon healthy (already running or freshly started)\n"
            "  1  daemon failed to start or never became healthy — read the --log file\n"
            "  2  usage error\n"
            "  3  headless daemon already running but --headed requested; shut it down\n"
            "     (playwright_client.py action shutdown) and re-run"
        ),
    )
    parser.add_argument("--ensure", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Daemon port. Default: {DEFAULT_PORT}")
    parser.add_argument("--headed", action="store_true", help="Start (or require) a headed daemon")
    parser.add_argument("--channel", default="", help="Optional browser channel forwarded to the daemon, e.g. chrome")
    parser.add_argument("--log", default=str(DEFAULT_LOG), help=f"Daemon log file. Default: {DEFAULT_LOG}")
    parser.add_argument(
        "--wait",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        help=f"Seconds to wait for the daemon to become healthy. Default: {DEFAULT_WAIT_SECONDS:.0f}",
    )
    return parser


def ensure_main(argv: list[str]) -> int:
    args = build_ensure_parser().parse_args(argv)

    health = check_health(args.port)
    if health is not None:
        if args.headed and health.get("headless"):
            print(
                f"A headless daemon is already running on port {args.port} but --headed was requested.\n"
                f"Shut it down first (playwright_client.py --port {args.port} action shutdown), then re-run.",
                file=sys.stderr,
            )
            return 3
        print(health_summary("already-running", args.port, health))
        return 0

    try:
        python_path = prepare_runtime()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Failed to prepare Playwright runtime: {exc}", file=sys.stderr)
        return 1

    log_path = Path(args.log).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [str(python_path), str(SCRIPT_DIR / "playwright_daemon.py"), "--port", str(args.port)]
    if args.headed:
        command.append("--headed")
    if args.channel:
        command.extend(["--channel", args.channel])
    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=log_file,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    deadline = time.monotonic() + max(args.wait, 1.0)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            print(
                f"Daemon exited with code {process.returncode} before becoming healthy. See {log_path}",
                file=sys.stderr,
            )
            return 1
        health = check_health(args.port, timeout=2.0)
        if health is not None:
            print(health_summary("started", args.port, health))
            return 0
        time.sleep(0.5)

    print(f"Daemon not healthy after {args.wait:.0f}s. See {log_path}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare runtime and launch the Playwright workflow daemon",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  playwright_launch.py --port 17337\n"
            "  playwright_launch.py --port 17337 --headed\n"
            "  playwright_launch.py --port 17337 --channel chrome\n"
            "  playwright_launch.py --ensure --port 17337\n"
            "  playwright_launch.py --ensure --headed --port 17337\n\n"
            "All unknown trailing args are forwarded to playwright_daemon.py.\n"
            "--ensure switches to ensure-daemon mode (health check; start in the\n"
            "background only if down; re-check). See: playwright_launch.py --ensure --help"
        ),
    )
    parser.add_argument(
        "daemon_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to playwright_daemon.py. Example: --port 17337 --headed",
    )
    return parser


def main(argv: list[str]) -> int:
    # Ensure-daemon mode has its own strict parser (and its own --help).
    if "--ensure" in argv:
        return ensure_main(argv)

    parser = build_parser()
    # Show the launcher's own help when asked; otherwise forward every arg to the
    # daemon verbatim. A leading option like `--port` confuses the REMAINDER-based
    # parse_known_args (it routes `--port` to "unknown" and keeps only its value),
    # which silently dropped the port. Build the forward list straight from argv.
    if any(arg in ("-h", "--help") for arg in argv):
        print(parser.format_help())
        return 0
    daemon_args = [arg for arg in argv if arg != "--"]

    try:
        python_path = prepare_runtime()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Failed to prepare Playwright runtime: {exc}", file=sys.stderr)
        return 1

    command = [str(python_path), str(SCRIPT_DIR / "playwright_daemon.py"), *daemon_args]
    os.execv(str(python_path), command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
