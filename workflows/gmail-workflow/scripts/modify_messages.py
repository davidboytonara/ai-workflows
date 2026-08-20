#!/usr/bin/env python3
"""Reversible Gmail message state changes: trash and label modifications.

SAFETY: this script performs ONLY reversible operations:
  - move to Trash (recoverable in Gmail for ~30 days) via messages.trash
  - add / remove labels, including mark-read (remove UNREAD) and
    mark-unread (add UNREAD)
It NEVER permanently deletes (no messages.delete) and NEVER sends email.
Requires the gmail.modify OAuth scope.

Always preview with --dry-run first; it prints From/Subject per id and makes
no changes.
"""

import argparse
import json
from typing import Dict, List

from utils.auth_helper import build_gmail_service
from utils.logger import setup_logger, log_error_with_context


logger = setup_logger(__name__)


def _get_header(headers: List[Dict[str, str]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _peek(service, mid: str):
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=mid, format="metadata", metadataHeaders=["From", "Subject"])
        .execute()
    )
    headers = msg.get("payload", {}).get("headers", [])
    return _get_header(headers, "From"), _get_header(headers, "Subject"), msg.get("labelIds", [])


def run(account, ids, action, add_labels, remove_labels, dry_run) -> List[Dict]:
    service = build_gmail_service(account=account)
    results: List[Dict] = []
    for mid in ids:
        try:
            frm, subj, _labels = _peek(service, mid)
        except Exception as exc:  # noqa: BLE001
            log_error_with_context(logger, exc, {"operation": "messages.get", "message_id": mid})
            results.append({"id": mid, "status": "error_peek"})
            continue

        if dry_run:
            logger.info("DRY-RUN %-6s | %-42s | %s", action, frm[:42], subj[:60])
            results.append(
                {"id": mid, "from": frm, "subject": subj, "status": "dry-run"}
            )
            continue

        try:
            if action == "trash":
                service.users().messages().trash(userId="me", id=mid).execute()
            else:
                body: Dict[str, List[str]] = {}
                if add_labels:
                    body["addLabelIds"] = add_labels
                if remove_labels:
                    body["removeLabelIds"] = remove_labels
                service.users().messages().modify(userId="me", id=mid, body=body).execute()
            logger.info("%-6s OK | %-42s | %s", action, frm[:42], subj[:60])
            results.append({"id": mid, "from": frm, "subject": subj, "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            log_error_with_context(logger, exc, {"operation": action, "message_id": mid})
            results.append({"id": mid, "from": frm, "subject": subj, "status": "error"})
    return results


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Reversible Gmail trash / label changes (never permanent-delete, never send).",
    )
    p.add_argument("--account", required=True, help="Account alias (work | personal)")
    p.add_argument("--ids", required=True, help="Comma-separated message IDs")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--trash", action="store_true", help="Move messages to Trash (reversible)")
    grp.add_argument("--mark-read", action="store_true", help="Remove the UNREAD label")
    grp.add_argument("--mark-unread", action="store_true", help="Add the UNREAD label")
    grp.add_argument("--add-label", help="Add this label ID")
    grp.add_argument("--remove-label", help="Remove this label ID")
    p.add_argument("--dry-run", action="store_true", help="Preview only; make no changes")
    p.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    ids = [x.strip() for x in a.ids.split(",") if x.strip()]
    add_labels: List[str] = []
    remove_labels: List[str] = []
    if a.trash:
        action = "trash"
    elif a.mark_read:
        action, remove_labels = "modify", ["UNREAD"]
    elif a.mark_unread:
        action, add_labels = "modify", ["UNREAD"]
    elif a.add_label:
        action, add_labels = "modify", [a.add_label]
    else:  # remove_label
        action, remove_labels = "modify", [a.remove_label]

    results = run(a.account, ids, action, add_labels, remove_labels, a.dry_run)
    ok = sum(1 for r in results if r.get("status") == "ok")
    dry = sum(1 for r in results if r.get("status") == "dry-run")
    err = sum(1 for r in results if str(r.get("status", "")).startswith("error"))

    if a.json:
        print(json.dumps({
            "action": action, "add": add_labels, "remove": remove_labels,
            "results": results,
            "summary": {"ok": ok, "dry_run": dry, "error": err, "total": len(results)},
        }))
    else:
        print(f"action={action} add={add_labels} remove={remove_labels} "
              f"-> ok={ok} dry_run={dry} error={err} total={len(results)}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
