#!/usr/bin/env python3
"""Download attachments from a Gmail message via the mail module's Gmail adapter.

Usage:
    python3 fetch_attachment.py <message_id> <output_dir> [--account ADDRESS] [--filename NAME]

    message_id   Gmail message ID (hex, e.g. 19e698158b22243d)
    output_dir   Directory to save attachments into (created if missing)
    --account    Account address from mail.yaml (default: grace@example.com)
    --filename   Only download the attachment matching this filename
"""

import argparse
import base64
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE_DIR))

from adapters.gmail import GmailAdapter  # noqa: E402


def _safe_name(filename: str) -> str:
    """Strip path separators from a Gmail-supplied filename.

    Gmail filenames routinely contain dates ("Registered-Post Received
    21/07/2026 ....pdf"). Joined to an output directory unsanitised, the slashes
    are read as directories and the write fails with FileNotFoundError - or, on a
    crafted name, escapes the output directory entirely.
    """
    return filename.replace('/', '-').replace('\\', '-').lstrip('.') or 'attachment'


def fetch_attachments(message_id: str, output_dir: Path, account: str, filename: str | None = None) -> list[Path]:
    adapter = GmailAdapter({"address": account})
    service = adapter._get_service()
    if not service:
        raise RuntimeError(f"Could not authenticate Gmail for {account} — token missing or expired. Run /mails setup.")

    msg = service.users().messages().get(userId="me", id=message_id).execute()

    saved = []

    def walk(part):
        fname = part.get("filename", "")
        body = part.get("body", {})
        att_id = body.get("attachmentId")
        if fname and att_id and (filename is None or fname == filename):
            att = service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=att_id
            ).execute()
            data = base64.urlsafe_b64decode(att["data"])
            # Gmail filenames routinely contain dates with slashes; joining one
            # unsanitised reads them as directories and raises FileNotFoundError.
            out = output_dir / _safe_name(fname)
            out.write_bytes(data)
            saved.append(out)
        for sub in part.get("parts", []):
            walk(sub)

    walk(msg.get("payload", {}))
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message_id")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--account", default="grace@example.com")
    parser.add_argument("--filename", default=None)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    saved = fetch_attachments(args.message_id, args.output_dir, args.account, args.filename)
    if not saved:
        print(f"No attachments found on message {args.message_id}" + (f" matching '{args.filename}'" if args.filename else ""))
        sys.exit(1)
    for path in saved:
        print(f"Saved: {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
