#!/usr/bin/env python3
"""Google Drive helpers for Google Docs workflow.

Exit codes:
  0  success
  1  business / API failure
  2  usage error
"""

from __future__ import annotations

import argparse
import re
from typing import Any

from gdocs_auth import build_drive_service
from gdocs_common import write_json

DOCUMENT_URL_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")
FILE_URL_RE = re.compile(r"/file/d/([a-zA-Z0-9_-]+)")
FOLDER_URL_RE = re.compile(r"/folders/([a-zA-Z0-9_-]+)")
QUERY_ID_RE = re.compile(r"[?&]id=([a-zA-Z0-9_-]+)")
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DEFAULT_INFO_FIELDS = (
    "id,name,mimeType,parents,webViewLink,owners(displayName,emailAddress),"
    "shared,trashed"
)
DEFAULT_PERMISSION_FIELDS = "id,type,role,emailAddress,domain,allowFileDiscovery"
DEFAULT_COMMENT_FIELDS = (
    "id,content,anchor,quotedFileContent/value,resolved,createdTime,modifiedTime,"
    "author/displayName,author/emailAddress,htmlContent"
)


def resolve_drive_id(value: str) -> str:
    for pattern in (DOCUMENT_URL_RE, FILE_URL_RE, FOLDER_URL_RE, QUERY_ID_RE):
        match = pattern.search(value)
        if match:
            return match.group(1)
    return value



def build_file_url(file_id: str, mime_type: str | None = None) -> str:
    if mime_type == "application/vnd.google-apps.document":
        return f"https://docs.google.com/document/d/{file_id}/edit"
    return f"https://drive.google.com/file/d/{file_id}/view"



def get_file_info(
    service,
    file_id: str,
    *,
    fields: str = DEFAULT_INFO_FIELDS,
) -> dict[str, Any]:
    info = service.files().get(fileId=file_id, fields=fields).execute()
    info.setdefault("url", build_file_url(file_id, info.get("mimeType")))
    return info



def create_folder(
    service,
    name: str,
    *,
    parent_id: str | None = None,
    fields: str = "id,name,mimeType,parents,webViewLink",
) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME_TYPE}
    if parent_id:
        body["parents"] = [parent_id]
    created = service.files().create(body=body, fields=fields).execute()
    created.setdefault("url", created.get("webViewLink") or f"https://drive.google.com/drive/folders/{created['id']}")
    return created



def move_file_to_folder(
    service,
    file_id: str,
    folder_id: str,
    *,
    fields: str = "id,name,mimeType,parents,webViewLink",
) -> dict[str, Any]:
    current = service.files().get(fileId=file_id, fields="id,parents").execute()
    existing_parents = current.get("parents", [])
    remove_parents = ",".join(existing_parents)
    moved = service.files().update(
        fileId=file_id,
        addParents=folder_id,
        removeParents=remove_parents,
        fields=fields,
    ).execute()
    moved.setdefault("url", moved.get("webViewLink") or build_file_url(file_id, moved.get("mimeType")))
    return moved



def create_permission(
    service,
    file_id: str,
    *,
    role: str,
    email_address: str | None = None,
    domain: str | None = None,
    permission_type: str | None = None,
    send_notification_email: bool = True,
    transfer_ownership: bool = False,
    fields: str = DEFAULT_PERMISSION_FIELDS,
) -> dict[str, Any]:
    inferred_type = permission_type
    if inferred_type is None:
        if email_address:
            inferred_type = "user"
        elif domain:
            inferred_type = "domain"
        else:
            inferred_type = "anyone"

    body: dict[str, Any] = {"role": role, "type": inferred_type}
    if email_address:
        body["emailAddress"] = email_address
    if domain:
        body["domain"] = domain

    return service.permissions().create(
        fileId=file_id,
        body=body,
        fields=fields,
        sendNotificationEmail=send_notification_email,
        transferOwnership=transfer_ownership,
    ).execute()



def create_comment(
    service,
    file_id: str,
    content: str,
    *,
    anchor: str | None = None,
    quoted_file_content: str | None = None,
    fields: str = DEFAULT_COMMENT_FIELDS,
) -> dict[str, Any]:
    body: dict[str, Any] = {"content": content}
    if anchor:
        body["anchor"] = anchor
    if quoted_file_content:
        body["quotedFileContent"] = {"value": quoted_file_content}
    return service.comments().create(fileId=file_id, body=body, fields=fields).execute()



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Google Drive helpers for Google Docs workflow.")
    parser.add_argument("--account", help="Account alias")
    subparsers = parser.add_subparsers(dest="command")

    info = subparsers.add_parser("info", help="Get Drive file metadata")
    info.add_argument("--file-id", required=True, help="Drive file id or URL")
    info.add_argument("--fields", default=DEFAULT_INFO_FIELDS, help="Drive fields selector")
    info.add_argument("--output", help="Optional path to write JSON output")

    create_folder_parser = subparsers.add_parser("create-folder", help="Create Drive folder")
    create_folder_parser.add_argument("--name", required=True, help="Folder name")
    create_folder_parser.add_argument("--parent-id", help="Parent folder id or URL")
    create_folder_parser.add_argument("--output", help="Optional path to write JSON output")

    move = subparsers.add_parser("move", help="Move file into folder")
    move.add_argument("--file-id", required=True, help="Drive file id or URL")
    move.add_argument("--folder-id", required=True, help="Destination folder id or URL")
    move.add_argument("--output", help="Optional path to write JSON output")

    share = subparsers.add_parser("share", help="Create Drive permission")
    share.add_argument("--file-id", required=True, help="Drive file id or URL")
    share.add_argument("--role", default="reader", help="Permission role")
    share.add_argument("--email", help="Share with user or group email")
    share.add_argument("--domain", help="Share with Google Workspace domain")
    share.add_argument("--type", dest="permission_type", choices=["user", "group", "domain", "anyone"], help="Override permission type")
    share.add_argument("--no-notify", action="store_true", help="Disable notification email")
    share.add_argument("--transfer-ownership", action="store_true", help="Transfer ownership when role=owner")
    share.add_argument("--output", help="Optional path to write JSON output")

    comment = subparsers.add_parser("comment", help="Create Drive comment")
    comment.add_argument("--file-id", required=True, help="Drive file id or URL")
    comment.add_argument("--content", required=True, help="Comment text")
    comment.add_argument("--anchor", help="Optional Drive API anchor JSON/string")
    comment.add_argument("--quoted-file-content", help="Optional quoted file content snippet")
    comment.add_argument("--output", help="Optional path to write JSON output")
    return parser



def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    service = build_drive_service(account=args.account)

    if args.command == "info":
        result = get_file_info(service, resolve_drive_id(args.file_id), fields=args.fields)
    elif args.command == "create-folder":
        result = create_folder(
            service,
            args.name,
            parent_id=resolve_drive_id(args.parent_id) if args.parent_id else None,
        )
    elif args.command == "move":
        result = move_file_to_folder(
            service,
            resolve_drive_id(args.file_id),
            resolve_drive_id(args.folder_id),
        )
    elif args.command == "share":
        result = create_permission(
            service,
            resolve_drive_id(args.file_id),
            role=args.role,
            email_address=args.email,
            domain=args.domain,
            permission_type=args.permission_type,
            send_notification_email=not args.no_notify,
            transfer_ownership=args.transfer_ownership,
        )
    elif args.command == "comment":
        result = create_comment(
            service,
            resolve_drive_id(args.file_id),
            args.content,
            anchor=args.anchor,
            quoted_file_content=args.quoted_file_content,
        )
    else:  # pragma: no cover
        parser.error(f"Unsupported command: {args.command}")

    output_path = getattr(args, "output", None)
    write_json(result, output_path)
    if output_path:
        write_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
