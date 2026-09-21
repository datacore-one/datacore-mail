#!/usr/bin/env python3
"""Create org-mode tasks from email scan results.

Reads scan output from email_scanner, determines which items need action,
creates tasks in the appropriate space's next_actions.org with :email: tags.

Usage:
    python3 task_creator.py --scan-file data/scan_cache.json --data-dir ~/Data

Output: JSON summary of created tasks.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

# Add shared lib to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "lib"))
from triage_utils import create_triage_task

# Categories that warrant task creation
TASK_CATEGORIES = {"actionable", "unknown", "github"}
# For github, only create tasks when action is "task" (not "review" or "auto_archive")
GITHUB_TASK_ACTIONS = {"task", "create_task"}


def _make_task_id(sender: str, email_id: str, today: str) -> str:
    """Generate idempotent task ID: mail-{sender_short}-{id_short}-{date}."""
    # Shorten sender: strip domain, take first 12 chars
    sender_short = sender.split("@")[0] if "@" in sender else sender
    sender_short = sender_short[:12].replace(".", "-").replace("+", "-")
    id_short = email_id[:8] if len(email_id) >= 8 else email_id
    return f"mail-{sender_short}-{id_short}-{today}"


def _resolve_org_file(data_dir: Path, target_org: str | None) -> Path:
    """Resolve the target org file, falling back through known locations."""
    if target_org:
        return Path(target_org)

    # Try 1-acme first (primary work space)
    primary = data_dir / "1-acme" / "org" / "next_actions.org"
    if primary.exists():
        return primary

    # Fall back to 0-personal
    return data_dir / "0-personal" / "org" / "next_actions.org"


def create_tasks_from_scan(
    scan: dict,
    data_dir: Path,
    target_org: str | None = None,
) -> dict:
    """Process scan results and create org-mode tasks for actionable items.

    Creates tasks for:
    - actionable: direct action required from a known sender
    - unknown: no rule matched — needs manual review
    - github: GitHub notifications with action="task" (security advisories, etc.)

    Returns summary dict with: created, skipped, errors.
    """
    today = date.today().isoformat()
    org_file = _resolve_org_file(data_dir, target_org)

    if not org_file.exists():
        return {
            "created": 0,
            "skipped": 0,
            "errors": 1,
            "error_details": [f"Org file not found: {org_file}"],
            "tasks": [],
        }

    created = []
    skipped = 0
    errors = []

    categories = scan.get("categories", {})

    for cat in TASK_CATEGORIES:
        emails = categories.get(cat, [])
        for email in emails:
            # For github, only create tasks for emails that explicitly need action
            if cat == "github":
                action = email.get("action", "")
                if action not in GITHUB_TASK_ACTIONS:
                    continue

            email_id = email.get("id", "")
            sender = email.get("sender", "unknown")
            sender_name = email.get("sender_name") or sender
            subject = email.get("subject", "(no subject)")
            gmail_url = email.get("gmail_url", "")
            snippet = email.get("snippet", "")
            priority = email.get("priority", "MEDIUM")
            reason = email.get("reason", "")

            if not email_id:
                continue

            task_id = _make_task_id(sender, email_id, today)

            # Build heading
            if cat == "unknown":
                heading = f"Review email from {sender_name}: {subject[:60]}"
            elif cat == "github":
                heading = f"Act on GitHub email: {subject[:60]}"
            else:
                heading = f"Reply to {sender_name}: {subject[:60]}"

            # Build Gmail URL org-link
            external_url = f"[[{gmail_url}][View in Gmail]]" if gmail_url else gmail_url

            properties = {
                "TRIAGE_ID": task_id,
                "EXTERNAL_URL": external_url,
                "EXTERNAL_ID": f"gmail:{sender}/{email_id}",
                "SOURCE": "email-triage",
                "SENDER": sender,
                "EMAIL_CATEGORY": cat,
            }

            # Context body: snippet and classification reason
            context_lines = []
            if snippet:
                context_lines.append(f"Snippet: {snippet}")
            if reason:
                context_lines.append(f"Classified as: {reason}")
            if priority:
                context_lines.append(f"Priority: {priority}")
            context_body = "\n".join(context_lines)

            result = create_triage_task(
                org_file=org_file,
                heading=heading,
                tags=["email"],
                properties=properties,
                context_body=context_body,
                scheduled_date=date.today(),
            )

            if result.get("skipped"):
                skipped += 1
            elif result.get("success"):
                created.append({
                    "id": task_id,
                    "heading": heading,
                    "category": cat,
                    "sender": sender,
                    "subject": subject,
                })
            else:
                errors.append(
                    f"Failed to create task for {sender}/{email_id}: {result.get('error')}"
                )

    return {
        "created": len(created),
        "skipped": skipped,
        "errors": len(errors),
        "error_details": errors,
        "tasks": created,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Create org-mode tasks from email scan results")
    parser.add_argument("--scan-file", required=True, help="Path to scan_cache.json")
    parser.add_argument("--data-dir", default=str(Path.home() / "Data"),
                        help="Path to Data directory (default: ~/Data)")
    parser.add_argument("--org-file", default=None,
                        help="Target org file (default: 1-acme/org/next_actions.org)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be created without writing")
    args = parser.parse_args()

    scan = json.loads(Path(args.scan_file).read_text())
    data_dir = Path(args.data_dir)

    if args.dry_run:
        categories = scan.get("categories", {})
        print("DRY RUN — would create tasks for:")
        for cat in TASK_CATEGORIES:
            emails = categories.get(cat, [])
            for email in emails:
                if cat == "github" and email.get("action") not in GITHUB_TASK_ACTIONS:
                    continue
                sender = email.get("sender_name") or email.get("sender", "unknown")
                subject = email.get("subject", "(no subject)")
                print(f"  [{cat}] {sender}: {subject}")
        return

    result = create_tasks_from_scan(scan, data_dir, args.org_file)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
