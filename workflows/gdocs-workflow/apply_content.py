#!/usr/bin/env python3
"""Write markdown or text content into a Google Docs document.

Exit codes:
  0  success
  1  business / API failure
  2  usage error
"""

from __future__ import annotations

import argparse
from pathlib import Path

from gdocs_auth import build_docs_service
from gdocs_common import (
    build_markdown_insert_requests,
    build_text_insert_requests,
    document_url,
    get_body_end_index,
    read_text,
    resolve_document_id,
    write_json,
)

VALID_FORMATS = {"auto", "markdown", "text"}
VALID_MODES = {"replace", "append"}



def _resolve_format(path: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    return "markdown" if path.suffix.lower() in {".md", ".markdown"} else "text"



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write markdown or text content into a Google Docs document.")
    parser.add_argument("--document-id", required=True, help="Document id or URL")
    parser.add_argument("--content-file", required=True, help="Path to .md or .txt input file")
    parser.add_argument("--mode", default="replace", choices=sorted(VALID_MODES), help="Replace body or append to end")
    parser.add_argument("--format", default="auto", choices=sorted(VALID_FORMATS), help="Input file format")
    parser.add_argument("--output", help="Optional path to write JSON result")
    parser.add_argument("--account", help="Account alias")
    args = parser.parse_args(argv)

    document_id = resolve_document_id(args.document_id)
    content_path = Path(args.content_file)
    content = read_text(content_path)
    content_format = _resolve_format(content_path, args.format)

    service = build_docs_service(account=args.account)
    document = service.documents().get(documentId=document_id).execute()
    body_end_index = get_body_end_index(document)

    requests: list[dict] = []
    if args.mode == "replace" and body_end_index > 2:
        requests.append(
            {
                "deleteContentRange": {
                    "range": {
                        "startIndex": 1,
                        "endIndex": body_end_index - 1,
                    }
                }
            }
        )
        insert_index = 1
        prefix_newline = False
    else:
        insert_index = body_end_index - 1
        prefix_newline = body_end_index > 2

    if content_format == "markdown":
        insert_requests, stats = build_markdown_insert_requests(
            content,
            start_index=insert_index,
            prefix_newline=prefix_newline,
        )
    else:
        insert_requests, stats = build_text_insert_requests(
            content,
            start_index=insert_index,
            prefix_newline=prefix_newline,
        )

    requests.extend(insert_requests)

    if not requests:
        result = {
            "documentId": document_id,
            "url": document_url(document_id),
            "mode": args.mode,
            "format": content_format,
            "requestsApplied": 0,
            "message": "No changes applied; content file was empty.",
        }
        write_json(result, args.output)
        if args.output:
            write_json(result)
        return 0

    response = service.documents().batchUpdate(
        documentId=document_id,
        body={"requests": requests},
    ).execute()

    result = {
        "documentId": document_id,
        "url": document_url(document_id),
        "mode": args.mode,
        "format": content_format,
        "contentFile": str(content_path),
        "requestsApplied": len(requests),
        "replyCount": len(response.get("replies", [])),
        **stats,
    }
    write_json(result, args.output)
    if args.output:
        write_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
