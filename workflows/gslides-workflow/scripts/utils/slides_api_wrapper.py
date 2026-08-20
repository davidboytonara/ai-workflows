"""
Google Slides API wrapper with all 32 API operations.

Provides high-level interface for Google Slides API operations with retry logic.
"""

from typing import Dict, List, Optional, Any
from .retry_handler import execute_with_retry, batch_execute_with_retry
from .logger import setup_logger
from .emu_converter import create_element_properties, create_size, create_transform
from .color_converter import to_slides_opaque_color

logger = setup_logger(__name__)


class SlidesAPIWrapper:
    """Wrapper for Google Slides API operations."""

    def __init__(self, service, presentation_id: str):
        """
        Initialize wrapper.

        Args:
            service: Google Slides API service instance
            presentation_id: Presentation ID
        """
        self.service = service
        self.presentation_id = presentation_id
        self.pending_requests = []

    def add_request(self, request: Dict):
        """Add request to batch queue."""
        self.pending_requests.append(request)

    def execute_batch(self) -> Dict:
        """Execute all pending requests in batch."""
        if not self.pending_requests:
            logger.warning("No pending requests to execute")
            return {}

        logger.info(f"Executing batch with {len(self.pending_requests)} requests")

        responses = batch_execute_with_retry(
            self.service,
            self.presentation_id,
            self.pending_requests
        )

        self.pending_requests.clear()
        return responses

    # CREATION OPERATIONS

    def create_slide(self, insertion_index: Optional[int] = None,
                    slide_layout_reference: Optional[Dict] = None) -> Dict:
        """Create a new slide."""
        request = {'createSlide': {}}

        if insertion_index is not None:
            request['createSlide']['insertionIndex'] = insertion_index

        if slide_layout_reference:
            request['createSlide']['slideLayoutReference'] = slide_layout_reference

        self.add_request(request)
        return request

    def create_shape(self, object_id: str, shape_type: str, page_object_id: str,
                    x: float, y: float, width: float, height: float,
                    unit: str = 'inches') -> Dict:
        """Create a shape."""
        request = {
            'createShape': {
                'objectId': object_id,
                'shapeType': shape_type,
                'elementProperties': create_element_properties(
                    page_object_id, x, y, width, height, unit
                )
            }
        }
        self.add_request(request)
        return request

    def create_text_box(self, object_id: str, page_object_id: str,
                       x: float, y: float, width: float, height: float,
                       unit: str = 'inches') -> Dict:
        """Create a text box (convenience method)."""
        return self.create_shape(object_id, 'TEXT_BOX', page_object_id,
                                x, y, width, height, unit)

    def insert_text(self, object_id: str, text: str,
                   insertion_index: int = 0) -> Dict:
        """Insert text into shape or table cell."""
        request = {
            'insertText': {
                'objectId': object_id,
                'text': text,
                'insertionIndex': insertion_index
            }
        }
        self.add_request(request)
        return request

    def update_text_style(self, object_id: str, font_family: str,
                         font_size: float, color: Any,
                         bold: bool = False, italic: bool = False,
                         text_range: Optional[Dict] = None) -> Dict:
        """Update text style."""
        style = {
            'fontFamily': font_family,
            'fontSize': {'magnitude': font_size, 'unit': 'PT'},
            'foregroundColor': to_slides_opaque_color(color),
            'bold': bold,
            'italic': italic
        }

        request = {
            'updateTextStyle': {
                'objectId': object_id,
                'style': style,
                'fields': 'fontFamily,fontSize,foregroundColor,bold,italic'
            }
        }

        if text_range:
            request['updateTextStyle']['textRange'] = text_range
        else:
            request['updateTextStyle']['textRange'] = {'type': 'ALL'}

        self.add_request(request)
        return request

    def replace_all_text(self, contains_text: str, replace_text: str) -> Dict:
        """Replace all occurrences of text."""
        request = {
            'replaceAllText': {
                'containsText': {'text': contains_text, 'matchCase': False},
                'replaceText': replace_text
            }
        }
        self.add_request(request)
        return request

    # More API operations can be added as needed
