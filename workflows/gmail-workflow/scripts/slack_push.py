#!/usr/bin/env python3
"""Push a Slack message to ``CASPER_SLACK_WEBHOOK_URL``.

Auto-prefixes gmail content with ``[GMAIL]`` to disambiguate from heartbeat
ops alerts (which post to the same webhook in this v1 setup). Honors a
``GMAIL_QUIET_HOURS`` window so manual runs at 3am stay quiet even if cron
schedules already exclude these.

Usage:

    echo '<text>' | slack_push.py --kind urgent
    slack_push.py --kind digest --text '<text>'

Exit codes:
  0  success (or no-op due to quiet hours / DRY_RUN / missing webhook)
  1  POST failed; caller should retry idempotently
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from utils.logger import setup_logger
from utils.state_io import quiet_hours_active

# Load ~/.agents/.env and ~/.agents/.config into os.environ (see .env.example).
import os as _os, sys as _sys
_d = _os.path.dirname(_os.path.abspath(__file__))
while _d != _os.path.dirname(_d):
    if _os.path.isfile(_os.path.join(_d, '_shared', 'agents_config.py')):
        _sys.path.insert(0, _os.path.join(_d, '_shared'))
        break
    _d = _os.path.dirname(_d)
import agents_config  # noqa: F401,E402


logger = setup_logger(__name__)

KIND_PREFIX = {
    "urgent": ":rotating_light: [GMAIL] Urgent",
    "digest": ":envelope_with_arrow: [GMAIL] Digest",
    "anomaly": ":chart_with_upwards_trend: [GMAIL] Topic spike",
}


def post(webhook: str, payload: dict, timeout: int = 10) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return 0, str(exc)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Push a Slack message via incoming webhook.")
    p.add_argument("--kind", required=True, choices=sorted(KIND_PREFIX.keys()))
    p.add_argument("--text", default=None, help="Message text; if omitted reads stdin")
    p.add_argument("--no-prefix", action="store_true", help="Skip auto-prefix (caller already formatted)")
    p.add_argument("--ignore-quiet-hours", action="store_true", help="Push even during quiet hours")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if os.environ.get("GMAIL_SUMMARIZER_DRY_RUN", "").lower() in ("1", "true", "yes"):
        logger.info("DRY_RUN: would push %s message; skipping", args.kind)
        return 0

    if not args.ignore_quiet_hours and quiet_hours_active():
        logger.info("quiet hours active; skipping %s push", args.kind)
        return 0

    webhook = os.environ.get("CASPER_SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        logger.warning("CASPER_SLACK_WEBHOOK_URL not set; skipping push")
        return 0

    text = args.text if args.text is not None else sys.stdin.read()
    text = text.rstrip()
    if not text:
        logger.info("empty message; nothing to push")
        return 0

    if not args.no_prefix:
        prefix = KIND_PREFIX[args.kind]
        if not text.startswith(prefix):
            text = f"{prefix}\n{text}"

    status, body = post(webhook, {"text": text})
    if 200 <= status < 300:
        return 0

    logger.error("slack push failed: status=%s body=%r", status, body[:200])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
