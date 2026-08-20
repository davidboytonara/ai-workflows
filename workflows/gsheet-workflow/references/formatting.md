# Formatting Reference

## Cell Formatting Options

### Text Formatting
```bash
--bold              # Bold text
--italic            # Italic text
--underline         # Underline text
--font-size N       # Font size in points (8-72)
--font-family NAME  # Font family (Arial, Roboto, etc.)
```

### Colors
```bash
--text-color "#HEX" # Text color
--bg-color "#HEX"   # Background color
```

Common colors:
- `#4285F4` - Google Blue
- `#34A853` - Google Green  
- `#FBBC05` - Google Yellow
- `#EA4335` - Google Red
- `#FFFFFF` - White
- `#000000` - Black
- `#F3F3F3` - Light Gray

### Alignment
```bash
--align LEFT|CENTER|RIGHT      # Horizontal
--valign TOP|MIDDLE|BOTTOM     # Vertical
--wrap WRAP|CLIP|OVERFLOW_CELL # Text wrapping
```

### Number Formats
```bash
--number-format currency    # $1,234.56
--number-format percentage  # 12.34%
--number-format date        # 2024-01-15
--number-format datetime    # 2024-01-15 14:30:00
--number-format number      # 1,234.56
--number-format integer     # 1,234
--number-format text        # Treat as text
--number-format "#,##0.00"  # Custom pattern
```

## Conditional Formatting

### Rule Types
```bash
--rule greater_than    # Value > threshold
--rule less_than       # Value < threshold
--rule equal_to        # Value == threshold
--rule not_equal       # Value != threshold
--rule between         # min <= Value <= max (use "min,max")
--rule contains        # Text contains string
--rule not_contains    # Text doesn't contain
--rule not_empty       # Cell is not blank
--rule is_empty        # Cell is blank
```

### Examples

Highlight values > 1000 in green:
```bash
$HOME/.agents/.venv/bin/python format_cells.py --spreadsheet ID --range "B2:B100" \
  --conditional --rule greater_than --value 1000 --highlight-color "#00FF00"
```

Highlight values between 50-100 in yellow:
```bash
$HOME/.agents/.venv/bin/python format_cells.py --spreadsheet ID --range "C2:C100" \
  --conditional --rule between --value "50,100" --highlight-color "#FFFF00"
```

Highlight cells containing "ERROR":
```bash
$HOME/.agents/.venv/bin/python format_cells.py --spreadsheet ID --range "D2:D100" \
  --conditional --rule contains --value "ERROR" --highlight-color "#FF0000"
```

## Alternating Row Colors

Apply zebra striping to a sheet:
```bash
$HOME/.agents/.venv/bin/python format_cells.py --spreadsheet ID --alternating --sheet "Data" \
  --header-color "#4285F4" --first-color "#FFFFFF" --second-color "#F3F3F3"
```

## Complete Example

Format a data table with headers:
```bash
SKILL=/mnt/skills/user/google-sheets
ID="your-spreadsheet-id"

# Format header row
$HOME/.agents/.venv/bin/python $SKILL/scripts/format_cells.py --spreadsheet "$ID" --range "A1:E1" \
  --bold --bg-color "#4285F4" --text-color "#FFFFFF" --align CENTER

# Format currency column
$HOME/.agents/.venv/bin/python $SKILL/scripts/format_cells.py --spreadsheet "$ID" --range "C2:C100" \
  --number-format currency --align RIGHT

# Format percentage column
$HOME/.agents/.venv/bin/python $SKILL/scripts/format_cells.py --spreadsheet "$ID" --range "D2:D100" \
  --number-format percentage

# Conditional formatting for high values
$HOME/.agents/.venv/bin/python $SKILL/scripts/format_cells.py --spreadsheet "$ID" --range "C2:C100" \
  --conditional --rule greater_than --value 10000 --highlight-color "#00FF00"

# Conditional formatting for low values
$HOME/.agents/.venv/bin/python $SKILL/scripts/format_cells.py --spreadsheet "$ID" --range "C2:C100" \
  --conditional --rule less_than --value 1000 --highlight-color "#FF0000"
```
