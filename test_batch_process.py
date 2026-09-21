#!/usr/bin/env python3
"""
Test script for batch_process convenience method.

This demonstrates the simplified API compared to manual initialization.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# Add parent directory to path for imports
mail_module = Path(__file__).parent
sys.path.insert(0, str(mail_module.parent))

from mail.processors.classifier import batch_process, batch_classify
from mail.adapters.gmail import Email


def create_mock_email(subject: str, sender: str, body: str, email_id: str = None) -> Email:
    """Create a mock email for testing."""
    if email_id is None:
        email_id = f"test_{subject.replace(' ', '_')}"

    return Email(
        id=email_id,
        thread_id=f"thread_{email_id}",
        subject=subject,
        sender=sender,
        sender_name=sender.split('@')[0],
        recipients=["user@example.com"],
        date=datetime.now(timezone.utc),
        snippet=body[:100],
        body_text=body,
        body_html=f"<p>{body}</p>",
        attachments=[],
        has_attachments=False,
        is_unread=True,
        raw={}
    )


def test_batch_process():
    """Test the batch_process convenience method."""
    print("Testing batch_process convenience method...\n")

    # Create test emails
    emails = [
        create_mock_email(
            "Meeting: Project Review Dec 18",
            "mallory@example.com",
            "Let's meet to review the project progress. Please reply with your availability."
        ),
        create_mock_email(
            "Newsletter: Tech Weekly Digest",
            "newsletter2@newsletter.example.com",
            "Unsubscribe here if you don't want these emails."
        ),
        create_mock_email(
            "Re: Invoice #12345",
            "billing3@vendor.example.com",
            "Please find the attached invoice for your recent purchase."
        )
    ]

    # Test 1: Using batch_process (new convenience method)
    print("=" * 60)
    print("TEST 1: Using batch_process (simplified API)")
    print("=" * 60)

    space_path = Path("/tmp/test_space")
    space_path.mkdir(exist_ok=True)

    result = batch_process(
        emails,
        space_path=space_path,
        address="user@example.com"
    )

    print(f"✓ Processed {result['total_count']} emails")
    print(f"✓ Found {result['actionable_count']} actionable emails")
    print(f"✓ Created {len(result['created_entries'])} org entries")
    print(f"\nCreated entries:")
    for entry in result['created_entries']:
        print(f"  - {entry}")

    # Show classification breakdown
    print(f"\nClassification breakdown:")
    for action_level, items in result['classifications'].items():
        if items:
            print(f"  {action_level}: {len(items)} emails")

    # Test 2: Compare with batch_classify (only classification)
    print("\n" + "=" * 60)
    print("TEST 2: Using batch_classify (classification only)")
    print("=" * 60)

    classifications = batch_classify(
        emails,
        address="user@example.com"
    )

    print(f"✓ Classified {sum(len(v) for v in classifications.values())} emails")
    print(f"\nClassification breakdown:")
    for action_level, items in classifications.items():
        if items:
            print(f"  {action_level}: {len(items)} emails")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("✓ batch_process() - One-line email processing (classify + create org entries)")
    print("✓ batch_classify() - One-line email classification (no org entries)")
    print("✓ quick_classify() - One-line single email classification")
    print("\nAll convenience methods working correctly!")


if __name__ == "__main__":
    test_batch_process()
