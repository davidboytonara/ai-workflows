#!/usr/bin/env python3
"""
Google Sheets - Post-write Verification

Re-reads a range and compares it cell-by-cell against the values a write was
meant to leave there. Companion to update_spreadsheet.py:
- verify an update with the same --values / --values-file,
- verify an append with the updatedRange it reported plus the appended rows,
- verify a clear with --expect-empty.

Comparison is tolerant of USER_ENTERED coercion: a cell matches when the
expected value equals either the formatted or the raw/formula read-back
(string-equal, numeric-equal, percent, or case-insensitive formula match).

Exit codes:
  0  verified: range matches expectation
  1  verification failed (mismatch) or read error
  2  usage error
"""

import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Suppress known non-critical warnings
warnings.filterwarnings('ignore', message='.*importlib.metadata.*')
warnings.filterwarnings('ignore', category=FutureWarning, module='google.api_core')
warnings.filterwarnings('ignore', message='.*urllib3.*OpenSSL.*')

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def normalize_cell(value: Any) -> str:
    """Normalize one cell value to a comparison string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value).strip()


def as_number(text: str) -> Optional[float]:
    """Parse a cell string as a number; supports thousands commas and percent."""
    candidate = text.replace(",", "")
    try:
        if candidate.endswith("%"):
            return float(candidate[:-1]) / 100.0
        return float(candidate)
    except ValueError:
        return None


def values_equal(expected: str, actual: str) -> bool:
    """Tolerant scalar comparison: exact string or numeric equality."""
    if expected == actual:
        return True
    expected_number = as_number(expected)
    actual_number = as_number(actual)
    if expected_number is not None and actual_number is not None:
        return abs(expected_number - actual_number) < 1e-9
    return False


def formulas_equal(expected: str, actual: str) -> bool:
    """Case- and whitespace-insensitive formula comparison."""
    strip = str.maketrans("", "", " \t")
    return expected.translate(strip).upper() == actual.translate(strip).upper()


def cell_matches(expected: Any, formatted: Any, raw: Any) -> bool:
    """One cell: expected vs the formatted and raw/formula read-backs."""
    expected_norm = normalize_cell(expected)
    raw_norm = normalize_cell(raw)
    if expected_norm.startswith("="):
        return formulas_equal(expected_norm, raw_norm)
    formatted_norm = normalize_cell(formatted)
    return values_equal(expected_norm, raw_norm) or values_equal(expected_norm, formatted_norm)


def compare_grid(
    expected: List[List[Any]],
    formatted: List[List[Any]],
    raw: List[List[Any]],
) -> List[Dict[str, Any]]:
    """Compare grids cell-by-cell; missing trailing cells count as empty.

    Returns a list of mismatch records (empty list = verified).
    """
    mismatches: List[Dict[str, Any]] = []
    row_count = max(len(expected), len(formatted), len(raw))
    for row_index in range(row_count):
        expected_row = expected[row_index] if row_index < len(expected) else []
        formatted_row = formatted[row_index] if row_index < len(formatted) else []
        raw_row = raw[row_index] if row_index < len(raw) else []
        column_count = max(len(expected_row), len(formatted_row), len(raw_row))
        for column_index in range(column_count):
            expected_cell = expected_row[column_index] if column_index < len(expected_row) else ""
            formatted_cell = formatted_row[column_index] if column_index < len(formatted_row) else ""
            raw_cell = raw_row[column_index] if column_index < len(raw_row) else ""
            if cell_matches(expected_cell, formatted_cell, raw_cell):
                continue
            mismatches.append({
                'row': row_index + 1,
                'column': column_index + 1,
                'expected': expected_cell,
                'formatted': formatted_cell,
                'raw': raw_cell,
            })
    return mismatches


def find_nonempty_cells(values: List[List[Any]]) -> List[Dict[str, Any]]:
    """Cells that are not empty, for --expect-empty verification."""
    found: List[Dict[str, Any]] = []
    for row_index, row in enumerate(values):
        for column_index, cell in enumerate(row):
            if normalize_cell(cell) != "":
                found.append({
                    'row': row_index + 1,
                    'column': column_index + 1,
                    'value': cell,
                })
    return found


def read_range_both(
    spreadsheet_id: str,
    range_notation: str,
    account: Optional[str] = None,
) -> Tuple[List[List[Any]], List[List[Any]]]:
    """Read one range twice: FORMATTED_VALUE and FORMULA render options."""
    from scripts.utils.auth_helper import build_sheets_service
    from scripts.utils.rate_limiter import get_global_limiter

    limiter = get_global_limiter(verbose=False)
    service = build_sheets_service(account=account)

    def fetch(render_option: str) -> List[List[Any]]:
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueRenderOption=render_option,
            ).execute(),
            f"Verify read {range_notation} ({render_option})",
        )
        return result.get('values', [])

    return fetch('FORMATTED_VALUE'), fetch('FORMULA')


if __name__ == "__main__":
    """Command-line interface for post-write verification."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Verify a Google Sheets write by re-reading the affected range',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Verify an update against the values that were written
  python verify_values.py --spreadsheet ID --range "Data!A1:B2" --values '[["Name","Value"],["Item1",100]]'

  # Verify an append (use the updatedRange reported by the append)
  python verify_values.py --spreadsheet ID --range "Data!A5:B5" --values-file appended.json

  # Verify a clear
  python verify_values.py --spreadsheet ID --range "Data!A1:Z100" --expect-empty

Exit codes: 0 verified, 1 mismatch or read error, 2 usage error.
        '''
    )

    parser.add_argument('--spreadsheet', required=True, help='Spreadsheet ID or URL')
    parser.add_argument('--range', required=True, help='Range to verify (A1 notation)')
    parser.add_argument('--values', help='JSON 2D array of expected values')
    parser.add_argument('--values-file', help='Path to JSON file with expected values')
    parser.add_argument('--expect-empty', action='store_true', help='Expect the range to hold no values')
    parser.add_argument('--output', help='Output JSON file path')
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)',
    )

    args = parser.parse_args()

    provided = [bool(args.values), bool(args.values_file), args.expect_empty]
    if sum(provided) != 1:
        parser.error("Provide exactly one of --values, --values-file, or --expect-empty")

    expected_values: List[List[Any]] = []
    if args.values or args.values_file:
        try:
            if args.values:
                expected_values = json.loads(args.values)
            else:
                with open(args.values_file, 'r', encoding='utf-8') as f:
                    expected_values = json.load(f)
        except (OSError, ValueError) as e:
            parser.error(f"Expected values are not valid JSON: {e}")
        if not isinstance(expected_values, list) or not all(isinstance(row, list) for row in expected_values):
            parser.error("Expected values must be a JSON 2D array (list of rows)")

    try:
        from scripts.utils.common_utils import extract_spreadsheet_id_from_url

        spreadsheet_id = extract_spreadsheet_id_from_url(args.spreadsheet) or args.spreadsheet
        formatted_values, raw_values = read_range_both(
            spreadsheet_id, args.range, account=args.account,
        )

        if args.expect_empty:
            problems = find_nonempty_cells(formatted_values)
            result: Dict[str, Any] = {
                'spreadsheetId': spreadsheet_id,
                'range': args.range,
                'mode': 'expect_empty',
                'verified': not problems,
                'nonEmptyCells': problems,
            }
        else:
            mismatches = compare_grid(expected_values, formatted_values, raw_values)
            result = {
                'spreadsheetId': spreadsheet_id,
                'range': args.range,
                'mode': 'values',
                'verified': not mismatches,
                'expectedRows': len(expected_values),
                'actualRows': len(formatted_values),
                'mismatches': mismatches,
            }

        if result['verified']:
            print(f"\n✓ Verified: {args.range} matches the expected state")
        else:
            detail = result.get('mismatches') or result.get('nonEmptyCells')
            print(f"\n❌ Verification failed for {args.range}: {len(detail)} differing cells")

        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"Result saved to: {args.output}")
        else:
            print(json.dumps(result, indent=2))

        sys.exit(0 if result['verified'] else 1)

    except SystemExit:
        raise
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        sys.exit(1)
