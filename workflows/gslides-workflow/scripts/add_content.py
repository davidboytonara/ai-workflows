#!/usr/bin/env python3
"""
Add slides with content to a Google Slides presentation.

Takes a JSON specification and creates slides with titles, bullets, and speaker notes.
"""

import sys
import os
import json
import argparse
import uuid
import warnings
from typing import Dict, List, Any, Optional

warnings.filterwarnings('ignore', message='.*importlib.metadata.*')
warnings.filterwarnings('ignore', category=FutureWarning, module='google.api_core')

sys.path.insert(0, os.path.dirname(__file__))

from utils.auth_helper import build_service
from utils.logger import setup_logger
from utils.retry_handler import execute_with_retry
from utils.emu_converter import inches_to_emu
from utils.color_converter import to_slides_opaque_color

logger = setup_logger(__name__)

# Standard slide dimensions (16:9 widescreen)
SLIDE_WIDTH = 10.0  # inches
SLIDE_HEIGHT = 5.625  # inches

# Layout configurations (positions in inches)
LAYOUTS = {
    'TITLE': {
        'title': {'x': 0.5, 'y': 2.0, 'width': 9.0, 'height': 1.5},
        'subtitle': {'x': 0.5, 'y': 3.5, 'width': 9.0, 'height': 0.8}
    },
    'TITLE_AND_BODY': {
        'title': {'x': 0.5, 'y': 0.4, 'width': 9.0, 'height': 0.8},
        'body': {'x': 0.5, 'y': 1.4, 'width': 9.0, 'height': 3.8}
    },
    'SECTION_HEADER': {
        'title': {'x': 0.5, 'y': 2.2, 'width': 9.0, 'height': 1.2}
    },
    'TITLE_AND_TWO_COLUMNS': {
        'title': {'x': 0.5, 'y': 0.4, 'width': 9.0, 'height': 0.8},
        'left': {'x': 0.5, 'y': 1.4, 'width': 4.3, 'height': 3.8},
        'right': {'x': 5.2, 'y': 1.4, 'width': 4.3, 'height': 3.8}
    },
    'BLANK': {}
}


def generate_id() -> str:
    """Generate a unique object ID for slides elements."""
    return f"obj_{uuid.uuid4().hex[:12]}"


def create_text_box_request(object_id: str, page_id: str, 
                            x: float, y: float, width: float, height: float) -> Dict:
    """Create a text box on a slide."""
    return {
        'createShape': {
            'objectId': object_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': page_id,
                'size': {
                    'width': {'magnitude': inches_to_emu(width), 'unit': 'EMU'},
                    'height': {'magnitude': inches_to_emu(height), 'unit': 'EMU'}
                },
                'transform': {
                    'scaleX': 1.0,
                    'scaleY': 1.0,
                    'translateX': inches_to_emu(x),
                    'translateY': inches_to_emu(y),
                    'unit': 'EMU'
                }
            }
        }
    }


def create_insert_text_request(object_id: str, text: str) -> Dict:
    """Insert text into an element."""
    return {
        'insertText': {
            'objectId': object_id,
            'text': text,
            'insertionIndex': 0
        }
    }


def create_text_style_request(object_id: str, font_size: float, 
                               bold: bool = False, font_family: str = 'Arial') -> Dict:
    """Style text in an element."""
    return {
        'updateTextStyle': {
            'objectId': object_id,
            'style': {
                'fontSize': {'magnitude': font_size, 'unit': 'PT'},
                'fontFamily': font_family,
                'bold': bold
            },
            'textRange': {'type': 'ALL'},
            'fields': 'fontSize,fontFamily,bold'
        }
    }


def create_bullets_request(object_id: str) -> Dict:
    """Add bullet formatting to text."""
    return {
        'createParagraphBullets': {
            'objectId': object_id,
            'textRange': {'type': 'ALL'},
            'bulletPreset': 'BULLET_DISC_CIRCLE_SQUARE'
        }
    }


def create_speaker_notes_request(page_id: str, notes_text: str) -> Dict:
    """Add speaker notes to a slide."""
    return {
        'updateNotesPage': {
            'pageObjectId': page_id,
            'notesPage': {
                'notesProperties': {
                    'speakerNotesObjectId': f"notes_{page_id}"
                }
            }
        }
    }


def add_slide_content(service, presentation_id: str, content: Dict) -> None:
    """
    Add slides with content to a presentation.
    
    Args:
        service: Google Slides API service
        presentation_id: Target presentation ID
        content: Content specification with slides array
    """
    slides_data = content.get('slides', [])
    if not slides_data:
        logger.warning("No slides in content specification")
        return
    
    logger.info(f"Adding {len(slides_data)} slides to presentation {presentation_id}")
    
    # Get existing presentation to find insertion point
    pres = execute_with_retry(
        lambda: service.presentations().get(presentationId=presentation_id)
    )
    existing_slides = len(pres.get('slides', []))
    
    requests = []
    slide_ids = []
    
    # Phase 1: Create all slides first
    for i, slide_data in enumerate(slides_data):
        slide_id = generate_id()
        slide_ids.append(slide_id)
        
        requests.append({
            'createSlide': {
                'objectId': slide_id,
                'insertionIndex': existing_slides + i
            }
        })
    
    # Execute slide creation
    if requests:
        execute_with_retry(
            lambda: service.presentations().batchUpdate(
                presentationId=presentation_id,
                body={'requests': requests}
            )
        )
        logger.info(f"Created {len(slide_ids)} slides")
    
    # Phase 2: Add content to each slide
    for i, (slide_id, slide_data) in enumerate(zip(slide_ids, slides_data)):
        content_requests = []
        layout = slide_data.get('layout', 'TITLE_AND_BODY')
        layout_config = LAYOUTS.get(layout, LAYOUTS['TITLE_AND_BODY'])
        
        # Add title
        title = slide_data.get('title', '')
        if title and 'title' in layout_config:
            title_id = generate_id()
            pos = layout_config['title']
            
            content_requests.append(create_text_box_request(
                title_id, slide_id, pos['x'], pos['y'], pos['width'], pos['height']
            ))
            content_requests.append(create_insert_text_request(title_id, title))
            content_requests.append(create_text_style_request(title_id, 32, bold=True))
        
        # Add subtitle (for TITLE layout)
        subtitle = slide_data.get('subtitle', '')
        if subtitle and 'subtitle' in layout_config:
            subtitle_id = generate_id()
            pos = layout_config['subtitle']
            
            content_requests.append(create_text_box_request(
                subtitle_id, slide_id, pos['x'], pos['y'], pos['width'], pos['height']
            ))
            content_requests.append(create_insert_text_request(subtitle_id, subtitle))
            content_requests.append(create_text_style_request(subtitle_id, 18))
        
        # Add body content (bullets)
        bullets = slide_data.get('bullets', [])
        if bullets and 'body' in layout_config:
            body_id = generate_id()
            pos = layout_config['body']
            
            # Join bullets with newlines
            bullet_text = '\n'.join(bullets)
            
            content_requests.append(create_text_box_request(
                body_id, slide_id, pos['x'], pos['y'], pos['width'], pos['height']
            ))
            content_requests.append(create_insert_text_request(body_id, bullet_text))
            content_requests.append(create_text_style_request(body_id, 18))
            content_requests.append(create_bullets_request(body_id))
        
        # Add two-column content
        left_content = slide_data.get('left_column', [])
        right_content = slide_data.get('right_column', [])
        
        if left_content and 'left' in layout_config:
            left_id = generate_id()
            pos = layout_config['left']
            left_text = '\n'.join(left_content) if isinstance(left_content, list) else left_content
            
            content_requests.append(create_text_box_request(
                left_id, slide_id, pos['x'], pos['y'], pos['width'], pos['height']
            ))
            content_requests.append(create_insert_text_request(left_id, left_text))
            content_requests.append(create_text_style_request(left_id, 16))
            if isinstance(left_content, list):
                content_requests.append(create_bullets_request(left_id))
        
        if right_content and 'right' in layout_config:
            right_id = generate_id()
            pos = layout_config['right']
            right_text = '\n'.join(right_content) if isinstance(right_content, list) else right_content
            
            content_requests.append(create_text_box_request(
                right_id, slide_id, pos['x'], pos['y'], pos['width'], pos['height']
            ))
            content_requests.append(create_insert_text_request(right_id, right_text))
            content_requests.append(create_text_style_request(right_id, 16))
            if isinstance(right_content, list):
                content_requests.append(create_bullets_request(right_id))
        
        # Execute content requests for this slide
        if content_requests:
            execute_with_retry(
                lambda reqs=content_requests: service.presentations().batchUpdate(
                    presentationId=presentation_id,
                    body={'requests': reqs}
                )
            )
            logger.debug(f"Added content to slide {i + 1}")
        
        # Add speaker notes (separate API call)
        notes = slide_data.get('speaker_notes', '')
        if notes:
            add_speaker_notes(service, presentation_id, slide_id, notes)
    
    logger.info(f"✓ Content added to {len(slides_data)} slides")


def add_speaker_notes(service, presentation_id: str, slide_id: str, notes: str) -> None:
    """Add speaker notes to a specific slide."""
    try:
        # Get the slide to find the notes page
        pres = execute_with_retry(
            lambda: service.presentations().get(presentationId=presentation_id)
        )
        
        # Find the slide and its notes page
        for slide in pres.get('slides', []):
            if slide.get('objectId') == slide_id:
                notes_page = slide.get('slideProperties', {}).get('notesPage', {})
                notes_page_id = notes_page.get('objectId')
                
                if notes_page_id:
                    # Find the notes shape (usually contains placeholder text)
                    for element in notes_page.get('pageElements', []):
                        shape = element.get('shape', {})
                        placeholder = shape.get('placeholder', {})
                        if placeholder.get('type') == 'BODY':
                            notes_shape_id = element.get('objectId')
                            
                            # Clear existing text and add new notes
                            requests = [
                                {
                                    'deleteText': {
                                        'objectId': notes_shape_id,
                                        'textRange': {'type': 'ALL'}
                                    }
                                },
                                {
                                    'insertText': {
                                        'objectId': notes_shape_id,
                                        'text': notes,
                                        'insertionIndex': 0
                                    }
                                }
                            ]
                            
                            execute_with_retry(
                                lambda: service.presentations().batchUpdate(
                                    presentationId=presentation_id,
                                    body={'requests': requests}
                                )
                            )
                            logger.debug(f"Added speaker notes to slide {slide_id}")
                            return
        
        logger.warning(f"Could not find notes placeholder for slide {slide_id}")
        
    except Exception as e:
        logger.warning(f"Failed to add speaker notes: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Add slides with content to a Google Slides presentation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Add content from JSON file
  python add_content.py --presentation-id "1ABC..." --content-file slides.json

  # Add content using a named Google account
  python add_content.py --account work --presentation-id "1ABC..." --content-file slides.json

  # Content JSON format:
  {
    "slides": [
      {
        "title": "Welcome",
        "layout": "TITLE",
        "subtitle": "Presentation Subtitle"
      },
      {
        "title": "Key Points",
        "layout": "TITLE_AND_BODY",
        "bullets": ["Point 1", "Point 2", "Point 3"],
        "speaker_notes": "Emphasize point 2"
      }
    ]
  }

Layouts: TITLE, TITLE_AND_BODY, SECTION_HEADER, TITLE_AND_TWO_COLUMNS, BLANK
        '''
    )
    
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)'
    )
    parser.add_argument('--presentation-id', required=True,
                        help='Google Slides presentation ID or URL')
    parser.add_argument('--content-file', required=True,
                        help='JSON file with slide content')
    
    args = parser.parse_args()
    
    try:
        # Extract presentation ID from URL if needed
        pres_id = args.presentation_id
        if 'docs.google.com' in pres_id:
            parts = pres_id.split('/')
            if 'd' in parts:
                pres_id = parts[parts.index('d') + 1]
        
        # Load content
        with open(args.content_file) as f:
            content = json.load(f)
        
        # Build service and add content
        service = build_service('slides', 'v1', account=args.account)
        add_slide_content(service, pres_id, content)
        
        print(f"\n✓ SUCCESS!")
        print(f"  Slides added: {len(content.get('slides', []))}")
        print(f"  View: https://docs.google.com/presentation/d/{pres_id}/edit")
        
    except FileNotFoundError:
        print(f"❌ Error: Content file not found: {args.content_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON in content file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to add content: {str(e)}")
        print(f"❌ Error: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
