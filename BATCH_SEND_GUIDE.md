# Batch Email Sending Guide

Complete guide for using batch outbound email sending in the mail module.

## Overview

The batch sending feature extends the mail module's `send_email()` for **fresh outbound campaigns** with:
- Template-based emails with variable substitution
- Per-recipient personalization
- CSV-based recipient management
- Dry-run and preview modes
- Rate limiting and hooks
- Integration with comms module campaigns

## Quick Start

### 1. Create Email Template

Create a template file (e.g., `templates/outreach.md`):

```markdown
---
subject: Hi {{name}}, let's connect about {{topic}}
from_name: Your Name
reply_to: you@example.com
---

Hi {{name}},

I noticed your work on {{topic}} and thought we should connect.

{{custom_message}}

Looking forward to hearing from you!

Best,
Your Name
```

**Variables**: Any `{{variable}}` in subject or body will be replaced with recipient context.

### 2. Create Recipients CSV

Create a CSV file (e.g., `recipients/prospects.csv`):

```csv
email,name,topic,custom_message
alice@example.com,Alice,AI research,Your paper on neural networks was fascinating.
bob@example.com,Bob,blockchain,Your talk at the conference was excellent.
carol@example.com,Carol,data privacy,I'd love to discuss GDPR compliance.
```

**Format**:
- First row: column headers
- Required: `email`
- Optional: `name` (falls back to email prefix)
- All other columns become context variables

### 3. Preview Before Sending

```bash
cd .datacore/modules/mail

python batch_send.py preview \
  --account alice@example.com \
  --template templates/outreach.md \
  --recipients recipients/prospects.csv
```

Shows how first 3 emails will look with variables replaced.

### 4. Validate Setup

```bash
python batch_send.py validate \
  --account alice@example.com \
  --template templates/outreach.md \
  --recipients recipients/prospects.csv
```

Checks:
- Template exists and is valid
- Recipients CSV is properly formatted
- Account is configured

### 5. Dry Run

```bash
python batch_send.py send \
  --account alice@example.com \
  --template templates/outreach.md \
  --recipients recipients/prospects.csv \
  --dry-run
```

Simulates sending without actually sending emails. Shows what would happen.

### 6. Send for Real

```bash
python batch_send.py send \
  --account alice@example.com \
  --template templates/outreach.md \
  --recipients recipients/prospects.csv \
  --delay 2.0
```

Sends emails with 2-second delay between each (rate limiting).

## Python API

### Basic Usage

```python
from pathlib import Path
from mail.batch_send import (
    BatchEmailSender,
    EmailTemplate,
    Recipient,
    batch_send_email
)
from mail.adapters import get_adapter

# Setup adapter
adapter = get_adapter('gmail')({'address': 'alice@example.com'})

# Create template
template = EmailTemplate(
    subject="Hi {{name}}, let's talk {{topic}}",
    body="Hello {{name}},\n\nI'd love to discuss {{topic}} with you.\n\nBest,\nMe"
)

# Create recipients
recipients = [
    Recipient('alice@example.com', name='Alice',
             context={'topic': 'AI ethics'}),
    Recipient('bob@example.com', name='Bob',
             context={'topic': 'blockchain'})
]

# Send batch (convenience function)
result = batch_send_email(adapter, template, recipients, delay=1.0)

print(f"Sent {result.successful}/{result.total} emails")
print(f"Success rate: {result.success_rate:.1f}%")

# Check failures
for failed in result.get_failed():
    print(f"Failed: {failed.recipient} - {failed.error}")
```

### Advanced Usage with Hooks

```python
from mail.batch_send import BatchEmailSender

sender = BatchEmailSender(adapter, dry_run=False)

# Pre-send validation hook
def validate_email(recipient, subject, body):
    """Return False to skip this recipient."""
    if len(body) < 50:
        print(f"Skipping {recipient.email}: body too short")
        return False
    return True

sender.set_pre_send_hook(validate_email)

# Post-send callback hook
def log_send(result):
    """Called after each send."""
    status = "✓" if result.success else "✗"
    print(f"{status} {result.recipient}")

sender.set_post_send_hook(log_send)

# Custom rate limiter
import time
def rate_limit():
    time.sleep(2.0)  # 2 seconds between sends

sender.set_rate_limiter(rate_limit)

# Send with hooks
result = sender.send_batch(template, recipients)
```

### Loading from Files

```python
from mail.batch_send import EmailTemplate, load_recipients_from_csv

# Load template from file
template = EmailTemplate.from_file(Path('templates/outreach.md'))

# Load recipients from CSV
recipients = load_recipients_from_csv(Path('recipients/prospects.csv'))

# Send
result = batch_send_email(adapter, template, recipients)
```

### Per-Recipient Customization

```python
from mail.batch_send import Recipient

# Advanced recipient with overrides
recipient = Recipient(
    email='alice@example.com',
    name='Alice',
    context={
        'topic': 'AI research',
        'detail': 'your work on neural networks',
        'call_to_action': 'review this proposal'
    },
    # Optional per-recipient overrides
    cc=['erin@example.com'],
    attachments=[Path('proposal.pdf')]
)

recipients = [recipient]
result = batch_send_email(adapter, template, recipients)
```

### Preview Mode

```python
from mail.batch_send import BatchEmailSender

sender = BatchEmailSender(adapter, dry_run=True)

# Preview for specific recipient
preview = sender.preview(template, recipients[0])

print(f"To: {preview['to']}")
print(f"Subject: {preview['subject']}")
print(f"\n{preview['body']}")
```

## Template System

### Variable Substitution

Templates use `{{variable}}` syntax for substitution:

```markdown
Hi {{name}},

I saw your work on {{topic}} and wanted to reach out about {{detail}}.

Best regards,
{{sender_name}}
```

### Built-in Variables

Recipients automatically get:
- `{{email}}` - recipient's email address
- `{{name}}` - recipient's name (or email prefix if not provided)

Custom variables come from recipient context.

### Conditional Content

For conditional content, use Python to generate different templates:

```python
def get_template(recipient_type):
    if recipient_type == 'investor':
        return EmailTemplate(
            subject="Investment opportunity: {{company}}",
            body="Dear {{name}},\n\nWe're raising {{amount}}..."
        )
    else:
        return EmailTemplate(
            subject="Partnership with {{company}}",
            body="Hi {{name}},\n\nLet's collaborate on {{topic}}..."
        )
```

## Campaign Integration

### Integration with Comms Module

The batch sending system integrates with comms module campaigns:

```python
# In comms module campaign workflow:
from mail.batch_send import batch_send_email, EmailTemplate
from mail.adapters import get_adapter

# Load campaign template
template = EmailTemplate.from_file(
    Path('campaigns/investor-outreach/email-template.md')
)

# Load campaign recipients
recipients = load_recipients_from_csv(
    Path('campaigns/investor-outreach/recipients.csv')
)

# Get configured mail account
adapter = get_adapter('gmail')({'address': 'ivan@example.com'})

# Send campaign batch
result = batch_send_email(
    adapter,
    template,
    recipients,
    delay=3.0  # Be conservative with rate limiting
)

# Log results to campaign tracking
log_campaign_results('investor-outreach', result)
```

### Campaign Tracking

Track batch send results for campaign analytics:

```python
from datetime import datetime

def log_campaign_results(campaign_name, batch_result):
    """Log campaign send results for analytics."""

    log_entry = {
        'campaign': campaign_name,
        'timestamp': datetime.now().isoformat(),
        'total': batch_result.total,
        'successful': batch_result.successful,
        'failed': batch_result.failed,
        'success_rate': batch_result.success_rate,
        'failed_recipients': [
            {'email': r.recipient, 'error': r.error}
            for r in batch_result.get_failed()
        ]
    }

    # Save to campaign log
    import json
    log_path = Path(f'campaigns/{campaign_name}/send-log.json')

    if log_path.exists():
        logs = json.loads(log_path.read_text())
        logs.append(log_entry)
    else:
        logs = [log_entry]

    log_path.write_text(json.dumps(logs, indent=2))
```

## Best Practices

### Rate Limiting

**Always use rate limiting** for batch sends to avoid:
- Gmail API rate limits (quota exceeded)
- Being flagged as spam
- Account suspension

Recommended delays:
- Small batches (<10): 1-2 seconds
- Medium batches (10-50): 2-5 seconds
- Large batches (>50): 5-10 seconds

```python
result = batch_send_email(adapter, template, recipients, delay=5.0)
```

### Testing Strategy

1. **Preview**: Check how emails look
2. **Validate**: Verify setup is correct
3. **Dry run**: Simulate full send
4. **Test send**: Send to yourself first
5. **Small batch**: Try 3-5 real recipients
6. **Full batch**: Send to all after confirming quality

### Email Quality

**Before sending**:
- ✓ Test all variable substitutions work
- ✓ Preview renders correctly
- ✓ Check for typos in template
- ✓ Verify recipient data is correct
- ✓ Test with your own email first
- ✓ Ensure opt-out/unsubscribe info if needed

**During send**:
- ✓ Monitor for errors
- ✓ Check success rate
- ✓ Review failed sends
- ✓ Stop if success rate drops below 90%

**After send**:
- ✓ Track bounces
- ✓ Monitor replies
- ✓ Check spam complaints
- ✓ Log results for analytics

### Privacy & Compliance

**IMPORTANT**:
- Get consent before sending marketing emails
- Include unsubscribe mechanism for newsletters
- Follow CAN-SPAM, GDPR, and other regulations
- Don't send to purchased/scraped email lists
- Respect opt-outs immediately

### Error Handling

```python
result = batch_send_email(adapter, template, recipients)

# Check for failures
if result.failed > 0:
    print(f"Warning: {result.failed} emails failed")

    # Log failures for retry
    failed_recipients = [
        r for r in recipients
        if r.email in [f.recipient for f in result.get_failed()]
    ]

    # Save for manual review or retry
    save_failed_recipients('failed-batch.csv', failed_recipients)

# Check success rate
if result.success_rate < 90:
    print("ERROR: Success rate too low, investigate!")
    # Pause campaign, check account status, etc.
```

## Troubleshooting

### "Account not configured"

Run Gmail OAuth setup:
```bash
cd .datacore/modules/mail
python adapters/gmail.py setup --account alice@example.com
```

### "Quota exceeded"

You hit Gmail API daily send limit (500-2000 depending on account type).

**Solutions**:
- Use longer delays between sends
- Spread campaign over multiple days
- Use multiple sending accounts
- Upgrade to Google Workspace for higher limits

### "Failed to send" errors

Check:
1. Internet connection
2. Gmail API credentials still valid
3. Recipient email addresses valid
4. Template renders without errors
5. Adapter has send permissions

### Low success rate

Possible causes:
- Invalid recipient email addresses
- Template rendering errors
- Gmail blocking (account flagged)
- Network issues

**Debug**:
```python
# Enable detailed logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Dry run to check rendering
result = batch_send_email(adapter, template, recipients, dry_run=True)
```

## Examples

### Example 1: Investor Outreach

**Template** (`templates/investor-outreach.md`):
```markdown
---
subject: {{company}} - Series A update for {{quarter}}
---

Hi {{name}},

As one of our valued investors, here's our {{quarter}} update:

Revenue: {{revenue}}
Growth: {{growth}}
Key milestones: {{milestones}}

{{custom_note}}

Best regards,
CEO Name
```

**Recipients** (`recipients/investors.csv`):
```csv
email,name,company,quarter,revenue,growth,milestones,custom_note
carol@example.com,Alice,Acme Inc,Q4 2024,$2M,150%,Launched product X,Thanks for your continued support!
dave@example.com,Bob,Acme Inc,Q4 2024,$2M,150%,Launched product X,Looking forward to our call next week.
```

**Send**:
```bash
python batch_send.py send \
  --account frank@example.com \
  --template templates/investor-outreach.md \
  --recipients recipients/investors.csv \
  --delay 3.0
```

### Example 2: Product Launch Announcement

**Template**:
```markdown
---
subject: Introducing {{product}} - built for {{industry}}
---

Hi {{name}},

We just launched {{product}}, designed specifically for {{industry}}.

Key features:
{{features}}

{{personal_note}}

Try it free: {{signup_link}}

Best,
Product Team
```

**Send with Python**:
```python
template = EmailTemplate.from_file(Path('templates/launch.md'))

recipients = [
    Recipient('bob@example.com', name='Alice', context={
        'product': 'Acme Pro',
        'industry': 'fintech',
        'features': '- Real-time analytics\n- Fraud detection',
        'personal_note': 'Given your work in payments, this should be perfect.',
        'signup_link': 'https://acme.com/signup?ref=alice'
    }),
    # ... more recipients
]

result = batch_send_email(adapter, template, recipients, delay=2.0)
```

### Example 3: Event Invitations

**Template with RSVP tracking**:
```markdown
---
subject: You're invited: {{event_name}} on {{event_date}}
---

Hi {{name}},

You're invited to {{event_name}}!

When: {{event_date}} at {{event_time}}
Where: {{location}}

{{event_description}}

RSVP: {{rsvp_link}}

See you there!
```

**Generate unique RSVP links**:
```python
import uuid

recipients = []
for email, name in contacts:
    rsvp_id = str(uuid.uuid4())
    recipients.append(Recipient(
        email=email,
        name=name,
        context={
            'event_name': 'Tech Meetup',
            'event_date': 'Jan 15, 2025',
            'event_time': '6:00 PM',
            'location': 'Downtown Office',
            'event_description': 'Join us for networking and demos.',
            'rsvp_link': f'https://events.com/rsvp/{rsvp_id}'
        }
    ))

result = batch_send_email(adapter, template, recipients)
```

## API Reference

See `batch_send.py` for complete API documentation.

**Key classes**:
- `EmailTemplate` - Template with variable substitution
- `Recipient` - Single recipient with context
- `BatchEmailSender` - Main batch sending class
- `BatchSendResult` - Results with success/failure details

**Key functions**:
- `batch_send_email()` - Convenience function for simple sends
- `load_recipients_from_csv()` - Load recipients from CSV file

## Integration Points

### With Comms Module

The batch sending system is designed to integrate with comms module campaign workflows:

1. **Campaign templates** stored in `campaigns/{name}/`
2. **Recipient lists** managed per campaign
3. **Send logs** tracked for analytics
4. **Follow-up sequences** triggered by responses

### With CRM Module

Integrate with CRM for recipient management:

```python
# Load recipients from CRM
from crm import CRMModule

crm = CRMModule()
contacts = crm.get_contacts(status='active', tag='investor')

recipients = [
    Recipient(c.email, name=c.name, context=c.custom_fields)
    for c in contacts
]

result = batch_send_email(adapter, template, recipients)

# Update CRM with send status
for r in result.get_successful():
    crm.log_interaction(r.recipient, 'email_sent',
                        message_id=r.message_id)
```

## Future Enhancements

Planned features:
- [ ] HTML email templates (currently plain text only)
- [ ] Attachment templates (per-recipient file substitution)
- [ ] A/B testing (multiple templates, split recipients)
- [ ] Scheduled sends (queue for future delivery)
- [ ] Response tracking (link clicks, open rates)
- [ ] Bounce handling (update recipient status)
- [ ] Retry failed sends automatically
- [ ] Integration with email verification services

## Support

For issues or questions:
1. Check this guide
2. Review example scripts in `examples/`
3. Check mail module README
4. Create issue in datacore repo
