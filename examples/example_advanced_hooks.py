#!/usr/bin/env python3
"""
Advanced example: Batch sending with validation hooks and rate limiting.

This demonstrates:
- Pre-send validation hooks
- Post-send callback hooks
- Custom rate limiting
- Error handling and retry logic
"""

from pathlib import Path
import sys
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from batch_send import (
    BatchEmailSender,
    EmailTemplate,
    Recipient,
    SendResult
)
from adapters import get_adapter


class CampaignTracker:
    """Track campaign sends for analytics."""

    def __init__(self, campaign_name: str):
        self.campaign_name = campaign_name
        self.sent_count = 0
        self.failed_recipients = []

    def on_send(self, result: SendResult):
        """Called after each send attempt."""
        if result.success:
            self.sent_count += 1
            status = "✓"
        else:
            self.failed_recipients.append(result.recipient)
            status = "✗"

        print(f"  {status} {result.recipient}")

    def summary(self):
        """Print campaign summary."""
        print(f"\nCampaign: {self.campaign_name}")
        print(f"Sent: {self.sent_count}")
        print(f"Failed: {len(self.failed_recipients)}")

        if self.failed_recipients:
            print(f"\nFailed recipients:")
            for r in self.failed_recipients:
                print(f"  - {r}")


def validate_email_content(recipient: Recipient, subject: str, body: str) -> bool:
    """
    Validate email content before sending.

    Return False to skip sending to this recipient.
    """

    # Check minimum body length
    if len(body) < 100:
        print(f"  ⚠ Skipping {recipient.email}: body too short")
        return False

    # Check that all required variables were replaced
    if '{{' in subject or '{{' in body:
        print(f"  ⚠ Skipping {recipient.email}: unreplaced variables found")
        return False

    # Check recipient email format
    if '@' not in recipient.email or '.' not in recipient.email:
        print(f"  ⚠ Skipping {recipient.email}: invalid email format")
        return False

    return True


def rate_limiter_with_cooldown():
    """
    Custom rate limiter with progressive cooldown.

    Starts with 2 second delay, adds 1 second every 10 emails
    to avoid hitting rate limits.
    """
    base_delay = 2.0
    extra_delay = 0.1  # Add time every N sends

    count = 0

    def limiter():
        nonlocal count
        count += 1

        # Progressive backoff every 10 emails
        delay = base_delay + (count // 10) * extra_delay

        print(f"  (waiting {delay:.1f}s before next send...)")
        time.sleep(delay)

    return limiter


def main():
    """Run advanced batch send with hooks."""

    print("=" * 70)
    print("ADVANCED BATCH SEND EXAMPLE")
    print("Demonstrates hooks, validation, and rate limiting")
    print("=" * 70)

    # Setup
    account = input("\nEnter your Gmail address: ")
    adapter = get_adapter('gmail')({'address': account})

    if not adapter.is_configured():
        print(f"\nAccount not configured. Please run:")
        print(f"  python ../adapters/gmail.py setup --account {account}")
        sys.exit(1)

    # Create test recipients
    recipients = [
        Recipient('alice@example.com', name='Alice',
                 context={
                     'topic': 'AI research',
                     'specific_detail': 'your paper on neural networks',
                     'reason_for_contact': 'we are building similar technology',
                     'value_proposition': 'I think our approaches could complement each other.',
                     'sender_name': 'Bob',
                     'sender_title': 'CTO',
                     'sender_company': 'TechCorp'
                 }),
        Recipient('bob@example.com', name='Bob',
                 context={
                     'topic': 'blockchain',
                     'specific_detail': 'your work on consensus algorithms',
                     'reason_for_contact': 'we are exploring similar problems',
                     'value_proposition': 'Would love to exchange insights.',
                     'sender_name': 'Bob',
                     'sender_title': 'CTO',
                     'sender_company': 'TechCorp'
                 }),
        # Invalid recipient (missing variables) - should be skipped
        Recipient('invalid@example.com', name='Invalid',
                 context={'topic': 'test'}),  # Missing required variables
    ]

    # Load template
    template_path = Path(__file__).parent / 'templates/outreach.md'
    template = EmailTemplate.from_file(template_path)

    # Setup batch sender with hooks
    print("\nSetting up batch sender with hooks...")

    sender = BatchEmailSender(adapter, dry_run=True)  # dry_run=True for testing

    # Campaign tracker
    tracker = CampaignTracker('test-campaign')

    # Set hooks
    sender.set_pre_send_hook(validate_email_content)
    sender.set_post_send_hook(tracker.on_send)
    sender.set_rate_limiter(rate_limiter_with_cooldown())

    print("✓ Hooks configured:")
    print("  - Pre-send: Content validation")
    print("  - Post-send: Campaign tracking")
    print("  - Rate limiter: Progressive cooldown")

    # Preview
    print("\n" + "=" * 70)
    print("PREVIEW: First valid email")
    print("=" * 70)

    preview = sender.preview(template, recipients[0])
    print(f"\nTo: {preview['to']}")
    print(f"Subject: {preview['subject']}")
    print(f"\n{preview['body'][:200]}...\n")

    # Confirm
    response = input(f"\nProceed with batch send to {len(recipients)} recipients? (yes/no): ")

    if response.lower() != 'yes':
        print("Cancelled.")
        sys.exit(0)

    # Send
    print("\n" + "=" * 70)
    print("SENDING BATCH")
    print("=" * 70)
    print("\n(DRY RUN MODE - not actually sending)\n")

    result = sender.send_batch(template, recipients)

    # Results
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    tracker.summary()

    print(f"\nSuccess rate: {result.success_rate:.1f}%")

    # Detailed failures
    if result.failed > 0:
        print("\nDetailed failures:")
        for r in result.get_failed():
            print(f"  {r.recipient}:")
            print(f"    Error: {r.error}")

    print("\nNote: This was a DRY RUN. Set dry_run=False to actually send.\n")


if __name__ == "__main__":
    main()
