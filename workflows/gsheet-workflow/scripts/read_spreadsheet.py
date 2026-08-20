#!/usr/bin/env python3
"""
Google Sheets - Read Operations

Provides functionality to read data from Google Sheets spreadsheets.
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
    extract_spreadsheet_id_from_url,
    validate_spreadsheet_id,
    validate_a1_notation,
    get_sheet_id,
    handle_api_error
)

# Initialize global rate limiter
limiter = get_global_limiter(verbose=True)


def get_spreadsheet_info(
    spreadsheet_id_or_url: str,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get metadata about a spreadsheet.

    Args:
        spreadsheet_id_or_url: Spreadsheet ID or URL

    Returns:
        dict: Spreadsheet metadata
    """
    try:
        # Extract ID if URL provided
        spreadsheet_id = extract_spreadsheet_id_from_url(spreadsheet_id_or_url)
        if not spreadsheet_id:
            spreadsheet_id = spreadsheet_id_or_url

        if not validate_spreadsheet_id(spreadsheet_id):
            raise ValueError(f"Invalid spreadsheet ID: {spreadsheet_id}")

        service = build_sheets_service(account=account)

        # Get spreadsheet metadata with rate limiting
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute(),
            f"Get spreadsheet info"
        )

        # Extract useful information
        info = {
            'spreadsheetId': result['spreadsheetId'],
            'title': result['properties']['title'],
            'locale': result['properties'].get('locale', 'en_US'),
            'timeZone': result['properties'].get('timeZone', 'UTC'),
            'spreadsheetUrl': f"https://docs.google.com/spreadsheets/d/{result['spreadsheetId']}/edit",
            'sheets': []
        }

        for sheet in result.get('sheets', []):
            props = sheet['properties']
            info['sheets'].append({
                'sheetId': props['sheetId'],
                'title': props['title'],
                'index': props['index'],
                'rowCount': props['gridProperties']['rowCount'],
                'columnCount': props['gridProperties']['columnCount'],
                'frozen_rows': props['gridProperties'].get('frozenRowCount', 0),
                'frozen_columns': props['gridProperties'].get('frozenColumnCount', 0)
            })

        print(f"\n📊 Spreadsheet Info:")
        print(f"  Title: {info['title']}")
        print(f"  ID: {info['spreadsheetId']}")
        print(f"  URL: {info['spreadsheetUrl']}")
        print(f"\n  Sheets ({len(info['sheets'])}):")
        for sheet in info['sheets']:
            print(f"    • {sheet['title']} ({sheet['rowCount']}x{sheet['columnCount']})")
        print()

        return info

    except Exception as e:
        error_msg = handle_api_error(e, f"Getting spreadsheet info")
        print(error_msg)
        raise


def read_values(
    spreadsheet_id: str,
    range_notation: str,
    formatted: bool = True,
    account: Optional[str] = None,
) -> List[List[Any]]:
    """
    Read values from a range.

    Args:
        spreadsheet_id: Spreadsheet ID
        range_notation: A1 notation range (e.g., "Sheet1!A1:B10")
        formatted: If True, return formatted values; otherwise raw values

    Returns:
        list: 2D array of values
    """
    try:
        # Validate A1 notation
        validate_a1_notation(range_notation)

        service = build_sheets_service(account=account)

        value_render_option = 'FORMATTED_VALUE' if formatted else 'UNFORMATTED_VALUE'

        # Read values with rate limiting
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueRenderOption=value_render_option
            ).execute(),
            f"Read values from {range_notation}"
        )

        values = result.get('values', [])

        if not values:
            print(f"\n⚠️  No data found in range: {range_notation}\n")
            return []

        print(f"\n✓ Read {len(values)} rows from {range_notation}")
        print(f"  First row: {values[0][:5]}{'...' if len(values[0]) > 5 else ''}")
        print()

        return values

    except Exception as e:
        error_msg = handle_api_error(e, f"Reading values from {range_notation}")
        print(error_msg)
        raise


def read_multiple_ranges(
    spreadsheet_id: str,
    ranges: List[str],
    formatted: bool = True,
    account: Optional[str] = None,
) -> Dict[str, List[List[Any]]]:
    """
    Read multiple ranges in a single batch request.

    Args:
        spreadsheet_id: Spreadsheet ID
        ranges: List of A1 notation ranges
        formatted: If True, return formatted values

    Returns:
        dict: Mapping of range to values
    """
    try:
        service = build_sheets_service(account=account)

        value_render_option = 'FORMATTED_VALUE' if formatted else 'UNFORMATTED_VALUE'

        # Batch read with rate limiting
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().values().batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=ranges,
                valueRenderOption=value_render_option
            ).execute(),
            f"Batch read {len(ranges)} ranges"
        )

        data = {}
        for value_range in result.get('valueRanges', []):
            range_name = value_range['range']
            values = value_range.get('values', [])
            data[range_name] = values

        print(f"\n✓ Read {len(data)} ranges:")
        for range_name, values in data.items():
            print(f"  • {range_name}: {len(values)} rows")
        print()

        return data

    except Exception as e:
        error_msg = handle_api_error(e, f"Batch reading ranges")
        print(error_msg)
        raise


if __name__ == "__main__":
    """Command-line interface for reading from spreadsheets."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Read data from Google Sheets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Get spreadsheet info
  python read_spreadsheet.py --info SPREADSHEET_ID

  # Read single range
  python read_spreadsheet.py --spreadsheet SPREADSHEET_ID --range "Sheet1!A1:C10"

  # Read multiple ranges
  python read_spreadsheet.py --spreadsheet SPREADSHEET_ID --ranges "Sheet1!A1:B5,Sheet1!D1:E5"

  # Read raw (unformatted) values
  python read_spreadsheet.py --spreadsheet SPREADSHEET_ID --range "Sheet1!A1:C10" --raw
        '''
    )

    parser.add_argument('--info', help='Get spreadsheet info (provide spreadsheet ID or URL)')
    parser.add_argument('--spreadsheet', help='Spreadsheet ID')
    parser.add_argument('--range', help='Range to read (A1 notation)')
    parser.add_argument('--ranges', help='Comma-separated ranges for batch read')
    parser.add_argument('--raw', action='store_true', help='Return raw unformatted values')
    parser.add_argument('--output', help='Output JSON file path')
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)',
    )

    args = parser.parse_args()

    try:
        result = None

        if args.info:
            result = get_spreadsheet_info(args.info, account=args.account)
        elif args.spreadsheet and args.range:
            result = read_values(args.spreadsheet, args.range, formatted=not args.raw, account=args.account)
        elif args.spreadsheet and args.ranges:
            ranges_list = args.ranges.split(',')
            result = read_multiple_ranges(args.spreadsheet, ranges_list, formatted=not args.raw, account=args.account)
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
