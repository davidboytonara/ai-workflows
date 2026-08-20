"""
Common Utilities for Google Sheets API

Provides helper functions for working with Google Sheets API:
- A1 notation <-> GridRange conversion
- Sheet ID lookups
- Cell formatting helpers
- Data validation
- Error handling

Example:
    >>> from scripts.common_utils import a1_to_grid_range, get_sheet_id
    >>> grid = a1_to_grid_range("Sheet1!A1:B10", spreadsheet)
    >>> sheet_id = get_sheet_id("Sheet1", spreadsheet)
"""

import re
from typing import Optional, Dict, Any, List, Tuple


class SheetsUtilityError(Exception):
    """Raised when a utility operation fails."""
    pass


def column_letter_to_index(column: str) -> int:
    """
    Convert column letter(s) to zero-based index.

    Args:
        column: Column letter(s) (e.g., 'A', 'Z', 'AA', 'ZZ')

    Returns:
        int: Zero-based column index

    Example:
        >>> column_letter_to_index('A')
        0
        >>> column_letter_to_index('Z')
        25
        >>> column_letter_to_index('AA')
        26
    """
    column = column.upper()
    index = 0
    for i, char in enumerate(reversed(column)):
        index += (ord(char) - ord('A') + 1) * (26 ** i)
    return index - 1


def column_index_to_letter(index: int) -> str:
    """
    Convert zero-based column index to letter(s).

    Args:
        index: Zero-based column index

    Returns:
        str: Column letter(s)

    Example:
        >>> column_index_to_letter(0)
        'A'
        >>> column_index_to_letter(25)
        'Z'
        >>> column_index_to_letter(26)
        'AA'
    """
    column = ""
    index += 1  # Make it 1-based for calculation
    while index > 0:
        index -= 1
        column = chr(index % 26 + ord('A')) + column
        index //= 26
    return column


def parse_a1_notation(a1_range: str) -> Dict[str, Any]:
    """
    Parse A1 notation into components.

    Args:
        a1_range: A1 notation string (e.g., "Sheet1!A1:B10", "A1:B10", "Sheet1!A1")

    Returns:
        dict: Parsed components with keys:
            - sheet_name: str or None
            - start_col: str (e.g., 'A')
            - start_row: int or None
            - end_col: str or None
            - end_row: int or None
            - is_range: bool

    Example:
        >>> parse_a1_notation("Sheet1!A1:B10")
        {'sheet_name': 'Sheet1', 'start_col': 'A', 'start_row': 1,
         'end_col': 'B', 'end_row': 10, 'is_range': True}
    """
    # Pattern: [SheetName!]A1[:B10]
    pattern = r"(?:(?P<sheet>[^!]+)!)?(?P<start_col>[A-Z]+)(?P<start_row>\d+)?(?::(?P<end_col>[A-Z]+)(?P<end_row>\d+)?)?"

    match = re.match(pattern, a1_range.strip(), re.IGNORECASE)
    if not match:
        raise SheetsUtilityError(f"Invalid A1 notation: {a1_range}")

    groups = match.groupdict()

    return {
        'sheet_name': groups.get('sheet'),
        'start_col': groups['start_col'].upper(),
        'start_row': int(groups['start_row']) if groups['start_row'] else None,
        'end_col': groups['end_col'].upper() if groups['end_col'] else None,
        'end_row': int(groups['end_row']) if groups['end_row'] else None,
        'is_range': groups['end_col'] is not None or groups['end_row'] is not None
    }


def a1_to_grid_range(
    a1_range: str,
    spreadsheet: Optional[Dict] = None,
    sheet_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Convert A1 notation to GridRange object.

    Args:
        a1_range: A1 notation (e.g., "Sheet1!A1:B10")
        spreadsheet: Spreadsheet metadata (for sheet name lookup)
        sheet_id: Optional explicit sheet ID

    Returns:
        dict: GridRange object compatible with Sheets API

    Raises:
        SheetsUtilityError: If conversion fails

    Example:
        >>> a1_to_grid_range("Sheet1!A1:B10", spreadsheet)
        {'sheetId': 0, 'startRowIndex': 0, 'endRowIndex': 10,
         'startColumnIndex': 0, 'endColumnIndex': 2}
    """
    parsed = parse_a1_notation(a1_range)

    grid_range = {}

    # Determine sheet ID
    if sheet_id is not None:
        grid_range['sheetId'] = sheet_id
    elif parsed['sheet_name'] and spreadsheet:
        grid_range['sheetId'] = get_sheet_id(parsed['sheet_name'], spreadsheet)
    elif spreadsheet:
        # Use first sheet if no sheet name specified
        grid_range['sheetId'] = spreadsheet['sheets'][0]['properties']['sheetId']

    # Convert columns
    grid_range['startColumnIndex'] = column_letter_to_index(parsed['start_col'])

    if parsed['end_col']:
        grid_range['endColumnIndex'] = column_letter_to_index(parsed['end_col']) + 1
    elif not parsed['is_range']:
        grid_range['endColumnIndex'] = grid_range['startColumnIndex'] + 1

    # Convert rows (A1 notation is 1-based, GridRange is 0-based)
    if parsed['start_row']:
        grid_range['startRowIndex'] = parsed['start_row'] - 1

    if parsed['end_row']:
        grid_range['endRowIndex'] = parsed['end_row']
    elif parsed['start_row'] and not parsed['is_range']:
        grid_range['endRowIndex'] = parsed['start_row']

    return grid_range


def parse_a1_range(a1_range: str) -> Dict[str, Any]:
    """
    Parse A1 notation and return grid range indices.

    This is a convenience wrapper around parse_a1_notation that returns
    0-based indices suitable for GridRange objects.

    Args:
        a1_range: A1 notation string (e.g., "Sheet1!A1:B10")

    Returns:
        dict: Parsed range with keys:
            - sheet: str or None (sheet name)
            - start_row: int (0-based row index)
            - end_row: int (0-based end row index, exclusive)
            - start_col: int (0-based column index)
            - end_col: int (0-based end column index, exclusive)

    Example:
        >>> parse_a1_range("Sheet1!A1:B10")
        {'sheet': 'Sheet1', 'start_row': 0, 'end_row': 10, 'start_col': 0, 'end_col': 2}
    """
    parsed = parse_a1_notation(a1_range)
    
    result = {
        'sheet': parsed.get('sheet_name'),
        'start_col': column_letter_to_index(parsed['start_col']),
    }
    
    # Convert 1-based rows to 0-based indices
    if parsed['start_row'] is not None:
        result['start_row'] = parsed['start_row'] - 1
    else:
        result['start_row'] = 0
    
    # End column (exclusive)
    if parsed['end_col']:
        result['end_col'] = column_letter_to_index(parsed['end_col']) + 1
    else:
        result['end_col'] = result['start_col'] + 1
    
    # End row (exclusive)
    if parsed['end_row'] is not None:
        result['end_row'] = parsed['end_row']
    elif parsed['start_row'] is not None:
        result['end_row'] = parsed['start_row']  # Already exclusive (start_row + 1 - 1 + 1)
    else:
        result['end_row'] = 1000  # Default for unbounded
    
    return result


def grid_range_to_a1(
    grid_range: Dict[str, Any],
    spreadsheet: Optional[Dict] = None,
    include_sheet_name: bool = True
) -> str:
    """
    Convert GridRange object to A1 notation.

    Args:
        grid_range: GridRange object
        spreadsheet: Spreadsheet metadata (for sheet name lookup)
        include_sheet_name: Whether to include sheet name in output

    Returns:
        str: A1 notation

    Example:
        >>> grid_range_to_a1({'sheetId': 0, 'startRowIndex': 0, 'endRowIndex': 10,
        ...                    'startColumnIndex': 0, 'endColumnIndex': 2}, spreadsheet)
        'Sheet1!A1:B10'
    """
    parts = []

    # Add sheet name if requested
    if include_sheet_name and 'sheetId' in grid_range and spreadsheet:
        sheet_name = get_sheet_name(grid_range['sheetId'], spreadsheet)
        if sheet_name:
            # Escape sheet name if it contains special characters
            if any(c in sheet_name for c in [' ', '!', "'"]):
                sheet_name = f"'{sheet_name}'"
            parts.append(f"{sheet_name}!")

    # Start column (required)
    start_col = column_index_to_letter(grid_range.get('startColumnIndex', 0))

    # Start row (optional, 0-based to 1-based)
    start_row = grid_range.get('startRowIndex')
    if start_row is not None:
        start_cell = f"{start_col}{start_row + 1}"
    else:
        start_cell = start_col

    parts.append(start_cell)

    # End cell (if range)
    end_col_idx = grid_range.get('endColumnIndex')
    end_row_idx = grid_range.get('endRowIndex')

    if end_col_idx or end_row_idx:
        end_col = column_index_to_letter(end_col_idx - 1) if end_col_idx else start_col
        end_row = end_row_idx if end_row_idx else (start_row + 1 if start_row is not None else '')

        if end_row:
            end_cell = f"{end_col}{end_row}"
        else:
            end_cell = end_col

        # Only add range if different from start
        if end_cell != start_cell:
            parts.append(f":{end_cell}")

    return ''.join(parts)


def get_sheet_id(sheet_name: str, spreadsheet: Dict) -> int:
    """
    Get sheet ID from sheet name.

    Args:
        sheet_name: Name of the sheet
        spreadsheet: Spreadsheet metadata

    Returns:
        int: Sheet ID

    Raises:
        SheetsUtilityError: If sheet not found

    Example:
        >>> get_sheet_id("Sheet1", spreadsheet)
        0
    """
    for sheet in spreadsheet.get('sheets', []):
        if sheet['properties']['title'] == sheet_name:
            return sheet['properties']['sheetId']

    raise SheetsUtilityError(f"Sheet not found: {sheet_name}")


def get_sheet_name(sheet_id: int, spreadsheet: Dict) -> Optional[str]:
    """
    Get sheet name from sheet ID.

    Args:
        sheet_id: Sheet ID
        spreadsheet: Spreadsheet metadata

    Returns:
        str: Sheet name, or None if not found

    Example:
        >>> get_sheet_name(0, spreadsheet)
        'Sheet1'
    """
    for sheet in spreadsheet.get('sheets', []):
        if sheet['properties']['sheetId'] == sheet_id:
            return sheet['properties']['title']

    return None


def validate_spreadsheet_id(spreadsheet_id: str) -> bool:
    """
    Validate spreadsheet ID format.

    Args:
        spreadsheet_id: Spreadsheet ID to validate

    Returns:
        bool: True if valid format

    Example:
        >>> validate_spreadsheet_id("1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms")
        True
    """
    # Google Sheets IDs are typically 44 characters alphanumeric with - and _
    pattern = r'^[a-zA-Z0-9_-]{20,}$'
    return bool(re.match(pattern, spreadsheet_id))


def extract_spreadsheet_id_from_url(url: str) -> Optional[str]:
    """
    Extract spreadsheet ID from Google Sheets URL.

    Args:
        url: Google Sheets URL

    Returns:
        str: Spreadsheet ID, or None if not found

    Example:
        >>> extract_spreadsheet_id_from_url(
        ...     "https://docs.google.com/spreadsheets/d/1ABC.../edit"
        ... )
        '1ABC...'
    """
    patterns = [
        r'/spreadsheets/d/([a-zA-Z0-9_-]+)',
        r'[?&]id=([a-zA-Z0-9_-]+)'
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def validate_spreadsheet_title(title: str) -> bool:
    """
    Validate spreadsheet title.

    Args:
        title: Spreadsheet title to validate

    Returns:
        bool: True if valid

    Raises:
        ValueError: If title is invalid

    Note:
        Google Sheets titles must be:
        - Non-empty
        - Maximum 255 characters
    """
    if not title or not title.strip():
        raise ValueError("Spreadsheet title cannot be empty")

    if len(title) > 255:
        raise ValueError(f"Spreadsheet title too long ({len(title)} characters). Maximum is 255 characters")

    return True


def validate_sheet_name(sheet_name: str) -> bool:
    """
    Validate sheet name.

    Args:
        sheet_name: Sheet name to validate

    Returns:
        bool: True if valid

    Raises:
        ValueError: If sheet name is invalid

    Note:
        Google Sheets sheet names cannot contain:
        - Colon (:)
        - Asterisk (*)
        - Question mark (?)
        - Forward slash (/)
        - Backslash (\\)
        - Square brackets ([ ])
    """
    if not sheet_name or not sheet_name.strip():
        raise ValueError("Sheet name cannot be empty")

    invalid_chars = [':', '*', '?', '/', '\\', '[', ']']
    for char in invalid_chars:
        if char in sheet_name:
            raise ValueError(
                f"Sheet name '{sheet_name}' contains invalid character '{char}'. "
                f"Sheet names cannot contain: {', '.join(invalid_chars)}"
            )

    if len(sheet_name) > 100:
        raise ValueError(f"Sheet name too long ({len(sheet_name)} characters). Maximum is 100 characters")

    return True


def validate_a1_notation(a1_notation: str) -> bool:
    """
    Validate A1 notation format.

    Args:
        a1_notation: A1 notation string to validate

    Returns:
        bool: True if valid

    Raises:
        ValueError: If A1 notation is invalid

    Example:
        >>> validate_a1_notation("Sheet1!A1:B10")
        True
        >>> validate_a1_notation("A1:B10")
        True
    """
    if not a1_notation or not a1_notation.strip():
        raise ValueError("A1 notation cannot be empty")

    # Pattern supports: [SheetName!]A1[:B10] or [SheetName!]A:B or [SheetName!]1:10
    pattern = r"^(?:(?:[^!]+)!)?(?:[A-Z]+\d+(?::[A-Z]+\d+)?|[A-Z]+:[A-Z]+|\d+:\d+)$"

    if not re.match(pattern, a1_notation):
        raise ValueError(
            f"Invalid A1 notation: '{a1_notation}'. "
            f"Valid formats: 'A1', 'A1:B10', 'Sheet1!A1:B10', 'A:B', '1:10'"
        )

    return True


def rgb_to_color_dict(r: int, g: int, b: int, alpha: float = 1.0) -> Dict[str, float]:
    """
    Convert RGB values (0-255) to Google Sheets Color object (0.0-1.0).

    Args:
        r: Red (0-255)
        g: Green (0-255)
        b: Blue (0-255)
        alpha: Alpha transparency (0.0-1.0)

    Returns:
        dict: Color object for Sheets API

    Example:
        >>> rgb_to_color_dict(255, 0, 0)
        {'red': 1.0, 'green': 0.0, 'blue': 0.0, 'alpha': 1.0}
    """
    return {
        'red': r / 255.0,
        'green': g / 255.0,
        'blue': b / 255.0,
        'alpha': alpha
    }


def hex_to_color_dict(hex_color: str) -> Dict[str, float]:
    """
    Convert hex color to Google Sheets Color object.

    Args:
        hex_color: Hex color string (e.g., '#FF0000' or 'FF0000')

    Returns:
        dict: Color object for Sheets API

    Example:
        >>> hex_to_color_dict("#FF0000")
        {'red': 1.0, 'green': 0.0, 'blue': 0.0, 'alpha': 1.0}
    """
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        raise SheetsUtilityError(f"Invalid hex color: {hex_color} (must be 6 characters)")

    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    return rgb_to_color_dict(r, g, b)


def format_cell_value(value: Any, value_type: str = 'auto') -> Dict[str, Any]:
    """
    Format a value for Google Sheets API.

    Args:
        value: The value to format
        value_type: Type of value ('auto', 'string', 'number', 'boolean', 'formula')

    Returns:
        dict: userEnteredValue object for Sheets API

    Example:
        >>> format_cell_value(42, 'number')
        {'numberValue': 42}
        >>> format_cell_value('=SUM(A1:A10)', 'formula')
        {'formulaValue': '=SUM(A1:A10)'}
    """
    if value_type == 'auto':
        # Auto-detect type
        if isinstance(value, bool):
            value_type = 'boolean'
        elif isinstance(value, (int, float)):
            value_type = 'number'
        elif isinstance(value, str) and value.startswith('='):
            value_type = 'formula'
        else:
            value_type = 'string'

    if value_type == 'string':
        return {'stringValue': str(value)}
    elif value_type == 'number':
        return {'numberValue': float(value)}
    elif value_type == 'boolean':
        return {'boolValue': bool(value)}
    elif value_type == 'formula':
        return {'formulaValue': str(value)}
    else:
        raise SheetsUtilityError(f"Unknown value type: {value_type}")


def handle_api_error(error: Exception, context: str = "API operation") -> str:
    """
    Format API error into user-friendly message.

    Args:
        error: The exception raised
        context: Description of what was being attempted

    Returns:
        str: Formatted error message

    Example:
        >>> try:
        ...     # API call
        ... except Exception as e:
        ...     print(handle_api_error(e, "Creating spreadsheet"))
    """
    from googleapiclient.errors import HttpError

    if isinstance(error, HttpError):
        status = error.resp.status
        error_details = error.error_details if hasattr(error, 'error_details') else []

        messages = [f"[✗] {context} failed (HTTP {status})"]

        if status == 400:
            messages.append("Bad Request - Check your parameters")
        elif status == 401:
            messages.append("Unauthorized - Authentication failed")
        elif status == 403:
            messages.append("Forbidden - Check permissions or API enabled")
        elif status == 404:
            messages.append("Not Found - Spreadsheet or sheet doesn't exist")
        elif status == 429:
            messages.append("Rate Limit Exceeded - Too many requests")
        elif status >= 500:
            messages.append("Server Error - Google API issue, try again later")

        if error_details:
            for detail in error_details:
                if 'message' in detail:
                    messages.append(f"  • {detail['message']}")

        return "\n".join(messages)
    else:
        return f"[✗] {context} failed: {str(error)}"


def batch_requests(requests: List[Dict], batch_size: int = 100) -> List[List[Dict]]:
    """
    Split requests into batches for batchUpdate.

    Args:
        requests: List of request objects
        batch_size: Maximum requests per batch (default: 100)

    Returns:
        list: List of batches

    Example:
        >>> requests = [{'request1': {}}, {'request2': {}}, ...]
        >>> batches = batch_requests(requests, batch_size=50)
    """
    return [requests[i:i + batch_size] for i in range(0, len(requests), batch_size)]


if __name__ == "__main__":
    """
    Test utility functions.

    Usage:
        python scripts/common_utils.py
    """
    print("Testing Common Utilities...")
    print("-" * 60)

    # Test column conversions
    print("\n[Column Conversions]")
    assert column_letter_to_index('A') == 0
    assert column_letter_to_index('Z') == 25
    assert column_letter_to_index('AA') == 26
    assert column_index_to_letter(0) == 'A'
    assert column_index_to_letter(25) == 'Z'
    assert column_index_to_letter(26) == 'AA'
    print("✓ Column conversions working")

    # Test A1 parsing
    print("\n[A1 Notation Parsing]")
    parsed = parse_a1_notation("Sheet1!A1:B10")
    assert parsed['sheet_name'] == 'Sheet1'
    assert parsed['start_col'] == 'A'
    assert parsed['start_row'] == 1
    assert parsed['end_col'] == 'B'
    assert parsed['end_row'] == 10
    print("✓ A1 notation parsing working")

    # Test color conversions
    print("\n[Color Conversions]")
    color = rgb_to_color_dict(255, 0, 0)
    assert color['red'] == 1.0
    assert color['green'] == 0.0
    assert color['blue'] == 0.0

    color = hex_to_color_dict("#FF0000")
    assert color['red'] == 1.0
    print("✓ Color conversions working")

    # Test spreadsheet ID extraction
    print("\n[Spreadsheet ID Extraction]")
    url = "https://docs.google.com/spreadsheets/d/1ABC123XYZ/edit"
    sheet_id = extract_spreadsheet_id_from_url(url)
    assert sheet_id == "1ABC123XYZ"
    print("✓ Spreadsheet ID extraction working")

    print("\n" + "-" * 60)
    print("[✓] All utility tests passed!")
    print("-" * 60)
