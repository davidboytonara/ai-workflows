"""
Color conversion utilities for Google Slides API.

Converts between different color formats:
- Hex (#RRGGBB) to RGB (0.0-1.0)
- RGB (0-255) to RGB (0.0-1.0)
- Named colors to hex
"""

import re
from typing import Dict, Union, Tuple


# Common named colors
NAMED_COLORS = {
    'black': '#000000',
    'white': '#FFFFFF',
    'red': '#FF0000',
    'green': '#00FF00',
    'blue': '#0000FF',
    'yellow': '#FFFF00',
    'cyan': '#00FFFF',
    'magenta': '#FF00FF',
    'gray': '#808080',
    'grey': '#808080',
    'darkgray': '#A9A9A9',
    'darkgrey': '#A9A9A9',
    'lightgray': '#D3D3D3',
    'lightgrey': '#D3D3D3',
}


def hex_to_rgb_normalized(hex_color: str) -> Dict[str, float]:
    """
    Convert hex color to Google Slides API RGB format (0.0 to 1.0).

    Args:
        hex_color: Hex color string (e.g., '#0066CC' or '0066CC')

    Returns:
        Dict with 'red', 'green', 'blue' keys (0.0 to 1.0)

    Examples:
        >>> hex_to_rgb_normalized('#0066CC')
        {'red': 0.0, 'green': 0.4, 'blue': 0.8}
    """
    # Remove '#' prefix if present
    hex_color = hex_color.lstrip('#')

    # Validate hex format
    if not re.match(r'^[0-9A-Fa-f]{6}$', hex_color):
        raise ValueError(f"Invalid hex color: {hex_color}")

    # Convert to RGB (0-255)
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # Normalize to 0.0-1.0
    return {
        'red': round(r / 255.0, 4),
        'green': round(g / 255.0, 4),
        'blue': round(b / 255.0, 4)
    }


def rgb_to_normalized(r: int, g: int, b: int) -> Dict[str, float]:
    """
    Convert RGB (0-255) to Google Slides API format (0.0-1.0).

    Args:
        r: Red value (0-255)
        g: Green value (0-255)
        b: Blue value (0-255)

    Returns:
        Dict with 'red', 'green', 'blue' keys (0.0 to 1.0)
    """
    if not all(0 <= val <= 255 for val in [r, g, b]):
        raise ValueError("RGB values must be between 0 and 255")

    return {
        'red': round(r / 255.0, 4),
        'green': round(g / 255.0, 4),
        'blue': round(b / 255.0, 4)
    }


def named_color_to_rgb(color_name: str) -> Dict[str, float]:
    """
    Convert named color to RGB format.

    Args:
        color_name: Color name (e.g., 'red', 'blue')

    Returns:
        Dict with 'red', 'green', 'blue' keys (0.0 to 1.0)
    """
    color_name = color_name.lower()
    if color_name not in NAMED_COLORS:
        raise ValueError(f"Unknown color name: {color_name}")

    hex_color = NAMED_COLORS[color_name]
    return hex_to_rgb_normalized(hex_color)


def to_slides_color(color: Union[str, Tuple[int, int, int], Dict]) -> Dict[str, float]:
    """
    Universal color converter - accepts multiple formats.

    Args:
        color: Can be:
            - Hex string: '#0066CC'
            - Named color: 'red'
            - RGB tuple: (0, 102, 204)
            - RGB dict: {'red': 0.0, 'green': 0.4, 'blue': 0.8}

    Returns:
        Dict with 'red', 'green', 'blue' keys (0.0 to 1.0)
    """
    if isinstance(color, str):
        # Check if it's a named color
        if color.lower() in NAMED_COLORS:
            return named_color_to_rgb(color)
        # Otherwise treat as hex
        return hex_to_rgb_normalized(color)

    elif isinstance(color, (tuple, list)):
        if len(color) != 3:
            raise ValueError("RGB tuple must have 3 values")
        return rgb_to_normalized(*color)

    elif isinstance(color, dict):
        # Validate and return if already in correct format
        required_keys = {'red', 'green', 'blue'}
        if not required_keys.issubset(color.keys()):
            raise ValueError(f"RGB dict must have keys: {required_keys}")

        # Check if values are already normalized (0.0-1.0)
        if all(0.0 <= color[k] <= 1.0 for k in required_keys):
            return {k: round(color[k], 4) for k in required_keys}
        # If values are 0-255, normalize them
        elif all(0 <= color[k] <= 255 for k in required_keys):
            return rgb_to_normalized(int(color['red']), int(color['green']), int(color['blue']))
        else:
            raise ValueError("RGB dict values must be 0.0-1.0 or 0-255")

    else:
        raise TypeError(f"Unsupported color format: {type(color)}")


def to_slides_opaque_color(color: Union[str, Tuple[int, int, int], Dict]) -> Dict:
    """
    Convert color to Google Slides API opaqueColor format.

    Args:
        color: Any supported color format

    Returns:
        Dict in Google Slides API opaqueColor format

    Example:
        >>> to_slides_opaque_color('#0066CC')
        {
            'opaqueColor': {
                'rgbColor': {
                    'red': 0.0,
                    'green': 0.4,
                    'blue': 0.8
                }
            }
        }
    """
    rgb = to_slides_color(color)
    return {
        'opaqueColor': {
            'rgbColor': rgb
        }
    }


def rgb_to_hex(rgb_dict: Dict[str, float]) -> str:
    """
    Convert normalized RGB (0.0-1.0) to hex color.

    Args:
        rgb_dict: Dict with 'red', 'green', 'blue' keys (0.0 to 1.0)

    Returns:
        Hex color string (e.g., '#0066CC')
    """
    r = int(rgb_dict['red'] * 255)
    g = int(rgb_dict['green'] * 255)
    b = int(rgb_dict['blue'] * 255)
    return f'#{r:02X}{g:02X}{b:02X}'


def calculate_contrast_ratio(color1: Dict[str, float], color2: Dict[str, float]) -> float:
    """
    Calculate WCAG contrast ratio between two colors.

    Args:
        color1: First color (normalized RGB)
        color2: Second color (normalized RGB)

    Returns:
        Contrast ratio (1.0 to 21.0)
    """
    def relative_luminance(rgb):
        """Calculate relative luminance."""
        def adjust(val):
            if val <= 0.03928:
                return val / 12.92
            return ((val + 0.055) / 1.055) ** 2.4

        r = adjust(rgb['red'])
        g = adjust(rgb['green'])
        b = adjust(rgb['blue'])
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    l1 = relative_luminance(color1)
    l2 = relative_luminance(color2)

    lighter = max(l1, l2)
    darker = min(l1, l2)

    return (lighter + 0.05) / (darker + 0.05)


def validate_contrast(foreground: Union[str, Dict], background: Union[str, Dict],
                     level: str = 'AA') -> bool:
    """
    Validate color contrast meets WCAG standards.

    Args:
        foreground: Foreground color (any format)
        background: Background color (any format)
        level: WCAG level ('AA' or 'AAA')

    Returns:
        True if contrast meets standard
    """
    fg_rgb = to_slides_color(foreground)
    bg_rgb = to_slides_color(background)

    ratio = calculate_contrast_ratio(fg_rgb, bg_rgb)

    # WCAG 2.1 standards
    if level == 'AA':
        return ratio >= 4.5  # Normal text
    elif level == 'AAA':
        return ratio >= 7.0  # Normal text
    else:
        raise ValueError("Level must be 'AA' or 'AAA'")


if __name__ == '__main__':
    # Test examples
    print("Hex to RGB:", hex_to_rgb_normalized('#0066CC'))
    print("Named color:", named_color_to_rgb('red'))
    print("RGB tuple:", to_slides_color((0, 102, 204)))
    print("Opaque color:", to_slides_opaque_color('#0066CC'))
    print("Contrast ratio:", calculate_contrast_ratio(
        hex_to_rgb_normalized('#000000'),
        hex_to_rgb_normalized('#FFFFFF')
    ))
