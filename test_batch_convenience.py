#!/usr/bin/env python3
"""
Test script for batch_classify() and quick_classify() convenience methods.

This demonstrates the simplified API that requires no complex initialization.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys

# Add parent directories to path for imports
mail_module = Path(__file__).parent
sys.path.insert(0, str(mail_module.parent))

# Now we can import from the mail module
from mail.processors.classifier import batch_classify, quick_classify
from mail.adapters.gmail import Email


def create_mock_email(
    sender: str,
    subject: str,
    body: str = "",
    recipients: list = None,
    is_unread: bool = True,
    has_attachments: bool = False
) -> Email:
    """Create a mock Email object for testing."""

    if recipients is None:
        recipients = ['user@example.com']

    # Generate IDs
    email_id = f'test_{abs(hash(sender + subject))}'
    thread_id = f'thread_{abs(hash(sender))}'

    # Extract sender name (if present)
    sender_name = ""
    sender_email = sender
    if '<' in sender and '>' in sender:
        sender_name = sender.split('<')[0].strip()
        sender_email = sender.split('<')[1].split('>')[0].strip()

    # Create minimal raw structure
    raw = {
        'id': email_id,
        'threadId': thread_id,
        'labelIds': ['INBOX', 'UNREAD'] if is_unread else ['INBOX'],
        'snippet': body[:100] if body else subject[:100],
        'payload': {
            'headers': [
                {'name': 'From', 'value': sender},
                {'name': 'To', 'value': ', '.join(recipients)},
                {'name': 'Subject', 'value': subject},
                {'name': 'Date', 'value': datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0000')}
            ],
            'parts': []
        }
    }

    attachments = []
    if has_attachments:
        raw['payload']['parts'] = [
            {
                'filename': 'invoice.pdf',
                'mimeType': 'application/pdf',
                'body': {'size': 50000}
            }
        ]
        attachments = [
            {
                'filename': 'invoice.pdf',
                'mimeType': 'application/pdf',
                'size': 50000
            }
        ]

    return Email(
        id=email_id,
        thread_id=thread_id,
        subject=subject,
        sender=sender_email,
        sender_name=sender_name,
        recipients=recipients,
        date=datetime.now(timezone.utc),
        snippet=body[:100] if body else subject[:100],
        body_text=body,
        body_html="",
        labels=['INBOX', 'UNREAD'] if is_unread else ['INBOX'],
        is_unread=is_unread,
        is_starred=False,
        has_attachments=has_attachments,
        attachments=attachments,
        raw=raw
    )


def test_quick_classify():
    """Test quick_classify() - single email classification."""
    print("\n" + "="*70)
    print("TEST 1: quick_classify() - Single Email Classification")
    print("="*70)

    # Create test email
    email = create_mock_email(
        sender="noreply6@service.example.com",
        subject="[datacore/core] Issue #123: Bug in processor",
        body="@username mentioned you in an issue...",
        recipients=["user@example.com"]
    )

    # Classify with minimal setup
    classification = quick_classify(email, address="user@example.com")

    print(f"\nEmail: {email.subject}")
    print(f"From: {email.sender}")
    print(f"\nClassification:")
    print(f"  Action: {classification.action}")
    print(f"  Tracks: {', '.join(classification.tracks)}")
    print(f"  Priority: {classification.priority}")
    print(f"  Suggested Title: {classification.suggested_title}")
    print(f"  Processor Route: {classification.processor or 'None (standard)'}")
    print(f"  Matched Rules: {', '.join(classification.matched_rules[:3])}...")

    assert classification.action == 'GITHUB', f"Expected GITHUB, got {classification.action}"
    assert 'GITHUB' in classification.tracks, "GITHUB should be in tracks"
    print("\n✓ Test passed!")


def test_batch_classify_simple():
    """Test batch_classify() with minimal arguments."""
    print("\n" + "="*70)
    print("TEST 2: batch_classify() - Simple Usage (No Config)")
    print("="*70)

    # Create diverse test emails
    emails = [
        create_mock_email(
            "noreply6@service.example.com",
            "[datacore/core] PR #456: Add feature X",
            "Pull request opened by @developer..."
        ),
        create_mock_email(
            "newsletter1@newsletter.example.com",
            "TechCrunch Daily: Top Stories",
            "Unsubscribe at bottom..."
        ),
        create_mock_email(
            "erin@example.com",
            "Re: Q4 Planning",
            "Can you review the attached document?"
        ),
        create_mock_email(
            "noreply5@service.example.com",
            "You Won the Lottery!!!",
            "Click here to claim..."
        ),
        create_mock_email(
            "billing5@vendor.example.com",
            "Invoice INV-2024-001",
            "Please find attached invoice...",
            has_attachments=True
        )
    ]

    # Simplest possible usage - just pass emails
    results = batch_classify(emails)

    print(f"\nProcessed {len(emails)} emails")
    print(f"\nResults by Action Level:")
    for action, items in results.items():
        if items:
            print(f"\n  {action}: {len(items)} email(s)")
            for item in items:
                print(f"    - {item['subject'][:50]}")
                print(f"      Tracks: {', '.join(item['tracks'])}")

    assert len(results['GITHUB']) >= 1, "Should have at least 1 GitHub email"
    assert len(results['INFORMATIONAL']) >= 1, "Should have at least 1 newsletter"
    print("\n✓ Test passed!")


def test_batch_classify_with_config():
    """Test batch_classify() with custom config and space path."""
    print("\n" + "="*70)
    print("TEST 3: batch_classify() - With Custom Config")
    print("="*70)

    emails = [
        create_mock_email(
            "peggy@example.com",
            "Partnership Opportunity",
            "I'd like to discuss..."
        ),
        create_mock_email(
            "github-actions@github.com",
            "[datacore/core] CI Build Failed",
            "The CI pipeline failed..."
        )
    ]

    # Usage with custom config
    results = batch_classify(
        emails,
        config={
            'destination': 'org/custom-inbox.org',
            'address': 'custom@example.com'
        },
        space_path=Path('/tmp/test-space')
    )

    print(f"\nProcessed {len(emails)} emails with custom config")
    print(f"Config: destination='org/custom-inbox.org', address='custom@example.com'")

    total = sum(len(items) for items in results.values())
    assert total == len(emails), f"Should process all {len(emails)} emails"
    print("\n✓ Test passed!")


def test_batch_classify_with_address():
    """Test batch_classify() with just address override."""
    print("\n" + "="*70)
    print("TEST 4: batch_classify() - With Address Only")
    print("="*70)

    emails = [
        create_mock_email(
            "rupert@example.com",
            "Team Update",
            recipients=["niaj@example.com", "support7@vendor.example.com"]
        )
    ]

    # Usage with just address (config auto-generated)
    results = batch_classify(emails, address="niaj@example.com")

    print(f"\nProcessed with address='niaj@example.com'")

    # Check that email was processed
    total = sum(len(items) for items in results.values())
    assert total == 1, "Should process the email"
    print("\n✓ Test passed!")


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("MAIL MODULE: Batch Convenience Methods Test Suite")
    print("="*70)

    try:
        test_quick_classify()
        test_batch_classify_simple()
        test_batch_classify_with_config()
        test_batch_classify_with_address()

        print("\n" + "="*70)
        print("ALL TESTS PASSED ✓")
        print("="*70)
        print("\nSummary:")
        print("  - quick_classify(): One-liner for single email classification")
        print("  - batch_classify(): Minimal args needed, smart defaults")
        print("  - Both methods eliminate complex initialization boilerplate")
        print("\n")

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
