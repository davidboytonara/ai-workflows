#!/usr/bin/env python3
"""Read Gmail messages with filters and output as plain text.

Supported filters:
- subject
- from address
- body text
- attachment file name

Results are limited to 10 messages and formatted as human-readable text.
"""

import argparse
import base64
from email.message import Message
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from utils.auth_helper import build_gmail_service
from utils.logger import setup_logger, log_error_with_context


logger = setup_logger(__name__)


def build_query(
    subject: Optional[str],
    from_address: Optional[str],
    body: Optional[str],
    attachment_name: Optional[str],
) -> str:
    """Build Gmail search query string from filters."""
    parts: List[str] = ["in:inbox"]

    if subject:
        parts.append(f"subject:\"{subject}\"")
    if from_address:
        parts.append(f"from:{from_address}")
    if body:
        parts.append(body)
    if attachment_name:
        parts.append("has:attachment")
        parts.append(f"filename:{attachment_name}")

    return " ".join(parts)


def decode_part(part: Dict) -> str:
    """Decode a MIME part to text, converting HTML to plain text if needed."""
    mime_type = part.get("mimeType", "")
    body = part.get("body", {})
    data = body.get("data")

    if not data:
        return ""

    raw_bytes = base64.urlsafe_b64decode(data.encode("utf-8"))

    if mime_type == "text/plain":
        return raw_bytes.decode("utf-8", errors="replace")

    if mime_type == "text/html":
        soup = BeautifulSoup(raw_bytes.decode("utf-8", errors="replace"), "html.parser")
        return soup.get_text("\n", strip=True)

    return ""


def extract_attachments(payload: Dict) -> List[Dict[str, Optional[str]]]:
    """Extract attachment metadata (file name, mime type, size) from message payload."""
    attachments: List[Dict[str, Optional[str]]] = []

    def walk(part: Dict):
        filename = part.get("filename")
        mime_type = part.get("mimeType")
        body = part.get("body", {})

        if filename:
            attachments.append(
                {
                    "filename": filename,
                    "mime_type": mime_type,
                    "size": body.get("size"),
                }
            )

        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return attachments


def extract_body_text(payload: Dict) -> str:
    """Extract concatenated plain-text body from MIME payload."""
    texts: List[str] = []

    def walk(part: Dict):
        mime_type = part.get("mimeType", "")

        if mime_type in {"text/plain", "text/html"}:
            text = decode_part(part)
            if text:
                texts.append(text)

        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return "\n\n".join(texts).strip()


def get_header(headers: List[Dict[str, str]], name: str) -> str:
    """Get a header value from Gmail message headers."""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def format_message(msg: Dict) -> str:
    """Format a Gmail message into human-readable text."""
    message_id = msg.get("id", "unknown")
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])

    subject = get_header(headers, "Subject")
    from_ = get_header(headers, "From")
    to = get_header(headers, "To")
    date = get_header(headers, "Date")

    body_text = extract_body_text(payload)
    attachments = extract_attachments(payload)

    lines: List[str] = []
    lines.append("=" * 80)
    lines.append(f"Message ID: {message_id}")
    lines.append(f"Subject:    {subject}")
    lines.append(f"From:       {from_}")
    lines.append(f"To:         {to}")
    lines.append(f"Date:       {date}")

    if attachments:
        lines.append("")
        lines.append("Attachments:")
        for att in attachments:
            lines.append(
                f"  - {att.get('filename')} ({att.get('mime_type')}, size={att.get('size')})"
            )
        lines.append("")
        lines.append(f"To download attachments, run:")
        lines.append(f"  $HOME/.agents/.venv/bin/python scripts/download_attachments.py --message-id {message_id} --output-dir ./downloads")

    lines.append("")
    lines.append("Body:")
    lines.append("-" * 80)
    lines.append(body_text or "[No body content]")
    lines.append("")

    return "\n".join(lines)


def read_emails(
    subject: Optional[str],
    from_address: Optional[str],
    body: Optional[str],
    attachment_name: Optional[str],
    max_results: int = 10,
    account: Optional[str] = None,
) -> None:
    """Read Gmail messages with the given filters and print them."""
    query = build_query(subject, from_address, body, attachment_name)
    logger.info(f"Using query: {query}")

    service = build_gmail_service(account=account)

    try:
        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log_error_with_context(
            logger,
            exc,
            {
                "operation": "messages.list",
                "query": query,
            },
        )
        raise SystemExit(1) from exc

    messages_meta = response.get("messages", [])

    if not messages_meta:
        print("No messages found for the given filters.")
        return

    for meta in messages_meta:
        msg_id = meta.get("id")
        try:
            full_msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            log_error_with_context(
                logger,
                exc,
                {
                    "operation": "messages.get",
                    "message_id": msg_id,
                },
            )
            continue

        formatted = format_message(full_msg)
        print(formatted)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read Gmail messages with filters and output as plain text.",
    )
    parser.add_argument("--subject", help="Filter by subject text")
    parser.add_argument("--from", dest="from_address", help="Filter by From address")
    parser.add_argument("--body", help="Filter by body text")
    parser.add_argument(
        "--attachment-name",
        help="Filter by attachment file name",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum number of messages to return (default: 10, max: 10)",
    )
    parser.add_argument(
        "--account",
        help="Account alias to select a non-default OAuth token (for example: work or personal)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    max_results = min(args.max_results, 10)

    read_emails(
        subject=args.subject,
        from_address=args.from_address,
        body=args.body,
        attachment_name=args.attachment_name,
        max_results=max_results,
        account=args.account,
    )


if __name__ == "__main__":
    main()
