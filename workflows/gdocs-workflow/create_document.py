#!/usr/bin/env python3
"""Create a Google Docs document.

Exit codes:
  0  success
  1  business / API failure
  2  usage error
"""

from __future__ import annotations

import argparse

from drive_helpers import move_file_to_folder, resolve_drive_id
from gdocs_auth import build_docs_service, build_drive_service
from gdocs_common import document_url, write_json



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a Google Docs document.")
    parser.add_argument("--title", required=True, help="Document title")
    parser.add_argument("--output", help="Optional path to write JSON metadata")
    parser.add_argument("--folder-id", help="Optional Drive folder id or URL for immediate placement")
    parser.add_argument("--account", help="Account alias")
    args = parser.parse_args(argv)

    service = build_docs_service(account=args.account)
    created = service.documents().create(body={"title": args.title}).execute()

    result = {
        "documentId": created["documentId"],
        "title": created.get("title", args.title),
        "revisionId": created.get("revisionId"),
        "url": document_url(created["documentId"]),
    }
    if args.folder_id:
        drive_service = build_drive_service(account=args.account)
        placement = move_file_to_folder(
            drive_service,
            created["documentId"],
            resolve_drive_id(args.folder_id),
        )
        result["parents"] = placement.get("parents", [])
        result["drivePlacement"] = {
            "folderId": resolve_drive_id(args.folder_id),
            "webViewLink": placement.get("webViewLink") or placement.get("url"),
        }
    write_json(result, args.output)
    if args.output:
        write_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
