#!/usr/bin/env python3
"""
Google Sheets - Update Operations

Provides functionality to update, append, and clear data in Google Sheets.
"""

import sys
import json
import warnings
from pathlib import Path
from typing import List, Dict, Any, Optional

# Suppress known non-critical warnings
warnings.filterwarnings('ignore', message='.*importlib.metadata.*')
warnings.filterwarnings('ignore', category=FutureWarning, module='google.api_core')
warnings.filterwarnings('ignore', message='.*urllib3.*OpenSSL.*')

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.auth_helper import build_sheets_service
from scripts.utils.rate_limiter import get_global_limiter
from scripts.utils.common_utils import (
    validate_a1_notation,
    handle_api_error
)

# Initialize global rate limiter
limiter = get_global_limiter(verbose=True)


def update_values(
    spreadsheet_id: str,
    range_notation: str,
    values: List[List[Any]],
    value_input_option: str = 'USER_ENTERED',
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update values in a range.

    Args:
        spreadsheet_id: Spreadsheet ID
        range_notation: A1 notation range
        values: 2D array of values
        value_input_option: How to interpret values ('USER_ENTERED' or 'RAW')

    Returns:
        dict: Update result
    """
    try:
        # Validate A1 notation
        validate_a1_notation(range_notation)

        # Validate value_input_option
        if value_input_option not in ['USER_ENTERED', 'RAW']:
            raise ValueError(f"Invalid value_input_option: '{value_input_option}'. Must be 'USER_ENTERED' or 'RAW'")

        # Validate values is not empty
        if not values:
            raise ValueError("Values cannot be empty")

        service = build_sheets_service(account=account)

        body = {'values': values}

        # Update with rate limiting
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueInputOption=value_input_option,
                body=body
            ).execute(),
            f"Update values in {range_notation}"
        )

        updated_cells = result.get('updatedCells', 0)
        updated_rows = result.get('updatedRows', 0)
        updated_columns = result.get('updatedColumns', 0)

        print(f"\n✓ Updated {range_notation}")
        print(f"  Cells: {updated_cells}")
        print(f"  Rows: {updated_rows}")
        print(f"  Columns: {updated_columns}")
        print()

        return result

    except Exception as e:
        error_msg = handle_api_error(e, f"Updating values in {range_notation}")
        print(error_msg)
        raise


def append_rows(
    spreadsheet_id: str,
    range_notation: str,
    values: List[List[Any]],
    value_input_option: str = 'USER_ENTERED',
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Append rows to the end of a sheet.

    Args:
        spreadsheet_id: Spreadsheet ID
        range_notation: Range or sheet name
        values: 2D array of values to append
        value_input_option: How to interpret values

    Returns:
        dict: Append result
    """
    try:
        service = build_sheets_service(account=account)

        body = {'values': values}

        # Append with rate limiting
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueInputOption=value_input_option,
                insertDataOption='INSERT_ROWS',
                body=body
            ).execute(),
            f"Append rows to {range_notation}"
        )

        updated_range = result.get('updates', {}).get('updatedRange', range_notation)
        updated_rows = result.get('updates', {}).get('updatedRows', len(values))

        print(f"\n✓ Appended {updated_rows} rows to {range_notation}")
        print(f"  Updated range: {updated_range}")
        print()

        return result

    except Exception as e:
        error_msg = handle_api_error(e, f"Appending rows to {range_notation}")
        print(error_msg)
        raise


def clear_range(
    spreadsheet_id: str,
    range_notation: str,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Clear values from a range (formatting preserved).

    Args:
        spreadsheet_id: Spreadsheet ID
        range_notation: A1 notation range

    Returns:
        dict: Clear result
    """
    try:
        service = build_sheets_service(account=account)

        # Clear with rate limiting
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                body={}
            ).execute(),
            f"Clear range {range_notation}"
        )

        print(f"\n✓ Cleared range: {range_notation}")
        print(f"  (Formatting preserved)")
        print()

        return result

    except Exception as e:
        error_msg = handle_api_error(e, f"Clearing range {range_notation}")
        print(error_msg)
        raise


if __name__ == "__main__":
    """Command-line interface for updating spreadsheets."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Update, append, or clear data in Google Sheets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Update values
  python update_spreadsheet.py --spreadsheet ID --range "Sheet1!A1:B2" --values '[[1,2],[3,4]]'

  # Append rows
  python update_spreadsheet.py --spreadsheet ID --append --range "Sheet1" --values '[["New","Row"]]'

  # Clear range
  python update_spreadsheet.py --spreadsheet ID --clear --range "Sheet1!A1:Z100"

  # Update with raw values (no formula parsing)
  python update_spreadsheet.py --spreadsheet ID --range "Sheet1!A1" --values '[["=SUM(1+1)"]]' --raw
        '''
    )

    parser.add_argument('--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('--range', required=True, help='Range (A1 notation)')
    parser.add_argument('--values', help='JSON array of values')
    parser.add_argument('--values-file', help='Path to JSON file with values')
    parser.add_argument('--append', action='store_true', help='Append instead of update')
    parser.add_argument('--clear', action='store_true', help='Clear range')
    parser.add_argument('--raw', action='store_true', help='Use RAW value input (no formula parsing)')
    parser.add_argument('--output', help='Output JSON file path')
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)',
    )

    args = parser.parse_args()

    try:
        result = None
        value_input_option = 'RAW' if args.raw else 'USER_ENTERED'

        if args.clear:
            result = clear_range(args.spreadsheet, args.range, account=args.account)
        else:
            # Get values from command line or file
            if args.values:
                values = json.loads(args.values)
            elif args.values_file:
                with open(args.values_file, 'r') as f:
                    values = json.load(f)
            else:
                print("❌ Error: Must provide --values or --values-file")
                parser.print_help()
                sys.exit(1)

            if args.append:
                result = append_rows(args.spreadsheet, args.range, values, value_input_option, account=args.account)
            else:
                result = update_values(args.spreadsheet, args.range, values, value_input_option, account=args.account)

        if result:
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(result, f, indent=2)
                print(f"Result saved to: {args.output}")
            else:
                print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        sys.exit(1)
