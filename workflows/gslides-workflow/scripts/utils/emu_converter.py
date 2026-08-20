"""
Unit conversion utilities for Google Slides API.

Google Slides uses EMU (English Metric Units) for positioning and sizing.
Conversion factors:
- 1 inch = 914,400 EMU
- 1 point = 12,700 EMU
- 1 cm = 360,000 EMU
"""

from typing import Dict, Union


# Conversion constants
EMU_PER_INCH = 914400
EMU_PER_POINT = 12700
EMU_PER_CM = 360000


def inches_to_emu(inches: float) -> int:
    """
    Convert inches to EMU.

    Args:
        inches: Value in inches

    Returns:
        Value in EMU (integer)

    Example:
        >>> inches_to_emu(2.5)
        2286000
    """
    return int(inches * EMU_PER_INCH)


def emu_to_inches(emu: int) -> float:
    """
    Convert EMU to inches.

    Args:
        emu: Value in EMU

    Returns:
        Value in inches (float)
    """
    return round(emu / EMU_PER_INCH, 4)


def points_to_emu(points: float) -> int:
    """
    Convert points to EMU.

    Args:
        points: Value in points

    Returns:
        Value in EMU (integer)

    Example:
        >>> points_to_emu(12)
        152400
    """
    return int(points * EMU_PER_POINT)


def emu_to_points(emu: int) -> float:
    """
    Convert EMU to points.

    Args:
        emu: Value in EMU

    Returns:
        Value in points (float)
    """
    return round(emu / EMU_PER_POINT, 2)


def cm_to_emu(cm: float) -> int:
    """
    Convert centimeters to EMU.

    Args:
        cm: Value in centimeters

    Returns:
        Value in EMU (integer)
    """
    return int(cm * EMU_PER_CM)


def emu_to_cm(emu: int) -> float:
    """
    Convert EMU to centimeters.

    Args:
        emu: Value in EMU

    Returns:
        Value in centimeters (float)
    """
    return round(emu / EMU_PER_CM, 4)


def create_size(width: float, height: float, unit: str = 'inches') -> Dict:
    """
    Create Google Slides API size object.

    Args:
        width: Width value
        height: Height value
        unit: Unit of measurement ('inches', 'points', 'cm')

    Returns:
        Dict in Google Slides API size format

    Example:
        >>> create_size(5, 3, 'inches')
        {
            'width': {'magnitude': 4572000, 'unit': 'EMU'},
            'height': {'magnitude': 2743200, 'unit': 'EMU'}
        }
    """
    if unit == 'inches':
        width_emu = inches_to_emu(width)
        height_emu = inches_to_emu(height)
    elif unit == 'points':
        width_emu = points_to_emu(width)
        height_emu = points_to_emu(height)
    elif unit == 'cm':
        width_emu = cm_to_emu(width)
        height_emu = cm_to_emu(height)
    else:
        raise ValueError(f"Unsupported unit: {unit}. Use 'inches', 'points', or 'cm'")

    return {
        'width': {'magnitude': width_emu, 'unit': 'EMU'},
        'height': {'magnitude': height_emu, 'unit': 'EMU'}
    }


def create_transform(x: float, y: float, unit: str = 'inches',
                    scale_x: float = 1.0, scale_y: float = 1.0,
                    shear_x: float = 0.0, shear_y: float = 0.0) -> Dict:
    """
    Create Google Slides API transform object.

    Args:
        x: X position
        y: Y position
        unit: Unit of measurement ('inches', 'points', 'cm')
        scale_x: Horizontal scale (default: 1.0)
        scale_y: Vertical scale (default: 1.0)
        shear_x: Horizontal shear (default: 0.0)
        shear_y: Vertical shear (default: 0.0)

    Returns:
        Dict in Google Slides API transform format

    Example:
        >>> create_transform(2, 3, 'inches')
        {
            'scaleX': 1.0,
            'scaleY': 1.0,
            'shearX': 0.0,
            'shearY': 0.0,
            'translateX': 1828800,
            'translateY': 2743200,
            'unit': 'EMU'
        }
    """
    if unit == 'inches':
        x_emu = inches_to_emu(x)
        y_emu = inches_to_emu(y)
    elif unit == 'points':
        x_emu = points_to_emu(x)
        y_emu = points_to_emu(y)
    elif unit == 'cm':
        x_emu = cm_to_emu(x)
        y_emu = cm_to_emu(y)
    else:
        raise ValueError(f"Unsupported unit: {unit}")

    return {
        'scaleX': scale_x,
        'scaleY': scale_y,
        'shearX': shear_x,
        'shearY': shear_y,
        'translateX': x_emu,
        'translateY': y_emu,
        'unit': 'EMU'
    }


def create_element_properties(page_object_id: str, x: float, y: float,
                              width: float, height: float, unit: str = 'inches') -> Dict:
    """
    Create complete element properties for page elements.

    Args:
        page_object_id: ID of the slide (page) to place element on
        x: X position
        y: Y position
        width: Element width
        height: Element height
        unit: Unit of measurement ('inches', 'points', 'cm')

    Returns:
        Dict with pageObjectId, size, and transform

    Example:
        >>> create_element_properties('slide_1', 1, 2, 5, 3, 'inches')
        {
            'pageObjectId': 'slide_1',
            'size': {...},
            'transform': {...}
        }
    """
    return {
        'pageObjectId': page_object_id,
        'size': create_size(width, height, unit),
        'transform': create_transform(x, y, unit)
    }


def parse_position_string(position_str: str) -> Dict[str, float]:
    """
    Parse position string to dict.

    Args:
        position_str: String like "1,2,5,3" (x,y,width,height)

    Returns:
        Dict with x, y, width, height keys

    Example:
        >>> parse_position_string("1,2,5,3")
        {'x': 1.0, 'y': 2.0, 'width': 5.0, 'height': 3.0}
    """
    try:
        parts = [float(p.strip()) for p in position_str.split(',')]
        if len(parts) != 4:
            raise ValueError("Position must have 4 values: x,y,width,height")

        return {
            'x': parts[0],
            'y': parts[1],
            'width': parts[2],
            'height': parts[3]
        }
    except (ValueError, AttributeError) as e:
        raise ValueError(f"Invalid position string: {position_str}. Expected format: 'x,y,width,height'") from e


def calculate_center_position(container_width: float, container_height: float,
                              element_width: float, element_height: float,
                              unit: str = 'inches') -> Dict[str, float]:
    """
    Calculate position to center an element within a container.

    Args:
        container_width: Width of container
        container_height: Height of container
        element_width: Width of element to center
        element_height: Height of element to center
        unit: Unit of measurement

    Returns:
        Dict with 'x' and 'y' position for centered element
    """
    return {
        'x': (container_width - element_width) / 2,
        'y': (container_height - element_height) / 2,
        'unit': unit
    }


# Standard slide sizes
SLIDE_SIZES = {
    'standard': {'width': 10.0, 'height': 7.5, 'unit': 'inches'},  # 4:3
    'widescreen': {'width': 10.0, 'height': 5.625, 'unit': 'inches'},  # 16:9
    'custom': {'width': 11.0, 'height': 8.5, 'unit': 'inches'},  # Letter
}


def get_slide_size(size_name: str = 'widescreen') -> Dict:
    """
    Get standard slide size dimensions.

    Args:
        size_name: 'standard' (4:3), 'widescreen' (16:9), or 'custom'

    Returns:
        Dict with width, height, and unit
    """
    if size_name not in SLIDE_SIZES:
        raise ValueError(f"Unknown size: {size_name}. Use: {list(SLIDE_SIZES.keys())}")
    return SLIDE_SIZES[size_name].copy()


if __name__ == '__main__':
    # Test examples
    print("2.5 inches =", inches_to_emu(2.5), "EMU")
    print("12 points =", points_to_emu(12), "EMU")
    print("Size object:", create_size(5, 3, 'inches'))
    print("Transform:", create_transform(2, 3, 'inches'))
    print("Parse position:", parse_position_string("1,2,5,3"))
    print("Center position:", calculate_center_position(10, 7.5, 5, 3, 'inches'))
