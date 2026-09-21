#!/usr/bin/env python3
"""
Bulk archive Gmail inbox threads matching a Gmail SEARCH QUERY (not explicit IDs).

Complements archive_threads.py (which takes explicit thread IDs). Use this for
"clear the whole backlog of X" jobs that span more history than a days-window
scan — e.g. clear every GitHub notification regardless of age.

Dry-run by default: prints count + a sample so you can eyeball before clearing.

Usage:
    # See what would be archived (no changes):
    python3 archive_by_query.py --query "in:inbox from:noreply6@service.example.com"

    # Actually archive (remove INBOX + UNREAD):
    python3 archive_by_query.py --query "in:inbox from:noreply6@service.example.com" --execute

    # Custom account / sample size:
    python3 archive_by_query.py --account grace@example.com --query "..." --sample 15
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


def list_threads(service, query, cap=2000):
    """Return [(thread_id, snippet)] for all threads matching query."""
    out, token = [], None
    while True:
        resp = service.users().threads().list(
            userId="me", q=query, maxResults=100, pageToken=token,
        ).execute()
        for t in resp.get("threads", []):
            out.append((t["id"], t.get("snippet", "")))
        token = resp.get("nextPageToken")
        if not token or len(out) >= cap:
            break
    return out


def archive_thread(service, tid):
    try:
        service.users().threads().modify(
            userId="me", id=tid,
            body={"removeLabelIds": ["INBOX", "UNREAD"]},
        ).execute()
        return True, ""
    except Exception as e:
        return False, str(e)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--account", default="grace@example.com")
    p.add_argument("--query", required=True, help="Gmail search query")
    p.add_argument("--execute", action="store_true", help="Archive (default: dry-run)")
    p.add_argument("--sample", type=int, default=12, help="Dry-run sample size")
    args = p.parse_args(argv)

    adapter = get_adapter(args.account)
    service = adapter._get_service()
    if not service:
        print("Could not get Gmail service (auth failed?).", file=sys.stderr)
        return 1

    threads = list_threads(service, args.query)
    print(f"Query: {args.query}")
    print(f"Matching inbox threads: {len(threads)}")
    for tid, snip in threads[: args.sample]:
        print(f"  - {snip[:90]}")
    if len(threads) > args.sample:
        print(f"  ... and {len(threads) - args.sample} more")

    if not args.execute:
        print("\n(dry-run — pass --execute to archive)")
        return 0

    ok, errs = 0, 0
    for tid, _ in threads:
        success, err = archive_thread(service, tid)
        if success:
            ok += 1
        else:
            errs += 1
            print(f"  ERROR {tid}: {err}", file=sys.stderr)
    print(f"\nDone: {ok}/{len(threads)} archived. {errs} errors.")
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
