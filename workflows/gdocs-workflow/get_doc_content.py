#!/usr/bin/env python3
"""Inspect Google Docs document content and structure.

Exit codes:
  0  success
  1  business / API failure
  2  usage error
"""

from __future__ import annotations

import argparse
from typing import Any

from gdocs_auth import build_docs_service
from gdocs_common import (
    document_url,
    extract_body_text,
    summarize_inline_objects,
    summarize_paragraph,
    summarize_table,
    resolve_document_id,
    write_json,
)


def _content_summary(document: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    content_items: list[dict[str, Any]] = []
    outline: list[dict[str, Any]] = []
    inline_objects = summarize_inline_objects(document)

    for element in document.get("body", {}).get("content", []):
        if "paragraph" in element:
            paragraph = element["paragraph"]
            paragraph_summary = summarize_paragraph(paragraph)
            named_style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
            item = {
                "type": "paragraph",
                "startIndex": element.get("startIndex"),
                "endIndex": element.get("endIndex"),
                "namedStyleType": named_style,
                "text": paragraph_summary["text"],
                "inlineObjectIds": paragraph_summary["inlineObjectIds"],
            }
            content_items.append(item)
            if named_style.startswith("HEADING_") and paragraph_summary["text"]:
                outline.append(
                    {
                        "namedStyleType": named_style,
                        "level": int(named_style.split("_")[-1]),
                        "text": paragraph_summary["text"],
                        "startIndex": element.get("startIndex"),
                        "endIndex": element.get("endIndex"),
                    }
                )
            continue

        if "table" in element:
            content_items.append(
                {
                    "type": "table",
                    "startIndex": element.get("startIndex"),
                    "endIndex": element.get("endIndex"),
                    **summarize_table(element["table"]),
                }
            )
            continue

        if "tableOfContents" in element:
            content_items.append(
                {
                    "type": "tableOfContents",
                    "startIndex": element.get("startIndex"),
                    "endIndex": element.get("endIndex"),
                }
            )
            continue

        if "sectionBreak" in element:
            content_items.append(
                {
                    "type": "sectionBreak",
                    "startIndex": element.get("startIndex"),
                    "endIndex": element.get("endIndex"),
                }
            )

    return content_items, outline, inline_objects


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Google Docs document content and structure.")
    parser.add_argument("--document-id", required=True, help="Document id or URL")
    parser.add_argument("--output", help="Optional path to write JSON output")
    parser.add_argument("--compact", action="store_true", help="Return compact metadata + outline + preview")
    parser.add_argument("--account", help="Account alias")
    args = parser.parse_args(argv)

    document_id = resolve_document_id(args.document_id)
    service = build_docs_service(account=args.account)
    document = service.documents().get(documentId=document_id).execute()

    full_text = extract_body_text(document)
    content_items, outline, inline_objects = _content_summary(document)
    paragraph_count = sum(1 for item in content_items if item["type"] == "paragraph")
    table_count = sum(1 for item in content_items if item["type"] == "table")
    image_count = len(inline_objects)

    result = {
        "documentId": document_id,
        "title": document.get("title"),
        "revisionId": document.get("revisionId"),
        "url": document_url(document_id),
        "stats": {
            "paragraphCount": paragraph_count,
            "tableCount": table_count,
            "headingCount": len(outline),
            "inlineObjectCount": len(inline_objects),
            "imageCount": image_count,
            "approxCharacterCount": len(full_text),
            "approxWordCount": len(full_text.split()),
        },
        "outline": outline,
        "inlineObjects": inline_objects,
    }

    if args.compact:
        result["preview"] = full_text[:2000].rstrip()
    else:
        result["fullText"] = full_text
        result["content"] = content_items
        result["namedStyles"] = document.get("namedStyles", {}).get("styles", [])

    write_json(result, args.output)
    if args.output:
        write_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
