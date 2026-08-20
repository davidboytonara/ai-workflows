#!/usr/bin/env python3
"""Apply changes to Google Slides presentation using batchUpdate API.

Supports declarative updates via JSON:
- replace_text: Find and replace text (slide-scoped or global)
- add_table_row: Add row to existing table
- delete_table_row: Remove row from table
- update_table_cell: Update specific cell content
- add_text_box: Add new text element (for diagram captions)
- add_bullet: Add bullet point to existing shape
- delete_slide: Remove slide
- duplicate_slide: Copy slide
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from typing import Any, Dict, List, Optional

warnings.filterwarnings('ignore', message='.*importlib.metadata.*')
warnings.filterwarnings('ignore', category=FutureWarning, module='google.api_core')
warnings.filterwarnings('ignore', message='.*urllib3.*OpenSSL.*')

SCRIPT_DIR = os.path.dirname(__file__)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from googleapiclient.errors import HttpError
from utils.auth_helper import build_service
from utils.logger import setup_logger
from utils.retry_handler import execute_with_retry

logger = setup_logger(__name__)

# Default text box styling
DEFAULT_TEXT_BOX_STYLE = {
    'fontSize': 14,
    'fontFamily': 'Arial',
    'bold': False
}

# EMU conversion (English Metric Units - 914400 EMU = 1 inch)
EMU_PER_PT = 12700
EMU_PER_INCH = 914400


def normalize_presentation_id(value: str) -> str:
    """Extract presentation ID from URL if needed."""
    if value.startswith('http') and 'docs.google.com' in value:
        parts = value.split('/')
        if 'd' in parts:
            idx = parts.index('d') + 1
            if idx < len(parts):
                return parts[idx]
    return value


def get_presentation(slides_service, presentation_id: str) -> Dict[str, Any]:
    """Fetch presentation data."""
    return execute_with_retry(
        lambda: slides_service.presentations().get(presentationId=presentation_id)
    )


def find_slide_by_index(presentation: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
    """Find slide by 1-based index."""
    slides = presentation.get('slides', [])
    if 1 <= index <= len(slides):
        return slides[index - 1]
    return None


def find_table_in_slide(slide: Dict[str, Any], table_index: int = 0) -> Optional[Dict[str, Any]]:
    """Find table element in slide by index (0-based)."""
    tables_found = 0
    for element in slide.get('pageElements', []):
        if 'table' in element:
            if tables_found == table_index:
                return element
            tables_found += 1
    return None


def find_image_in_slide(slide: Dict[str, Any], image_index: int = 0) -> Optional[Dict[str, Any]]:
    """Find image element in slide by index (0-based)."""
    images_found = 0
    for element in slide.get('pageElements', []):
        if 'image' in element:
            if images_found == image_index:
                return element
            images_found += 1
    return None


def build_replace_text_request(
    find: str,
    replace: str,
    slide_object_id: Optional[str] = None,
    match_case: bool = False
) -> Dict[str, Any]:
    """Build replaceAllText request."""
    request = {
        'replaceAllText': {
            'replaceText': replace,
            'containsText': {
                'text': find,
                'matchCase': match_case
            }
        }
    }
    if slide_object_id:
        request['replaceAllText']['pageObjectIds'] = [slide_object_id]
    return request


def build_add_table_row_request(
    table_object_id: str,
    row_index: int,
    insert_below: bool = True
) -> Dict[str, Any]:
    """Build insertTableRows request."""
    return {
        'insertTableRows': {
            'tableObjectId': table_object_id,
            'cellLocation': {
                'tableObjectId': table_object_id,
                'rowIndex': row_index,
                'columnIndex': 0
            },
            'insertBelow': insert_below,
            'number': 1
        }
    }


def build_delete_table_row_request(
    table_object_id: str,
    row_index: int
) -> Dict[str, Any]:
    """Build deleteTableRow request."""
    return {
        'deleteTableRow': {
            'tableObjectId': table_object_id,
            'cellLocation': {
                'tableObjectId': table_object_id,
                'rowIndex': row_index,
                'columnIndex': 0
            }
        }
    }


def build_update_table_cell_request(
    table_object_id: str,
    row_index: int,
    column_index: int,
    text: str
) -> List[Dict[str, Any]]:
    """Build requests to update table cell text (delete + insert)."""
    cell_location = {
        'tableObjectId': table_object_id,
        'rowIndex': row_index,
        'columnIndex': column_index
    }
    
    # We need to delete existing text and insert new text
    # This requires knowing the cell's objectId which we get from table structure
    return [
        {
            'deleteText': {
                'objectId': table_object_id,
                'cellLocation': cell_location,
                'textRange': {
                    'type': 'ALL'
                }
            }
        },
        {
            'insertText': {
                'objectId': table_object_id,
                'cellLocation': cell_location,
                'text': text,
                'insertionIndex': 0
            }
        }
    ]


def build_create_text_box_request(
    slide_object_id: str,
    text: str,
    x: float,
    y: float,
    width: float,
    height: float,
    object_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Build requests to create text box with content."""
    import uuid
    element_id = object_id or f'textbox_{uuid.uuid4().hex[:8]}'
    
    return [
        {
            'createShape': {
                'objectId': element_id,
                'shapeType': 'TEXT_BOX',
                'elementProperties': {
                    'pageObjectId': slide_object_id,
                    'size': {
                        'width': {'magnitude': width, 'unit': 'EMU'},
                        'height': {'magnitude': height, 'unit': 'EMU'}
                    },
                    'transform': {
                        'scaleX': 1,
                        'scaleY': 1,
                        'translateX': x,
                        'translateY': y,
                        'unit': 'EMU'
                    }
                }
            }
        },
        {
            'insertText': {
                'objectId': element_id,
                'text': text,
                'insertionIndex': 0
            }
        }
    ]


def build_delete_slide_request(slide_object_id: str) -> Dict[str, Any]:
    """Build deleteObject request for slide."""
    return {
        'deleteObject': {
            'objectId': slide_object_id
        }
    }


def build_duplicate_slide_request(
    slide_object_id: str,
    insertion_index: Optional[int] = None
) -> Dict[str, Any]:
    """Build duplicateObject request for slide."""
    request = {
        'duplicateObject': {
            'objectId': slide_object_id
        }
    }
    if insertion_index is not None:
        request['duplicateObject']['objectIds'] = {}
    return request


def calculate_caption_position(
    image_element: Dict[str, Any],
    position: str = 'below',
    padding: int = 10
) -> Dict[str, float]:
    """Calculate position for caption relative to image."""
    transform = image_element.get('transform', {})
    size = image_element.get('size', {})
    
    img_x = transform.get('translateX', 0)
    img_y = transform.get('translateY', 0)
    img_width = size.get('width', {}).get('magnitude', 3000000)
    img_height = size.get('height', {}).get('magnitude', 2000000)
    
    padding_emu = padding * EMU_PER_PT
    caption_height = 30 * EMU_PER_PT  # 30pt height
    caption_width = img_width
    
    if position == 'below':
        return {
            'x': img_x,
            'y': img_y + img_height + padding_emu,
            'width': caption_width,
            'height': caption_height
        }
    elif position == 'above':
        return {
            'x': img_x,
            'y': img_y - caption_height - padding_emu,
            'width': caption_width,
            'height': caption_height
        }
    elif position == 'right':
        return {
            'x': img_x + img_width + padding_emu,
            'y': img_y,
            'width': caption_width,
            'height': caption_height
        }
    elif position == 'left':
        return {
            'x': img_x - caption_width - padding_emu,
            'y': img_y,
            'width': caption_width,
            'height': caption_height
        }
    else:
        # Default: below
        return {
            'x': img_x,
            'y': img_y + img_height + padding_emu,
            'width': caption_width,
            'height': caption_height
        }


def process_update(
    update: Dict[str, Any],
    presentation: Dict[str, Any],
    presentation_id: str
) -> List[Dict[str, Any]]:
    """Process single update and return list of API requests."""
    update_type = update.get('type')
    requests = []
    
    if update_type == 'replace_text':
        find = update.get('find', '')
        replace = update.get('replace', '')
        match_case = update.get('matchCase', False)
        scope = update.get('scope', {})
        
        slide_object_id = None
        if scope.get('slideIndex'):
            slide = find_slide_by_index(presentation, scope['slideIndex'])
            if slide:
                slide_object_id = slide.get('objectId')
            else:
                logger.warning(f"Slide index {scope['slideIndex']} not found")
                return []
        
        requests.append(build_replace_text_request(find, replace, slide_object_id, match_case))
    
    elif update_type == 'add_table_row':
        slide_index = update.get('slideIndex')
        table_index = update.get('tableIndex', 0)
        cells = update.get('cells', [])
        position = update.get('position', 'end')
        
        slide = find_slide_by_index(presentation, slide_index)
        if not slide:
            logger.warning(f"Slide index {slide_index} not found")
            return []
        
        table_element = find_table_in_slide(slide, table_index)
        if not table_element:
            logger.warning(f"Table index {table_index} not found in slide {slide_index}")
            return []
        
        table = table_element.get('table', {})
        table_object_id = table_element.get('objectId')
        num_rows = table.get('rows', 0)
        num_cols = table.get('columns', 0)
        
        # Determine row index for insertion
        if position == 'end':
            row_index = num_rows - 1
            insert_below = True
        elif position == 'start':
            row_index = 0
            insert_below = False
        elif isinstance(position, int):
            row_index = position
            insert_below = True
        else:
            row_index = num_rows - 1
            insert_below = True
        
        # Add the row
        requests.append(build_add_table_row_request(table_object_id, row_index, insert_below))
        
        # Fill in cell values
        new_row_index = row_index + 1 if insert_below else row_index
        for col_idx, cell_text in enumerate(cells):
            if col_idx >= num_cols:
                break
            if cell_text:  # Only update non-empty cells
                requests.extend(build_update_table_cell_request(
                    table_object_id, new_row_index, col_idx, cell_text
                ))
    
    elif update_type == 'delete_table_row':
        slide_index = update.get('slideIndex')
        table_index = update.get('tableIndex', 0)
        row_index = update.get('rowIndex')
        
        slide = find_slide_by_index(presentation, slide_index)
        if not slide:
            logger.warning(f"Slide index {slide_index} not found")
            return []
        
        table_element = find_table_in_slide(slide, table_index)
        if not table_element:
            logger.warning(f"Table index {table_index} not found in slide {slide_index}")
            return []
        
        table_object_id = table_element.get('objectId')
        requests.append(build_delete_table_row_request(table_object_id, row_index))
    
    elif update_type == 'update_table_cell':
        slide_index = update.get('slideIndex')
        table_index = update.get('tableIndex', 0)
        row_index = update.get('rowIndex')
        column_index = update.get('columnIndex')
        text = update.get('text', '')
        
        slide = find_slide_by_index(presentation, slide_index)
        if not slide:
            logger.warning(f"Slide index {slide_index} not found")
            return []
        
        table_element = find_table_in_slide(slide, table_index)
        if not table_element:
            logger.warning(f"Table index {table_index} not found in slide {slide_index}")
            return []
        
        table_object_id = table_element.get('objectId')
        requests.extend(build_update_table_cell_request(
            table_object_id, row_index, column_index, text
        ))
    
    elif update_type == 'add_text_box':
        slide_index = update.get('slideIndex')
        text = update.get('text', '')
        near_element = update.get('nearElement')
        position = update.get('position', 'below')
        
        slide = find_slide_by_index(presentation, slide_index)
        if not slide:
            logger.warning(f"Slide index {slide_index} not found")
            return []
        
        slide_object_id = slide.get('objectId')
        
        # Determine position
        if near_element == 'image':
            image_index = update.get('imageIndex', 0)
            image_element = find_image_in_slide(slide, image_index)
            if image_element:
                pos = calculate_caption_position(image_element, position)
            else:
                logger.warning(f"Image index {image_index} not found in slide {slide_index}")
                # Default position
                pos = {'x': 1000000, 'y': 4000000, 'width': 7000000, 'height': 500000}
        elif update.get('x') is not None:
            # Explicit position in EMU
            pos = {
                'x': update.get('x', 1000000),
                'y': update.get('y', 4000000),
                'width': update.get('width', 5000000),
                'height': update.get('height', 500000)
            }
        else:
            # Default: bottom center of slide
            pos = {'x': 1000000, 'y': 4500000, 'width': 7000000, 'height': 500000}
        
        requests.extend(build_create_text_box_request(
            slide_object_id, text,
            pos['x'], pos['y'], pos['width'], pos['height']
        ))
    
    elif update_type == 'delete_slide':
        slide_index = update.get('slideIndex')
        slide = find_slide_by_index(presentation, slide_index)
        if not slide:
            logger.warning(f"Slide index {slide_index} not found")
            return []
        
        requests.append(build_delete_slide_request(slide.get('objectId')))
    
    elif update_type == 'duplicate_slide':
        slide_index = update.get('slideIndex')
        insertion_index = update.get('insertAtIndex')
        
        slide = find_slide_by_index(presentation, slide_index)
        if not slide:
            logger.warning(f"Slide index {slide_index} not found")
            return []
        
        requests.append(build_duplicate_slide_request(
            slide.get('objectId'), insertion_index
        ))
    
    else:
        logger.warning(f"Unknown update type: {update_type}")
    
    return requests


def apply_updates(
    presentation_id: str,
    changes: Dict[str, Any],
    dry_run: bool = False,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply all updates from changes JSON."""
    slides_service = build_service('slides', 'v1', account=account)
    
    # Fetch current presentation state
    presentation = get_presentation(slides_service, presentation_id)
    
    # Build all requests
    all_requests = []
    for update in changes.get('updates', []):
        requests = process_update(update, presentation, presentation_id)
        all_requests.extend(requests)
    
    if not all_requests:
        return {'status': 'no_changes', 'requestCount': 0}
    
    if dry_run:
        return {
            'status': 'dry_run',
            'requestCount': len(all_requests),
            'requests': all_requests
        }
    
    # Execute batchUpdate
    result = execute_with_retry(
        lambda: slides_service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={'requests': all_requests}
        )
    )
    
    return {
        'status': 'success',
        'requestCount': len(all_requests),
        'replies': result.get('replies', [])
    }


def main():
    parser = argparse.ArgumentParser(
        description='Apply changes to Google Slides presentation'
    )
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)'
    )
    parser.add_argument('--presentation-id', required=True,
                        help='Google Slides presentation ID or URL')
    parser.add_argument('--changes-file', required=True,
                        help='Path to JSON file with changes')
    parser.add_argument('--dry-run', action='store_true',
                        help='Validate changes without applying them')
    args = parser.parse_args()

    presentation_id = normalize_presentation_id(args.presentation_id)
    
    # Load changes
    try:
        with open(args.changes_file, 'r', encoding='utf-8') as fh:
            changes = json.load(fh)
    except Exception as e:
        print(f"❌ Failed to load changes file: {e}")
        sys.exit(1)
    
    # Validate changes structure
    if 'updates' not in changes or not isinstance(changes['updates'], list):
        print("❌ Changes file must have 'updates' array")
        sys.exit(1)

    try:
        result = apply_updates(
            presentation_id,
            changes,
            dry_run=args.dry_run,
            account=args.account,
        )
        
        if result['status'] == 'dry_run':
            print(f"\n🔍 DRY RUN - {result['requestCount']} requests would be sent:")
            for i, req in enumerate(result.get('requests', []), 1):
                req_type = list(req.keys())[0]
                print(f"  {i}. {req_type}")
        elif result['status'] == 'success':
            print(f"\n✓ SUCCESS! Applied {result['requestCount']} updates")
            print(f"  View: https://docs.google.com/presentation/d/{presentation_id}/edit")
        else:
            print(f"\n⚠ No changes applied ({result['status']})")
            
    except HttpError as error:
        logger.error("Google API error: %s", error)
        print(f"❌ API error {error.resp.status}: {error}")
        sys.exit(1)
    except Exception as exc:
        logger.error("Failed to apply updates: %s", exc)
        print(f"❌ Error: {exc}")
        sys.exit(1)


if __name__ == '__main__':
    main()
