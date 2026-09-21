#!/usr/bin/env python3
"""
Bulk archive + mark read Gmail threads by thread ID.

Usage:
    # From CLI args:
    python3 archive_threads.py 19e6990f4ab9f536 19e6988b3440e9df ...

    # From stdin (one ID per line):
    cat ids.txt | python3 archive_threads.py -

    # With custom account:
    python3 archive_threads.py --account olivia@example.com <ids...>

Use case: complement to email_scanner.py for one-off bulk archival of
threads identified during interactive triage (e.g. cold outreach,
promotional, informational receipts that the scanner left in inbox).
"""
import argparse
import importlib.util
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent  # .datacore/modules/mail


def get_adapter(account: str):
    adapter_path = MODULE_ROOT / "adapters" / "gmail.py"
    spec = importlib.util.spec_from_file_location("gmail_adapter", adapter_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.GmailAdapter({"address": account})


def archive_thread(service, tid: str):
    try:
        service.users().threads().modify(
            userId="me",
            id=tid,
            body={"removeLabelIds": ["INBOX", "UNREAD"]},
        ).execute()
        return True, ""
    except Exception as e:
        return False, str(e)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--account", default="grace@example.com")
    p.add_argument(
        "ids",
        nargs="+",
        help="Thread IDs to archive. Use '-' to read one per line from stdin.",
    )
    args = p.parse_args(argv)

    if args.ids == ["-"]:
        ids = [line.strip() for line in sys.stdin if line.strip()]
    else:
        ids = args.ids

    if not ids:
        print("No thread IDs provided.", file=sys.stderr)
        return 2

    adapter = get_adapter(args.account)
    service = adapter._get_service()
    if not service:
        print("Could not get Gmail service (auth failed?).", file=sys.stderr)
        return 1

    ok, errs = 0, []
    for tid in ids:
        success, err = archive_thread(service, tid)
        if success:
            print(f"  archived: {tid}")
            ok += 1
        else:
            print(f"  ERROR    {tid}: {err}")
            errs.append((tid, err))

    print(f"\nDone: {ok}/{len(ids)} archived. {len(errs)} errors.")
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
