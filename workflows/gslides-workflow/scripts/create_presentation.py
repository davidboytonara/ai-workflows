#!/usr/bin/env python3
"""
Create Google Slides presentation from specification.

Main script for creating presentations with brand guidelines and content.
"""

import sys
import os
import json
import argparse
import warnings
from typing import Dict, Optional

# Suppress known non-critical warnings
warnings.filterwarnings('ignore', message='.*importlib.metadata.*')
warnings.filterwarnings('ignore', category=FutureWarning, module='google.api_core')
warnings.filterwarnings('ignore', message='.*urllib3.*OpenSSL.*')

sys.path.insert(0, os.path.dirname(__file__))

from utils.auth_helper import build_service
from utils.slides_api_wrapper import SlidesAPIWrapper
from utils.logger import setup_logger, log_success
from utils.retry_handler import execute_with_retry

logger = setup_logger(__name__)


def create_presentation_from_template(
    template_id: str,
    title: str,
    account: Optional[str] = None,
) -> str:
    """
    Create presentation by copying template.

    Args:
        template_id: Google Drive template ID
        title: New presentation title

    Returns:
        New presentation ID
    """
    logger.info(f"Creating presentation from template: {template_id}")

    drive_service = build_service('drive', 'v3', account=account)

    # Copy template
    copy_request = drive_service.files().copy(
        fileId=template_id,
        body={'name': title}
    )

    copied_file = execute_with_retry(lambda: copy_request)
    presentation_id = copied_file['id']

    logger.info(f"✓ Presentation created: {presentation_id}")
    return presentation_id


def create_blank_presentation(title: str, account: Optional[str] = None) -> str:
    """
    Create blank presentation.

    Args:
        title: Presentation title

    Returns:
        Presentation ID
    """
    logger.info(f"Creating blank presentation: {title}")

    slides_service = build_service('slides', 'v1', account=account)

    create_request = slides_service.presentations().create(
        body={'title': title}
    )

    presentation = execute_with_retry(lambda: create_request)
    presentation_id = presentation['presentationId']

    logger.info(f"✓ Presentation created: {presentation_id}")
    return presentation_id


def main():
    """Main creation function."""
    parser = argparse.ArgumentParser(
        description='Create Google Slides presentation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Create blank presentation
  python create_presentation.py --title "My Presentation"

  # Create from template
  python create_presentation.py --title "Q4 Review" --template-id "1ABC..."

  # Create with brand guidelines
  python create_presentation.py --title "Branded Deck" --brand-file brand.json

  # Create using a named Google account
  python create_presentation.py --account work --title "Team Review"

  # Create and export to PowerPoint
  python create_presentation.py --title "Export Test" --export-pptx

Note: Must be run from skill root directory.
        '''
    )

    parser.add_argument(
        '--account',
        help='Account alias to select a non-default OAuth token (for example: work or personal)'
    )
    parser.add_argument('--title', required=True, help='Presentation title')
    parser.add_argument('--template-id', help='Template ID (optional)')
    parser.add_argument('--spec-file', help='Presentation specification JSON')
    parser.add_argument('--brand-file', help='Brand guidelines JSON')
    parser.add_argument('--export-pptx', action='store_true', help='Export to PPTX')
    parser.add_argument('--output', default='presentation_info.json',
                       help='Output file for presentation info')

    args = parser.parse_args()

    try:
        # Create presentation
        if args.template_id:
            presentation_id = create_presentation_from_template(
                args.template_id,
                args.title,
                account=args.account,
            )
        else:
            presentation_id = create_blank_presentation(args.title, account=args.account)

        # Generate presentation URL
        url = f"https://docs.google.com/presentation/d/{presentation_id}/edit"

        # Save output
        output_data = {
            'presentation_id': presentation_id,
            'url': url,
            'title': args.title
        }

        with open(args.output, 'w') as f:
            json.dump(output_data, f, indent=2)

        # Log success
        log_success(logger, "Create Presentation", output_data)

        print(f"\n✓ SUCCESS!")
        print(f"  Presentation ID: {presentation_id}")
        print(f"  URL: {url}")
        print(f"  Output saved to: {args.output}")

    except Exception as e:
        logger.error(f"Failed to create presentation: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
