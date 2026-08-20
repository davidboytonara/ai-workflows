import sys
import types
import unittest
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parents[1]
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

fake_gdocs_auth = types.ModuleType("gdocs_auth")
fake_gdocs_auth.build_docs_service = lambda account=None: None
fake_gdocs_auth.build_drive_service = lambda account=None: None
fake_gdocs_auth.build_helper = lambda: types.SimpleNamespace(credential_root=WORKFLOW_DIR / "credentials")
sys.modules.setdefault("gdocs_auth", fake_gdocs_auth)

from gdocs_common import (  # noqa: E402
    build_insert_image_request,
    build_insert_table_request,
)
from get_doc_content import _content_summary  # noqa: E402
from update_document import _friendly_requests, _normalize_operations  # noqa: E402


class RequestHelpersTest(unittest.TestCase):
    def test_build_insert_table_request_with_tab(self) -> None:
        request, summary, estimated_delta = build_insert_table_request(
            {"rows": 2, "columns": 3, "index": 9, "tabId": "tab-1"}
        )

        self.assertEqual(
            request,
            {
                "insertTable": {
                    "rows": 2,
                    "columns": 3,
                    "location": {"index": 9, "tabId": "tab-1"},
                }
            },
        )
        self.assertEqual(
            summary,
            {"op": "insert_table", "index": 9, "rows": 2, "columns": 3, "tabId": "tab-1"},
        )
        self.assertEqual(estimated_delta, 15)

    def test_build_insert_image_request_with_object_size(self) -> None:
        request, summary, estimated_delta = build_insert_image_request(
            {
                "uri": "https://example.com/image.png",
                "index": 12,
                "width": 144,
                "height": {"magnitude": 72, "unit": "pt"},
            }
        )

        self.assertEqual(
            request,
            {
                "insertInlineImage": {
                    "uri": "https://example.com/image.png",
                    "location": {"index": 12},
                    "objectSize": {
                        "width": {"magnitude": 144.0, "unit": "PT"},
                        "height": {"magnitude": 72.0, "unit": "PT"},
                    },
                }
            },
        )
        self.assertEqual(
            summary,
            {
                "op": "insert_image",
                "index": 12,
                "uri": "https://example.com/image.png",
                "objectSize": {
                    "width": {"magnitude": 144.0, "unit": "PT"},
                    "height": {"magnitude": 72.0, "unit": "PT"},
                },
            },
        )
        self.assertEqual(estimated_delta, 1)

    def test_friendly_requests_support_table_and_image_insertions(self) -> None:
        requests, normalized_ops, estimated_end_index = _friendly_requests(
            [
                {"op": "insert_table", "rows": 2, "columns": 2},
                {"op": "insert_image", "uri": "https://example.com/image.png", "width": 144},
            ],
            initial_text="hello\n",
            initial_end_index=7,
        )

        self.assertEqual(
            requests,
            [
                {"insertTable": {"rows": 2, "columns": 2, "location": {"index": 6}}},
                {
                    "insertInlineImage": {
                        "uri": "https://example.com/image.png",
                        "location": {"index": 17},
                        "objectSize": {"width": {"magnitude": 144.0, "unit": "PT"}},
                    }
                },
            ],
        )
        self.assertEqual(
            normalized_ops,
            [
                {"op": "insert_table", "index": 6, "rows": 2, "columns": 2},
                {
                    "op": "insert_image",
                    "index": 17,
                    "uri": "https://example.com/image.png",
                    "objectSize": {"width": {"magnitude": 144.0, "unit": "PT"}},
                },
            ],
        )
        self.assertEqual(estimated_end_index, 19)

    def test_normalize_operations_preserves_raw_write_control(self) -> None:
        operations, raw_batch = _normalize_operations(
            {
                "requests": [{"insertText": {"location": {"index": 1}, "text": "x"}}],
                "writeControl": {"requiredRevisionId": "rev-1"},
            }
        )

        self.assertIsNone(operations)
        self.assertEqual(
            raw_batch,
            {
                "requests": [{"insertText": {"location": {"index": 1}, "text": "x"}}],
                "writeControl": {"requiredRevisionId": "rev-1"},
            },
        )


class InspectSummaryTest(unittest.TestCase):
    def test_content_summary_exposes_table_and_inline_image_metadata(self) -> None:
        document = {
            "inlineObjects": {
                "kix.inlineobj.1": {
                    "inlineObjectProperties": {
                        "embeddedObject": {
                            "title": "Diagram",
                            "description": "Architecture",
                            "size": {
                                "height": {"magnitude": 50, "unit": "PT"},
                                "width": {"magnitude": 100, "unit": "PT"},
                            },
                            "imageProperties": {
                                "contentUri": "https://lh3.googleusercontent.com/image",
                                "sourceUri": "https://example.com/source.png",
                            },
                        }
                    }
                }
            },
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 13,
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "Intro "}},
                                {"inlineObjectElement": {"inlineObjectId": "kix.inlineobj.1"}},
                                {"textRun": {"content": "\n"}},
                            ],
                            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                        },
                    },
                    {
                        "startIndex": 13,
                        "endIndex": 31,
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "content": [
                                                {
                                                    "paragraph": {
                                                        "elements": [{"textRun": {"content": "A1\n"}}]
                                                    }
                                                }
                                            ]
                                        },
                                        {
                                            "content": [
                                                {
                                                    "paragraph": {
                                                        "elements": [{"textRun": {"content": "B1\n"}}]
                                                    }
                                                }
                                            ]
                                        },
                                    ]
                                },
                                {
                                    "tableCells": [
                                        {
                                            "content": [
                                                {
                                                    "paragraph": {
                                                        "elements": [{"textRun": {"content": "A2\n"}}]
                                                    }
                                                }
                                            ]
                                        },
                                        {
                                            "content": [
                                                {
                                                    "paragraph": {
                                                        "elements": [
                                                            {"inlineObjectElement": {"inlineObjectId": "kix.inlineobj.1"}},
                                                            {"textRun": {"content": "\n"}},
                                                        ]
                                                    }
                                                }
                                            ]
                                        },
                                    ]
                                },
                            ]
                        },
                    },
                ]
            },
        }

        content_items, outline, inline_objects = _content_summary(document)

        self.assertEqual(outline, [])
        self.assertEqual(
            inline_objects,
            [
                {
                    "inlineObjectId": "kix.inlineobj.1",
                    "title": "Diagram",
                    "description": "Architecture",
                    "contentUri": "https://lh3.googleusercontent.com/image",
                    "sourceUri": "https://example.com/source.png",
                    "size": {
                        "height": {"magnitude": 50, "unit": "PT"},
                        "width": {"magnitude": 100, "unit": "PT"},
                    },
                }
            ],
        )
        self.assertEqual(
            content_items,
            [
                {
                    "type": "paragraph",
                    "startIndex": 1,
                    "endIndex": 13,
                    "namedStyleType": "NORMAL_TEXT",
                    "text": "Intro [INLINE_OBJECT]",
                    "inlineObjectIds": ["kix.inlineobj.1"],
                },
                {
                    "type": "table",
                    "startIndex": 13,
                    "endIndex": 31,
                    "rows": 2,
                    "columns": 2,
                    "cellCount": 4,
                    "cells": [
                        [
                            {"text": "A1", "inlineObjectIds": []},
                            {"text": "B1", "inlineObjectIds": []},
                        ],
                        [
                            {"text": "A2", "inlineObjectIds": []},
                            {"text": "[INLINE_OBJECT]", "inlineObjectIds": ["kix.inlineobj.1"]},
                        ],
                    ],
                    "cellText": [["A1", "B1"], ["A2", "[INLINE_OBJECT]"]],
                    "inlineObjectIds": ["kix.inlineobj.1"],
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
