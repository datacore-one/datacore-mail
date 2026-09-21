#!/usr/bin/env python3
"""
Basic example: Send batch emails with template and CSV recipients.

This demonstrates the simplest workflow for batch sending.
"""

from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from batch_send import (
    EmailTemplate,
    load_recipients_from_csv,
    batch_send_email
)
from adapters import get_adapter


def main():
    """Run basic batch send example."""

    # 1. Setup mail adapter (Gmail)
    print("Setting up Gmail adapter...")
    account = input("Enter your Gmail address: ")

    adapter = get_adapter('gmail')({'address': account})

    if not adapter.is_configured():
        print(f"\nAccount not configured. Please run:")
        print(f"  python ../adapters/gmail.py setup --account {account}")
        sys.exit(1)

    print("✓ Account configured\n")

    # 2. Load template
    print("Loading email template...")
    template_path = Path(__file__).parent / 'templates/outreach.md'
    template = EmailTemplate.from_file(template_path)
    print(f"✓ Loaded: {template_path.name}\n")

    # 3. Load recipients
    print("Loading recipients...")
    recipients_path = Path(__file__).parent / 'recipients/sample-outreach.csv'
    recipients = load_recipients_from_csv(recipients_path)
    print(f"✓ Loaded {len(recipients)} recipients\n")

    # 4. Preview first email
    print("=" * 70)
    print("PREVIEW: First Email")
    print("=" * 70)

    first = recipients[0]
    context = first.get_full_context()
    subject, body = template.render(context)

    print(f"\nTo: {first.email}")
    print(f"Subject: {subject}")
    print(f"\n{body}\n")

    # 5. Confirm send
    print("=" * 70)
    response = input(f"\nSend to {len(recipients)} recipients? (yes/no): ")

    if response.lower() != 'yes':
        print("Cancelled.")
        sys.exit(0)

    # 6. Send batch
    print("\nSending batch emails...")
    print("(Using 2 second delay between sends for rate limiting)\n")

    result = batch_send_email(
        adapter,
        template,
        recipients,
        dry_run=False,  # Set to True to test without actually sending
        delay=2.0       # 2 seconds between sends
    )

    # 7. Show results
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"\nTotal: {result.total}")
    print(f"Successful: {result.successful}")
    print(f"Failed: {result.failed}")
    print(f"Success rate: {result.success_rate:.1f}%\n")

    # Show successful sends
    if result.successful > 0:
        print("✓ Successful sends:")
        for r in result.get_successful():
            print(f"  - {r.recipient} (ID: {r.message_id})")

    # Show failures
    if result.failed > 0:
        print("\n✗ Failed sends:")
        for r in result.get_failed():
            print(f"  - {r.recipient}: {r.error}")

    print()


if __name__ == "__main__":
    main()
