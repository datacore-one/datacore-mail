#!/usr/bin/env python3
"""today_brief_section.py — Render the Email section for the /today briefing.

Reads per-account scan caches written by triage-email.sh and produces a
markdown section showing:
  - Overnight summary table (per-account counts)
  - Items left for review (the actionable queue)
  - Last triage timestamp + audit log pointer

Usage:
    python3 today_brief_section.py
    python3 today_brief_section.py --json   # machine-readable
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATE_DIR = Path.home() / "Data" / ".datacore" / "state" / "mail"

# A briefing section is meant to describe last night. Two days of slack covers
# a missed run or a weekend; past that it is history and must be labelled so.
STALE_AFTER_DAYS = 2


def _staleness_days(completed_at: str) -> int | None:
    """Whole days between an audit line's completed_at and now, or None.

    Returns None when the timestamp is missing or unparseable — an unknown age
    is not the same claim as a fresh one, and the caller must not treat it as
    either.
    """
    if not completed_at or completed_at == "?":
        return None
    try:
        ts = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - ts).days)
DEFAULT_ACCOUNTS = ["grace@example.com", "heidi@example.com"]


def safe_account_name(account: str) -> str:
    return account.replace("@", "_").replace(".", "_")


def load_cache(state_dir: Path, account: str) -> dict | None:
    path = state_dir / f"scan_cache_{safe_account_name(account)}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def load_last_audit_line(state_dir: Path) -> dict | None:
    audit = state_dir / "audit.jsonl"
    if not audit.exists():
        return None
    last = None
    for line in audit.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            last = json.loads(line)
        except json.JSONDecodeError:
            continue
    return last


def category_counts(cache: dict) -> dict:
    cats = cache.get("categories", {})
    out = {}
    for k, v in cats.items():
        if isinstance(v, list):
            out[k] = len(v)
        elif isinstance(v, (int, float)):
            out[k] = int(v)
        else:
            out[k] = 0
    return out


def actionable_items(cache: dict) -> list[dict]:
    """Items that need user attention — pulled from the scanner's emails list."""
    emails = cache.get("emails", [])
    if not emails:
        return []
    keep_categories = {"actionable", "unknown", "github", "forward_accounting"}
    out = []
    for e in emails:
        if e.get("category") in keep_categories:
            sender_name = e.get("sender_name") or ""
            sender_email = e.get("sender") or ""
            if sender_name and sender_email and sender_name != sender_email:
                sender_display = f"{sender_name} <{sender_email}>"
            else:
                sender_display = sender_name or sender_email
            out.append({
                "category": e.get("category"),
                "from": sender_display,
                "subject": e.get("subject", "")[:120],
                "id": e.get("id"),
                "gmail_url": e.get("gmail_url"),
            })
    return out


def render_markdown(state_dir: Path, accounts: list[str]) -> str:
    last_audit = load_last_audit_line(state_dir)
    parts = ["### Email"]

    # --- Overnight summary ---
    if last_audit:
        ts = last_audit.get("completed_at", "?")
        stale_age = _staleness_days(ts)
        if stale_age is not None and stale_age >= STALE_AFTER_DAYS:
            # Say it loudly rather than dressing old numbers as this morning's.
            # The scan runs on winston and writes .datacore/state/mail/, which
            # is gitignored (**/.datacore/state/) and therefore has no route to
            # any other machine. When the hourly rsync stops, this file simply
            # stops advancing — and every field below stays perfectly
            # well-formed while describing a run from months ago. That is how a
            # June 3 scan was reported as "Overnight triage" in every briefing
            # for eleven weeks: nothing was broken enough to look broken.
            parts.append(
                f"\n> ⚠️ **STALE — this triage ran {stale_age} days ago "
                f"({ts}).** Treat the numbers below as history, not this "
                f"morning. The scan runs on winston at 03:30 UTC; its state "
                f"reaches this machine only via the hourly rsync of "
                f"`.datacore/state/mail/` (gitignored, so git will not carry "
                f"it). Check that pull before trusting this section.\n"
            )
        parts.append(f"\n**Overnight triage** — {ts} (run_id={last_audit.get('run_id','?')})\n")
        parts.append("| Account | Scanned | Archived | Processed | Errors |")
        parts.append("|---------|---------|----------|-----------|--------|")
        for acct, stats in (last_audit.get("accounts") or {}).items():
            if "error" in stats:
                parts.append(f"| {acct} | — | — | — | {stats['error']} |")
            else:
                parts.append(
                    f"| {acct} | {stats.get('scanned',0)} | "
                    f"{stats.get('archived',0)} | {stats.get('processed',0)} | "
                    f"{stats.get('errors',0)} |"
                )
        parts.append(
            f"| **Total** | **{last_audit.get('total_scanned',0)}** | "
            f"**{last_audit.get('total_archived',0)}** | "
            f"**{last_audit.get('total_processed',0)}** | "
            f"**{last_audit.get('total_errors',0)}** |"
        )
    else:
        parts.append("\n⚠ No audit log entry found — triage may not have run.\n")

    # --- Actionable per account ---
    parts.append("\n**Left for you:**\n")
    any_actionable = False
    for account in accounts:
        cache = load_cache(state_dir, account)
        if not cache:
            parts.append(f"- *{account}*: no cache (scan not run yet)")
            continue
        items = actionable_items(cache)
        cat_counts = category_counts(cache)
        if not items:
            parts.append(f"- *{account}*: **inbox clean** (0 items)")
            continue
        any_actionable = True
        parts.append(f"\n*{account}* — {len(items)} item(s):")
        parts.append("")
        parts.append("| # | Category | Sender | Subject |")
        parts.append("|---|----------|--------|---------|")
        for i, it in enumerate(items, 1):
            sender = it["from"][:60].replace("|", "/")
            subj = it["subject"][:100].replace("|", "/")
            parts.append(f"| {i} | {it['category']} | {sender} | {subj} |")
        parts.append("")
        parts.append(f"_Category counts: {cat_counts}_")

    if not any_actionable:
        parts.append("\n*Both inboxes are clean — no items need your attention.*")

    # --- Pointers ---
    parts.append("\n**Audit**: `~/Data/.datacore/state/mail/audit.jsonl` "
                 "(JSONL, one line per run). For human-readable per-account "
                 "scan logs see `~/Data/.datacore/state/mail/scan_<account>_<run_id>.log`.")

    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR,
                        help=f"Mail state directory (default: {DEFAULT_STATE_DIR})")
    parser.add_argument("--accounts", nargs="+", default=DEFAULT_ACCOUNTS,
                        help="Accounts to render. Default: acme + example-org")
    parser.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON instead of markdown")
    args = parser.parse_args()

    if args.json:
        last_audit = load_last_audit_line(args.state_dir)
        per_account = {}
        for acct in args.accounts:
            cache = load_cache(args.state_dir, acct)
            per_account[acct] = {
                "cache_present": cache is not None,
                "scanned_at": cache.get("scanned_at") if cache else None,
                "inbox_count": cache.get("inbox_count") if cache else None,
                "categories": category_counts(cache) if cache else None,
                "actionable": actionable_items(cache) if cache else [],
            }
        out = {
            "rendered_at": datetime.now(timezone.utc).isoformat(),
            "last_audit": last_audit,
            "accounts": per_account,
        }
        json.dump(out, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_markdown(args.state_dir, args.accounts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
