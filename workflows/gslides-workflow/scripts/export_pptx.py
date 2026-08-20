#!/usr/bin/env python3
"""
Export Google Slides presentation to PowerPoint (PPTX) format.

Downloads a Google Slides presentation as a .pptx file.
"""

import sys
import os
import argparse
import warnings
from typing import Optional

# Suppress known non-critical warnings
warnings.filterwarnings('ignore', message='.*importlib.metadata.*')
warnings.filterwarnings('ignore', category=FutureWarning, module='google.api_core')
warnings.filterwarnings('ignore', message='.*urllib3.*OpenSSL.*')

sys.path.insert(0, os.path.dirname(__file__))

from utils.auth_helper import build_service
from utils.logger import setup_logger
from utils.retry_handler import execute_with_retry

logger = setup_logger(__name__)


def extract_presentation_id(url_or_id: str) -> str:
    """
    Extract presentation ID from URL or return ID as-is.

    Args:
        url_or_id: Google Slides URL or presentation ID

    Returns:
        Presentation ID

    Examples:
        >>> extract_presentation_id("1ABC123XYZ")
        "1ABC123XYZ"
        >>> extract_presentation_id("https://docs.google.com/presentation/d/1ABC123XYZ/edit")
        "1ABC123XYZ"
    """
    if url_or_id.startswith('http'):
        # Extract ID from URL
        # Format: https://docs.google.com/presentation/d/PRESENTATION_ID/edit
        parts = url_or_id.split('/')
        if 'd' in parts:
            id_index = parts.index('d') + 1
            if id_index < len(parts):
                return parts[id_index]
    return url_or_id


def export_presentation_to_pptx(
    presentation_id: str,
    output_file: str,
    account: Optional[str] = None,
) -> None:
    """
    Export Google Slides presentation to PowerPoint format.

    Args:
        presentation_id: Google Slides presentation ID
        output_file: Path to output PPTX file
    """
    logger.info(f"Exporting presentation {presentation_id} to {output_file}")

    # Build Drive service (exports are done via Drive API)
    drive_service = build_service('drive', 'v3', account=account)

    # Export as PPTX
    # MIME type for PowerPoint: application/vnd.openxmlformats-officedocument.presentationml.presentation
    export_request = drive_service.files().export_media(
        fileId=presentation_id,
        mimeType='application/vnd.openxmlformats-officedocument.presentationml.presentation'
    )

    # Execute with retry
    file_content = execute_with_retry(lambda: export_request)

    # Write to file
    with open(output_file, 'wb') as f:
        f.write(file_content)

    logger.info(f"✓ Presentation exported successfully to {output_file}")


def get_presentation_title(
    presentation_id: str,
    account: Optional[str] = None,
) -> Optional[str]:
    """
    Get presentation title from Google Slides.

    Args:
        presentation_id: Google Slides presentation ID

    Returns:
        Presentation title or None if not found
    """
    try:
        slides_service = build_service('slides', 'v1', account=account)
        presentation = execute_with_retry(
            lambda: slides_service.presentations().get(presentationId=presentation_id)
        )
        return presentation.get('title', 'Untitled')
    except Exception as e:
        logger.warning(f"Could not retrieve presentation title: {e}")
        return None


def main():
    """Main export function."""
    parser = argparse.ArgumentParser(
        description='Export Google Slides presentation to PowerPoint (PPTX)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Export by presentation ID
  python export_pptx.py --presentation-id "1ABC123XYZ" --output presentation.pptx

  # Export by URL
  python export_pptx.py --presentation-id "https://docs.google.com/presentation/d/1ABC.../edit" --output deck.pptx

  # Export with a named Google account
  python export_pptx.py --account work --presentation-id "1ABC123XYZ" --output team-deck.pptx

  # Auto-generate filename from presentation title
  python export_pptx.py --presentation-id "1ABC123XYZ"

Note: Must be run from skill root directory or have authentication configured.
        '''
    )

    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)'
    )
    parser.add_argument('--presentation-id', required=True,
                       help='Google Slides presentation ID or URL')
    parser.add_argument('--output',
                       help='Output PPTX file path (default: auto-generated from title)')

    args = parser.parse_args()

    try:
        # Extract presentation ID from URL if needed
        presentation_id = extract_presentation_id(args.presentation_id)
        logger.info(f"Presentation ID: {presentation_id}")

        # Determine output filename
        if args.output:
            output_file = args.output
        else:
            # Auto-generate filename from title
            title = get_presentation_title(presentation_id, account=args.account)
            if title:
                # Sanitize filename (remove invalid characters)
                safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                output_file = f"{safe_title}.pptx"
            else:
                output_file = f"presentation_{presentation_id}.pptx"

        logger.info(f"Output file: {output_file}")

        # Export presentation
        export_presentation_to_pptx(presentation_id, output_file, account=args.account)

        # Success message
        print(f"\n✓ SUCCESS!")
        print(f"  Presentation ID: {presentation_id}")
        print(f"  Exported to: {output_file}")

        # Show file size
        file_size = os.path.getsize(output_file)
        file_size_mb = file_size / (1024 * 1024)
        print(f"  File size: {file_size_mb:.2f} MB")

    except Exception as e:
        logger.error(f"Failed to export presentation: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
