#!/usr/bin/env python3
"""Download attachments from a Gmail message.

Retrieves a message by ID and saves all attachments to a specified output directory.
"""

import argparse
import base64
import os
from pathlib import Path
from typing import Dict, List

from utils.auth_helper import build_gmail_service
from utils.logger import setup_logger, log_error_with_context, log_success


logger = setup_logger(__name__)


def extract_attachment_parts(payload: Dict) -> List[Dict]:
    """Extract attachment parts with metadata from message payload."""
    attachments: List[Dict] = []

    def walk(part: Dict):
        filename = part.get("filename")
        mime_type = part.get("mimeType")
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")

        if filename and attachment_id:
            attachments.append(
                {
                    "filename": filename,
                    "mime_type": mime_type,
                    "attachment_id": attachment_id,
                    "size": body.get("size"),
                }
            )

        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return attachments


def download_attachment(
    service,
    user_id: str,
    message_id: str,
    attachment_id: str,
    filename: str,
    output_dir: str,
) -> str:
    """Download a single attachment and save to output directory."""
    try:
        attachment = (
            service.users()
            .messages()
            .attachments()
            .get(userId=user_id, messageId=message_id, id=attachment_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log_error_with_context(
            logger,
            exc,
            {
                "operation": "attachments.get",
                "message_id": message_id,
                "attachment_id": attachment_id,
                "filename": filename,
            },
        )
        raise

    data = attachment.get("data")
    if not data:
        raise ValueError(f"No data in attachment: {filename}")

    file_data = base64.urlsafe_b64decode(data.encode("utf-8"))

    output_path = Path(output_dir) / filename
    output_path.write_bytes(file_data)

    return str(output_path)


def download_attachments_from_message(
    message_id: str,
    output_dir: str = ".",
    account: str | None = None,
) -> None:
    """Download all attachments from a Gmail message."""
    service = build_gmail_service(account=account)

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    try:
        message = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log_error_with_context(
            logger,
            exc,
            {
                "operation": "messages.get",
                "message_id": message_id,
            },
        )
        raise SystemExit(1) from exc

    payload = message.get("payload", {})
    attachments = extract_attachment_parts(payload)

    if not attachments:
        print(f"No attachments found in message {message_id}")
        return

    print(f"Found {len(attachments)} attachment(s) in message {message_id}:")
    for att in attachments:
        print(f"  - {att['filename']} ({att['mime_type']}, size={att['size']})")

    print(f"\nDownloading to: {os.path.abspath(output_dir)}")

    downloaded_files: List[str] = []
    for att in attachments:
        try:
            output_path = download_attachment(
                service=service,
                user_id="me",
                message_id=message_id,
                attachment_id=att["attachment_id"],
                filename=att["filename"],
                output_dir=output_dir,
            )
            downloaded_files.append(output_path)
            logger.info(f"✓ Downloaded: {output_path}")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"✗ Failed to download {att['filename']}: {exc}")
            continue

    if downloaded_files:
        log_success(
            logger,
            "Download attachments",
            {
                "message_id": message_id,
                "count": len(downloaded_files),
                "output_dir": os.path.abspath(output_dir),
            },
        )

        print(f"\n✓ Downloaded {len(downloaded_files)} attachment(s):")
        for path in downloaded_files:
            print(f"  - {path}")
    else:
        print("\n✗ No attachments were successfully downloaded.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download all attachments from a Gmail message.",
    )
    parser.add_argument(
        "--message-id",
        required=True,
        help="Gmail message ID (from read_emails.py output or Gmail URL)",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Output directory for attachments (default: current directory)",
    )
    parser.add_argument(
        "--account",
        help="Account alias to select a non-default OAuth token (for example: work or personal)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    download_attachments_from_message(
        message_id=args.message_id,
        output_dir=args.output_dir,
        account=args.account,
    )


if __name__ == "__main__":
    main()
