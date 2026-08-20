#!/usr/bin/env python3
"""
Google Sheets - Cell Formatting Operations

Provides functionality to format cells (colors, fonts, borders, alignment, number formats).
"""

import sys
import json
import argparse
import warnings
from pathlib import Path
from typing import Dict, Any, Optional, List

warnings.filterwarnings('ignore', message='.*importlib.metadata.*')
warnings.filterwarnings('ignore', category=FutureWarning, module='google.api_core')

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.auth_helper import build_sheets_service
from scripts.utils.rate_limiter import get_global_limiter
from scripts.utils.common_utils import (
    parse_a1_range,
    get_sheet_id,
    handle_api_error
)

limiter = get_global_limiter(verbose=True)


def hex_to_rgb(hex_color: str) -> Dict[str, float]:
    """Convert hex color to Google Sheets RGB format (0.0-1.0)."""
    hex_color = hex_color.lstrip('#')
    return {
        'red': int(hex_color[0:2], 16) / 255.0,
        'green': int(hex_color[2:4], 16) / 255.0,
        'blue': int(hex_color[4:6], 16) / 255.0
    }


def format_cells(
    spreadsheet_id: str,
    range_notation: str,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    font_size: Optional[int] = None,
    font_family: Optional[str] = None,
    text_color: Optional[str] = None,
    bg_color: Optional[str] = None,
    align: Optional[str] = None,
    valign: Optional[str] = None,
    number_format: Optional[str] = None,
    wrap: Optional[str] = None,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Apply formatting to a cell range.

    Args:
        spreadsheet_id: Spreadsheet ID
        range_notation: A1 notation range (e.g., "Sheet1!A1:B10")
        bold: Make text bold
        italic: Make text italic
        underline: Underline text
        font_size: Font size in points
        font_family: Font family name
        text_color: Text color as hex (e.g., "#FF0000")
        bg_color: Background color as hex
        align: Horizontal alignment (LEFT, CENTER, RIGHT)
        valign: Vertical alignment (TOP, MIDDLE, BOTTOM)
        number_format: Number format pattern
        wrap: Text wrap strategy (WRAP, CLIP, OVERFLOW_CELL)

    Returns:
        dict: API response
    """
    try:
        service = build_sheets_service(account=account)
        
        # Get spreadsheet to find sheet ID
        spreadsheet = limiter.execute_with_backoff(
            lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute(),
            "Get spreadsheet info"
        )
        
        # Parse range to get sheet name and grid range
        range_info = parse_a1_range(range_notation)
        sheet_name = range_info.get('sheet', 'Sheet1')
        sheet_id = get_sheet_id(sheet_name, spreadsheet)
        
        # Build cell format
        cell_format = {}
        fields = []
        
        # Text format
        text_format = {}
        if bold:
            text_format['bold'] = True
            fields.append('userEnteredFormat.textFormat.bold')
        if italic:
            text_format['italic'] = True
            fields.append('userEnteredFormat.textFormat.italic')
        if underline:
            text_format['underline'] = True
            fields.append('userEnteredFormat.textFormat.underline')
        if font_size:
            text_format['fontSize'] = font_size
            fields.append('userEnteredFormat.textFormat.fontSize')
        if font_family:
            text_format['fontFamily'] = font_family
            fields.append('userEnteredFormat.textFormat.fontFamily')
        if text_color:
            text_format['foregroundColor'] = hex_to_rgb(text_color)
            fields.append('userEnteredFormat.textFormat.foregroundColor')
        
        if text_format:
            cell_format['textFormat'] = text_format
        
        # Background color
        if bg_color:
            cell_format['backgroundColor'] = hex_to_rgb(bg_color)
            fields.append('userEnteredFormat.backgroundColor')
        
        # Alignment
        if align:
            cell_format['horizontalAlignment'] = align.upper()
            fields.append('userEnteredFormat.horizontalAlignment')
        if valign:
            cell_format['verticalAlignment'] = valign.upper()
            fields.append('userEnteredFormat.verticalAlignment')
        
        # Number format
        if number_format:
            format_patterns = {
                'currency': '$#,##0.00',
                'percentage': '0.00%',
                'date': 'yyyy-mm-dd',
                'datetime': 'yyyy-mm-dd hh:mm:ss',
                'number': '#,##0.00',
                'integer': '#,##0',
                'text': '@'
            }
            pattern = format_patterns.get(number_format.lower(), number_format)
            cell_format['numberFormat'] = {'type': 'NUMBER', 'pattern': pattern}
            fields.append('userEnteredFormat.numberFormat')
        
        # Text wrap
        if wrap:
            cell_format['wrapStrategy'] = wrap.upper()
            fields.append('userEnteredFormat.wrapStrategy')
        
        # Build grid range
        grid_range = {
            'sheetId': sheet_id,
            'startRowIndex': range_info.get('start_row', 0),
            'endRowIndex': range_info.get('end_row', range_info.get('start_row', 0) + 1),
            'startColumnIndex': range_info.get('start_col', 0),
            'endColumnIndex': range_info.get('end_col', range_info.get('start_col', 0) + 1)
        }
        
        # Build request
        request = {
            'repeatCell': {
                'range': grid_range,
                'cell': {'userEnteredFormat': cell_format},
                'fields': ','.join(fields)
            }
        }
        
        # Execute
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Format cells {range_notation}"
        )
        
        print(f"\n✓ Formatted cells: {range_notation}")
        if bold:
            print("  • Bold: Yes")
        if bg_color:
            print(f"  • Background: {bg_color}")
        if text_color:
            print(f"  • Text color: {text_color}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Formatting cells {range_notation}")
        print(error_msg)
        raise


def add_conditional_formatting(
    spreadsheet_id: str,
    range_notation: str,
    rule_type: str,
    value: Any,
    highlight_color: str = "#FFFF00",
    text_color: Optional[str] = None,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add conditional formatting rule.

    Args:
        spreadsheet_id: Spreadsheet ID
        range_notation: A1 notation range
        rule_type: Rule type (greater_than, less_than, equal_to, between, contains, not_empty)
        value: Value for comparison (or "min,max" for between)
        highlight_color: Background color when condition is met
        text_color: Text color when condition is met

    Returns:
        dict: API response
    """
    try:
        service = build_sheets_service(account=account)
        
        # Get spreadsheet info
        spreadsheet = limiter.execute_with_backoff(
            lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute(),
            "Get spreadsheet info"
        )
        
        # Parse range
        range_info = parse_a1_range(range_notation)
        sheet_name = range_info.get('sheet', 'Sheet1')
        sheet_id = get_sheet_id(sheet_name, spreadsheet)
        
        # Build grid range
        grid_range = {
            'sheetId': sheet_id,
            'startRowIndex': range_info.get('start_row', 0),
            'endRowIndex': range_info.get('end_row', range_info.get('start_row', 0) + 1),
            'startColumnIndex': range_info.get('start_col', 0),
            'endColumnIndex': range_info.get('end_col', range_info.get('start_col', 0) + 1)
        }
        
        # Build condition
        condition_type_map = {
            'greater_than': 'NUMBER_GREATER',
            'less_than': 'NUMBER_LESS',
            'equal_to': 'NUMBER_EQ',
            'not_equal': 'NUMBER_NOT_EQ',
            'between': 'NUMBER_BETWEEN',
            'contains': 'TEXT_CONTAINS',
            'not_contains': 'TEXT_NOT_CONTAINS',
            'not_empty': 'NOT_BLANK',
            'is_empty': 'BLANK'
        }
        
        condition = {'type': condition_type_map.get(rule_type, 'NUMBER_GREATER')}
        
        if rule_type == 'between':
            min_val, max_val = str(value).split(',')
            condition['values'] = [
                {'userEnteredValue': min_val.strip()},
                {'userEnteredValue': max_val.strip()}
            ]
        elif rule_type not in ['not_empty', 'is_empty']:
            condition['values'] = [{'userEnteredValue': str(value)}]
        
        # Build format
        format_spec = {'backgroundColor': hex_to_rgb(highlight_color)}
        if text_color:
            format_spec['textFormat'] = {'foregroundColor': hex_to_rgb(text_color)}
        
        # Build request
        request = {
            'addConditionalFormatRule': {
                'rule': {
                    'ranges': [grid_range],
                    'booleanRule': {
                        'condition': condition,
                        'format': format_spec
                    }
                },
                'index': 0
            }
        }
        
        # Execute
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Add conditional formatting to {range_notation}"
        )
        
        print(f"\n✓ Added conditional formatting: {range_notation}")
        print(f"  • Rule: {rule_type} {value}")
        print(f"  • Highlight: {highlight_color}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Adding conditional formatting to {range_notation}")
        print(error_msg)
        raise


def add_alternating_colors(
    spreadsheet_id: str,
    sheet_name: str,
    header_color: str = "#4285F4",
    first_row_color: str = "#FFFFFF",
    second_row_color: str = "#F3F3F3",
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Apply alternating row colors to a sheet.

    Args:
        spreadsheet_id: Spreadsheet ID
        sheet_name: Sheet name
        header_color: Header row background color
        first_row_color: Odd row background color
        second_row_color: Even row background color

    Returns:
        dict: API response
    """
    try:
        service = build_sheets_service(account=account)
        
        # Get spreadsheet info
        spreadsheet = limiter.execute_with_backoff(
            lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute(),
            "Get spreadsheet info"
        )
        
        sheet_id = get_sheet_id(sheet_name, spreadsheet)
        
        # Build request
        request = {
            'addBanding': {
                'bandedRange': {
                    'bandedRangeId': sheet_id + 1000,  # Unique ID
                    'range': {'sheetId': sheet_id},
                    'rowProperties': {
                        'headerColor': hex_to_rgb(header_color),
                        'firstBandColor': hex_to_rgb(first_row_color),
                        'secondBandColor': hex_to_rgb(second_row_color)
                    }
                }
            }
        }
        
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Add alternating colors to {sheet_name}"
        )
        
        print(f"\n✓ Added alternating colors to: {sheet_name}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Adding alternating colors to {sheet_name}")
        print(error_msg)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Format cells in Google Sheets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Bold with background color
  python format_cells.py --spreadsheet ID --range "A1:D1" --bold --bg-color "#4285F4"

  # Full formatting
  python format_cells.py --spreadsheet ID --range "A1:B10" \\
    --bold --font-size 12 --text-color "#000000" --bg-color "#FFFF00" --align CENTER

  # Number format
  python format_cells.py --spreadsheet ID --range "B2:B100" --number-format currency

  # Conditional formatting
  python format_cells.py --spreadsheet ID --range "C2:C100" \\
    --conditional --rule greater_than --value 1000 --highlight-color "#00FF00"

  # Alternating row colors
  python format_cells.py --spreadsheet ID --alternating --sheet "Data"
        '''
    )
    
    parser.add_argument('--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('--range', help='Range in A1 notation')
    parser.add_argument('--sheet', help='Sheet name (for alternating colors)')
    
    # Basic formatting
    parser.add_argument('--bold', action='store_true', help='Bold text')
    parser.add_argument('--italic', action='store_true', help='Italic text')
    parser.add_argument('--underline', action='store_true', help='Underline text')
    parser.add_argument('--font-size', type=int, help='Font size')
    parser.add_argument('--font-family', help='Font family')
    parser.add_argument('--text-color', help='Text color (hex)')
    parser.add_argument('--bg-color', help='Background color (hex)')
    parser.add_argument('--align', choices=['LEFT', 'CENTER', 'RIGHT'], help='Horizontal alignment')
    parser.add_argument('--valign', choices=['TOP', 'MIDDLE', 'BOTTOM'], help='Vertical alignment')
    parser.add_argument('--number-format', help='Number format (currency, percentage, date, etc.)')
    parser.add_argument('--wrap', choices=['WRAP', 'CLIP', 'OVERFLOW_CELL'], help='Text wrap')
    
    # Conditional formatting
    parser.add_argument('--conditional', action='store_true', help='Add conditional formatting')
    parser.add_argument('--rule', help='Conditional rule type')
    parser.add_argument('--value', help='Value for conditional rule')
    parser.add_argument('--highlight-color', default='#FFFF00', help='Highlight color')
    
    # Alternating colors
    parser.add_argument('--alternating', action='store_true', help='Add alternating row colors')
    parser.add_argument('--header-color', default='#4285F4', help='Header color')
    parser.add_argument('--first-color', default='#FFFFFF', help='First row color')
    parser.add_argument('--second-color', default='#F3F3F3', help='Second row color')
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)',
    )
    
    args = parser.parse_args()
    
    try:
        if args.alternating:
            if not args.sheet:
                print("❌ Error: --sheet required for alternating colors")
                sys.exit(1)
            add_alternating_colors(
                args.spreadsheet, args.sheet,
                args.header_color, args.first_color, args.second_color, account=args.account
            )
        elif args.conditional:
            if not args.range or not args.rule:
                print("❌ Error: --range and --rule required for conditional formatting")
                sys.exit(1)
            add_conditional_formatting(
                args.spreadsheet, args.range, args.rule,
                args.value, args.highlight_color, args.text_color, account=args.account
            )
        else:
            if not args.range:
                print("❌ Error: --range required")
                sys.exit(1)
            format_cells(
                args.spreadsheet, args.range,
                bold=args.bold, italic=args.italic, underline=args.underline,
                font_size=args.font_size, font_family=args.font_family,
                text_color=args.text_color, bg_color=args.bg_color,
                align=args.align, valign=args.valign,
                number_format=args.number_format, wrap=args.wrap, account=args.account
            )
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        sys.exit(1)
