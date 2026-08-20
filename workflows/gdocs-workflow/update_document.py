#!/usr/bin/env python3
"""Apply JSON updates to a Google Docs document.

Supported friendly operations:
- clear_body
- replace_all_text
- insert_end
- insert_index
- insert_table
- insert_image
- delete_range
- style_paragraph
- style_text

Also accepts raw Google Docs API batchUpdate bodies via `{ "requests": [...] }`.

Exit codes:
  0  success
  1  business / API failure
  2  usage error
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from gdocs_auth import build_docs_service
from gdocs_common import (
    build_insert_image_request,
    build_insert_table_request,
    build_text_style,
    document_url,
    extract_body_text,
    get_body_end_index,
    load_json,
    resolve_document_id,
    write_json,
)


def _count_replacements(text: str, needle: str, replacement: str, match_case: bool) -> tuple[int, str]:
    if match_case:
        count = text.count(needle)
        return count, text.replace(needle, replacement)
    count = len(re.findall(re.escape(needle), text, flags=re.IGNORECASE))
    return count, re.sub(re.escape(needle), replacement, text, flags=re.IGNORECASE)


def _insert_model_text(text: str, index: int, inserted: str) -> str:
    position = max(index - 1, 0)
    return text[:position] + inserted + text[position:]


def _delete_model_range(text: str, start_index: int, end_index: int) -> str:
    start = max(start_index - 1, 0)
    end = max(end_index - 1, 0)
    return text[:start] + text[end:]


def _normalize_operations(payload: Any) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    if isinstance(payload, dict) and "requests" in payload:
        requests = payload["requests"]
        if not isinstance(requests, list):
            raise ValueError("`requests` must be a list")
        raw_batch = {"requests": requests}
        if "writeControl" in payload:
            raw_batch["writeControl"] = payload["writeControl"]
        return None, raw_batch
    if isinstance(payload, dict) and "operations" in payload:
        operations = payload["operations"]
    else:
        operations = payload
    if not isinstance(operations, list):
        raise ValueError("Changes file must be a list, `{\"operations\": [...]}`, or `{\"requests\": [...]}`")
    return operations, None


def _build_paragraph_style(op: dict[str, Any]) -> tuple[dict[str, Any], str]:
    style: dict[str, Any] = {}
    fields: list[str] = []
    if op.get("namedStyleType"):
        style["namedStyleType"] = str(op["namedStyleType"])
        fields.append("namedStyleType")
    if op.get("alignment"):
        style["alignment"] = str(op["alignment"])
        fields.append("alignment")
    return style, ",".join(fields)


def _friendly_requests(
    operations: list[dict[str, Any]],
    *,
    initial_text: str,
    initial_end_index: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    requests: list[dict[str, Any]] = []
    normalized_ops: list[dict[str, Any]] = []
    current_text = initial_text
    current_end_index = initial_end_index

    for position, op in enumerate(operations, start=1):
        if not isinstance(op, dict):
            raise ValueError(f"Operation #{position} must be an object")
        op_name = str(op.get("op") or op.get("type") or "").strip().lower()
        if not op_name:
            raise ValueError(f"Operation #{position} missing `op`")

        if op_name == "clear_body":
            if current_end_index > 2:
                requests.append(
                    {
                        "deleteContentRange": {
                            "range": {
                                "startIndex": 1,
                                "endIndex": current_end_index - 1,
                            }
                        }
                    }
                )
                current_text = "\n"
                current_end_index = 2
            normalized_ops.append({"op": op_name})
            continue

        if op_name == "replace_all_text":
            contains = op.get("contains")
            replace = op.get("replace", "")
            match_case = bool(op.get("matchCase", False))
            if not isinstance(contains, str) or contains == "":
                raise ValueError(f"Operation #{position} replace_all_text requires non-empty `contains`")
            replace_str = str(replace)
            requests.append(
                {
                    "replaceAllText": {
                        "containsText": {
                            "text": contains,
                            "matchCase": match_case,
                        },
                        "replaceText": replace_str,
                    }
                }
            )
            replace_count, current_text = _count_replacements(current_text, contains, replace_str, match_case)
            current_end_index += replace_count * (len(replace_str) - len(contains))
            normalized_ops.append(
                {
                    "op": op_name,
                    "contains": contains,
                    "replace": replace_str,
                    "matchCase": match_case,
                    "estimatedReplacementCount": replace_count,
                }
            )
            continue

        if op_name == "insert_end":
            text = str(op.get("text", ""))
            if not text:
                raise ValueError(f"Operation #{position} insert_end requires `text`")
            insert_index = current_end_index - 1
            requests.append({"insertText": {"location": {"index": insert_index}, "text": text}})
            current_text = _insert_model_text(current_text, insert_index, text)
            current_end_index += len(text)
            normalized_ops.append({"op": op_name, "index": insert_index, "text": text})
            continue

        if op_name == "insert_index":
            if op.get("index") is None:
                raise ValueError(f"Operation #{position} insert_index requires `index`")
            index = int(op["index"])
            text = str(op.get("text", ""))
            if not text:
                raise ValueError(f"Operation #{position} insert_index requires `text`")
            if index < 1 or index > current_end_index - 1:
                raise ValueError(
                    f"Operation #{position} insert_index out of range: {index} not in [1, {current_end_index - 1}]"
                )
            requests.append({"insertText": {"location": {"index": index}, "text": text}})
            current_text = _insert_model_text(current_text, index, text)
            current_end_index += len(text)
            normalized_ops.append({"op": op_name, "index": index, "text": text})
            continue

        if op_name == "insert_table":
            fallback_index = current_end_index - 1
            request, summary, estimated_delta = build_insert_table_request(op, fallback_index=fallback_index)
            requests.append(request)
            current_end_index += estimated_delta
            normalized_ops.append(summary)
            continue

        if op_name == "insert_image":
            fallback_index = current_end_index - 1
            request, summary, estimated_delta = build_insert_image_request(op, fallback_index=fallback_index)
            requests.append(request)
            current_text = _insert_model_text(current_text, int(summary["index"]), "[INLINE_OBJECT]")
            current_end_index += estimated_delta
            normalized_ops.append(summary)
            continue

        if op_name == "delete_range":
            if op.get("startIndex") is None or op.get("endIndex") is None:
                raise ValueError(f"Operation #{position} delete_range requires `startIndex` and `endIndex`")
            start_index = int(op["startIndex"])
            end_index = int(op["endIndex"])
            if start_index < 1 or end_index > current_end_index or start_index >= end_index:
                raise ValueError(
                    f"Operation #{position} delete_range invalid: [{start_index}, {end_index}) with doc end {current_end_index}"
                )
            requests.append(
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": start_index,
                            "endIndex": end_index,
                        }
                    }
                }
            )
            current_text = _delete_model_range(current_text, start_index, end_index)
            current_end_index -= end_index - start_index
            normalized_ops.append({"op": op_name, "startIndex": start_index, "endIndex": end_index})
            continue

        if op_name == "style_paragraph":
            if op.get("startIndex") is None or op.get("endIndex") is None:
                raise ValueError(f"Operation #{position} style_paragraph requires `startIndex` and `endIndex`")
            style, fields = _build_paragraph_style(op)
            if not fields:
                raise ValueError(f"Operation #{position} style_paragraph requires style fields")
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": int(op["startIndex"]),
                            "endIndex": int(op["endIndex"]),
                        },
                        "paragraphStyle": style,
                        "fields": fields,
                    }
                }
            )
            normalized_ops.append(
                {
                    "op": op_name,
                    "startIndex": int(op["startIndex"]),
                    "endIndex": int(op["endIndex"]),
                    "fields": fields,
                }
            )
            continue

        if op_name == "style_text":
            if op.get("startIndex") is None or op.get("endIndex") is None:
                raise ValueError(f"Operation #{position} style_text requires `startIndex` and `endIndex`")
            style, fields = build_text_style(op)
            if not fields:
                raise ValueError(f"Operation #{position} style_text requires style fields")
            requests.append(
                {
                    "updateTextStyle": {
                        "range": {
                            "startIndex": int(op["startIndex"]),
                            "endIndex": int(op["endIndex"]),
                        },
                        "textStyle": style,
                        "fields": fields,
                    }
                }
            )
            normalized_ops.append(
                {
                    "op": op_name,
                    "startIndex": int(op["startIndex"]),
                    "endIndex": int(op["endIndex"]),
                    "fields": fields,
                }
            )
            continue

        raise ValueError(f"Unsupported operation #{position}: {op_name}")

    return requests, normalized_ops, current_end_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply JSON updates to a Google Docs document.")
    parser.add_argument("--document-id", required=True, help="Document id or URL")
    parser.add_argument("--changes-file", required=True, help="Path to JSON changes file")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print normalized requests without applying")
    parser.add_argument("--output", help="Optional path to write JSON result")
    parser.add_argument("--account", help="Account alias")
    args = parser.parse_args(argv)

    document_id = resolve_document_id(args.document_id)
    changes_path = Path(args.changes_file)
    payload = load_json(changes_path)
    operations, raw_batch = _normalize_operations(payload)

    service = build_docs_service(account=args.account)
    document = service.documents().get(documentId=document_id).execute()
    initial_text = extract_body_text(document)
    initial_end_index = get_body_end_index(document)

    if raw_batch is not None:
        requests = raw_batch["requests"]
        normalized_ops = [{"op": "raw_request", "count": len(raw_batch["requests"])}]
        if "writeControl" in raw_batch:
            normalized_ops[0]["writeControl"] = raw_batch["writeControl"]
        estimated_end_index = initial_end_index
    else:
        requests, normalized_ops, estimated_end_index = _friendly_requests(
            operations or [],
            initial_text=initial_text,
            initial_end_index=initial_end_index,
        )

    result = {
        "documentId": document_id,
        "url": document_url(document_id),
        "changesFile": str(changes_path),
        "dryRun": args.dry_run,
        "operations": normalized_ops,
        "requests": requests,
        "initialEndIndex": initial_end_index,
        "estimatedEndIndex": estimated_end_index,
    }
    if raw_batch is not None and "writeControl" in raw_batch:
        result["writeControl"] = raw_batch["writeControl"]

    if args.dry_run:
        write_json(result, args.output)
        if args.output:
            write_json(result)
        return 0

    if not requests:
        result["message"] = "No changes applied; request list was empty."
        del result["requests"]
        write_json(result, args.output)
        if args.output:
            write_json(result)
        return 0

    batch_body: dict[str, Any] = {"requests": requests}
    if raw_batch is not None and "writeControl" in raw_batch:
        batch_body["writeControl"] = raw_batch["writeControl"]

    response = service.documents().batchUpdate(
        documentId=document_id,
        body=batch_body,
    ).execute()
    result["dryRun"] = False
    result["replyCount"] = len(response.get("replies", []))
    result["requestsApplied"] = len(requests)
    if response.get("writeControl"):
        result["appliedWriteControl"] = response["writeControl"]
    del result["requests"]

    write_json(result, args.output)
    if args.output:
        write_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
