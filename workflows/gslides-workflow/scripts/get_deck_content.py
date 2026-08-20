#!/usr/bin/env python3
"""Extract slide content with element-level objectIds for targeted updates.

Enhanced version that captures:
- Slide objectIds
- Text shape objectIds with placeholder type
- Table structure with row/column data
- Image positions for caption placement
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import warnings
from typing import Any, Dict, List, Optional

warnings.filterwarnings('ignore', message='.*importlib.metadata.*')
warnings.filterwarnings('ignore', category=FutureWarning, module='google.api_core')
warnings.filterwarnings('ignore', message='.*urllib3.*OpenSSL.*')

SCRIPT_DIR = os.path.dirname(__file__)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from utils.auth_helper import build_service
from utils.logger import setup_logger
from utils.retry_handler import execute_with_retry

logger = setup_logger(__name__)

GOOGLE_SLIDES_MIME = 'application/vnd.google-apps.presentation'
PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'


def normalize_presentation_id(value: str) -> str:
    """Extract the presentation ID from a full URL if needed."""
    if value.startswith('http') and 'docs.google.com' in value:
        parts = value.split('/')
        if 'd' in parts:
            idx = parts.index('d') + 1
            if idx < len(parts):
                return parts[idx]
    return value


def extract_text_elements(text_elements: List[Dict[str, Any]]) -> str:
    """Extract plain text from textElements array."""
    parts: List[str] = []
    for element in text_elements or []:
        run = element.get('textRun')
        if run and run.get('content'):
            parts.append(run['content'])
    return ''.join(parts)


def split_lines(value: str) -> List[str]:
    """Normalize text into trimmed lines, dropping empties."""
    if not value:
        return []
    cleaned = value.replace('\u2022', '').replace('\xa0', ' ')
    return [line.strip() for line in cleaned.splitlines() if line.strip()]


def extract_transform(element: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract position/size from element transform."""
    transform = element.get('transform')
    size = element.get('size')
    if not transform and not size:
        return None
    
    result = {}
    if transform:
        result['translateX'] = transform.get('translateX', 0)
        result['translateY'] = transform.get('translateY', 0)
        result['scaleX'] = transform.get('scaleX', 1)
        result['scaleY'] = transform.get('scaleY', 1)
    if size:
        width = size.get('width', {})
        height = size.get('height', {})
        result['width'] = width.get('magnitude', 0)
        result['height'] = height.get('magnitude', 0)
        result['widthUnit'] = width.get('unit', 'EMU')
        result['heightUnit'] = height.get('unit', 'EMU')
    return result


def parse_table_from_api(element: Dict[str, Any]) -> Dict[str, Any]:
    """Parse table element into structured format with objectId."""
    table = element.get('table', {})
    object_id = element.get('objectId')
    
    rows_data = []
    for row_idx, row in enumerate(table.get('tableRows', [])):
        cells_data = []
        for cell_idx, cell in enumerate(row.get('tableCells', [])):
            text = cell.get('text', {})
            cell_text = extract_text_elements(text.get('textElements', []))
            cells_data.append({
                'rowIndex': row_idx,
                'columnIndex': cell_idx,
                'text': cell_text.strip()
            })
        rows_data.append({'cells': cells_data})
    
    return {
        'objectId': object_id,
        'type': 'table',
        'rows': table.get('rows', len(rows_data)),
        'columns': table.get('columns', len(rows_data[0]['cells']) if rows_data else 0),
        'data': rows_data,
        'transform': extract_transform(element)
    }


def parse_text_shape_from_api(element: Dict[str, Any]) -> Dict[str, Any]:
    """Parse text shape element with objectId and placeholder info."""
    shape = element.get('shape', {})
    object_id = element.get('objectId')
    
    text = extract_text_elements(shape.get('text', {}).get('textElements', []))
    lines = split_lines(text)
    
    placeholder = shape.get('placeholder') or {}
    placeholder_type = placeholder.get('type')
    
    return {
        'objectId': object_id,
        'type': 'textShape',
        'placeholderType': placeholder_type,
        'text': text.strip(),
        'lines': lines,
        'transform': extract_transform(element)
    }


def parse_image_from_api(element: Dict[str, Any]) -> Dict[str, Any]:
    """Parse image element with objectId and position."""
    image = element.get('image', {})
    object_id = element.get('objectId')
    
    return {
        'objectId': object_id,
        'type': 'image',
        'contentUrl': image.get('contentUrl'),
        'sourceUrl': image.get('sourceUrl'),
        'transform': extract_transform(element)
    }


def parse_slide_from_api(slide: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Parse slide with all elements and their objectIds."""
    slide_object_id = slide.get('objectId')
    
    title = ''
    title_object_id = None
    body_lines: List[str] = []
    elements: List[Dict[str, Any]] = []
    tables: List[Dict[str, Any]] = []
    images: List[Dict[str, Any]] = []
    text_shapes: List[Dict[str, Any]] = []
    
    for element in slide.get('pageElements', []):
        object_id = element.get('objectId')
        
        # Handle tables
        if 'table' in element:
            table_data = parse_table_from_api(element)
            tables.append(table_data)
            elements.append(table_data)
            # Flatten table text for body
            for row in table_data['data']:
                for cell in row['cells']:
                    if cell['text']:
                        body_lines.append(cell['text'])
            continue
        
        # Handle images
        if 'image' in element:
            image_data = parse_image_from_api(element)
            images.append(image_data)
            elements.append(image_data)
            continue
        
        # Handle text shapes
        shape = element.get('shape')
        if shape and 'text' in shape:
            shape_data = parse_text_shape_from_api(element)
            text_shapes.append(shape_data)
            elements.append(shape_data)
            
            lines = shape_data['lines']
            if not lines:
                continue
            
            # Check if this is a title placeholder
            if shape_data['placeholderType'] in ('TITLE', 'CENTERED_TITLE') and not title:
                title = lines[0]
                title_object_id = object_id
                body_lines.extend(lines[1:])
            else:
                body_lines.extend(lines)
    
    # Fallback: use first line as title if none found
    if not title and body_lines:
        title = body_lines[0]
        body_lines = body_lines[1:]
    
    return {
        'index': index,
        'objectId': slide_object_id,
        'title': title,
        'titleObjectId': title_object_id,
        'body': body_lines,
        'elements': elements,
        'tables': tables,
        'images': images,
        'textShapes': text_shapes
    }


def read_via_slides_api(
    presentation_id: str,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """Read presentation via Slides API with full element details."""
    slides_service = build_service('slides', 'v1', account=account)
    presentation = execute_with_retry(
        lambda: slides_service.presentations().get(presentationId=presentation_id)
    )
    slides = presentation.get('slides', [])
    result = [parse_slide_from_api(slide, idx + 1) for idx, slide in enumerate(slides)]
    
    return {
        'presentationId': presentation_id,
        'title': presentation.get('title', ''),
        'slideCount': len(result),
        'source': 'slides-api',
        'slides': result
    }


def fetch_drive_metadata(drive_service, presentation_id: str) -> Dict[str, Any]:
    """Fetch file metadata from Drive API."""
    def make_request():
        return drive_service.files().get(
            fileId=presentation_id,
            fields='id,name,mimeType',
            supportsAllDrives=True
        )
    return execute_with_retry(make_request)


def extract_deck_content(
    presentation_id: str,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract deck content with element-level objectIds.
    
    Returns enhanced structure with:
    - Slide objectIds
    - Text shape objectIds and placeholder types
    - Table structure with row/column data
    - Image positions for caption placement
    """
    drive_service = build_service('drive', 'v3', account=account)
    metadata = fetch_drive_metadata(drive_service, presentation_id)
    mime_type = metadata.get('mimeType', '')
    
    if mime_type == GOOGLE_SLIDES_MIME:
        return read_via_slides_api(presentation_id, account=account)
    else:
        # For non-Google Slides files, we need to import first
        raise ValueError(
            f"File is not a Google Slides presentation (mimeType: {mime_type}). "
            "Please convert to Google Slides format first for update support."
        )


def main():
    parser = argparse.ArgumentParser(
        description='Extract slide content with element-level objectIds for targeted updates'
    )
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)'
    )
    parser.add_argument('--presentation-id', required=True,
                        help='Google Slides presentation ID or URL')
    parser.add_argument('--output', help='Optional path to save the JSON output')
    parser.add_argument('--compact', action='store_true',
                        help='Output compact JSON without element details')
    args = parser.parse_args()

    presentation_id = normalize_presentation_id(args.presentation_id)

    try:
        content = extract_deck_content(presentation_id, account=args.account)
        
        # Compact mode: remove detailed element arrays for simpler output
        if args.compact:
            for slide in content.get('slides', []):
                slide.pop('elements', None)
                slide.pop('textShapes', None)
                # Keep tables and images as they're often needed
    except HttpError as error:
        logger.error("Google API error: %s", error)
        print(f"❌ API error {error.resp.status}: {error}")
        sys.exit(1)
    except Exception as exc:
        logger.error("Failed to extract deck content: %s", exc)
        print(f"❌ Error: {exc}")
        sys.exit(1)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as fh:
            json.dump(content, fh, ensure_ascii=False, indent=2)
        print(f"\n✓ SUCCESS! Deck content saved to {args.output}")
        print(f"  Slides: {content['slideCount']}")
        print(f"  Source: {content['source']}")
    else:
        print(json.dumps(content, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
