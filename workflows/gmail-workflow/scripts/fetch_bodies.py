#!/usr/bin/env python3
"""Fetch text bodies for given Gmail message IDs.

Used by the gmail-summarizer ingest workflow when the snippet from
``list_unprocessed.py`` is insufficient for classification.

Output (when ``--json``):

    {"bodies": [{"id": "...", "body": "<plain text, truncated>"}, ...]}

Bodies are truncated to ``--max-chars`` (default 4000) to keep classifier
input bounded.
"""

from __future__ import annotations

import argparse
import base64
import json
from typing import List

from bs4 import BeautifulSoup

from utils.auth_helper import build_gmail_service
from utils.logger import setup_logger, log_error_with_context

logger = setup_logger(__name__)


def decode_part(part: dict) -> str:
    mime_type = part.get("mimeType", "")
    body = part.get("body", {})
    data = body.get("data")
    if not data:
        return ""
    raw = base64.urlsafe_b64decode(data.encode("utf-8"))
    if mime_type == "text/plain":
        return raw.decode("utf-8", errors="replace")
    if mime_type == "text/html":
        return BeautifulSoup(raw.decode("utf-8", errors="replace"), "html.parser").get_text("\n", strip=True)
    return ""


def extract_body_text(payload: dict) -> str:
    texts: List[str] = []

    def walk(part: dict) -> None:
        if part.get("mimeType", "") in {"text/plain", "text/html"}:
            text = decode_part(part)
            if text:
                texts.append(text)
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return "\n\n".join(texts).strip()


def fetch_bodies(ids: list[str], account: str, max_chars: int) -> dict:
    service = build_gmail_service(account=account)
    out: list[dict] = []

    for mid in ids:
        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=mid, format="full")
                .execute()
            )
        except Exception as exc:
            log_error_with_context(logger, exc, {"operation": "messages.get", "message_id": mid})
            out.append({"id": mid, "body": "", "error": str(exc)})
            continue

        text = extract_body_text(msg.get("payload", {}))
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n…[truncated {len(text) - max_chars} chars]"
        out.append({"id": mid, "body": text})

    return {"bodies": out}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch plain-text bodies for given message IDs.")
    p.add_argument("--ids", required=True, help="Comma-separated message IDs")
    p.add_argument("--account", required=True, help="Account alias (work | personal)")
    p.add_argument("--max-chars", type=int, default=4000, help="Truncate body to this many chars (default 4000)")
    p.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    ids = [s.strip() for s in args.ids.split(",") if s.strip()]
    if not ids:
        print(json.dumps({"bodies": []}) if args.json else "")
        return 0

    result = fetch_bodies(ids, args.account, args.max_chars)
    if args.json:
        print(json.dumps(result))
    else:
        for entry in result["bodies"]:
            print(f"=== {entry['id']} ===")
            print(entry.get("body", ""))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
