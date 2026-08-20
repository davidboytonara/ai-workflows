# Google Docs content input

`$HOME/.agents/.venv/bin/python .agents/workflows/gdocs-workflow/cli.py content` accepts `.md` or `.txt`.

## Markdown support in v1

Supported:
- headings: `#` to `######`
- unordered lists: `- item`, `* item`, `+ item`
- ordered lists: `1. item`, `1) item`
- nested lists via tabs or 2-space indentation
- paragraphs separated by blank lines

Not supported in markdown importer v1:
- tables
- images
- inline bold / italic / links
- comments / suggestions
- footnotes

Use `update --changes-file ...` with raw Docs API requests when richer formatting needed.

## Example markdown

```md
# Project Brief

Short intro paragraph.

## Goals
- Reduce manual work
- Improve consistency
  - Reuse templates
  - Keep audit trail

## Next steps
1. Create doc
2. Inspect indexes
3. Apply precise updates
```

## Plain text mode

`.txt` files keep text as-is. Workflow appends trailing newline automatically when needed.
