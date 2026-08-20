#!/usr/bin/env python3
"""Cross-check triage ACTION candidates against the whole mailbox for resolution evidence.

Read-only. For each candidate message id this script:

1. Extracts entity keys (PR numbers, invoice refs, i-Memo ids, PO/quotation refs)
   from the subject + body.
2. Analyzes the candidate's own thread: did the user reply after the inbound?
   (reuses ``analyze_thread_reply_status`` from build_attention_view.py)
3. Searches ALL mail (including sent, excluding spam/trash) for each entity key
   and collects messages NEWER than the candidate, flagging which are the
   user's own.

Verdict per candidate:

- ``likely_resolved`` — user replied in-thread after the inbound, OR a newer
  own-authored message references the same entity key (cross-thread evidence,
  e.g. an "Approved" reply in a different thread).
- ``verify``          — newer third-party activity references the entity key;
  the ask may have been handled elsewhere.
- ``open``            — no resolution evidence found in the mailbox.

Rationale: unread is a weak proxy for unresolved. Typical case: an ERP
approval reminder stays unread while the approval reply itself lives in a
separate, already-read thread minutes later.

Own addresses must be supplied by you (``--own-address``, repeatable, or by
filling in ``DEFAULT_OWN_ADDRESSES`` locally) and should be your personal
send-as aliases only. Group addresses (e.g. it@example.com) are deliberately
excluded — group rebroadcasts carry the group in From and would fake "own"
replies; add them explicitly via ``--own-address`` if ever needed.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from typing import Any, Optional

from build_attention_view import (
    analyze_thread_reply_status,
    get_header,
    is_own_from,
    normalize_own_addresses,
)
from fetch_bodies import extract_body_text
from utils.auth_helper import build_gmail_service
from utils.logger import setup_logger, log_error_with_context

logger = setup_logger(__name__)

# Your own send-as addresses. Left empty on purpose: pass --own-address
# (repeatable) or fill this in locally. See CREDENTIALS.md.
DEFAULT_OWN_ADDRESSES = ()
MAX_KEYS_PER_MESSAGE = 5
DEFAULT_MAX_RELATED = 10
DEFAULT_RESOLUTION_DAYS = 3

# Business-reference formats worth cross-matching. These are examples — replace
# them with the reference shapes your own vendors and ERP actually emit.
ENTITY_KEY_PATTERNS = (
    re.compile(r"\b8\d{9}\b"),                                 # SAP PR/PO number
    re.compile(r"\bPI(?:INV|WIN)/\d{4}/\d+\b", re.IGNORECASE),  # vendor invoice / progress ref
    re.compile(r"\bINVID\d{4,}\b", re.IGNORECASE),              # opex invoice id
    re.compile(r"\bIM-[A-Z]{2,6}-\d{6,}\b"),                    # internal memo ref
    re.compile(r"\b[A-Z]{2,5}-PO-\d{2}-\d{2}-\d{4}\b"),         # PO ref (e.g. ABC-PO-01-26-0001)
    re.compile(r"\b\d{2,4}/QUO/[A-Z]{2,6}/[IVXLC]+/\d{4}\b"),   # quotation ref (e.g. 001/QUO/ABC/VII/2026)
)


def extract_entity_keys(text: str) -> list[str]:
    """Extract dedicated business reference keys from text, capped and deduped."""
    keys: list[str] = []
    seen: set[str] = set()
    for pattern in ENTITY_KEY_PATTERNS:
        for match in pattern.findall(text or ""):
            norm = match.upper()
            if norm in seen:
                continue
            seen.add(norm)
            keys.append(match)
            if len(keys) >= MAX_KEYS_PER_MESSAGE:
                return keys
    return keys


def decide_verdict(reply_state: str, related: list[dict[str, Any]]) -> tuple[str, str]:
    """Combine in-thread reply state with cross-thread entity evidence."""
    if reply_state == "replied_after_inbound":
        return "likely_resolved", "user replied in-thread after the inbound message"
    own_newer = [r for r in related if r["is_own"] and r["newer_than_candidate"]]
    if own_newer:
        ref = own_newer[0]
        return (
            "likely_resolved",
            f"newer own message references {ref['matched_key']} ({ref['subject'][:60]!r})",
        )
    other_newer = [r for r in related if r["newer_than_candidate"]]
    if other_newer:
        ref = other_newer[0]
        return (
            "verify",
            f"newer third-party activity references {ref['matched_key']} ({ref['subject'][:60]!r})",
        )
    return "open", "no resolution evidence found in mailbox"


def search_related(
    service: Any,
    key: str,
    candidate_id: str,
    candidate_date_ms: int,
    own_addresses: set[str],
    max_related: int,
) -> list[dict[str, Any]]:
    """Find messages across ALL mail (incl. sent) referencing an entity key."""
    try:
        # -in:draft: an unsent draft is not resolution evidence
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=f'"{key}" -in:draft', maxResults=max_related)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log_error_with_context(logger, exc, {"operation": "messages.list", "key": key})
        return []

    related: list[dict[str, Any]] = []
    for meta in resp.get("messages", []):
        mid = meta.get("id")
        if not mid or mid == candidate_id:
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
        except Exception as exc:  # noqa: BLE001
            log_error_with_context(logger, exc, {"operation": "messages.get", "message_id": mid})
            continue
        headers = msg.get("payload", {}).get("headers", [])
        from_header = get_header(headers, "From")
        date_ms = int(msg.get("internalDate", 0))
        related.append(
            {
                "id": mid,
                "thread_id": msg.get("threadId", ""),
                "from": from_header,
                "subject": get_header(headers, "Subject"),
                "internal_date_ms": date_ms,
                "is_own": is_own_from(from_header, own_addresses),
                "newer_than_candidate": date_ms > candidate_date_ms,
                "matched_key": key,
            }
        )
    return related


def check_message(
    service: Any,
    message_id: str,
    own_addresses: set[str],
    now_ms: int,
    resolution_days: int,
    max_related: int,
) -> dict[str, Any]:
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    headers = msg.get("payload", {}).get("headers", [])
    subject = get_header(headers, "Subject")
    body_text = extract_body_text(msg.get("payload", {}))
    candidate_date_ms = int(msg.get("internalDate", 0))
    thread_id = msg.get("threadId", "")

    entity_keys = extract_entity_keys(f"{subject}\n{body_text}")

    thread = (
        service.users()
        .threads()
        .get(
            userId="me",
            id=thread_id,
            format="metadata",
            metadataHeaders=["From", "To", "Cc", "Date", "Subject"],
        )
        .execute()
    )
    thread_fields = analyze_thread_reply_status(
        thread,
        own_addresses=own_addresses,
        now_ms=now_ms,
        resolution_days=resolution_days,
        actionable=True,
    )

    related: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for key in entity_keys:
        for rec in search_related(
            service, key, message_id, candidate_date_ms, own_addresses, max_related
        ):
            if rec["id"] in seen_ids:
                continue
            seen_ids.add(rec["id"])
            related.append(rec)
    related.sort(key=lambda r: r["internal_date_ms"], reverse=True)

    verdict, reason = decide_verdict(str(thread_fields.get("reply_state", "unknown")), related)
    return {
        "id": message_id,
        "thread_id": thread_id,
        "subject": subject,
        "internal_date_ms": candidate_date_ms,
        "entity_keys": entity_keys,
        "reply_state": thread_fields.get("reply_state"),
        "thread_status": thread_fields.get("status"),
        "related": related,
        "verdict": verdict,
        "reason": reason,
    }


def format_result(result: dict[str, Any]) -> str:
    lines = [
        "=" * 80,
        f"Message ID: {result['id']}",
        f"Subject:    {result['subject']}",
        f"Verdict:    {result['verdict'].upper()} — {result['reason']}",
        f"In-thread:  reply_state={result['reply_state']} status={result.get('thread_status')}",
        f"Entity keys: {', '.join(result['entity_keys']) or '(none found)'}",
    ]
    if result["related"]:
        lines.append("Related messages (newest first):")
        for rec in result["related"]:
            marker = "OWN  " if rec["is_own"] else "other"
            newer = "newer" if rec["newer_than_candidate"] else "older"
            lines.append(
                f"  [{marker}|{newer}] {rec['matched_key']}  {rec['from'][:40]:40s}  {rec['subject'][:55]}"
            )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cross-check ACTION candidates for resolution evidence (read-only)."
    )
    parser.add_argument("--ids", required=True, help="Comma-separated candidate message IDs")
    parser.add_argument("--account", help="Account alias (for example: work or personal)")
    parser.add_argument(
        "--own-address",
        action="append",
        default=None,
        help="Own send-as address (repeatable). Defaults to the user's personal aliases.",
    )
    parser.add_argument(
        "--max-related",
        type=int,
        default=DEFAULT_MAX_RELATED,
        help=f"Max related messages fetched per entity key (default {DEFAULT_MAX_RELATED})",
    )
    parser.add_argument(
        "--resolution-days",
        type=int,
        default=DEFAULT_RESOLUTION_DAYS,
        help="Quiet days after own reply before in-thread status is likely_resolved",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    if not ids:
        logger.error("no message ids given")
        return 2

    own_addresses = normalize_own_addresses(args.own_address or list(DEFAULT_OWN_ADDRESSES))
    service = build_gmail_service(account=args.account)
    now_ms = int(time.time() * 1000)

    results: list[dict[str, Any]] = []
    for mid in ids:
        try:
            results.append(
                check_message(
                    service, mid, own_addresses, now_ms, args.resolution_days, args.max_related
                )
            )
        except Exception as exc:  # noqa: BLE001
            log_error_with_context(logger, exc, {"operation": "check_message", "message_id": mid})
            results.append({"id": mid, "verdict": "error", "reason": str(exc)})

    if args.json:
        print(json.dumps({"results": results}))
    else:
        for result in results:
            print(format_result(result) if "subject" in result else f"{result['id']}: ERROR {result['reason']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
