# Content JSON Schema Reference

Complete schema for the `add_content.py` script.

## Basic Structure

```json
{
  "slides": [
    {
      "title": "string (required)",
      "layout": "LAYOUT_TYPE (optional, default: TITLE_AND_BODY)",
      "subtitle": "string (optional, for TITLE layout)",
      "bullets": ["array", "of", "strings"],
      "left_column": ["for", "two-column", "layout"],
      "right_column": ["for", "two-column", "layout"],
      "speaker_notes": "string (optional)"
    }
  ]
}
```

## Layout Types

### TITLE
Full-slide title with optional subtitle. Use for opening/closing slides.

```json
{
  "title": "Presentation Title",
  "layout": "TITLE",
  "subtitle": "Optional Subtitle Text"
}
```

### TITLE_AND_BODY (default)
Title at top, bullet points below. Most common layout.

```json
{
  "title": "Slide Title",
  "layout": "TITLE_AND_BODY",
  "bullets": [
    "First key point",
    "Second key point",
    "Third key point"
  ],
  "speaker_notes": "Notes for presenter"
}
```

### SECTION_HEADER
Large centered title for section dividers.

```json
{
  "title": "Section Name",
  "layout": "SECTION_HEADER"
}
```

### TITLE_AND_TWO_COLUMNS
Title with two columns of content below.

```json
{
  "title": "Comparison",
  "layout": "TITLE_AND_TWO_COLUMNS",
  "left_column": [
    "Left point 1",
    "Left point 2"
  ],
  "right_column": [
    "Right point 1",
    "Right point 2"
  ]
}
```

### BLANK
Empty slide for custom content.

```json
{
  "title": "",
  "layout": "BLANK"
}
```

## Complete Example

```json
{
  "slides": [
    {
      "title": "Q4 2024 Business Review",
      "layout": "TITLE",
      "subtitle": "Acme Corp - Fleet Operations"
    },
    {
      "title": "Agenda",
      "layout": "TITLE_AND_BODY",
      "bullets": [
        "Fleet performance metrics",
        "Revenue highlights",
        "Operational challenges",
        "Q1 2025 roadmap"
      ]
    },
    {
      "title": "Fleet Performance",
      "layout": "SECTION_HEADER"
    },
    {
      "title": "Fleet Utilization",
      "layout": "TITLE_AND_BODY",
      "bullets": [
        "Active vehicles: 1,250 (+15% QoQ)",
        "Average utilization: 78%",
        "Peak utilization: 92% (weekdays)",
        "Maintenance downtime: 4.2%"
      ],
      "speaker_notes": "Highlight the 15% growth. Mention the new Jakarta depot opened in October."
    },
    {
      "title": "Revenue vs Costs",
      "layout": "TITLE_AND_TWO_COLUMNS",
      "left_column": [
        "Revenue: $2.4M",
        "Growth: +22% YoY",
        "New contracts: 12",
        "Avg contract value: $180K"
      ],
      "right_column": [
        "Operating costs: $1.8M",
        "Maintenance: $320K",
        "Charging: $280K",
        "Margin: 25%"
      ]
    },
    {
      "title": "Key Takeaways",
      "layout": "TITLE_AND_BODY",
      "bullets": [
        "Fleet expansion on track",
        "Utilization exceeds target",
        "Cost optimization needed in maintenance",
        "Strong pipeline for Q1"
      ]
    },
    {
      "title": "Thank You",
      "layout": "TITLE",
      "subtitle": "Questions?"
    }
  ]
}
```

## Tips for Claude

1. **Generate content first** - Write all slide content as JSON before calling the script
2. **Use appropriate layouts** - TITLE for opening/closing, SECTION_HEADER for dividers
3. **Keep bullets concise** - 3-6 bullets per slide, each under 10 words
4. **Add speaker notes** - Help the presenter with talking points
5. **Validate JSON** - Use `$HOME/.agents/.venv/bin/python -m json.tool slides.json` to check syntax
