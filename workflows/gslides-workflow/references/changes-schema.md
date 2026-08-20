# Changes JSON Schema

Reference for the changes JSON format used by `update_slides.py`.

## Structure

```json
{
  "updates": [
    { "type": "update_type", ...params }
  ]
}
```

## Quick Usage

1) Extract current deck content (for slide indices and context):
```bash
$HOME/.agents/.venv/bin/python $SKILL/scripts/get_deck_content.py \
  --presentation-id "PRESENTATION_ID" \
  --output deck.json
```

2) Create a `changes.json` matching this schema, then preview/apply:
```bash
$HOME/.agents/.venv/bin/python $SKILL/scripts/update_slides.py \
  --presentation-id "PRESENTATION_ID" \
  --changes-file changes.json \
  --dry-run
# Remove --dry-run to apply
```

## Update Types

Supported update types:
- replace_text
- add_table_row
- delete_table_row
- update_table_cell
- add_text_box
- delete_slide
- duplicate_slide

### replace_text
Find and replace text globally or within specific slide.

```json
{
  "type": "replace_text",
  "find": "BCE",
  "replace": "Acme Energy",
  "matchCase": false,
  "scope": {"slideIndex": 5}
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| find | string | yes | Text to find |
| replace | string | yes | Replacement text |
| matchCase | boolean | no | Case-sensitive match (default: false) |
| scope.slideIndex | integer | no | 1-based slide index. Omit for global replace |

### add_table_row
Add row to existing table.

```json
{
  "type": "add_table_row",
  "slideIndex": 6,
  "tableIndex": 0,
  "position": "end",
  "cells": ["Carbon Reduction Report", "Report is ready", "", ""]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| slideIndex | integer | yes | 1-based slide index |
| tableIndex | integer | no | 0-based table index in slide (default: 0) |
| position | string\|int | no | "end", "start", or row number (default: "end") |
| cells | array | yes | Cell values for new row |

### delete_table_row
Remove row from table.

```json
{
  "type": "delete_table_row",
  "slideIndex": 6,
  "tableIndex": 0,
  "rowIndex": 3
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| slideIndex | integer | yes | 1-based slide index |
| tableIndex | integer | no | 0-based table index (default: 0) |
| rowIndex | integer | yes | 0-based row index to delete |

### update_table_cell
Update specific cell content.

```json
{
  "type": "update_table_cell",
  "slideIndex": 6,
  "tableIndex": 0,
  "rowIndex": 2,
  "columnIndex": 1,
  "text": "Updated status text"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| slideIndex | integer | yes | 1-based slide index |
| tableIndex | integer | no | 0-based table index (default: 0) |
| rowIndex | integer | yes | 0-based row index |
| columnIndex | integer | yes | 0-based column index |
| text | string | yes | New cell content |

### add_text_box
Add text box, optionally positioned near an image (for captions).

```json
{
  "type": "add_text_box",
  "slideIndex": 14,
  "text": "End-to-end digital solution for 2026",
  "nearElement": "image",
  "imageIndex": 0,
  "position": "below"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| slideIndex | integer | yes | 1-based slide index |
| text | string | yes | Text content |
| nearElement | string | no | "image" to position near image |
| imageIndex | integer | no | 0-based image index (default: 0) |
| position | string | no | "below", "above", "left", "right" (default: "below") |
| x, y | integer | no | Explicit position in EMU |
| width, height | integer | no | Explicit size in EMU |

### delete_slide
Remove slide from presentation.

```json
{
  "type": "delete_slide",
  "slideIndex": 10
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| slideIndex | integer | yes | 1-based slide index |

### duplicate_slide
Copy slide.

```json
{
  "type": "duplicate_slide",
  "slideIndex": 3,
  "insertAtIndex": 5
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| slideIndex | integer | yes | 1-based slide index to copy |
| insertAtIndex | integer | no | Position for new slide |

## Common Patterns

Global text replacement:
```json
{"type": "replace_text", "find": "2024", "replace": "2025"}
```

Add table row at end:
```json
{
  "type": "add_table_row",
  "slideIndex": 6,
  "tableIndex": 0,
  "cells": ["Requirement", "Status", "", ""]
}
```

Caption below the first image on a slide:
```json
{
  "type": "add_text_box",
  "slideIndex": 14,
  "text": "Figure 1: System Overview",
  "nearElement": "image",
  "position": "below"
}
```

## Complete Example

```json
{
  "updates": [
    {
      "type": "replace_text",
      "find": "BCE",
      "replace": "Acme Energy",
      "scope": {"slideIndex": 5}
    },
    {
      "type": "add_table_row",
      "slideIndex": 6,
      "tableIndex": 0,
      "position": "end",
      "cells": ["Carbon Reduction Report", "Report is ready", "", "Need Finance approval"]
    },
    {
      "type": "add_text_box",
      "slideIndex": 14,
      "text": "End-to-end digital solution for 2026",
      "nearElement": "image",
      "position": "below"
    }
  ]
}
```

## Indexing Notes

- slideIndex is 1-based (first slide is 1)
- tableIndex, rowIndex, columnIndex are 0-based
- imageIndex is 0-based

## EMU Units

Google Slides uses EMU (English Metric Units):
- 914400 EMU = 1 inch
- 12700 EMU = 1 point

For explicit positioning, use EMU values for x, y, width, height.
