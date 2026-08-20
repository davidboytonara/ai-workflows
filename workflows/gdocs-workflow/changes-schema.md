# Google Docs changes schema

`$HOME/.agents/.venv/bin/python .agents/workflows/gdocs-workflow/cli.py update --changes-file changes.json`

Accepted payload shapes:

1. Friendly ops:

```json
{
  "operations": [
    {"op": "replace_all_text", "contains": "{{name}}", "replace": "Jane"},
    {"op": "insert_end", "text": "\n## Next steps\n- Confirm owner\n- Set deadline\n"},
    {"op": "style_paragraph", "startIndex": 1, "endIndex": 16, "namedStyleType": "HEADING_1"},
    {"op": "style_text", "startIndex": 1, "endIndex": 16, "bold": true, "foregroundColor": "#1A73E8"}
  ]
}
```

2. Raw Google Docs API requests:

```json
{
  "requests": [
    {
      "replaceAllText": {
        "containsText": {"text": "{{date}}", "matchCase": true},
        "replaceText": "2026-04-17"
      }
    }
  ]
}
```

## Supported friendly ops

- `clear_body`
- `replace_all_text`
  - fields: `contains`, `replace`, optional `matchCase`
- `insert_end`
  - fields: `text`
- `insert_index`
  - fields: `index`, `text`
- `delete_range`
  - fields: `startIndex`, `endIndex`
- `style_paragraph`
  - fields: `startIndex`, `endIndex`, optional `namedStyleType`, `alignment`
- `style_text`
  - fields: `startIndex`, `endIndex`, any of `bold`, `italic`, `underline`, `strikethrough`, `link`, `fontFamily`, `fontSize`, `foregroundColor`, `backgroundColor`

## Dry run

Preview normalized requests before live apply:

```bash
$HOME/.agents/.venv/bin/python .agents/workflows/gdocs-workflow/cli.py update \
  --document-id "<id-or-url>" \
  --changes-file changes.json \
  --dry-run
```
