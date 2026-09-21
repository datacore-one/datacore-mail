# Classifier Convenience API

The ClassifierProcessor provides three convenience methods that eliminate the need for complex initialization boilerplate. These methods are ideal for scripts, notebooks, and quick integrations.

## Overview

| Method | Purpose | Returns |
|--------|---------|---------|
| `quick_classify()` | Classify a single email | `Classification` object |
| `batch_classify()` | Classify multiple emails | Dict grouped by action level |
| `batch_process()` | Classify and create org entries | Dict with classifications + created entries |

## quick_classify()

**One-liner for single email classification.**

```python
from mail.processors.classifier import quick_classify
from mail.adapters.gmail import Email

# Minimal usage
classification = quick_classify(email)

# With address for CC detection
classification = quick_classify(email, address="user@example.com")

print(f"Action: {classification.action}")
print(f"Tracks: {classification.tracks}")
print(f"Priority: {classification.priority}")
```

### Use Cases
- Quick email analysis in notebooks
- Testing classification rules
- One-off email processing
- Scripts that don't need to persist a processor instance

## batch_classify()

**Classify multiple emails with minimal setup.**

Returns a dictionary grouped by action level (ACTIONABLE, INFORMATIONAL, CC, SPAM, GITHUB, etc.).

```python
from mail.processors.classifier import batch_classify

# Simplest usage - just pass emails
results = batch_classify(emails)

# With custom address
results = batch_classify(emails, address="user@example.com")

# Full control with config and space path
results = batch_classify(
    emails,
    config={'destination': 'org/inbox.org', 'address': 'user@example.com'},
    space_path=Path('/path/to/space')
)

# Access results by action level
for email in results['ACTIONABLE']:
    print(f"{email['subject']} - {email['tracks']}")

for email in results['INFORMATIONAL']:
    print(f"{email['subject']} - {email['sender']}")
```

### Return Structure

```python
{
    'ACTIONABLE': [
        {
            'date': '2026-03-26',
            'sender': 'John Doe',
            'email': 'mallory@example.com',
            'subject': 'Re: Q4 Planning',
            'unread': True,
            'action': 'ACTIONABLE',
            'tracks': ['BUSINESS'],
            'has_attachment': False,
            'age_days': 0,
            'is_stale': False,
            'priority': 'HIGH',
            'suggested_title': 'Reply to John Doe re: Q4 Planning',
            'external_id': 'gmail:mallory@example.com/abc123',
            'gmail_url': 'https://mail.google.com/mail/u/0/#inbox/abc123',
            'matched_rules': ['actionable:reply_chain']
        }
    ],
    'INFORMATIONAL': [...],
    'CC': [...],
    'SPAM': [...],
    'GITHUB': [...],
    'ACCOUNTING': [...],
    'ARCHIVE': [...]
}
```

### Use Cases
- Batch email analysis
- Generating reports on email categories
- Filtering emails before processing
- Testing rule configurations

## batch_process()

**Classify emails AND create org entries for actionable ones.**

This is the complete workflow: classification + org entry creation for actionable emails.

```python
from mail.processors.classifier import batch_process
from pathlib import Path

# Simplest usage
result = batch_process(emails, space_path=Path('/path/to/space'))

# With custom address
result = batch_process(
    emails,
    space_path=Path('/path/to/space'),
    address="user@example.com"
)

# Full control
result = batch_process(
    emails,
    space_path=Path('/path/to/space'),
    config={'destination': 'org/inbox.org', 'address': 'user@example.com'}
)

print(f"Processed {result['total_count']} emails")
print(f"Created {len(result['created_entries'])} org entries")
print(f"Actionable: {result['actionable_count']}")
```

### Return Structure

```python
{
    'classifications': {
        # Same structure as batch_classify()
        'ACTIONABLE': [...],
        'INFORMATIONAL': [...],
        # etc.
    },
    'created_entries': [
        '/path/to/space/org/inbox.org'
    ],
    'actionable_count': 5,
    'total_count': 20
}
```

### Use Cases
- End-to-end email processing workflows
- Automated inbox processing
- Nightshift task execution
- Integration with GTD systems

## Comparison with Manual Initialization

### Before (Manual Initialization)

```python
from mail.processors.classifier import ClassifierProcessor
from pathlib import Path

# Complex setup required
config = {
    'destination': 'org/inbox.org',
    'address': 'user@example.com'
}
space_path = Path('/path/to/space')
processor = ClassifierProcessor(config, space_path)

# Classify each email
for email in emails:
    classification = processor.classify(email)
    # Manual handling...
```

### After (Convenience Methods)

```python
from mail.processors.classifier import batch_classify

# One line
results = batch_classify(emails, address="user@example.com")
```

## Parameters

### Config Dictionary (Optional)

All three methods accept an optional `config` dictionary:

```python
config = {
    'destination': 'org/inbox.org',  # Where to create org entries
    'address': 'user@example.com'     # Your email for CC detection
}
```

If not provided, config is auto-generated with sensible defaults. The `address` parameter is a shorthand for `config={'address': 'user@example.com'}`.

### Space Path (Optional)

- Required for `batch_process()` (needed to create org files)
- Optional for `batch_classify()` and `quick_classify()` (enables space-specific rules if provided)

## Best Practices

1. **Use `quick_classify()` for**:
   - Single email analysis
   - Interactive notebooks
   - Testing rules

2. **Use `batch_classify()` for**:
   - Analyzing email batches
   - Generating reports
   - Pre-filtering before processing

3. **Use `batch_process()` for**:
   - Complete email workflows
   - Automated processing
   - GTD integration

## Examples

### Example 1: Quick Email Triage

```python
from mail.processors.classifier import quick_classify
from mail.adapters.gmail import GmailAdapter

adapter = GmailAdapter({"address": "user@example.com"})
emails = adapter.pull_emails(days=1)

for email in emails:
    cls = quick_classify(email, address="user@example.com")
    if cls.action == 'ACTIONABLE' and cls.priority == 'HIGH':
        print(f"⚠️ HIGH PRIORITY: {email.subject}")
```

### Example 2: Weekly Email Report

```python
from mail.processors.classifier import batch_classify
from mail.adapters.gmail import GmailAdapter

adapter = GmailAdapter({"address": "user@example.com"})
emails = adapter.pull_emails(days=7)

results = batch_classify(emails, address="user@example.com")

print(f"Weekly Email Report")
print(f"==================")
print(f"Actionable: {len(results['ACTIONABLE'])}")
print(f"Informational: {len(results['INFORMATIONAL'])}")
print(f"GitHub: {len(results['GITHUB'])}")
print(f"Spam: {len(results['SPAM'])}")
```

### Example 3: Automated Inbox Processing

```python
from mail.processors.classifier import batch_process
from mail.adapters.gmail import GmailAdapter
from pathlib import Path

# Pull emails
adapter = GmailAdapter({"address": "user@example.com"})
emails = adapter.pull_unread()

# Process in one call
result = batch_process(
    emails,
    space_path=Path.cwd() / "0-personal",
    address="user@example.com"
)

print(f"Processed {result['total_count']} emails")
print(f"Created {len(result['created_entries'])} inbox entries")

# Mark processed emails as read
for email in emails:
    if any(email.external_id in e['external_id']
           for e in result['classifications']['ACTIONABLE']):
        adapter.mark_as_read(email.id)
```

## Testing

Test files demonstrating all convenience methods:

- `test_batch_convenience.py` - Tests for `batch_classify()` and `quick_classify()`
- `test_batch_process.py` - Tests for `batch_process()`

Run tests:

```bash
cd .datacore/modules/mail
python3 test_batch_convenience.py
python3 test_batch_process.py
```

## Migration Guide

If you have existing code using manual initialization:

```python
# Old way
processor = ClassifierProcessor(config, space_path)
for email in emails:
    cls = processor.classify(email)
    # handle classification

# New way - same functionality, cleaner
results = batch_classify(emails, config=config, space_path=space_path)
for email_result in results['ACTIONABLE']:
    # handle actionable emails
```

The convenience methods don't replace the ClassifierProcessor class - they're wrappers that make common patterns easier. For complex use cases with custom processing logic, you can still instantiate ClassifierProcessor directly.
