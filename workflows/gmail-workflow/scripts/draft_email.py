#!/usr/bin/env python3
"""Create or update Gmail drafts via the Gmail API.

This script creates (or updates) a draft message but NEVER sends email.

Capabilities:
- ``--from``                 set the From header to a verified send-as alias
                             (rule: match the address the original was sent TO).
- ``--reply-to-message-id``  thread the draft onto an existing conversation by
                             copying the original message's threadId and setting
                             In-Reply-To / References headers.
- ``--update-draft-id``      replace an existing draft in place (non-destructive)
                             instead of creating a new one.
"""

import argparse
import base64
from email.message import EmailMessage
from typing import Dict, List, Optional, Tuple

from utils.auth_helper import build_gmail_service
from utils.logger import setup_logger, log_error_with_context, log_success


logger = setup_logger(__name__)


def _get_header(headers: List[Dict[str, str]], name: str) -> str:
    """Case-insensitive lookup of a header value."""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _resolve_thread(service, reply_to_message_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Fetch the original message and derive (threadId, In-Reply-To, References).

    Returns (thread_id, in_reply_to, references). Any may be None if the original
    message or its RFC822 Message-ID header cannot be read.
    """
    orig = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=reply_to_message_id,
            format="metadata",
            metadataHeaders=["Message-ID", "References"],
        )
        .execute()
    )
    thread_id = orig.get("threadId")
    headers = orig.get("payload", {}).get("headers", [])
    msg_id = _get_header(headers, "Message-ID")
    refs = _get_header(headers, "References")

    in_reply_to = msg_id or None
    references = None
    if msg_id:
        references = f"{refs} {msg_id}".strip() if refs else msg_id
    return thread_id, in_reply_to, references


def _build_raw(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str],
    bcc: Optional[str],
    from_addr: Optional[str],
    in_reply_to: Optional[str],
    references: Optional[str],
) -> str:
    message = EmailMessage()
    message["To"] = to
    if from_addr:
        message["From"] = from_addr
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references

    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


def create_draft(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    account: Optional[str] = None,
    from_addr: Optional[str] = None,
    reply_to_message_id: Optional[str] = None,
    update_draft_id: Optional[str] = None,
) -> None:
    """Create (or update) a Gmail draft message. Never sends."""
    service = build_gmail_service(account=account)

    thread_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    if reply_to_message_id:
        try:
            thread_id, in_reply_to, references = _resolve_thread(service, reply_to_message_id)
        except Exception as exc:  # noqa: BLE001
            log_error_with_context(
                logger, exc, {"operation": "messages.get", "message_id": reply_to_message_id}
            )
            raise SystemExit(1) from exc
        if not thread_id:
            logger.warning(
                "reply-to message %s had no resolvable thread/Message-ID; "
                "draft will NOT be threaded",
                reply_to_message_id,
            )

    encoded_message = _build_raw(
        to, subject, body, cc, bcc, from_addr, in_reply_to, references
    )

    message_body: Dict = {"raw": encoded_message}
    if thread_id:
        message_body["threadId"] = thread_id
    draft_body: Dict = {"message": message_body}

    try:
        if update_draft_id:
            draft_body["id"] = update_draft_id
            draft = (
                service.users()
                .drafts()
                .update(userId="me", id=update_draft_id, body=draft_body)
                .execute()
            )
            operation = "drafts.update"
        else:
            draft = (
                service.users()
                .drafts()
                .create(userId="me", body=draft_body)
                .execute()
            )
            operation = "drafts.create"
    except Exception as exc:  # noqa: BLE001
        log_error_with_context(
            logger,
            exc,
            {
                "operation": operation if update_draft_id else "drafts.create",
                "to": to,
                "subject": subject,
                "from": from_addr,
            },
        )
        raise SystemExit(1) from exc

    draft_id = draft.get("id", "unknown")
    message_id = draft.get("message", {}).get("id", "unknown")
    threaded = "yes" if thread_id else "no"

    log_success(
        logger,
        f"{operation} Gmail draft",
        {
            "draft_id": draft_id,
            "message_id": message_id,
            "thread_id": thread_id or "-",
            "from": from_addr or "(account default)",
        },
    )

    print("✓ Draft created!" if not update_draft_id else "✓ Draft updated!")
    print(f"  Draft ID:    {draft_id}")
    print(f"  Message ID:  {message_id}")
    print(f"  From:        {from_addr or '(account default send-as)'}")
    print(f"  Threaded:    {threaded}{f' (thread {thread_id})' if thread_id else ''}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or update a Gmail draft message (does not send email).",
    )
    parser.add_argument("--to", required=True, help="Recipient email address(es), comma-separated")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--body", required=True, help="Email body text")
    parser.add_argument("--cc", help="CC email address(es), comma-separated")
    parser.add_argument("--bcc", help="BCC email address(es), comma-separated")
    parser.add_argument(
        "--from",
        dest="from_addr",
        help="From header; must be a verified send-as alias on the account. "
        "Rule: match the address the original email was sent TO.",
    )
    parser.add_argument(
        "--reply-to-message-id",
        help="Gmail message ID of the email being replied to. Threads the draft "
        "onto that conversation (sets threadId + In-Reply-To + References).",
    )
    parser.add_argument(
        "--update-draft-id",
        help="Update this existing draft in place instead of creating a new one "
        "(non-destructive; useful to correct a draft).",
    )
    parser.add_argument(
        "--account",
        help="Account alias to select a non-default OAuth token (for example: work or personal)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    create_draft(
        to=args.to,
        subject=args.subject,
        body=args.body,
        cc=args.cc,
        bcc=args.bcc,
        account=args.account,
        from_addr=args.from_addr,
        reply_to_message_id=args.reply_to_message_id,
        update_draft_id=args.update_draft_id,
    )


if __name__ == "__main__":
    main()
