from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

TEST_DIR = Path(__file__).resolve().parent
WORKFLOW_DIR = TEST_DIR.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))


class FakeGoogleAuthHelper:
    def __init__(self, *, profile, credential_root, logger_name):
        self.profile = profile
        self.credential_root = Path(credential_root)
        self.logger_name = logger_name

    def normalize_account_alias(self, account):
        return account.lower() if account else None

    def build_service(self, *args, **kwargs):
        return {"args": args, "kwargs": kwargs}


fake_google_auth_core = types.ModuleType("google_auth_core")
fake_google_auth_core.GoogleAuthHelper = FakeGoogleAuthHelper
ns = sys.modules.setdefault("google_auth_core", fake_google_auth_core)
ns.GoogleAuthHelper = FakeGoogleAuthHelper

import _env
import drive_helpers
import gdocs_auth


class FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeFilesResource:
    def __init__(self):
        self.get_calls = []
        self.update_calls = []
        self.create_calls = []

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        response = {"id": kwargs["fileId"], "parents": ["root"], "mimeType": "application/vnd.google-apps.document"}
        if kwargs.get("fields") != "id,parents":
            response.update({"name": "Spec Doc", "webViewLink": "https://drive.google.com/open?id=file-123"})
        return FakeRequest(response)

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return FakeRequest({
            "id": kwargs["fileId"],
            "name": "Spec Doc",
            "mimeType": "application/vnd.google-apps.document",
            "parents": [kwargs["addParents"]],
            "webViewLink": "https://drive.google.com/open?id=file-123",
        })

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        body = kwargs["body"]
        return FakeRequest({
            "id": "folder-123",
            "name": body["name"],
            "mimeType": body["mimeType"],
            "parents": body.get("parents", []),
            "webViewLink": "https://drive.google.com/drive/folders/folder-123",
        })


class FakePermissionsResource:
    def __init__(self):
        self.create_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        body = kwargs["body"]
        return FakeRequest({
            "id": "perm-123",
            "type": body["type"],
            "role": body["role"],
            "emailAddress": body.get("emailAddress"),
            "domain": body.get("domain"),
            "allowFileDiscovery": False,
        })


class FakeCommentsResource:
    def __init__(self):
        self.create_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        body = kwargs["body"]
        return FakeRequest({
            "id": "comment-123",
            "content": body["content"],
            "anchor": body.get("anchor"),
            "quotedFileContent": body.get("quotedFileContent", {}),
            "resolved": False,
        })


class FakeDriveService:
    def __init__(self):
        self.files_resource = FakeFilesResource()
        self.permissions_resource = FakePermissionsResource()
        self.comments_resource = FakeCommentsResource()

    def files(self):
        return self.files_resource

    def permissions(self):
        return self.permissions_resource

    def comments(self):
        return self.comments_resource


class EnvAndAuthTests(unittest.TestCase):
    def test_env_paths_stay_workflow_local(self):
        self.assertEqual(_env.SCRIPT_DIR, WORKFLOW_DIR)
        self.assertEqual(_env.CREDENTIALS_DIR, WORKFLOW_DIR / "credentials")

    def test_build_helper_uses_workflow_local_google_auth_paths(self):
        helper = gdocs_auth.build_helper()
        self.assertEqual(helper.credential_root, WORKFLOW_DIR / "credentials")


class DriveHelperTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeDriveService()

    def test_resolve_drive_id_accepts_docs_file_and_folder_urls(self):
        self.assertEqual(drive_helpers.resolve_drive_id("https://docs.google.com/document/d/doc-123/edit"), "doc-123")
        self.assertEqual(drive_helpers.resolve_drive_id("https://drive.google.com/file/d/file-123/view"), "file-123")
        self.assertEqual(drive_helpers.resolve_drive_id("https://drive.google.com/drive/folders/folder-123"), "folder-123")
        self.assertEqual(drive_helpers.resolve_drive_id("https://drive.google.com/open?id=file-789"), "file-789")

    def test_get_file_info_adds_document_url(self):
        result = drive_helpers.get_file_info(self.service, "file-123")
        self.assertEqual(result["url"], "https://docs.google.com/document/d/file-123/edit")
        self.assertEqual(self.service.files_resource.get_calls[0]["fields"], drive_helpers.DEFAULT_INFO_FIELDS)

    def test_create_folder_passes_parent_when_given(self):
        result = drive_helpers.create_folder(self.service, "Specs", parent_id="parent-123")
        self.assertEqual(result["parents"], ["parent-123"])
        self.assertEqual(self.service.files_resource.create_calls[0]["body"]["mimeType"], drive_helpers.FOLDER_MIME_TYPE)

    def test_move_file_to_folder_replaces_existing_parents(self):
        result = drive_helpers.move_file_to_folder(self.service, "file-123", "folder-456")
        self.assertEqual(result["parents"], ["folder-456"])
        self.assertEqual(self.service.files_resource.update_calls[0]["removeParents"], "root")
        self.assertEqual(self.service.files_resource.update_calls[0]["addParents"], "folder-456")

    def test_create_permission_infers_user_type_from_email(self):
        result = drive_helpers.create_permission(
            self.service,
            "file-123",
            role="writer",
            email_address="person@example.com",
            send_notification_email=False,
        )
        self.assertEqual(result["type"], "user")
        create_call = self.service.permissions_resource.create_calls[0]
        self.assertFalse(create_call["sendNotificationEmail"])
        self.assertEqual(create_call["body"]["emailAddress"], "person@example.com")

    def test_create_comment_passes_anchor_and_quote(self):
        result = drive_helpers.create_comment(
            self.service,
            "file-123",
            "Need revision",
            anchor='{"r":"head"}',
            quoted_file_content="Original line",
        )
        self.assertEqual(result["content"], "Need revision")
        self.assertEqual(result["anchor"], '{"r":"head"}')
        self.assertEqual(result["quotedFileContent"]["value"], "Original line")

    def test_main_dispatches_share_subcommand(self):
        with mock.patch.object(drive_helpers, "build_drive_service", return_value=self.service), mock.patch.object(
            drive_helpers, "write_json"
        ) as write_json:
            exit_code = drive_helpers.main([
                "--account",
                "work",
                "share",
                "--file-id",
                "file-123",
                "--email",
                "person@example.com",
                "--role",
                "commenter",
            ])
        self.assertEqual(exit_code, 0)
        self.assertEqual(self.service.permissions_resource.create_calls[0]["body"]["role"], "commenter")
        write_json.assert_called_once()


if __name__ == "__main__":
    unittest.main()
