#!/usr/bin/env python3
"""Export a Google Docs document via Google Drive API.

Exit codes:
  0  success
  1  business / API failure
  2  usage error
"""

from __future__ import annotations

import argparse
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload

from gdocs_auth import build_drive_service
from gdocs_common import document_url, resolve_document_id, write_json

EXPORT_MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "html": "text/html",
    "epub": "application/epub+zip",
}



def _resolve_format(output_path: Path, requested_format: str | None) -> str:
    if requested_format:
        return requested_format.lower()
    suffix = output_path.suffix.lower().lstrip(".")
    if suffix in EXPORT_MIME_TYPES:
        return suffix
    raise ValueError("Could not infer export format from output path. Pass --format explicitly.")



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a Google Docs document via Google Drive API.")
    parser.add_argument("--document-id", required=True, help="Document id or URL")
    parser.add_argument("--output", required=True, help="Output file path")
    parser.add_argument("--format", choices=sorted(EXPORT_MIME_TYPES), help="Export format; inferred from output suffix when omitted")
    parser.add_argument("--account", help="Account alias")
    args = parser.parse_args(argv)

    document_id = resolve_document_id(args.document_id)
    output_path = Path(args.output)
    export_format = _resolve_format(output_path, args.format)
    mime_type = EXPORT_MIME_TYPES[export_format]

    output_path.parent.mkdir(parents=True, exist_ok=True)

    service = build_drive_service(account=args.account)
    request = service.files().export_media(fileId=document_id, mimeType=mime_type)

    with output_path.open("wb") as handle:
        downloader = MediaIoBaseDownload(handle, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

    result = {
        "documentId": document_id,
        "url": document_url(document_id),
        "format": export_format,
        "mimeType": mime_type,
        "output": str(output_path),
        "bytes": output_path.stat().st_size,
    }
    write_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
