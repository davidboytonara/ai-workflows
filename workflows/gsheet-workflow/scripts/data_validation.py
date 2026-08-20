#!/usr/bin/env python3
"""
Google Sheets - Data Validation Operations

Provides functionality to create dropdown lists and validation rules.
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


def create_dropdown(
    spreadsheet_id: str,
    range_notation: str,
    values: List[str],
    show_dropdown: bool = True,
    strict: bool = True,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a dropdown list validation.

    Args:
        spreadsheet_id: Spreadsheet ID
        range_notation: Range in A1 notation (e.g., "Sheet1!C2:C100")
        values: List of dropdown options
        show_dropdown: Show dropdown arrow in cell
        strict: Reject input not in list

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
            'endRowIndex': range_info.get('end_row', 1000),
            'startColumnIndex': range_info.get('start_col', 0),
            'endColumnIndex': range_info.get('end_col', range_info.get('start_col', 0) + 1)
        }
        
        # Build validation rule
        request = {
            'setDataValidation': {
                'range': grid_range,
                'rule': {
                    'condition': {
                        'type': 'ONE_OF_LIST',
                        'values': [{'userEnteredValue': v} for v in values]
                    },
                    'showCustomUi': show_dropdown,
                    'strict': strict
                }
            }
        }
        
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Create dropdown in {range_notation}"
        )
        
        print(f"\n✓ Created dropdown: {range_notation}")
        print(f"  Options: {', '.join(values)}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Creating dropdown in {range_notation}")
        print(error_msg)
        raise


def create_dropdown_from_range(
    spreadsheet_id: str,
    target_range: str,
    source_range: str,
    show_dropdown: bool = True,
    strict: bool = True,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a dropdown list from values in another range.

    Args:
        spreadsheet_id: Spreadsheet ID
        target_range: Range to apply validation (e.g., "Sheet1!C2:C100")
        source_range: Range containing dropdown values (e.g., "Lists!A1:A10")
        show_dropdown: Show dropdown arrow
        strict: Reject invalid input

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
        
        # Parse target range
        target_info = parse_a1_range(target_range)
        target_sheet = target_info.get('sheet', 'Sheet1')
        target_sheet_id = get_sheet_id(target_sheet, spreadsheet)
        
        # Build target grid range
        grid_range = {
            'sheetId': target_sheet_id,
            'startRowIndex': target_info.get('start_row', 0),
            'endRowIndex': target_info.get('end_row', 1000),
            'startColumnIndex': target_info.get('start_col', 0),
            'endColumnIndex': target_info.get('end_col', target_info.get('start_col', 0) + 1)
        }
        
        # Build validation rule referencing source range
        request = {
            'setDataValidation': {
                'range': grid_range,
                'rule': {
                    'condition': {
                        'type': 'ONE_OF_RANGE',
                        'values': [{'userEnteredValue': f'={source_range}'}]
                    },
                    'showCustomUi': show_dropdown,
                    'strict': strict
                }
            }
        }
        
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Create dropdown from range in {target_range}"
        )
        
        print(f"\n✓ Created dropdown from range: {target_range}")
        print(f"  Source: {source_range}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Creating dropdown from range in {target_range}")
        print(error_msg)
        raise


def validate_number(
    spreadsheet_id: str,
    range_notation: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    strict: bool = True,
    show_warning: bool = True,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a number validation rule.

    Args:
        spreadsheet_id: Spreadsheet ID
        range_notation: Range in A1 notation
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        strict: Reject invalid input (False = show warning only)
        show_warning: Show warning for invalid input

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
            'endRowIndex': range_info.get('end_row', 1000),
            'startColumnIndex': range_info.get('start_col', 0),
            'endColumnIndex': range_info.get('end_col', range_info.get('start_col', 0) + 1)
        }
        
        # Determine condition type
        if min_value is not None and max_value is not None:
            condition = {
                'type': 'NUMBER_BETWEEN',
                'values': [
                    {'userEnteredValue': str(min_value)},
                    {'userEnteredValue': str(max_value)}
                ]
            }
            desc = f"between {min_value} and {max_value}"
        elif min_value is not None:
            condition = {
                'type': 'NUMBER_GREATER_THAN_EQ',
                'values': [{'userEnteredValue': str(min_value)}]
            }
            desc = f">= {min_value}"
        elif max_value is not None:
            condition = {
                'type': 'NUMBER_LESS_THAN_EQ',
                'values': [{'userEnteredValue': str(max_value)}]
            }
            desc = f"<= {max_value}"
        else:
            condition = {'type': 'NUMBER_GREATER_THAN_EQ', 'values': [{'userEnteredValue': '0'}]}
            desc = ">= 0"
        
        request = {
            'setDataValidation': {
                'range': grid_range,
                'rule': {
                    'condition': condition,
                    'strict': strict
                }
            }
        }
        
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Create number validation in {range_notation}"
        )
        
        print(f"\n✓ Created number validation: {range_notation}")
        print(f"  Rule: {desc}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Creating number validation in {range_notation}")
        print(error_msg)
        raise


def validate_date(
    spreadsheet_id: str,
    range_notation: str,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
    strict: bool = True,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a date validation rule.

    Args:
        spreadsheet_id: Spreadsheet ID
        range_notation: Range in A1 notation
        after_date: Minimum date (YYYY-MM-DD format)
        before_date: Maximum date (YYYY-MM-DD format)
        strict: Reject invalid input

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
            'endRowIndex': range_info.get('end_row', 1000),
            'startColumnIndex': range_info.get('start_col', 0),
            'endColumnIndex': range_info.get('end_col', range_info.get('start_col', 0) + 1)
        }
        
        # Determine condition
        if after_date and before_date:
            condition = {
                'type': 'DATE_BETWEEN',
                'values': [
                    {'userEnteredValue': after_date},
                    {'userEnteredValue': before_date}
                ]
            }
            desc = f"between {after_date} and {before_date}"
        elif after_date:
            condition = {
                'type': 'DATE_AFTER',
                'values': [{'userEnteredValue': after_date}]
            }
            desc = f"after {after_date}"
        elif before_date:
            condition = {
                'type': 'DATE_BEFORE',
                'values': [{'userEnteredValue': before_date}]
            }
            desc = f"before {before_date}"
        else:
            condition = {'type': 'DATE_IS_VALID'}
            desc = "valid date"
        
        request = {
            'setDataValidation': {
                'range': grid_range,
                'rule': {
                    'condition': condition,
                    'strict': strict
                }
            }
        }
        
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Create date validation in {range_notation}"
        )
        
        print(f"\n✓ Created date validation: {range_notation}")
        print(f"  Rule: {desc}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Creating date validation in {range_notation}")
        print(error_msg)
        raise


def clear_validation(
    spreadsheet_id: str,
    range_notation: str,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Clear data validation from a range.

    Args:
        spreadsheet_id: Spreadsheet ID
        range_notation: Range in A1 notation

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
            'endRowIndex': range_info.get('end_row', 1000),
            'startColumnIndex': range_info.get('start_col', 0),
            'endColumnIndex': range_info.get('end_col', range_info.get('start_col', 0) + 1)
        }
        
        request = {
            'setDataValidation': {
                'range': grid_range,
                'rule': None  # None clears validation
            }
        }
        
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Clear validation from {range_notation}"
        )
        
        print(f"\n✓ Cleared validation: {range_notation}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Clearing validation from {range_notation}")
        print(error_msg)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Create data validation rules in Google Sheets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Create dropdown list
  python data_validation.py --spreadsheet ID --range "B2:B100" \\
    --dropdown --values "Approved,Pending,Rejected"

  # Dropdown from another range
  python data_validation.py --spreadsheet ID --range "C2:C100" \\
    --dropdown-from-range --source "Lists!A1:A10"

  # Number validation (min only)
  python data_validation.py --spreadsheet ID --range "D2:D100" \\
    --number --min 0

  # Number validation (range)
  python data_validation.py --spreadsheet ID --range "E2:E100" \\
    --number --min 0 --max 100

  # Date validation
  python data_validation.py --spreadsheet ID --range "F2:F100" \\
    --date --after "2024-01-01"

  # Clear validation
  python data_validation.py --spreadsheet ID --range "B2:B100" --clear
        '''
    )
    
    parser.add_argument('--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('--range', required=True, help='Range in A1 notation')
    
    # Dropdown
    parser.add_argument('--dropdown', action='store_true', help='Create dropdown')
    parser.add_argument('--values', help='Comma-separated dropdown values')
    parser.add_argument('--dropdown-from-range', action='store_true', help='Dropdown from range')
    parser.add_argument('--source', help='Source range for dropdown')
    
    # Number validation
    parser.add_argument('--number', action='store_true', help='Number validation')
    parser.add_argument('--min', type=float, help='Minimum value')
    parser.add_argument('--max', type=float, help='Maximum value')
    
    # Date validation
    parser.add_argument('--date', action='store_true', help='Date validation')
    parser.add_argument('--after', help='After date (YYYY-MM-DD)')
    parser.add_argument('--before', help='Before date (YYYY-MM-DD)')
    
    # Options
    parser.add_argument('--warning', action='store_true', help='Show warning instead of reject')
    parser.add_argument('--clear', action='store_true', help='Clear validation')
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)',
    )
    
    args = parser.parse_args()
    
    try:
        strict = not args.warning
        
        if args.clear:
            clear_validation(args.spreadsheet, args.range, account=args.account)
        elif args.dropdown:
            if not args.values:
                print("❌ Error: --values required for dropdown")
                sys.exit(1)
            values = [v.strip() for v in args.values.split(',')]
            create_dropdown(args.spreadsheet, args.range, values, strict=strict, account=args.account)
        elif args.dropdown_from_range:
            if not args.source:
                print("❌ Error: --source required for dropdown-from-range")
                sys.exit(1)
            create_dropdown_from_range(args.spreadsheet, args.range, args.source, strict=strict, account=args.account)
        elif args.number:
            validate_number(args.spreadsheet, args.range, args.min, args.max, strict=strict, account=args.account)
        elif args.date:
            validate_date(args.spreadsheet, args.range, args.after, args.before, strict=strict, account=args.account)
        else:
            parser.print_help()
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        sys.exit(1)
