#!/usr/bin/env python3
"""Download attachments from a Gmail message.

The mail module could list attachment metadata (`GmailAdapter._extract_attachments`)
but had no way to fetch the bytes, so any PDF/DOCX that arrived by email was
visible-but-unreadable. This closes that gap.

Note on credentials: `gmail.py` computes CREDS_DIR as
`<module>/../../../env/credentials`, which resolves to `~/Data/env/credentials` —
a directory that does not exist. The real tokens live in
`~/Data/.datacore/env/credentials`. This script resolves the correct location and
falls back to the module's constant, so it works regardless of which one is
populated. Token filenames are `gmail_token_<md5(address)[:8]>.pickle`.

Usage
-----
    # list attachments on a message
    python3 .datacore/modules/mail/fetch_attachment.py --message-id 16441910efd36e41 --list

    # download all attachments to a directory
    python3 .datacore/modules/mail/fetch_attachment.py --message-id 16441910efd36e41 \
        --out ~/Downloads

    # only files matching a substring (case-insensitive)
    python3 .datacore/modules/mail/fetch_attachment.py --message-id 16441910efd36e41 \
        --out ~/Downloads --match .pdf

    # find the message first
    python3 .datacore/modules/mail/fetch_attachment.py --query "from:marand.si has:attachment" --list

`--account` selects which mailbox (default: grace@example.com).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import pickle
import re
import sys
from pathlib import Path

DATACORE_ROOT = Path.home() / "Data"
CRED_DIRS = [
    DATACORE_ROOT / ".datacore" / "env" / "credentials",  # actual location
    DATACORE_ROOT / "env" / "credentials",                # gmail.py's constant
]

SAFE_NAME = re.compile(r"[^A-Za-z0-9._@-]+")


def token_path(address: str) -> Path:
    addr_hash = hashlib.md5(address.encode()).hexdigest()[:8]
    name = f"gmail_token_{addr_hash}.pickle"
    for d in CRED_DIRS:
        candidate = d / name
        if candidate.exists():
            return candidate
    raise SystemExit(
        f"no token for {address}\nlooked in:\n  " + "\n  ".join(str(d / name) for d in CRED_DIRS)
    )


def get_service(address: str):
    tok = token_path(address)
    with tok.open("rb") as fh:
        creds = pickle.load(fh)

    if creds and getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
        from google.auth.transport.requests import Request

        creds.refresh(Request())
        with tok.open("wb") as fh:
            pickle.dump(creds, fh)

    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds)


def walk_parts(payload: dict):
    """Yield every part in a message payload, depth-first."""
    stack = [payload]
    while stack:
        part = stack.pop()
        yield part
        stack.extend(part.get("parts", []) or [])


def list_attachments(service, message_id: str) -> list[dict]:
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    out = []
    for part in walk_parts(msg.get("payload", {})):
        body = part.get("body", {}) or {}
        filename = part.get("filename") or ""
        if filename and body.get("attachmentId"):
            out.append(
                {
                    "filename": filename,
                    "mimeType": part.get("mimeType", ""),
                    "size": body.get("size", 0),
                    "attachmentId": body["attachmentId"],
                }
            )
    return out


def download(service, message_id: str, att: dict, out_dir: Path) -> Path:
    data = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=att["attachmentId"])
        .execute()
    )
    raw = base64.urlsafe_b64decode(data["data"])
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = SAFE_NAME.sub("_", att["filename"]) or "attachment.bin"
    dest = out_dir / safe
    n = 1
    while dest.exists():
        dest = out_dir / f"{dest.stem}_{n}{dest.suffix}"
        n += 1
    dest.write_bytes(raw)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", default="grace@example.com")
    ap.add_argument("--message-id", help="Gmail message ID")
    ap.add_argument("--query", help="Gmail search query; resolves to matching message IDs")
    ap.add_argument("--out", default=None, help="output directory (omit to just list)")
    ap.add_argument("--match", default=None, help="only files whose name contains this (case-insensitive)")
    ap.add_argument("--list", action="store_true", help="list attachments, download nothing")
    ap.add_argument("--max-messages", type=int, default=10, help="cap when using --query")
    args = ap.parse_args()

    if not args.message_id and not args.query:
        ap.error("need --message-id or --query")

    service = get_service(args.account)

    message_ids: list[str] = []
    if args.message_id:
        message_ids.append(args.message_id)
    else:
        res = (
            service.users()
            .messages()
            .list(userId="me", q=args.query, maxResults=args.max_messages)
            .execute()
        )
        message_ids = [m["id"] for m in res.get("messages", [])]
        if not message_ids:
            print(f"no messages match: {args.query}")
            return 0

    total = 0
    for mid in message_ids:
        atts = list_attachments(service, mid)
        if args.match:
            atts = [a for a in atts if args.match.lower() in a["filename"].lower()]
        if not atts:
            continue
        print(f"message {mid} — {len(atts)} attachment(s)")
        for a in atts:
            size_kb = int(a["size"]) / 1024 if a["size"] else 0
            print(f"  {a['filename']}  [{a['mimeType']}]  {size_kb:.0f} KB")
            if args.out and not args.list:
                dest = download(service, mid, a, Path(args.out).expanduser())
                print(f"    -> {dest}")
                total += 1

    if args.out and not args.list:
        print(f"\ndownloaded {total} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
