#!/usr/bin/env python3
"""
Google Sheets - Formula Operations

Provides functionality to insert formulas and manage named ranges.
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


def insert_formula(
    spreadsheet_id: str,
    cell: str,
    formula: str,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Insert a formula into a cell.

    Args:
        spreadsheet_id: Spreadsheet ID
        cell: Cell reference in A1 notation (e.g., "Sheet1!B10")
        formula: Formula string (e.g., "=SUM(B2:B9)")

    Returns:
        dict: API response
    """
    try:
        service = build_sheets_service(account=account)
        
        # Ensure formula starts with =
        if not formula.startswith('='):
            formula = '=' + formula
        
        # Use values().update with USER_ENTERED to interpret formula
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=cell,
                valueInputOption='USER_ENTERED',
                body={'values': [[formula]]}
            ).execute(),
            f"Insert formula in {cell}"
        )
        
        print(f"\n✓ Inserted formula: {cell}")
        print(f"  Formula: {formula}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Inserting formula in {cell}")
        print(error_msg)
        raise


def insert_formulas_batch(
    spreadsheet_id: str,
    formulas: List[Dict[str, str]],
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Insert multiple formulas in a batch.

    Args:
        spreadsheet_id: Spreadsheet ID
        formulas: List of dicts with 'cell' and 'formula' keys

    Returns:
        dict: API response
    """
    try:
        service = build_sheets_service(account=account)
        
        # Build batch data
        data = []
        for f in formulas:
            formula = f['formula']
            if not formula.startswith('='):
                formula = '=' + formula
            data.append({
                'range': f['cell'],
                'values': [[formula]]
            })
        
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    'valueInputOption': 'USER_ENTERED',
                    'data': data
                }
            ).execute(),
            f"Insert {len(formulas)} formulas"
        )
        
        print(f"\n✓ Inserted {len(formulas)} formulas")
        for f in formulas:
            print(f"  • {f['cell']}: {f['formula']}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, "Inserting formulas batch")
        print(error_msg)
        raise


def create_named_range(
    spreadsheet_id: str,
    name: str,
    range_notation: str,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a named range.

    Args:
        spreadsheet_id: Spreadsheet ID
        name: Name for the range (e.g., "SalesData")
        range_notation: A1 notation range (e.g., "Data!A1:D100")

    Returns:
        dict: API response
    """
    try:
        service = build_sheets_service(account=account)
        
        # Get spreadsheet to get sheet ID
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
            'endColumnIndex': range_info.get('end_col', 26)
        }
        
        request = {
            'addNamedRange': {
                'namedRange': {
                    'name': name,
                    'range': grid_range
                }
            }
        }
        
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Create named range '{name}'"
        )
        
        print(f"\n✓ Created named range: {name}")
        print(f"  Range: {range_notation}")
        print(f"  Usage: Use '{name}' in formulas (e.g., =SUM({name}))")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Creating named range '{name}'")
        print(error_msg)
        raise


def delete_named_range(
    spreadsheet_id: str,
    name: str,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete a named range.

    Args:
        spreadsheet_id: Spreadsheet ID
        name: Named range name to delete

    Returns:
        dict: API response
    """
    try:
        service = build_sheets_service(account=account)
        
        # Get spreadsheet to find named range ID
        spreadsheet = limiter.execute_with_backoff(
            lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute(),
            "Get spreadsheet info"
        )
        
        # Find named range ID
        named_range_id = None
        for nr in spreadsheet.get('namedRanges', []):
            if nr['name'] == name:
                named_range_id = nr['namedRangeId']
                break
        
        if not named_range_id:
            raise ValueError(f"Named range '{name}' not found")
        
        request = {
            'deleteNamedRange': {
                'namedRangeId': named_range_id
            }
        }
        
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Delete named range '{name}'"
        )
        
        print(f"\n✓ Deleted named range: {name}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Deleting named range '{name}'")
        print(error_msg)
        raise


def list_named_ranges(
    spreadsheet_id: str,
    account: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List all named ranges in a spreadsheet.

    Args:
        spreadsheet_id: Spreadsheet ID

    Returns:
        list: List of named range info
    """
    try:
        service = build_sheets_service(account=account)
        
        spreadsheet = limiter.execute_with_backoff(
            lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute(),
            "Get spreadsheet info"
        )
        
        named_ranges = spreadsheet.get('namedRanges', [])
        
        print(f"\n📋 Named Ranges ({len(named_ranges)} found):")
        for nr in named_ranges:
            grid = nr.get('range', {})
            sheet_id = grid.get('sheetId', 0)
            
            # Find sheet name
            sheet_name = 'Unknown'
            for sheet in spreadsheet.get('sheets', []):
                if sheet['properties']['sheetId'] == sheet_id:
                    sheet_name = sheet['properties']['title']
                    break
            
            print(f"  • {nr['name']} → {sheet_name}!")
        print()
        
        return named_ranges
        
    except Exception as e:
        error_msg = handle_api_error(e, "Listing named ranges")
        print(error_msg)
        raise


def fill_formula_down(
    spreadsheet_id: str,
    source_cell: str,
    target_range: str,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Copy a formula from source cell to target range (fill down).

    Args:
        spreadsheet_id: Spreadsheet ID
        source_cell: Source cell with formula (e.g., "Sheet1!C2")
        target_range: Target range to fill (e.g., "Sheet1!C2:C100")

    Returns:
        dict: API response
    """
    try:
        service = build_sheets_service(account=account)
        
        # First, read the source formula
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=source_cell,
                valueRenderOption='FORMULA'
            ).execute(),
            f"Read formula from {source_cell}"
        )
        
        formula = result.get('values', [['']])[0][0]
        if not formula.startswith('='):
            raise ValueError(f"Cell {source_cell} does not contain a formula")
        
        # Parse target range to determine number of rows
        range_info = parse_a1_range(target_range)
        start_row = range_info.get('start_row', 0)
        end_row = range_info.get('end_row', start_row + 1)
        num_rows = end_row - start_row
        
        # Create array of formulas (the API will auto-adjust relative references)
        formulas = [[formula] for _ in range(num_rows)]
        
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=target_range,
                valueInputOption='USER_ENTERED',
                body={'values': formulas}
            ).execute(),
            f"Fill formula to {target_range}"
        )
        
        print(f"\n✓ Filled formula down")
        print(f"  Source: {source_cell}")
        print(f"  Target: {target_range}")
        print(f"  Rows filled: {num_rows}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Filling formula from {source_cell}")
        print(error_msg)
        raise


# Common formula templates
FORMULA_TEMPLATES = {
    'sum': '=SUM({range})',
    'average': '=AVERAGE({range})',
    'count': '=COUNT({range})',
    'counta': '=COUNTA({range})',
    'max': '=MAX({range})',
    'min': '=MIN({range})',
    'sumif': '=SUMIF({criteria_range}, "{criteria}", {sum_range})',
    'countif': '=COUNTIF({range}, "{criteria}")',
    'vlookup': '=VLOOKUP({lookup_value}, {table_range}, {col_index}, FALSE)',
    'if': '=IF({condition}, {true_value}, {false_value})',
    'concatenate': '=CONCATENATE({values})',
    'today': '=TODAY()',
    'now': '=NOW()'
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Manage formulas and named ranges in Google Sheets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Insert formula
  python formulas.py --spreadsheet ID --cell "B10" --formula "=SUM(B2:B9)"

  # Insert multiple formulas
  python formulas.py --spreadsheet ID --formulas '[{"cell":"C10","formula":"=SUM(C2:C9)"},{"cell":"D10","formula":"=AVERAGE(D2:D9)"}]'

  # Create named range
  python formulas.py --spreadsheet ID --create-named-range --name "SalesData" --range "Data!A1:D100"

  # Delete named range
  python formulas.py --spreadsheet ID --delete-named-range --name "OldRange"

  # List named ranges
  python formulas.py --spreadsheet ID --list-named-ranges

  # Fill formula down
  python formulas.py --spreadsheet ID --fill-down --source "C2" --target "C2:C100"

Common formulas:
  =SUM(range)           Sum values
  =AVERAGE(range)       Average values
  =COUNT(range)         Count numbers
  =COUNTA(range)        Count non-empty
  =MAX(range)           Maximum value
  =MIN(range)           Minimum value
  =VLOOKUP(...)         Lookup value
  =IF(cond, t, f)       Conditional
        '''
    )
    
    parser.add_argument('--spreadsheet', required=True, help='Spreadsheet ID')
    
    # Single formula
    parser.add_argument('--cell', help='Cell for formula')
    parser.add_argument('--formula', help='Formula to insert')
    
    # Batch formulas
    parser.add_argument('--formulas', help='JSON array of {cell, formula} objects')
    
    # Named ranges
    parser.add_argument('--create-named-range', action='store_true', help='Create named range')
    parser.add_argument('--delete-named-range', action='store_true', help='Delete named range')
    parser.add_argument('--list-named-ranges', action='store_true', help='List named ranges')
    parser.add_argument('--name', help='Named range name')
    parser.add_argument('--range', help='Range in A1 notation')
    
    # Fill down
    parser.add_argument('--fill-down', action='store_true', help='Fill formula down')
    parser.add_argument('--source', help='Source cell for fill')
    parser.add_argument('--target', help='Target range for fill')
    
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)',
    )

    args = parser.parse_args()
    
    try:
        if args.list_named_ranges:
            list_named_ranges(args.spreadsheet, account=args.account)
        elif args.create_named_range:
            if not args.name or not args.range:
                print("❌ Error: --name and --range required")
                sys.exit(1)
            create_named_range(args.spreadsheet, args.name, args.range, account=args.account)
        elif args.delete_named_range:
            if not args.name:
                print("❌ Error: --name required")
                sys.exit(1)
            delete_named_range(args.spreadsheet, args.name, account=args.account)
        elif args.fill_down:
            if not args.source or not args.target:
                print("❌ Error: --source and --target required")
                sys.exit(1)
            fill_formula_down(args.spreadsheet, args.source, args.target, account=args.account)
        elif args.formulas:
            formulas = json.loads(args.formulas)
            insert_formulas_batch(args.spreadsheet, formulas, account=args.account)
        elif args.cell and args.formula:
            insert_formula(args.spreadsheet, args.cell, args.formula, account=args.account)
        else:
            parser.print_help()
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        sys.exit(1)
