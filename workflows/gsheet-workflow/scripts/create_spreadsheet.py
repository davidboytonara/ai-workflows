#!/usr/bin/env python3
"""
Google Sheets - Create Spreadsheet Operations

Provides functionality to create new Google Sheets spreadsheets.
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
    validate_spreadsheet_title,
    validate_sheet_name,
    handle_api_error
)

# Initialize global rate limiter
limiter = get_global_limiter(verbose=True)


def create_spreadsheet(
    title: str,
    sheet_names: Optional[List[str]] = None,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new Google Sheets spreadsheet.

    Args:
        title: Spreadsheet title
        sheet_names: List of sheet names to create (default: ["Sheet1"])

    Returns:
        dict: Created spreadsheet metadata including spreadsheetId and spreadsheetUrl
    """
    try:
        # Validate spreadsheet title
        validate_spreadsheet_title(title)

        service = build_sheets_service(account=account)

        # Build sheets list
        sheets = []
        if sheet_names:
            for i, sheet_name in enumerate(sheet_names):
                # Validate each sheet name
                validate_sheet_name(sheet_name)
                sheets.append({
                    'properties': {
                        'title': sheet_name,
                        'index': i,
                        'gridProperties': {
                            'rowCount': 1000,
                            'columnCount': 26
                        }
                    }
                })
        else:
            sheets = [{'properties': {'title': 'Sheet1'}}]

        spreadsheet_body = {
            'properties': {'title': title},
            'sheets': sheets
        }

        # Create spreadsheet with rate limiting
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().create(body=spreadsheet_body).execute(),
            f"Create spreadsheet '{title}'"
        )

        spreadsheet_id = result['spreadsheetId']
        spreadsheet_url = result['spreadsheetUrl']

        print(f"\n✓ Spreadsheet created successfully!")
        print(f"  Title: {title}")
        print(f"  ID: {spreadsheet_id}")
        print(f"  URL: {spreadsheet_url}")
        if sheet_names:
            print(f"  Sheets: {', '.join(sheet_names)}")
        print()

        return {
            'spreadsheetId': spreadsheet_id,
            'spreadsheetUrl': spreadsheet_url,
            'title': title,
            'sheets': [s['properties']['title'] for s in result.get('sheets', [])]
        }

    except Exception as e:
        error_msg = handle_api_error(e, f"Creating spreadsheet '{title}'")
        print(error_msg)
        raise


if __name__ == "__main__":
    """Command-line interface for creating spreadsheets."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Create a new Google Sheets spreadsheet',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Create spreadsheet with default sheet
  python create_spreadsheet.py --title "My Spreadsheet"

  # Create with custom sheet names
  python create_spreadsheet.py --title "Project Tracker" --sheets "Tasks,Team,Timeline"

  # Output to JSON file
  python create_spreadsheet.py --title "Data" --output spreadsheet.json
        '''
    )

    parser.add_argument('--title', required=True, help='Spreadsheet title')
    parser.add_argument('--sheets', help='Comma-separated list of sheet names')
    parser.add_argument('--output', help='Output JSON file path')
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)',
    )

    args = parser.parse_args()

    try:
        sheet_names = args.sheets.split(',') if args.sheets else None
        result = create_spreadsheet(args.title, sheet_names, account=args.account)

        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"Result saved to: {args.output}")
        else:
            print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        sys.exit(1)
