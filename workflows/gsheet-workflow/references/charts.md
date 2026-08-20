# Charts Reference

## Chart Types

| Type | Description | Best For |
|------|-------------|----------|
| `column` | Vertical bars | Comparing categories |
| `bar` | Horizontal bars | Comparing many categories |
| `line` | Connected points | Trends over time |
| `area` | Filled line chart | Cumulative trends |
| `pie` | Circular segments | Part-to-whole relationships |
| `scatter` | Points on X-Y plane | Correlations |
| `combo` | Mixed chart types | Complex comparisons |

## Basic Usage

```bash
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_charts.py --spreadsheet ID --sheet "Charts" \
  --type column --data-range "Data!A1:B12" --title "Monthly Sales"
```

## Options

```bash
--spreadsheet ID      # Spreadsheet ID (required)
--sheet NAME          # Destination sheet for chart (required)
--type TYPE           # Chart type (required)
--data-range RANGE    # Data range in A1 notation (required)
--title TEXT          # Chart title
--x-axis TEXT         # X-axis label
--y-axis TEXT         # Y-axis label
--legend POSITION     # Legend position
--width N             # Width in pixels (default: 600)
--height N            # Height in pixels (default: 400)
--stacked             # Stack series (bar/column/area)
```

### Legend Positions
- `BOTTOM_LEGEND` (default)
- `TOP_LEGEND`
- `LEFT_LEGEND`
- `RIGHT_LEGEND`
- `NO_LEGEND`

## Examples

### Column Chart
```bash
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_charts.py --spreadsheet ID --sheet "Dashboard" \
  --type column --data-range "Data!A1:B12" --title "Monthly Revenue" \
  --y-axis "Revenue ($)"
```

### Line Chart with Axis Labels
```bash
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_charts.py --spreadsheet ID --sheet "Trends" \
  --type line --data-range "Data!A1:D12" --title "Quarterly Trends" \
  --x-axis "Quarter" --y-axis "Value" --legend RIGHT_LEGEND
```

### Stacked Bar Chart
```bash
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_charts.py --spreadsheet ID --sheet "Analysis" \
  --type bar --data-range "Data!A1:D10" --title "Category Breakdown" \
  --stacked
```

### Pie Chart
```bash
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_charts.py --spreadsheet ID --sheet "Summary" \
  --type pie --data-range "Data!A1:B5" --title "Market Share" \
  --legend RIGHT_LEGEND
```

### Large Chart
```bash
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_charts.py --spreadsheet ID --sheet "Dashboard" \
  --type area --data-range "Data!A1:C24" --title "Full Year Overview" \
  --width 800 --height 500
```

## Managing Charts

### List All Charts
```bash
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_charts.py --spreadsheet ID --list
```

### Delete a Chart
```bash
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_charts.py --spreadsheet ID --delete --chart-id 12345
```

## Data Range Tips

1. **Include headers** - First row should contain labels
2. **First column = categories** - Used for X-axis/labels
3. **Subsequent columns = series** - Each column becomes a data series
4. **Contiguous data** - No gaps in the range

### Example Data Layout

For a chart showing revenue and profit by month:

| Month | Revenue | Profit |
|-------|---------|--------|
| Jan   | 50000   | 15000  |
| Feb   | 55000   | 18000  |
| Mar   | 48000   | 12000  |

Range: `Data!A1:C4`

## Complete Workflow

```bash
SKILL=/mnt/skills/user/google-sheets

# 1. Create spreadsheet
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_spreadsheet.py --title "Sales Dashboard" \
  --sheets "Data,Charts" --output info.json
ID=$($HOME/.agents/.venv/bin/python -c "import json; print(json.load(open('info.json'))['spreadsheetId'])")

# 2. Add data
$HOME/.agents/.venv/bin/python $SKILL/scripts/update_spreadsheet.py --spreadsheet "$ID" \
  --range "Data!A1" --values '[
    ["Month", "Revenue", "Costs", "Profit"],
    ["Jan", 50000, 35000, 15000],
    ["Feb", 55000, 37000, 18000],
    ["Mar", 48000, 36000, 12000],
    ["Apr", 62000, 40000, 22000]
  ]'

# 3. Create revenue chart
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_charts.py --spreadsheet "$ID" --sheet "Charts" \
  --type column --data-range "Data!A1:B5" --title "Monthly Revenue"

# 4. Create comparison chart
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_charts.py --spreadsheet "$ID" --sheet "Charts" \
  --type line --data-range "Data!A1:D5" --title "Revenue vs Costs vs Profit" \
  --legend BOTTOM_LEGEND
```
