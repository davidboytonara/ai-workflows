#!/usr/bin/env python3
"""
Apply brand guidelines to Google Slides presentations.

Accepts brand guidelines JSON and applies colors, fonts, logo, and spacing.
"""

import sys
import os
import json
import argparse
import warnings
from typing import Dict, Any, Optional

# Suppress known non-critical warnings
warnings.filterwarnings('ignore', message='.*importlib.metadata.*')
warnings.filterwarnings('ignore', category=FutureWarning, module='google.api_core')
warnings.filterwarnings('ignore', message='.*urllib3.*OpenSSL.*')

sys.path.insert(0, os.path.dirname(__file__))

from utils.slides_api_wrapper import SlidesAPIWrapper
from utils.auth_helper import build_service
from utils.color_converter import hex_to_rgb_normalized, to_slides_opaque_color
from utils.font_mapper import normalize_font_name
from utils.logger import setup_logger
from utils.retry_handler import execute_with_retry
from utils.emu_converter import inches_to_emu

logger = setup_logger(__name__)


def apply_brand_to_presentation(
    presentation_id: str,
    brand_spec: Dict,
    account: Optional[str] = None,
):
    """
    Apply brand guidelines to presentation.

    Args:
        presentation_id: Google Slides presentation ID
        brand_spec: Brand guidelines specification
    """
    logger.info(f"Applying brand guidelines to presentation {presentation_id}")

    service = build_service('slides', 'v1', account=account)
    wrapper = SlidesAPIWrapper(service, presentation_id)

    brand = brand_spec.get('brand', {})

    # Apply logo if specified
    if 'logo' in brand and brand['logo'].get('url'):
        apply_logo(wrapper, brand['logo'])

    # Apply colors to all slides
    colors = brand.get('colors', {})
    fonts = brand.get('fonts', {})

    # Get presentation to iterate slides
    pres = execute_with_retry(lambda: service.presentations().get(
        presentationId=presentation_id
    ))
    slides = pres.get('slides', [])

    logger.info(f"Processing {len(slides)} slides")

    for slide in slides:
        slide_id = slide.get('objectId')
        apply_brand_to_slide(wrapper, slide_id, colors, fonts)

    # Execute all brand application requests
    wrapper.execute_batch()

    logger.info("Brand guidelines applied successfully")


def apply_logo(wrapper: SlidesAPIWrapper, logo_spec: Dict[str, Any]) -> None:
    """
    Apply logo to slides.

    Args:
        wrapper: SlidesAPIWrapper instance
        logo_spec: Logo specification dict with:
            - url: URL of logo image
            - position: Optional position dict (x, y, width, height in inches)
            - placement: 'all_slides', 'first_slide', or 'title_slides' (default: 'all_slides')
    """
    logo_url = logo_spec.get('url')
    if not logo_url:
        logger.warning("Logo URL not provided, skipping logo application")
        return

    # Get presentation to iterate slides
    pres = execute_with_retry(lambda: wrapper.service.presentations().get(
        presentationId=wrapper.presentation_id
    ))
    slides = pres.get('slides', [])

    # Default position: top-right corner
    position = logo_spec.get('position', {
        'x': 9.0,  # inches from left
        'y': 0.25,  # inches from top
        'width': 0.75,  # inches
        'height': 0.75   # inches
    })

    placement = logo_spec.get('placement', 'all_slides')

    for idx, slide in enumerate(slides):
        slide_id = slide.get('objectId')

        # Determine if logo should be placed on this slide
        should_place = False
        if placement == 'all_slides':
            should_place = True
        elif placement == 'first_slide' and idx == 0:
            should_place = True
        elif placement == 'title_slides':
            # Check if slide has a title layout (heuristic: check for 'TITLE' in layout type)
            layout_properties = slide.get('slideProperties', {}).get('layoutObjectId', '')
            should_place = 'TITLE' in layout_properties.upper()

        if should_place:
            # Create unique object ID for logo
            logo_object_id = f"logo_{slide_id}"

            # Create image request
            request = {
                'createImage': {
                    'objectId': logo_object_id,
                    'url': logo_url,
                    'elementProperties': {
                        'pageObjectId': slide_id,
                        'size': {
                            'width': {'magnitude': inches_to_emu(position['width']), 'unit': 'EMU'},
                            'height': {'magnitude': inches_to_emu(position['height']), 'unit': 'EMU'}
                        },
                        'transform': {
                            'scaleX': 1.0,
                            'scaleY': 1.0,
                            'translateX': inches_to_emu(position['x']),
                            'translateY': inches_to_emu(position['y']),
                            'unit': 'EMU'
                        }
                    }
                }
            }
            wrapper.add_request(request)
            logger.debug(f"Added logo to slide {idx + 1}: {slide_id}")

    logger.info(f"Logo placement configured for {len(slides)} slides with '{placement}' strategy")


def apply_brand_to_slide(wrapper: SlidesAPIWrapper, slide_id: str,
                        colors: Dict[str, Any], fonts: Dict[str, Any]) -> None:
    """
    Apply brand colors and fonts to a specific slide.

    Args:
        wrapper: SlidesAPIWrapper instance
        slide_id: Slide object ID
        colors: Brand colors dict with keys like 'primary', 'secondary', 'accent', 'text'
        fonts: Brand fonts dict with keys like 'heading', 'body', 'default'
    """
    # Get slide details
    pres = execute_with_retry(lambda: wrapper.service.presentations().get(
        presentationId=wrapper.presentation_id
    ))

    # Find the specific slide
    slide = None
    for s in pres.get('slides', []):
        if s.get('objectId') == slide_id:
            slide = s
            break

    if not slide:
        logger.warning(f"Slide {slide_id} not found")
        return

    # Get all page elements on the slide
    page_elements = slide.get('pageElements', [])

    for element in page_elements:
        element_id = element.get('objectId')

        # Apply to text elements (shapes with text)
        if 'shape' in element:
            shape = element['shape']
            shape_type = shape.get('shapeType')

            # Apply text styling if shape contains text
            if 'text' in shape:
                # Determine if this is a title or body text based on placeholder type
                placeholder = shape.get('placeholder', {})
                placeholder_type = placeholder.get('type', '')

                # Apply appropriate font
                if 'TITLE' in placeholder_type or 'SUBTITLE' in placeholder_type:
                    font_family = fonts.get('heading', fonts.get('default', 'Arial'))
                else:
                    font_family = fonts.get('body', fonts.get('default', 'Arial'))

                # Normalize font name
                font_family = normalize_font_name(font_family)

                # Apply text color
                text_color = colors.get('text', '#000000')

                # Update text style request
                request = {
                    'updateTextStyle': {
                        'objectId': element_id,
                        'style': {
                            'fontFamily': font_family,
                            'foregroundColor': to_slides_opaque_color(text_color)
                        },
                        'textRange': {'type': 'ALL'},
                        'fields': 'fontFamily,foregroundColor'
                    }
                }
                wrapper.add_request(request)
                logger.debug(f"Applied brand text style to element: {element_id}")

            # Apply shape fill color for non-text shapes
            if shape_type != 'TEXT_BOX' and colors.get('accent'):
                request = {
                    'updateShapeProperties': {
                        'objectId': element_id,
                        'shapeProperties': {
                            'shapeBackgroundFill': {
                                'solidFill': to_slides_opaque_color(colors.get('accent'))
                            }
                        },
                        'fields': 'shapeBackgroundFill.solidFill'
                    }
                }
                wrapper.add_request(request)
                logger.debug(f"Applied brand accent color to shape: {element_id}")

        # Apply background color to slide if primary color specified
        if colors.get('background'):
            request = {
                'updatePageProperties': {
                    'objectId': slide_id,
                    'pageProperties': {
                        'pageBackgroundFill': {
                            'solidFill': to_slides_opaque_color(colors.get('background'))
                        }
                    },
                    'fields': 'pageBackgroundFill.solidFill'
                }
            }
            # Only add once per slide (check if not already added)
            if request not in wrapper.pending_requests:
                wrapper.add_request(request)
                logger.debug(f"Applied background color to slide: {slide_id}")

    logger.debug(f"Brand application completed for slide: {slide_id}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Apply brand guidelines to Google Slides presentation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Apply brand guidelines from JSON file
  python apply_brand.py --presentation-id "1ABC..." --brand-file brand.json

  # Apply brand guidelines using a named Google account
  python apply_brand.py --account work --presentation-id "1ABC..." --brand-file brand.json

  # Where brand.json contains:
  {
    "brand": {
      "colors": {
        "primary": "#141413",
        "background": "#faf9f5",
        "text": "#333333"
      },
      "fonts": {
        "heading": "Poppins",
        "body": "Lora"
      }
    }
  }

Note: Must be run from skill root directory.
        '''
    )
    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)'
    )
    parser.add_argument('--presentation-id', required=True,
                       help='Google Slides presentation ID or URL')
    parser.add_argument('--brand-file', required=True,
                       help='Path to brand guidelines JSON file')
    args = parser.parse_args()

    try:
        with open(args.brand_file) as f:
            brand_spec = json.load(f)

        apply_brand_to_presentation(args.presentation_id, brand_spec, account=args.account)
        print(f"\n✓ SUCCESS! Brand guidelines applied")
        print(f"View: https://docs.google.com/presentation/d/{args.presentation_id}/edit")

    except FileNotFoundError:
        print(f"❌ Error: Brand file not found: {args.brand_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON in brand file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        sys.exit(1)
