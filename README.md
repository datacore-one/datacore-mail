# Mail Module

> Multi-space, multi-account email integration for Datacore

Semi-automatic inbox processing with AI classification, specialized processors for GitHub/accounting/newsletters, and GTD task creation.


## Install

```bash
datacore module install https://github.com/datacore-one/datacore-mail
python3 -m pip install -r ~/Data/.datacore/modules/mail/requirements.txt   # if present
```

Requires a working [Datacore](https://datacore.one) installation.

## Quick Start

```bash
# Run interactive inbox processing
/mails

# The command will:
# 1. Auto-process trusted emails (CC, spam, newsletters)
# 2. Present ACTIONABLE emails for your decision
# 3. Execute approved actions
# 4. Report what was processed
```

## Features

- **Multi-space**: Each space has its own `.datacore/mail.yaml` configuration

### Inbound Email Processing
- **Multi-space**: Each space has its own `mail.yaml` configuration
- **Multi-account**: Multiple email addresses per space (e.g., `accounting@`, `info@`)
- **AI classification**: ACTIONABLE / INFORMATIONAL / IGNORE categorization
- **Specialized processors**: GitHub notifications, invoices, newsletters
- **Gmail support**: OAuth2 authentication with per-account tokens


### Outbound Batch Sending (NEW)
- **Template-based emails**: Variable substitution with `{{placeholder}}` syntax
- **Per-recipient personalization**: Custom context for each recipient
- **CSV-based recipient management**: Easy bulk sending from spreadsheets
- **Rate limiting**: Built-in delays to respect API quotas
- **Dry-run mode**: Preview and test before sending
- **Campaign integration**: Designed for comms module workflows
## Installation
The mail module is included in `.datacore/modules/mail/`. No additional installation required.
## Configuration

### Step 1: Gmail OAuth Setup

```bash
# Run setup for each Gmail account
python .datacore/modules/mail/adapters/gmail.py setup --account bob@example.com
```

This will:
1. Open browser for Google OAuth consent
2. Save token to `.datacore/env/mail/gmail-{account}.json`

### Step 2: Space Configuration

Create `.datacore/mail.yaml` in each space that needs email:

```yaml
# 1-teamspace/.datacore/mail.yaml
accounts:
  - name: main
    address: user@organization.example.com
    provider: gmail
    processor: classifier
    destination: org/inbox.org

  - name: accounting
    address: accounting@organization.example.com
    provider: gmail
    processor: accounting
    destination: org/accounting.org
    settings:
      extract_invoices: true
      invoice_folder: content/invoices
```

### Step 3: Sender Rules (Optional)

Create `.datacore/mail-rules.yaml` for sender-specific handling:

```yaml
# Base rules (sender patterns)
rules:
  - pattern: "@github.com$"
    action: github_process
    auto: true

  - pattern: "newsletter@"
    action: newsletter_queue

  - pattern: "noreply@"
    action: archive
    auto: true
```

## Commands

| Command | Purpose |
|---------|---------|
| `/mails` | Interactive inbox processing workflow |

## Processing Flow

```
/mails starts
    ↓
Preflight: Check OAuth tokens for all accounts
    ↓
Fetch: Get unread emails from Gmail
    ↓
Auto-process (no user decision needed):
  - CC emails (GitHub, invoices, FYI)
  - Known spam patterns
  - Newsletters with rules
    ↓
Classify remaining emails:
  - ACTIONABLE → Present to user
  - INFORMATIONAL → Auto-archive
  - IGNORE → Auto-archive
    ↓
Present ACTIONABLE emails grouped by sender
    ↓
User approves actions:
  - Create task in inbox.org
  - Create CRM note
  - Archive
  - Reply
    ↓
Execute actions, report summary
```

## Processors

| Processor | Description | Auto-Archive |
|-----------|-------------|--------------|
| `classifier` | AI classification into ACTIONABLE/INFORMATIONAL/IGNORE | No |
| `accounting` | Invoice extraction, vendor/amount/due date parsing | CC only |
| `github` | GitHub notification processing, issue linking | Yes |
| `newsletter` | Create research tasks for curated newsletters | Yes |
| `archive` | Just archive, no org entries | Yes |

## Email Classification

The mail-classifier agent categorizes emails:

### Inbound Processing
- `/mail-scan` - Scan configured mailboxes and process new emails
### Outbound Sending
- `/mail-compose` - Compose and send single emails
- Batch sending: See `BATCH_SEND_GUIDE.md` for templated campaigns

| Category | Description | Action |
|----------|-------------|--------|
| **ACTIONABLE** | Requires response or action | User decision |
| **INFORMATIONAL** | FYI, no action needed | Auto-archive |
| **IGNORE** | Spam, newsletters, automated | Auto-archive |

### What Triggers ACTIONABLE

- Direct question requiring answer
- Request for something (meeting, review, etc.)
- Contract, legal, or money discussion
- Unknown sender (needs review)

### What Auto-Processes

- CC emails (you're not primary recipient)
- GitHub notifications (processed separately)
- Invoices to accounting address
- Newsletters with matching rules
- Known spam patterns

## GTD Integration

ACTIONABLE emails become tasks in `{space}/org/inbox.org`:

```org
* TODO Reply to [[John Smith]] re: partnership proposal
  :PROPERTIES:
  :EXTERNAL_ID: gmail:user@organization.example.com/18d3f2a1b4c5d6e7
  :EXTERNAL_URL: https://mail.google.com/mail/#inbox/18d3f2a1b4c5d6e7
  :END:

  From: John Smith <john@example.com>
  Summary: Asking about timeline for partnership proposal response
```

## CRM Integration

New organization contacts can create CRM notes:

```markdown
# General Contact - Acme Corp

From: judy@example.com
Subject: Initial inquiry about data services
Date: 2025-01-07

## Context
Inbound inquiry from Acme Corp about our data services.

## Tags
#lead #inbound #services
```

## Settings

In module.yaml or settings.local.yaml:

```yaml
mail:
  auto_archive_cc: true        # Auto-archive CC/FYI emails
  auto_archive_spam: true      # Auto-archive detected spam
  daily_digest_enabled: true   # Aggregate daily news into single task
  github_auto_process: true    # Auto-process GitHub notifications
```

## File Locations

| File | Location | Purpose |
|------|----------|---------|
| Space config | `{space}/.datacore/mail.yaml` | Account configuration |
| Sender rules | `{space}/.datacore/mail-rules.yaml` | Per-sender handling |
| OAuth tokens | `.datacore/env/mail/gmail-{email}.json` | Gmail tokens |
| Invoices | `{space}/content/invoices/` | Extracted invoice PDFs |

## Architecture

```
{space}/.datacore/mail.yaml
            ↓
    Gmail Adapter (OAuth2)
            ↓
    Fetch unread emails
            ↓
    mail-classifier agent
            ↓
    Specialized Processors:
    ├─ GitHubProcessor
    ├─ AccountingProcessor
    └─ NewsletterProcessor
            ↓
    Actions:
    ├─ inbox.org (tasks)
    ├─ CRM notes
    └─ Archive
```

## External IDs

Emails use external ID format: `gmail:{address}/{message_id}`

Example: `gmail:accounting@organization.example.com/18d3f2a1b4c5d6e7`
This enables:
- Duplicate detection
- Opening email in Gmail via EXTERNAL_URL
- Tracking email → task relationship
## Dependencies
- `core@>=1.0.0` (required)
- `crm` (optional) - Create CRM notes from emails
- `nightshift` (optional) - Scheduled inbox processing
## Related DIPs
- [DIP-0009](../../dips/DIP-0009-gtd-specification.md) - GTD integration
- [DIP-0010](../../dips/DIP-0010-external-sync-architecture.md) - External sync pattern
- [DIP-0016](../../dips/DIP-0016-agent-registry.md) - Agent context patterns
## Version History
- **v1.1.0** - Gmail authorization script, moved config to `{space}/.datacore/`
- **v1.0.0** - Interactive `/mails` command, batch classification, action categories
- **v0.1.0** - Initial release: Gmail adapter, basic classification

Example: `gmail:billing2@vendor.example.com/18d3f2a1b4c5d6e7`
## Batch Outbound Sending
Send templated emails to multiple recipients with per-recipient personalization.
### Quick Start
```bash
# 1. Preview emails
python batch_send.py preview \
  --account alice@example.com \
  --template templates/outreach.md \
  --recipients recipients/prospects.csv
# 2. Dry run (test without sending)
python batch_send.py send \
  --account alice@example.com \
  --template templates/outreach.md \
  --recipients recipients/prospects.csv \
  --dry-run
# 3. Send for real
python batch_send.py send \
  --account alice@example.com \
  --template templates/outreach.md \
  --recipients recipients/prospects.csv \
  --delay 2.0
```
### Python API
```python
from mail.batch_send import batch_send_email, EmailTemplate, Recipient
from mail.adapters import get_adapter
# Setup
adapter = get_adapter('gmail')({'address': 'alice@example.com'})
template = EmailTemplate(
    subject="Hi {{name}}!",
    body="Hello {{name}}, {{message}}"
)
recipients = [
    Recipient('alice@example.com', name='Alice',
             context={'message': 'Great to meet you!'}),
    Recipient('bob@example.com', name='Bob',
             context={'message': 'Thanks for connecting!'})
]
# Send
result = batch_send_email(adapter, template, recipients, delay=2.0)
print(f"Sent {result.successful}/{result.total} emails")
```
### Documentation
See `BATCH_SEND_GUIDE.md` for:
- Complete API reference
- Template system details
- CSV format specification
- Advanced features (hooks, rate limiting)
- Campaign integration patterns
- Examples and best practices
### Examples
Check `examples/` directory for:
- `example_basic_send.py` - Simple batch sending workflow
- `example_advanced_hooks.py` - Validation, tracking, rate limiting
- `templates/` - Sample email templates
- `recipients/` - Sample CSV files
## Integration
### With Comms Module
Batch sending integrates with comms module campaign workflows:
```python
# Load campaign template and recipients
template = EmailTemplate.from_file('campaigns/investor-outreach/template.md')
recipients = load_recipients_from_csv('campaigns/investor-outreach/recipients.csv')
# Send campaign batch
result = batch_send_email(adapter, template, recipients)
# Log results for analytics
log_campaign_results('investor-outreach', result)
```
See `BATCH_SEND_GUIDE.md` for complete integration patterns.
