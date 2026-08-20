# Brand Integration Reference

## Detecting Available Brand Skills

Check for brand skills before creating presentations:

```bash
# List available skills
ls /mnt/skills/user/ | grep -i brand

# Example output:
# acme-brand-guidelines
```

## Reading Brand Guidelines from Another Skill

If a brand skill exists, read its output format:

```bash
# Check what the brand skill provides
cat /mnt/skills/user/<your-brand>-brand-guidelines/SKILL.md
```

## Brand JSON Format

The `apply_brand.py` script accepts this JSON structure:

```json
{
  "brand": {
    "name": "Company Name",
    "colors": {
      "primary": "#HEX",
      "secondary": "#HEX",
      "accent": "#HEX",
      "text": "#HEX",
      "background": "#HEX"
    },
    "fonts": {
      "heading": "Font Family Name",
      "body": "Font Family Name"
    },
    "logo": {
      "url": "https://publicly-accessible-url.com/logo.png",
      "placement": "all_slides|first_slide|title_slides",
      "position": {
        "x": 9.0,
        "y": 0.25,
        "width": 0.75,
        "height": 0.75
      }
    }
  }
}
```

## Color Application

Colors are applied to:

| Color Key | Applied To |
|-----------|------------|
| `primary` | (reserved for future use) |
| `text` | All text elements |
| `background` | Slide backgrounds |
| `accent` | Non-text shapes |

## Font Application

| Font Key | Applied To |
|----------|------------|
| `heading` | Title placeholders, section headers |
| `body` | Body text, bullets |

## Logo Placement Options

- `all_slides` - Logo on every slide (default)
- `first_slide` - Logo only on slide 1
- `title_slides` - Logo on slides with TITLE layout

## Workflow Example

```bash
SKILL=/mnt/skills/user/google-slides
BRAND=/mnt/skills/user/<your-brand>-brand-guidelines

# 1. Check if brand skill exists
if [ -d "$BRAND" ]; then
    echo "Brand skill found"
fi

# 2. Create presentation
$HOME/.agents/.venv/bin/python $SKILL/scripts/create_presentation.py --title "My Deck" --output info.json

# 3. Get presentation ID
PRES_ID=$($HOME/.agents/.venv/bin/python -c "import json; print(json.load(open('info.json'))['presentation_id'])")

# 4. Add content
$HOME/.agents/.venv/bin/python $SKILL/scripts/add_content.py --presentation-id "$PRES_ID" --content-file slides.json

# 5. Apply brand
$HOME/.agents/.venv/bin/python $SKILL/scripts/apply_brand.py --presentation-id "$PRES_ID" --brand-file brand.json
```

## Supported Google Fonts

The font mapper normalizes these common fonts:

- Arial, Helvetica → Arial
- Times, Times New Roman → Times New Roman
- Inter, Roboto, Open Sans, Lato, Montserrat, Poppins → (as-is, Google Fonts)

For custom fonts, ensure they're available in Google Fonts.
