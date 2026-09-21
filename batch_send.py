"""
Batch Email Sending for Mail Module.

Extends send_email() for fresh outbound campaigns with templating
and per-recipient customization for prospecting/outreach.

Integrates with comms module campaign workflows.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import re
from datetime import datetime


@dataclass
class EmailTemplate:
    """Template for batch email sending."""
    subject: str
    body: str
    from_name: Optional[str] = None
    reply_to: Optional[str] = None

    # Optional template customization
    variables: List[str] = field(default_factory=list)

    def render(self, context: Dict[str, Any]) -> tuple[str, str]:
        """
        Render template with context variables.

        Args:
            context: Dict of variable replacements

        Returns:
            Tuple of (rendered_subject, rendered_body)
        """
        rendered_subject = self._replace_vars(self.subject, context)
        rendered_body = self._replace_vars(self.body, context)

        return rendered_subject, rendered_body

    def _replace_vars(self, text: str, context: Dict[str, Any]) -> str:
        """Replace {{variable}} placeholders with context values."""
        def replace_match(match):
            var_name = match.group(1).strip()
            return str(context.get(var_name, match.group(0)))

        return re.sub(r'\{\{([^}]+)\}\}', replace_match, text)

    @classmethod
    def from_file(cls, template_path: Path) -> 'EmailTemplate':
        """
        Load template from markdown file with frontmatter.

        Expected format:
        ---
        subject: Your subject line with {{variable}}
        from_name: Optional sender name
        reply_to: Optional reply-to address
        ---

        Email body with {{variable}} placeholders...
        """
        content = template_path.read_text()

        # Parse frontmatter
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                import yaml
                metadata = yaml.safe_load(parts[1])
                body = parts[2].strip()

                return cls(
                    subject=metadata.get('subject', 'No Subject'),
                    body=body,
                    from_name=metadata.get('from_name'),
                    reply_to=metadata.get('reply_to')
                )

        # Fallback: no frontmatter, just body
        return cls(subject='No Subject', body=content)


@dataclass
class Recipient:
    """Individual recipient with personalization context."""
    email: str
    name: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    # Optional per-recipient overrides
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    attachments: List[Path] = field(default_factory=list)

    def get_full_context(self) -> Dict[str, Any]:
        """Get complete context including name and email."""
        ctx = {
            'email': self.email,
            'name': self.name or self.email.split('@')[0],
            **self.context
        }
        return ctx


@dataclass
class SendResult:
    """Result of sending to a single recipient."""
    recipient: str
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    sent_at: Optional[datetime] = None


@dataclass
class BatchSendResult:
    """Result of batch send operation."""
    total: int
    successful: int
    failed: int
    results: List[SendResult]

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        return (self.successful / self.total * 100) if self.total > 0 else 0.0

    def get_failed(self) -> List[SendResult]:
        """Get list of failed sends."""
        return [r for r in self.results if not r.success]

    def get_successful(self) -> List[SendResult]:
        """Get list of successful sends."""
        return [r for r in self.results if r.success]


class BatchEmailSender:
    """
    Batch email sender with templating and per-recipient customization.

    Usage:
        from mail.batch_send import BatchEmailSender, EmailTemplate, Recipient
        from mail.adapters import get_adapter

        # Setup adapter
        adapter = get_adapter('gmail')({'address': 'you@example.com'})
        sender = BatchEmailSender(adapter)

        # Create template
        template = EmailTemplate(
            subject="Hi {{name}}, let's connect!",
            body="Hello {{name}},\n\nI noticed {{detail}}..."
        )

        # Create recipient list
        recipients = [
            Recipient('alice@example.com', name='Alice',
                     context={'detail': 'your work on X'}),
            Recipient('bob@example.com', name='Bob',
                     context={'detail': 'your research on Y'})
        ]

        # Send batch
        result = sender.send_batch(template, recipients)
        print(f"Sent {result.successful}/{result.total} emails")
    """

    def __init__(self, adapter, dry_run: bool = False):
        """
        Initialize batch sender.

        Args:
            adapter: Mail adapter (e.g., GmailAdapter)
            dry_run: If True, don't actually send emails
        """
        self.adapter = adapter
        self.dry_run = dry_run

        # Optional hooks for validation and rate limiting
        self._pre_send_hook: Optional[Callable] = None
        self._post_send_hook: Optional[Callable] = None
        self._rate_limiter: Optional[Callable] = None

    def set_pre_send_hook(self, hook: Callable[[Recipient, str, str], bool]):
        """
        Set pre-send validation hook.

        Hook signature: (recipient, subject, body) -> bool
        Return False to skip sending to this recipient.
        """
        self._pre_send_hook = hook

    def set_post_send_hook(self, hook: Callable[[SendResult], None]):
        """
        Set post-send callback hook.

        Hook signature: (result) -> None
        """
        self._post_send_hook = hook

    def set_rate_limiter(self, limiter: Callable[[], None]):
        """
        Set rate limiting function (e.g., time.sleep).

        Hook signature: () -> None
        Called between each send.
        """
        self._rate_limiter = limiter

    def send_batch(
        self,
        template: EmailTemplate,
        recipients: List[Recipient],
        delay_between_sends: float = 0.0
    ) -> BatchSendResult:
        """
        Send templated email to multiple recipients.

        Each recipient gets a personalized email based on their context.

        Args:
            template: Email template with placeholders
            recipients: List of recipients with personalization data
            delay_between_sends: Seconds to wait between sends (rate limiting)

        Returns:
            BatchSendResult with success/failure details
        """
        import time

        results = []

        for recipient in recipients:
            # Render template for this recipient
            context = recipient.get_full_context()
            subject, body = template.render(context)

            # Pre-send hook (validation)
            if self._pre_send_hook:
                if not self._pre_send_hook(recipient, subject, body):
                    results.append(SendResult(
                        recipient=recipient.email,
                        success=False,
                        error="Skipped by pre-send hook"
                    ))
                    continue

            # Send email
            result = self._send_single(
                recipient=recipient,
                subject=subject,
                body=body
            )
            results.append(result)

            # Post-send hook
            if self._post_send_hook:
                self._post_send_hook(result)

            # Rate limiting
            if self._rate_limiter:
                self._rate_limiter()
            elif delay_between_sends > 0:
                time.sleep(delay_between_sends)

        # Compile results
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful

        return BatchSendResult(
            total=len(results),
            successful=successful,
            failed=failed,
            results=results
        )

    def _send_single(
        self,
        recipient: Recipient,
        subject: str,
        body: str
    ) -> SendResult:
        """Send email to single recipient."""
        try:
            if self.dry_run:
                # Dry run: simulate success
                return SendResult(
                    recipient=recipient.email,
                    success=True,
                    message_id=f"DRY_RUN_{recipient.email}",
                    sent_at=datetime.now()
                )

            # Actually send via adapter
            message_id = self.adapter.send_email(
                to=[recipient.email],
                subject=subject,
                body=body,
                cc=recipient.cc if recipient.cc else None,
                bcc=recipient.bcc if recipient.bcc else None,
                attachments=recipient.attachments if recipient.attachments else None
            )

            if message_id:
                return SendResult(
                    recipient=recipient.email,
                    success=True,
                    message_id=message_id,
                    sent_at=datetime.now()
                )
            else:
                return SendResult(
                    recipient=recipient.email,
                    success=False,
                    error="Adapter returned None (send failed)"
                )

        except Exception as e:
            return SendResult(
                recipient=recipient.email,
                success=False,
                error=str(e)
            )

    def preview(
        self,
        template: EmailTemplate,
        recipient: Recipient
    ) -> Dict[str, str]:
        """
        Preview rendered email for a recipient without sending.

        Args:
            template: Email template
            recipient: Recipient to preview for

        Returns:
            Dict with 'subject' and 'body' keys
        """
        context = recipient.get_full_context()
        subject, body = template.render(context)

        return {
            'to': recipient.email,
            'subject': subject,
            'body': body,
            'cc': recipient.cc,
            'bcc': recipient.bcc,
            'attachments': [str(p) for p in recipient.attachments]
        }


# =============================================================================
# Convenience Functions
# =============================================================================

def batch_send_email(
    adapter,
    template: EmailTemplate,
    recipients: List[Recipient],
    dry_run: bool = False,
    delay: float = 0.0
) -> BatchSendResult:
    """
    Convenience function for batch sending.

    Args:
        adapter: Mail adapter (e.g., GmailAdapter)
        template: Email template
        recipients: List of recipients
        dry_run: If True, don't actually send
        delay: Seconds to wait between sends

    Returns:
        BatchSendResult
    """
    sender = BatchEmailSender(adapter, dry_run=dry_run)
    return sender.send_batch(template, recipients, delay_between_sends=delay)


def load_recipients_from_csv(csv_path: Path) -> List[Recipient]:
    """
    Load recipients from CSV file.

    Expected CSV format:
    email,name,var1,var2,...
    alice@example.com,Alice,value1,value2

    First row is header. Columns after 'name' become context variables.

    Args:
        csv_path: Path to CSV file

    Returns:
        List of Recipient objects
    """
    import csv

    recipients = []

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)

        for row in reader:
            email = row.pop('email')
            name = row.pop('name', None)

            # Remaining columns become context
            context = {k: v for k, v in row.items() if v}

            recipients.append(Recipient(
                email=email,
                name=name,
                context=context
            ))

    return recipients


# =============================================================================
# CLI Interface
# =============================================================================

if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Batch Email Sender")
    parser.add_argument("command", choices=["send", "preview", "validate"],
                       help="Command to run")
    parser.add_argument("--account", required=True,
                       help="Email account address")
    parser.add_argument("--template", required=True, type=Path,
                       help="Path to email template file")
    parser.add_argument("--recipients", required=True, type=Path,
                       help="Path to recipients CSV file")
    parser.add_argument("--dry-run", action="store_true",
                       help="Don't actually send emails")
    parser.add_argument("--delay", type=float, default=1.0,
                       help="Delay between sends (seconds)")

    args = parser.parse_args()

    # Load adapter
    from adapters import get_adapter
    adapter = get_adapter('gmail')({'address': args.account})

    if not adapter.is_configured():
        print(f"ERROR: Account {args.account} not configured")
        print(f"Run: python gmail.py setup --account {args.account}")
        sys.exit(1)

    # Load template
    if not args.template.exists():
        print(f"ERROR: Template not found: {args.template}")
        sys.exit(1)

    template = EmailTemplate.from_file(args.template)

    # Load recipients
    if not args.recipients.exists():
        print(f"ERROR: Recipients file not found: {args.recipients}")
        sys.exit(1)

    recipients = load_recipients_from_csv(args.recipients)

    if args.command == "preview":
        print(f"\n=== Preview: First 3 Recipients ===\n")
        sender = BatchEmailSender(adapter, dry_run=True)

        for i, recipient in enumerate(recipients[:3]):
            preview = sender.preview(template, recipient)
            print(f"\n--- Recipient {i+1}: {preview['to']} ---")
            print(f"Subject: {preview['subject']}")
            print(f"\n{preview['body'][:200]}...")
            print()

    elif args.command == "validate":
        print(f"\n=== Validation ===\n")
        print(f"Template: {args.template}")
        print(f"Recipients: {len(recipients)}")
        print(f"Account: {args.account}")
        print(f"\nRecipients:")
        for r in recipients[:10]:
            print(f"  - {r.email} ({r.name})")
        if len(recipients) > 10:
            print(f"  ... and {len(recipients) - 10} more")
        print("\nReady to send!" if len(recipients) > 0 else "ERROR: No recipients")

    elif args.command == "send":
        print(f"\n=== Batch Send ===\n")
        print(f"Sending to {len(recipients)} recipients...")

        if args.dry_run:
            print("(DRY RUN - not actually sending)")

        result = batch_send_email(
            adapter,
            template,
            recipients,
            dry_run=args.dry_run,
            delay=args.delay
        )

        print(f"\n=== Results ===")
        print(f"Total: {result.total}")
        print(f"Successful: {result.successful}")
        print(f"Failed: {result.failed}")
        print(f"Success Rate: {result.success_rate:.1f}%")

        if result.failed > 0:
            print(f"\nFailed sends:")
            for r in result.get_failed():
                print(f"  ✗ {r.recipient}: {r.error}")

        print()
