#!/usr/bin/env python3
"""Detect topic-frequency spikes from the gmail-summarizer state file.

Reads ``topic_counts.daily`` per topic, computes a 7-day rolling mean and
stddev over the prior window (excluding today), and flags topics where
today's count satisfies BOTH:

    today >= max(3, mean + 2*stddev)
    today >= 1.5 * mean

Dual condition kills false positives at near-zero baselines.

Output (when ``--json``):

    {"flagged": [
        {"topic_key": "...", "today": 7, "mean": 1.4, "stddev": 0.5}, ...
    ]}
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone

from utils.logger import setup_logger
from utils.state_io import load_state

logger = setup_logger(__name__)


def stats(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) == 1:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return mean, math.sqrt(var)


def detect(window_days: int) -> dict:
    state = load_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    flagged: list[dict] = []

    for topic_key, payload in state.get("topic_counts", {}).items():
        daily = payload.get("daily", [])
        if not daily:
            continue

        today_n = 0
        prior: list[float] = []
        for entry in daily[-window_days:]:
            n = int(entry.get("n", 0))
            if entry.get("date") == today:
                today_n = n
            else:
                prior.append(float(n))

        if today_n == 0:
            continue

        mean, stddev = stats(prior)
        threshold = max(3.0, mean + 2 * stddev)
        if today_n >= threshold and today_n >= 1.5 * mean:
            flagged.append({
                "topic_key": topic_key,
                "today": today_n,
                "mean": round(mean, 2),
                "stddev": round(stddev, 2),
            })

    flagged.sort(key=lambda d: d["today"] - d["mean"], reverse=True)
    return {"flagged": flagged}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Detect topic-frequency spikes.")
    p.add_argument("--window-days", type=int, default=14, help="Lookback window (default 14 days)")
    p.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = detect(args.window_days)

    if args.json:
        print(json.dumps(result))
    else:
        if not result["flagged"]:
            print("No topic spikes detected.")
            return 0
        for f in result["flagged"]:
            print(f"{f['topic_key']}: {f['today']} today vs avg {f['mean']}/day (sd {f['stddev']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
