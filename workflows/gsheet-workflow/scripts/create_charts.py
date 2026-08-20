#!/usr/bin/env python3
"""
Google Sheets - Chart Creation Operations

Provides functionality to create various chart types in Google Sheets.
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
    """Convert hex color to Google Sheets RGB format."""
    hex_color = hex_color.lstrip('#')
    return {
        'red': int(hex_color[0:2], 16) / 255.0,
        'green': int(hex_color[2:4], 16) / 255.0,
        'blue': int(hex_color[4:6], 16) / 255.0
    }


def create_chart(
    spreadsheet_id: str,
    dest_sheet_name: str,
    chart_type: str,
    data_range: str,
    title: str = "",
    x_axis_title: str = "",
    y_axis_title: str = "",
    legend_position: str = "BOTTOM_LEGEND",
    position_x: int = 0,
    position_y: int = 0,
    width: int = 600,
    height: int = 400,
    stacked: bool = False,
    colors: Optional[List[str]] = None,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a chart in Google Sheets.

    Args:
        spreadsheet_id: Spreadsheet ID
        dest_sheet_name: Sheet where chart will be placed
        chart_type: Chart type (column, line, pie, bar, area, scatter, combo)
        data_range: Data range in A1 notation (e.g., "Data!A1:C10")
        title: Chart title
        x_axis_title: X-axis label
        y_axis_title: Y-axis label
        legend_position: Legend position (BOTTOM_LEGEND, TOP_LEGEND, LEFT_LEGEND, RIGHT_LEGEND, NO_LEGEND)
        position_x: X offset in pixels
        position_y: Y offset in pixels
        width: Chart width in pixels
        height: Chart height in pixels
        stacked: Stack series (for bar/column charts)
        colors: List of hex colors for series

    Returns:
        dict: API response with chart ID
    """
    try:
        service = build_sheets_service(account=account)
        
        # Get spreadsheet info
        spreadsheet = limiter.execute_with_backoff(
            lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute(),
            "Get spreadsheet info"
        )
        
        # Get sheet IDs
        dest_sheet_id = get_sheet_id(dest_sheet_name, spreadsheet)
        
        # Parse data range
        range_info = parse_a1_range(data_range)
        data_sheet_name = range_info.get('sheet', 'Sheet1')
        data_sheet_id = get_sheet_id(data_sheet_name, spreadsheet)
        
        # Build source range
        source_range = {
            'sheetId': data_sheet_id,
            'startRowIndex': range_info.get('start_row', 0),
            'endRowIndex': range_info.get('end_row', 100),
            'startColumnIndex': range_info.get('start_col', 0),
            'endColumnIndex': range_info.get('end_col', 10)
        }
        
        # Map chart types
        chart_type_map = {
            'column': 'COLUMN',
            'bar': 'BAR',
            'line': 'LINE',
            'area': 'AREA',
            'scatter': 'SCATTER',
            'combo': 'COMBO',
            'pie': 'PIE'
        }
        
        gsheet_chart_type = chart_type_map.get(chart_type.lower(), 'COLUMN')
        
        # Build chart spec based on type
        if gsheet_chart_type == 'PIE':
            chart_spec = {
                'title': title,
                'pieChart': {
                    'legendPosition': legend_position,
                    'domain': {
                        'sourceRange': {'sources': [source_range]}
                    },
                    'series': {
                        'sourceRange': {'sources': [source_range]}
                    }
                }
            }
        else:
            # Basic chart spec for most chart types
            basic_chart = {
                'chartType': gsheet_chart_type,
                'legendPosition': legend_position,
                'domains': [{
                    'domain': {
                        'sourceRange': {'sources': [source_range]}
                    }
                }],
                'series': [{
                    'series': {
                        'sourceRange': {'sources': [source_range]}
                    },
                    'targetAxis': 'LEFT_AXIS'
                }],
                'headerCount': 1
            }
            
            if stacked and gsheet_chart_type in ['COLUMN', 'BAR', 'AREA']:
                basic_chart['stackedType'] = 'STACKED'
            
            # Add axis titles
            axis = []
            if y_axis_title:
                axis.append({
                    'position': 'LEFT_AXIS',
                    'title': y_axis_title
                })
            if x_axis_title:
                axis.append({
                    'position': 'BOTTOM_AXIS',
                    'title': x_axis_title
                })
            
            if axis:
                basic_chart['axis'] = axis
            
            chart_spec = {
                'title': title,
                'basicChart': basic_chart
            }
        
        # Build request
        request = {
            'addChart': {
                'chart': {
                    'spec': chart_spec,
                    'position': {
                        'overlayPosition': {
                            'anchorCell': {
                                'sheetId': dest_sheet_id,
                                'rowIndex': position_y // 20,  # Approximate row
                                'columnIndex': position_x // 100  # Approximate column
                            },
                            'offsetXPixels': position_x % 100,
                            'offsetYPixels': position_y % 20,
                            'widthPixels': width,
                            'heightPixels': height
                        }
                    }
                }
            }
        }
        
        # Execute
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Create {chart_type} chart"
        )
        
        # Get chart ID from response
        chart_id = result.get('replies', [{}])[0].get('addChart', {}).get('chart', {}).get('chartId')
        
        print(f"\n✓ Created {chart_type} chart!")
        print(f"  Title: {title}")
        print(f"  Data: {data_range}")
        print(f"  Location: {dest_sheet_name}")
        if chart_id:
            print(f"  Chart ID: {chart_id}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Creating {chart_type} chart")
        print(error_msg)
        raise


def delete_chart(
    spreadsheet_id: str,
    chart_id: int,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete a chart by ID.

    Args:
        spreadsheet_id: Spreadsheet ID
        chart_id: Chart ID to delete

    Returns:
        dict: API response
    """
    try:
        service = build_sheets_service(account=account)
        
        request = {
            'deleteEmbeddedObject': {
                'objectId': chart_id
            }
        }
        
        result = limiter.execute_with_backoff(
            lambda: service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [request]}
            ).execute(),
            f"Delete chart {chart_id}"
        )
        
        print(f"\n✓ Deleted chart: {chart_id}")
        print()
        
        return result
        
    except Exception as e:
        error_msg = handle_api_error(e, f"Deleting chart {chart_id}")
        print(error_msg)
        raise


def list_charts(
    spreadsheet_id: str,
    account: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List all charts in a spreadsheet.

    Args:
        spreadsheet_id: Spreadsheet ID

    Returns:
        list: List of chart info dictionaries
    """
    try:
        service = build_sheets_service(account=account)
        
        spreadsheet = limiter.execute_with_backoff(
            lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute(),
            "Get spreadsheet"
        )
        
        charts = []
        for sheet in spreadsheet.get('sheets', []):
            sheet_name = sheet['properties']['title']
            for chart in sheet.get('charts', []):
                chart_info = {
                    'chartId': chart.get('chartId'),
                    'sheetName': sheet_name,
                    'title': chart.get('spec', {}).get('title', 'Untitled'),
                    'type': chart.get('spec', {}).get('basicChart', {}).get('chartType', 'Unknown')
                }
                charts.append(chart_info)
        
        print(f"\n📊 Charts in spreadsheet ({len(charts)} found):")
        for chart in charts:
            print(f"  • [{chart['chartId']}] {chart['title']} ({chart['type']}) on '{chart['sheetName']}'")
        print()
        
        return charts
        
    except Exception as e:
        error_msg = handle_api_error(e, "Listing charts")
        print(error_msg)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Create and manage charts in Google Sheets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Create column chart
  python create_charts.py --spreadsheet ID --sheet "Charts" \\
    --type column --data-range "Data!A1:B12" --title "Monthly Sales"

  # Create line chart with axis labels
  python create_charts.py --spreadsheet ID --sheet "Dashboard" \\
    --type line --data-range "Data!A1:C12" --title "Trends" \\
    --x-axis "Month" --y-axis "Value"

  # Create pie chart
  python create_charts.py --spreadsheet ID --sheet "Summary" \\
    --type pie --data-range "Data!A1:B5" --title "Distribution"

  # Create stacked bar chart
  python create_charts.py --spreadsheet ID --sheet "Charts" \\
    --type bar --data-range "Data!A1:D10" --title "Comparison" --stacked

  # List all charts
  python create_charts.py --spreadsheet ID --list

  # Delete chart
  python create_charts.py --spreadsheet ID --delete --chart-id 12345

Chart types: column, line, pie, bar, area, scatter, combo
        '''
    )
    
    parser.add_argument('--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('--sheet', help='Destination sheet for chart')
    parser.add_argument('--type', choices=['column', 'line', 'pie', 'bar', 'area', 'scatter', 'combo'],
                        help='Chart type')
    parser.add_argument('--data-range', help='Data range in A1 notation')
    parser.add_argument('--title', default='', help='Chart title')
    parser.add_argument('--x-axis', default='', help='X-axis title')
    parser.add_argument('--y-axis', default='', help='Y-axis title')
    parser.add_argument('--legend', default='BOTTOM_LEGEND',
                        choices=['BOTTOM_LEGEND', 'TOP_LEGEND', 'LEFT_LEGEND', 'RIGHT_LEGEND', 'NO_LEGEND'],
                        help='Legend position')
    parser.add_argument('--width', type=int, default=600, help='Chart width in pixels')
    parser.add_argument('--height', type=int, default=400, help='Chart height in pixels')
    parser.add_argument('--stacked', action='store_true', help='Stack series')
    parser.add_argument('--list', action='store_true', help='List all charts')
    parser.add_argument('--delete', action='store_true', help='Delete a chart')
    parser.add_argument('--chart-id', type=int, help='Chart ID (for delete)')
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)',
    )
    
    args = parser.parse_args()
    
    try:
        if args.list:
            list_charts(args.spreadsheet, account=args.account)
        elif args.delete:
            if not args.chart_id:
                print("❌ Error: --chart-id required for delete")
                sys.exit(1)
            delete_chart(args.spreadsheet, args.chart_id, account=args.account)
        else:
            if not args.sheet or not args.type or not args.data_range:
                print("❌ Error: --sheet, --type, and --data-range required")
                sys.exit(1)
            create_chart(
                args.spreadsheet, args.sheet, args.type, args.data_range,
                title=args.title, x_axis_title=args.x_axis, y_axis_title=args.y_axis,
                legend_position=args.legend, width=args.width, height=args.height,
                stacked=args.stacked, account=args.account
            )
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        sys.exit(1)
