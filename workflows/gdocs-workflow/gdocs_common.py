#!/usr/bin/env python3
"""Common helpers for Google Docs workflow scripts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOCUMENT_URL_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
UNORDERED_BULLET_RE = re.compile(r"^([ \t]*)([-*+])\s+(.+?)\s*$")
ORDERED_BULLET_RE = re.compile(r"^([ \t]*)\d+[.)]\s+(.+?)\s*$")
VALID_DIMENSION_UNITS = {"PT", "PX", "EMU"}


@dataclass(frozen=True)
class MarkdownBlock:
    kind: str
    text: str
    level: int = 0
    ordered: bool = False


def resolve_document_id(value: str) -> str:
    match = DOCUMENT_URL_RE.search(value)
    return match.group(1) if match else value


def document_url(document_id: str) -> str:
    return f"https://docs.google.com/document/d/{document_id}/edit"


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path: str | Path) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def write_json(data: Any, path: str | Path | None = None) -> None:
    rendered = json.dumps(data, ensure_ascii=False, indent=2)
    if path is None:
        print(rendered)
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered + "\n", encoding="utf-8")


def extract_text_from_paragraph(paragraph: dict[str, Any]) -> str:
    parts: list[str] = []
    for element in paragraph.get("elements", []):
        if "textRun" in element:
            parts.append(element["textRun"].get("content", ""))
        elif "inlineObjectElement" in element:
            parts.append("[INLINE_OBJECT]")
        elif "footnoteReference" in element:
            parts.append("[FOOTNOTE]")
        elif "person" in element:
            parts.append("[PERSON]")
        elif "richLink" in element:
            parts.append("[RICH_LINK]")
    return "".join(parts)


def extract_inline_object_ids_from_paragraph(paragraph: dict[str, Any]) -> list[str]:
    inline_object_ids: list[str] = []
    for element in paragraph.get("elements", []):
        inline_object = element.get("inlineObjectElement")
        if inline_object and inline_object.get("inlineObjectId"):
            inline_object_ids.append(str(inline_object["inlineObjectId"]))
    return inline_object_ids


def summarize_paragraph(paragraph: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": extract_text_from_paragraph(paragraph).rstrip("\n"),
        "inlineObjectIds": extract_inline_object_ids_from_paragraph(paragraph),
    }


def _inline_object_size(embedded_object: dict[str, Any]) -> dict[str, Any] | None:
    size = embedded_object.get("size") or {}
    height = size.get("height")
    width = size.get("width")
    if not height and not width:
        return None
    return {
        "height": height,
        "width": width,
    }


def summarize_inline_object(inline_object_id: str, inline_object: dict[str, Any]) -> dict[str, Any]:
    properties = inline_object.get("inlineObjectProperties") or {}
    embedded_object = properties.get("embeddedObject") or {}
    image_properties = embedded_object.get("imageProperties") or {}
    summary = {
        "inlineObjectId": inline_object_id,
        "title": embedded_object.get("title"),
        "description": embedded_object.get("description"),
        "contentUri": image_properties.get("contentUri"),
        "sourceUri": image_properties.get("sourceUri"),
        "cropProperties": image_properties.get("cropProperties"),
        "size": _inline_object_size(embedded_object),
    }
    return {key: value for key, value in summary.items() if value is not None}


def summarize_inline_objects(document: dict[str, Any]) -> list[dict[str, Any]]:
    inline_objects = document.get("inlineObjects") or {}
    return [
        summarize_inline_object(inline_object_id, inline_object)
        for inline_object_id, inline_object in sorted(inline_objects.items())
    ]


def summarize_table(table: dict[str, Any]) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    inline_object_ids: list[str] = []

    for row in table.get("tableRows", []):
        row_cells: list[dict[str, Any]] = []
        for cell in row.get("tableCells", []):
            cell_text_parts: list[str] = []
            cell_inline_ids: list[str] = []
            for item in cell.get("content", []):
                if "paragraph" not in item:
                    continue
                paragraph_summary = summarize_paragraph(item["paragraph"])
                if paragraph_summary["text"]:
                    cell_text_parts.append(paragraph_summary["text"])
                cell_inline_ids.extend(paragraph_summary["inlineObjectIds"])
            inline_object_ids.extend(cell_inline_ids)
            row_cells.append(
                {
                    "text": "\n".join(cell_text_parts),
                    "inlineObjectIds": cell_inline_ids,
                }
            )
        rows.append(row_cells)

    cell_text = [[cell["text"] for cell in row] for row in rows]
    return {
        "rows": len(rows),
        "columns": max((len(row) for row in rows), default=0),
        "cellCount": sum(len(row) for row in rows),
        "cells": rows,
        "cellText": cell_text,
        "inlineObjectIds": inline_object_ids,
    }


def extract_structural_text(elements: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for element in elements:
        if "paragraph" in element:
            parts.append(extract_text_from_paragraph(element["paragraph"]))
            continue
        if "table" in element:
            for row in element["table"].get("tableRows", []):
                row_cells: list[str] = []
                for cell in row.get("tableCells", []):
                    row_cells.append(extract_structural_text(cell.get("content", [])).strip())
                parts.append(" | ".join(row_cells) + "\n")
            continue
        if "tableOfContents" in element:
            parts.append(extract_structural_text(element["tableOfContents"].get("content", [])))
    return "".join(parts)


def extract_body_text(document: dict[str, Any]) -> str:
    body = document.get("body", {})
    return extract_structural_text(body.get("content", []))


def get_body_end_index(document: dict[str, Any]) -> int:
    content = document.get("body", {}).get("content", [])
    if not content:
        return 1
    return content[-1].get("endIndex", 1)


def _count_indent(indent: str) -> int:
    tabs = indent.count("\t")
    spaces = len(indent.replace("\t", ""))
    return tabs + (spaces // 2)


def parse_markdown_blocks(content: str) -> list[MarkdownBlock]:
    blocks: list[MarkdownBlock] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        text = " ".join(line.strip() for line in paragraph_lines).strip()
        paragraph_lines.clear()
        if text:
            blocks.append(MarkdownBlock(kind="paragraph", text=text))

    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw_line.strip():
            flush_paragraph()
            continue

        heading_match = HEADING_RE.match(raw_line)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            blocks.append(MarkdownBlock(kind="heading", text=heading_match.group(2).strip(), level=level))
            continue

        unordered_match = UNORDERED_BULLET_RE.match(raw_line)
        if unordered_match:
            flush_paragraph()
            blocks.append(
                MarkdownBlock(
                    kind="bullet",
                    text=unordered_match.group(3).strip(),
                    level=_count_indent(unordered_match.group(1)),
                    ordered=False,
                )
            )
            continue

        ordered_match = ORDERED_BULLET_RE.match(raw_line)
        if ordered_match:
            flush_paragraph()
            blocks.append(
                MarkdownBlock(
                    kind="bullet",
                    text=ordered_match.group(2).strip(),
                    level=_count_indent(ordered_match.group(1)),
                    ordered=True,
                )
            )
            continue

        paragraph_lines.append(raw_line)

    flush_paragraph()
    return blocks


def build_text_insert_requests(
    text: str,
    *,
    start_index: int,
    prefix_newline: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int | str]]:
    rendered = text
    if prefix_newline and rendered and not rendered.startswith("\n"):
        rendered = "\n" + rendered
    if rendered and not rendered.endswith("\n"):
        rendered += "\n"
    if not rendered:
        return [], {"charactersInserted": 0, "blocks": 0, "format": "text"}
    requests = [{"insertText": {"location": {"index": start_index}, "text": rendered}}]
    return requests, {
        "charactersInserted": len(rendered),
        "blocks": rendered.count("\n"),
        "format": "text",
    }


def build_markdown_insert_requests(
    markdown: str,
    *,
    start_index: int,
    prefix_newline: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int | str]]:
    blocks = parse_markdown_blocks(markdown)
    if not blocks:
        return [], {"charactersInserted": 0, "blocks": 0, "format": "markdown"}

    prefix = "\n" if prefix_newline else ""
    full_text = prefix
    actions: list[dict[str, Any]] = []
    offset = len(prefix)
    bullet_count = 0
    heading_count = 0

    for block in blocks:
        if block.kind == "bullet":
            rendered = f"{'\t' * block.level}{block.text}\n"
        else:
            rendered = f"{block.text}\n"
        start = offset
        full_text += rendered
        offset += len(rendered)

        if block.kind == "heading":
            heading_count += 1
            actions.append(
                {
                    "type": "paragraph_style",
                    "startIndex": start_index + start,
                    "endIndex": start_index + offset,
                    "namedStyleType": f"HEADING_{block.level}",
                }
            )
        elif block.kind == "bullet":
            bullet_count += 1
            actions.append(
                {
                    "type": "bullet",
                    "startIndex": start_index + start,
                    "endIndex": start_index + offset,
                    "bulletPreset": (
                        "NUMBERED_DECIMAL_ALPHA_ROMAN"
                        if block.ordered
                        else "BULLET_DISC_CIRCLE_SQUARE"
                    ),
                }
            )

    requests: list[dict[str, Any]] = [
        {"insertText": {"location": {"index": start_index}, "text": full_text}}
    ]
    for action in actions:
        if action["type"] == "paragraph_style":
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": action["startIndex"],
                            "endIndex": action["endIndex"],
                        },
                        "paragraphStyle": {"namedStyleType": action["namedStyleType"]},
                        "fields": "namedStyleType",
                    }
                }
            )
        elif action["type"] == "bullet":
            requests.append(
                {
                    "createParagraphBullets": {
                        "range": {
                            "startIndex": action["startIndex"],
                            "endIndex": action["endIndex"],
                        },
                        "bulletPreset": action["bulletPreset"],
                    }
                }
            )

    return requests, {
        "charactersInserted": len(full_text),
        "blocks": len(blocks),
        "headings": heading_count,
        "bullets": bullet_count,
        "format": "markdown",
    }


def _normalize_dimension(value: Any, *, field_name: str) -> dict[str, Any]:
    if isinstance(value, (int, float)):
        return {"magnitude": float(value), "unit": "PT"}
    if isinstance(value, dict):
        magnitude = value.get("magnitude")
        unit = value.get("unit", "PT")
        if magnitude is None:
            raise ValueError(f"{field_name} requires `magnitude`")
        unit_str = str(unit).upper()
        if unit_str not in VALID_DIMENSION_UNITS:
            raise ValueError(f"{field_name} unit must be one of {sorted(VALID_DIMENSION_UNITS)}")
        return {"magnitude": float(magnitude), "unit": unit_str}
    raise ValueError(f"{field_name} must be number or {{magnitude, unit}} object")


def build_insert_table_request(op: dict[str, Any], *, fallback_index: int | None = None) -> tuple[dict[str, Any], dict[str, Any], int]:
    rows = int(op.get("rows") or 0)
    columns = int(op.get("columns") or 0)
    if rows < 1 or columns < 1:
        raise ValueError("insert_table requires positive `rows` and `columns`")

    index_value = op.get("index", fallback_index)
    if index_value is None:
        raise ValueError("insert_table requires `index` when no fallback index provided")

    location: dict[str, Any] = {"index": int(index_value)}
    if op.get("tabId"):
        location["tabId"] = str(op["tabId"])

    request = {
        "insertTable": {
            "rows": rows,
            "columns": columns,
            "location": location,
        }
    }
    summary = {
        "op": "insert_table",
        "index": int(index_value),
        "rows": rows,
        "columns": columns,
    }
    if "tabId" in location:
        summary["tabId"] = location["tabId"]

    estimated_delta = 1 + rows + (rows * columns * 2)
    return request, summary, estimated_delta


def build_insert_image_request(op: dict[str, Any], *, fallback_index: int | None = None) -> tuple[dict[str, Any], dict[str, Any], int]:
    uri = op.get("uri") or op.get("url")
    if not uri:
        raise ValueError("insert_image requires `uri` or `url`")

    index_value = op.get("index", fallback_index)
    if index_value is None:
        raise ValueError("insert_image requires `index` when no fallback index provided")

    location: dict[str, Any] = {"index": int(index_value)}
    if op.get("tabId"):
        location["tabId"] = str(op["tabId"])

    request_body: dict[str, Any] = {
        "uri": str(uri),
        "location": location,
    }
    object_size: dict[str, Any] = {}
    if op.get("width") is not None:
        object_size["width"] = _normalize_dimension(op["width"], field_name="width")
    if op.get("height") is not None:
        object_size["height"] = _normalize_dimension(op["height"], field_name="height")
    if object_size:
        request_body["objectSize"] = object_size

    request = {"insertInlineImage": request_body}
    summary = {
        "op": "insert_image",
        "index": int(index_value),
        "uri": str(uri),
    }
    if object_size:
        summary["objectSize"] = object_size
    if "tabId" in location:
        summary["tabId"] = location["tabId"]

    return request, summary, 1


def parse_hex_color(value: str) -> dict[str, float]:
    color = value.strip().lstrip("#")
    if len(color) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in color):
        raise ValueError(f"Invalid hex color: {value}")
    return {
        "red": int(color[0:2], 16) / 255,
        "green": int(color[2:4], 16) / 255,
        "blue": int(color[4:6], 16) / 255,
    }


def build_text_style(op: dict[str, Any]) -> tuple[dict[str, Any], str]:
    style: dict[str, Any] = {}
    fields: list[str] = []

    for name in ("bold", "italic", "underline", "strikethrough"):
        if name in op:
            style[name] = bool(op[name])
            fields.append(name)

    link = op.get("link") or op.get("url")
    if link:
        style["link"] = {"url": str(link)}
        fields.append("link")

    if op.get("fontFamily"):
        style["weightedFontFamily"] = {"fontFamily": str(op["fontFamily"])}
        fields.append("weightedFontFamily")

    if op.get("fontSize") is not None:
        style["fontSize"] = {"magnitude": float(op["fontSize"]), "unit": "PT"}
        fields.append("fontSize")

    foreground = op.get("foregroundColor") or op.get("textColor")
    if foreground:
        style["foregroundColor"] = {"color": {"rgbColor": parse_hex_color(str(foreground))}}
        fields.append("foregroundColor")

    background = op.get("backgroundColor") or op.get("highlightColor")
    if background:
        style["backgroundColor"] = {"color": {"rgbColor": parse_hex_color(str(background))}}
        fields.append("backgroundColor")

    return style, ",".join(fields)
