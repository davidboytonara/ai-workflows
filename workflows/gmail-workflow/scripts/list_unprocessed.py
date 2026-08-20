#!/usr/bin/env python3
"""List unprocessed inbox messages for the gmail-summarizer heartbeat.

Lists messages from ``in:inbox newer_than:<N>d`` for one account, fetches
metadata-only headers, filters out IDs already present in the shared state
file, and emits JSON. No body fetch in this pass — saves quota.

Output (when ``--json``):

    {
      "messages": [{
        "id": "...",
        "account": "work",
        "thread_id": "...",
        "from": "...",
        "from_domain": "...",
        "subject": "...",
        "internal_date_ms": 1745539200000,
        "snippet": "..."
      }, ...],
      "query": "in:inbox newer_than:30d",
      "truncated": false,
      "remaining_estimate": 0
    }

Result size: capped by ``--max-results`` (default 50). The loop paginates on
``nextPageToken`` up to that ceiling. When the ceiling is hit while more
messages still match the query, ``truncated`` is ``true`` and
``remaining_estimate`` gives Gmail's rough count of unseen matches — so a
truncated run is visible instead of silently returning "the newest N". For a
full-inbox triage, pass ``--unread-only`` (scopes the query to ``is:unread``)
and/or raise ``--max-results``. The default stays 50 so the heartbeat's
batch + state-dedupe design is unchanged.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Optional

from utils.auth_helper import build_gmail_service
from utils.logger import setup_logger, log_error_with_context
from utils.state_io import load_state, state_lock

logger = setup_logger(__name__)

# Default result ceiling. Kept at 50 so existing (heartbeat) callers that rely
# on the batch + state-file dedupe design are unaffected; raise via --max-results.
BATCH_CAP = 50
EMAIL_ADDR_RE = re.compile(r"<([^>]+)>")


def extract_addr(from_header: str) -> str:
    """Pull bare ``user@host`` out of a From header value."""
    if not from_header:
        return ""
    match = EMAIL_ADDR_RE.search(from_header)
    return (match.group(1) if match else from_header).strip().lower()


def domain_of(addr: str) -> str:
    return addr.rsplit("@", 1)[-1] if "@" in addr else ""


def get_header(headers: list[dict[str, str]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def list_unprocessed(
    account: str,
    max_age_days: int,
    dry_run: bool,
    max_results: int = BATCH_CAP,
    unread_only: bool = False,
) -> dict:
    state = load_state()
    processed_ids = {
        mid for mid, rec in state.get("messages", {}).items()
        if rec.get("account") == account
    }

    service = build_gmail_service(account=account)
    query = f"in:inbox newer_than:{max_age_days}d"
    if unread_only:
        query += " is:unread"
    logger.info("Listing %s with query %r (max_results=%d)", account, query, max_results)

    collected: list[dict] = []
    page_token: Optional[str] = None
    truncated = False
    seen_count = 0          # total list entries encountered (incl. already-processed skips)
    size_estimate = 0       # Gmail's rough count of messages matching the query

    while len(collected) < max_results:
        try:
            resp = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    maxResults=min(max_results - len(collected), 100),
                    pageToken=page_token,
                )
                .execute()
            )
        except Exception as exc:
            log_error_with_context(logger, exc, {"operation": "messages.list", "query": query, "account": account})
            raise SystemExit(1) from exc

        size_estimate = size_estimate or int(resp.get("resultSizeEstimate", 0) or 0)
        page_msgs = resp.get("messages", [])

        hit_cap = False
        for idx, meta in enumerate(page_msgs):
            seen_count += 1
            mid = meta.get("id")
            if not mid or mid in processed_ids:
                continue

            try:
                msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=mid,
                        format="metadata",
                        metadataHeaders=["From", "Subject", "Date"],
                    )
                    .execute()
                )
            except Exception as exc:
                log_error_with_context(logger, exc, {"operation": "messages.get", "message_id": mid})
                continue

            headers = msg.get("payload", {}).get("headers", [])
            from_raw = get_header(headers, "From")
            addr = extract_addr(from_raw)
            collected.append({
                "id": mid,
                "account": account,
                "thread_id": msg.get("threadId", ""),
                "from": from_raw,
                "from_domain": domain_of(addr),
                "subject": get_header(headers, "Subject"),
                "internal_date_ms": int(msg.get("internalDate", 0)),
                "snippet": msg.get("snippet", ""),
            })

            if len(collected) >= max_results:
                # Hit the ceiling. If anything still matches the query beyond
                # what we've collected, the run is truncated — report it.
                more_on_page = any(m.get("id") for m in page_msgs[idx + 1:])
                if more_on_page or resp.get("nextPageToken"):
                    truncated = True
                hit_cap = True
                break

        if hit_cap:
            break

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # Gmail's estimate counts read+unread matches; subtract what we've already
    # walked past. Best-effort — resultSizeEstimate is approximate.
    remaining_estimate = max(0, size_estimate - seen_count) if truncated else 0

    if truncated:
        logger.warning(
            "cap reached: returned %d of ~%d matching %r (--max-results %d); "
            "raise --max-results or narrow the query to see the rest",
            len(collected), size_estimate, query, max_results,
        )

    if dry_run:
        logger.info("dry-run: %d unprocessed (would not write state)", len(collected))

    return {
        "messages": collected,
        "query": query,
        "truncated": truncated,
        "remaining_estimate": remaining_estimate,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="List unprocessed inbox messages.")
    p.add_argument("--account", required=True, help="Account alias (work | personal)")
    p.add_argument("--max-age-days", type=int, default=30, help="Max age in days (default 30)")
    p.add_argument(
        "--max-results", type=int, default=BATCH_CAP,
        help=f"Max messages to return (default {BATCH_CAP}); paginates up to this ceiling",
    )
    p.add_argument(
        "--unread-only", action="store_true",
        help="Scope the query to is:unread (use for full inbox triage)",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    p.add_argument("--dry-run", action="store_true", help="Read-only diagnostic mode")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    try:
        with state_lock(non_blocking=True):
            result = list_unprocessed(
                args.account,
                args.max_age_days,
                args.dry_run,
                max_results=args.max_results,
                unread_only=args.unread_only,
            )
    except BlockingIOError:
        logger.warning("state lock held by another run; exiting cleanly")
        if args.json:
            print(json.dumps({"messages": [], "query": "", "truncated": False, "remaining_estimate": 0}))
        return 0

    if args.json:
        print(json.dumps(result))
    else:
        for msg in result["messages"]:
            print(f"{msg['id']}  {msg['from']}  {msg['subject']}")
        if result["truncated"]:
            print(
                f"[truncated] returned {len(result['messages'])}; "
                f"~{result['remaining_estimate']} more match — raise --max-results or use --unread-only",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
