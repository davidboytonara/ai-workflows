#!/usr/bin/env python3
"""
Google Sheets - Sheet Management Operations

Provides functionality to create, delete, and rename sheets within spreadsheets.
"""

import sys
import json
import warnings
from pathlib import Path
from typing import Dict, Any, Optional

# Suppress known non-critical warnings
warnings.filterwarnings('ignore', message='.*importlib.metadata.*')
warnings.filterwarnings('ignore', category=FutureWarning, module='google.api_core')
warnings.filterwarnings('ignore', message='.*urllib3.*OpenSSL.*')

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.auth_helper import build_sheets_service
from scripts.utils.rate_limiter import get_global_limiter
from scripts.utils.common_utils import (
    validate_sheet_name,
    get_sheet_id,
    handle_api_error
)

# Initialize global rate limiter
limiter = get_global_limiter(verbose=True)


def create_sheet(
    spreadsheet_id: str,
    sheet_title: str,
    rows: int = 1000,
    columns: int = 26,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add a new sheet to a spreadsheet.

    Args:
        spreadsheet_id: Spreadsheet ID
        sheet_title: Title for the new sheet
        rows: Number of rows (default: 1000)
        columns: Number of columns (default: 26)

    Returns:
        dict: Created sheet properties
    """
    try:
        # Validate sheet name
        validate_sheet_name(sheet_title)

        # Validate row and column counts
        if rows < 1 or rows > 5000000:
            raise ValueError(f"Invalid row count: {rows}. Must be between 1 and 5,000,000")
        if columns < 1 or columns > 18278:
            raise ValueError(f"Invalid column count: {columns}. Must be between 1 and 18,278")

        service = build_sheets_service(account=account)

        request = {
            'addSheet': {
                'properties': {
                    'title': sheet_title,
                    'gridProperties': {
                        'rowCount': rows,
                        'columnCount': columns
                    }
                }
            }
        }

        body = {'requests': [request]}

        # Create sheet with rate limiting
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute(),
            f"Create sheet '{sheet_title}'"
        )

        sheet_props = result['replies'][0]['addSheet']['properties']

        print(f"\n✓ Created sheet: {sheet_title}")
        print(f"  Sheet ID: {sheet_props['sheetId']}")
        print(f"  Size: {rows}x{columns}")
        print()

        return sheet_props

    except Exception as e:
        error_msg = handle_api_error(e, f"Creating sheet '{sheet_title}'")
        print(error_msg)
        raise


def delete_sheet(
    spreadsheet_id: str,
    sheet_title: str,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete a sheet from a spreadsheet.

    Args:
        spreadsheet_id: Spreadsheet ID
        sheet_title: Title of sheet to delete

    Returns:
        dict: Delete result
    """
    try:
        service = build_sheets_service(account=account)

        # Get spreadsheet to find sheet ID
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheet_id = get_sheet_id(sheet_title, spreadsheet)

        request = {
            'deleteSheet': {
                'sheetId': sheet_id
            }
        }

        body = {'requests': [request]}

        # Delete with rate limiting
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute(),
            f"Delete sheet '{sheet_title}'"
        )

        print(f"\n✓ Deleted sheet: {sheet_title}")
        print()

        return result

    except Exception as e:
        error_msg = handle_api_error(e, f"Deleting sheet '{sheet_title}'")
        print(error_msg)
        raise


def rename_sheet(
    spreadsheet_id: str,
    old_title: str,
    new_title: str,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Rename a sheet.

    Args:
        spreadsheet_id: Spreadsheet ID
        old_title: Current sheet title
        new_title: New sheet title

    Returns:
        dict: Rename result
    """
    try:
        service = build_sheets_service(account=account)

        # Get spreadsheet to find sheet ID
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheet_id = get_sheet_id(old_title, spreadsheet)

        request = {
            'updateSheetProperties': {
                'properties': {
                    'sheetId': sheet_id,
                    'title': new_title
                },
                'fields': 'title'
            }
        }

        body = {'requests': [request]}

        # Rename with rate limiting
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute(),
            f"Rename sheet '{old_title}' to '{new_title}'"
        )

        print(f"\n✓ Renamed sheet: {old_title} → {new_title}")
        print()

        return result

    except Exception as e:
        error_msg = handle_api_error(e, f"Renaming sheet '{old_title}'")
        print(error_msg)
        raise


if __name__ == "__main__":
    """Command-line interface for managing sheets."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Manage sheets in Google Sheets spreadsheets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Create new sheet
  python manage_sheets.py --spreadsheet ID --create --title "New Sheet"

  # Create with custom size
  python manage_sheets.py --spreadsheet ID --create --title "Large" --rows 5000 --columns 50

  # Delete sheet
  python manage_sheets.py --spreadsheet ID --delete --title "Old Sheet"

  # Rename sheet
  python manage_sheets.py --spreadsheet ID --rename --old "Sheet1" --new "Data"
        '''
    )

    parser.add_argument('--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('--create', action='store_true', help='Create new sheet')
    parser.add_argument('--delete', action='store_true', help='Delete sheet')
    parser.add_argument('--rename', action='store_true', help='Rename sheet')
    parser.add_argument('--title', help='Sheet title (for create/delete)')
    parser.add_argument('--old', help='Old sheet title (for rename)')
    parser.add_argument('--new', help='New sheet title (for rename)')
    parser.add_argument('--rows', type=int, default=1000, help='Rows for new sheet')
    parser.add_argument('--columns', type=int, default=26, help='Columns for new sheet')
    parser.add_argument('--output', help='Output JSON file path')
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)',
    )

    args = parser.parse_args()

    try:
        result = None

        if args.create:
            if not args.title:
                print("❌ Error: --title required for create")
                sys.exit(1)
            result = create_sheet(args.spreadsheet, args.title, args.rows, args.columns, account=args.account)
        elif args.delete:
            if not args.title:
                print("❌ Error: --title required for delete")
                sys.exit(1)
            result = delete_sheet(args.spreadsheet, args.title, account=args.account)
        elif args.rename:
            if not args.old or not args.new:
                print("❌ Error: --old and --new required for rename")
                sys.exit(1)
            result = rename_sheet(args.spreadsheet, args.old, args.new, account=args.account)
        else:
            parser.print_help()
            sys.exit(1)

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
