"""
Font mapping and validation utilities for Google Slides API.

Maps common font names to Google Slides API format and validates font availability.
"""

from typing import Dict, Optional, List, Union, Any


# Common font mappings
# Google Slides supports Google Fonts and fonts in the template
GOOGLE_FONTS = {
    # Sans-serif fonts
    'arial': 'Arial',
    'helvetica': 'Arial',  # Map to Arial (similar)
    'roboto': 'Roboto',
    'open sans': 'Open Sans',
    'lato': 'Lato',
    'montserrat': 'Montserrat',
    'source sans pro': 'Source Sans Pro',
    'raleway': 'Raleway',
    'pt sans': 'PT Sans',
    'nunito': 'Nunito',
    'inter': 'Inter',
    'work sans': 'Work Sans',
    'poppins': 'Poppins',

    # Serif fonts
    'times new roman': 'Times New Roman',
    'times': 'Times New Roman',
    'georgia': 'Georgia',
    'garamond': 'Garamond',
    'palatino': 'Palatino',
    'merriweather': 'Merriweather',
    'pt serif': 'PT Serif',
    'lora': 'Lora',
    'playfair display': 'Playfair Display',

    # Monospace fonts
    'courier new': 'Courier New',
    'courier': 'Courier New',
    'consolas': 'Consolas',
    'monaco': 'Monaco',
    'source code pro': 'Source Code Pro',
    'roboto mono': 'Roboto Mono',
    'inconsolata': 'Inconsolata',

    # Display fonts
    'impact': 'Impact',
    'comic sans ms': 'Comic Sans MS',
    'comic sans': 'Comic Sans MS',
}


# Font weight mappings
FONT_WEIGHTS = {
    'thin': 100,
    'extralight': 200,
    'light': 300,
    'regular': 400,
    'normal': 400,
    'medium': 500,
    'semibold': 600,
    'bold': 700,
    'extrabold': 800,
    'black': 900,
}


def normalize_font_name(font_name: str) -> str:
    """
    Normalize font name to Google Slides API format.

    Args:
        font_name: Font name in any format

    Returns:
        Normalized font name

    Example:
        >>> normalize_font_name('inter')
        'Inter'
        >>> normalize_font_name('OPEN SANS')
        'Open Sans'
    """
    font_lower = font_name.lower().strip()

    # Check if it's in the mapping
    if font_lower in GOOGLE_FONTS:
        return GOOGLE_FONTS[font_lower]

    # Otherwise, return title case
    return font_name.strip().title()


def parse_font_family(font_string: str) -> Dict[str, str]:
    """
    Parse font family string that may include weight.

    Args:
        font_string: Font string like "Inter Bold" or "Open Sans SemiBold"

    Returns:
        Dict with 'family' and 'weight' keys

    Example:
        >>> parse_font_family("Inter Bold")
        {'family': 'Inter', 'weight': 'Bold'}
    """
    parts = font_string.strip().split()

    # Check if last part is a weight
    if len(parts) > 1 and parts[-1].lower() in FONT_WEIGHTS:
        weight = parts[-1]
        family = ' '.join(parts[:-1])
    else:
        weight = 'Regular'
        family = font_string

    return {
        'family': normalize_font_name(family),
        'weight': weight.capitalize()
    }


def is_bold_weight(weight: Union[str, int, float]) -> bool:
    """
    Check if font weight should be considered bold.

    Args:
        weight: Font weight name or number

    Returns:
        True if weight >= 700
    """
    if isinstance(weight, (int, float)):
        return weight >= 700

    weight_lower = str(weight).lower()
    if weight_lower in FONT_WEIGHTS:
        return FONT_WEIGHTS[weight_lower] >= 700

    # Default check
    return 'bold' in weight_lower or 'black' in weight_lower


def create_text_style(font_family: str, font_size: float, color: Dict[str, float],
                     bold: bool = False, italic: bool = False,
                     underline: bool = False) -> Dict[str, Any]:
    """
    Create Google Slides API text style object.

    Args:
        font_family: Font family name
        font_size: Font size in points
        color: Color in normalized RGB format
        bold: Apply bold
        italic: Apply italic
        underline: Apply underline

    Returns:
        Dict in Google Slides API textStyle format

    Example:
        >>> create_text_style('Inter', 16, {'red': 0.0, 'green': 0.0, 'blue': 0.0})
        {
            'fontFamily': 'Inter',
            'fontSize': {'magnitude': 16, 'unit': 'PT'},
            'foregroundColor': {...},
            'bold': False,
            'italic': False,
            'underline': False
        }
    """
    return {
        'fontFamily': normalize_font_name(font_family),
        'fontSize': {
            'magnitude': font_size,
            'unit': 'PT'
        },
        'foregroundColor': {
            'opaqueColor': {
                'rgbColor': color
            }
        },
        'bold': bold,
        'italic': italic,
        'underline': underline
    }


def get_font_size_for_type(text_type: str) -> float:
    """
    Get recommended font size for text type.

    Args:
        text_type: 'title', 'heading', 'subheading', 'body', 'caption'

    Returns:
        Font size in points
    """
    sizes = {
        'title': 36.0,
        'heading': 24.0,
        'subheading': 18.0,
        'body': 16.0,
        'caption': 12.0,
    }

    return sizes.get(text_type.lower(), 16.0)


def validate_font_size(font_size: float, min_size: float = 1.0, max_size: float = 400.0) -> bool:
    """
    Validate font size is within acceptable range.

    Args:
        font_size: Font size to validate
        min_size: Minimum acceptable size (default: 1.0)
        max_size: Maximum acceptable size (default: 400.0)

    Returns:
        True if valid
    """
    return min_size <= font_size <= max_size


def suggest_font_pairing(primary_font: str) -> Dict[str, str]:
    """
    Suggest font pairings for a given primary font.

    Args:
        primary_font: Primary font name

    Returns:
        Dict with 'heading' and 'body' font suggestions
    """
    # Common pairings
    pairings = {
        'Inter': {'heading': 'Inter', 'body': 'Inter'},
        'Roboto': {'heading': 'Roboto', 'body': 'Roboto'},
        'Montserrat': {'heading': 'Montserrat', 'body': 'Open Sans'},
        'Playfair Display': {'heading': 'Playfair Display', 'body': 'Source Sans Pro'},
        'Merriweather': {'heading': 'Merriweather', 'body': 'Open Sans'},
        'Lora': {'heading': 'Lora', 'body': 'Lato'},
        'Poppins': {'heading': 'Poppins', 'body': 'Roboto'},
    }

    normalized = normalize_font_name(primary_font)
    return pairings.get(normalized, {'heading': normalized, 'body': normalized})


def get_web_safe_fonts() -> List[str]:
    """
    Get list of web-safe fonts that work across all platforms.

    Returns:
        List of font names
    """
    return [
        'Arial',
        'Times New Roman',
        'Georgia',
        'Courier New',
        'Verdana',
        'Trebuchet MS',
        'Comic Sans MS',
        'Impact',
    ]


if __name__ == '__main__':
    # Test examples
    print("Normalize:", normalize_font_name('inter'))
    print("Parse:", parse_font_family("Inter Bold"))
    print("Is bold:", is_bold_weight("Bold"))
    print("Font size for body:", get_font_size_for_type('body'))
    print("Pairing:", suggest_font_pairing('Montserrat'))
    print("Web safe fonts:", get_web_safe_fonts())
