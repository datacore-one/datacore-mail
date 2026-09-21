# Batch Processing Convenience Methods

The mail module's ClassifierProcessor now includes three convenience methods that simplify common usage patterns.

## Overview

| Method | Purpose | Returns | Creates Org Entries? |
|--------|---------|---------|---------------------|
| `batch_process()` | Full email processing pipeline | Classifications + created entry paths | ✓ Yes (for actionable) |
| `batch_classify()` | Classification only | Classifications grouped by action level | ✗ No |
| `quick_classify()` | Single email classification | Classification object | ✗ No |

## Usage Examples

### 1. Full Processing Pipeline: `batch_process()`

**Use when:** You want to classify emails AND create org entries for actionable ones in a single call.

```python
from pathlib import Path
from mail.processors.classifier import batch_process

# Simplest usage - handles all setup
result = batch_process(
    emails,
    space_path=Path('/path/to/space')
)

print(f"Processed {result['total_count']} emails")
print(f"Created {len(result['created_entries'])} org entries")

# Access full classifications
for action_level, items in result['classifications'].items():
    print(f"{action_level}: {len(items)} emails")
```

**With custom configuration:**

```python
result = batch_process(
    emails,
    space_path=Path('/path/to/space'),
    config={
        'destination': 'org/inbox.org',
        'address': 'user@example.com'
    }
)
```

**Returns:**
```python
{
    'classifications': {
        'ACTIONABLE': [...],
        'INFORMATIONAL': [...],
        'CC': [...],
        'SPAM': [...],
        'GITHUB': [...],
        'ACCOUNTING': [...],
        'ARCHIVE': [...]
    },
    'created_entries': ['/path/to/space/org/inbox.org'],
    'actionable_count': 3,
    'total_count': 10
}
```

### 2. Classification Only: `batch_classify()`

**Use when:** You only need classifications without creating org entries (e.g., for reporting, analysis).

```python
from mail.processors.classifier import batch_classify

# Simplest usage
classifications = batch_classify(emails)

# With custom address for CC detection
classifications = batch_classify(
    emails,
    address="user@example.com"
)

# With full config
classifications = batch_classify(
    emails,
    config={'destination': 'org/inbox.org', 'address': 'user@example.com'},
    space_path=Path('/path/to/space')
)
```

**Returns:**
```python
{
    'ACTIONABLE': [
        {
            'date': '2026-03-26',
            'sender': 'John Doe',
            'email': 'mallory@example.com',
            'subject': 'Project Review',
            'unread': True,
            'action': 'ACTIONABLE',
            'tracks': ['BUSINESS', 'CALENDAR'],
            'priority': 'HIGH',
            'suggested_title': 'Decide: Project Review',
            'external_id': 'gmail:mallory@example.com/abc123',
            'gmail_url': 'https://mail.google.com/mail/u/0/#inbox/abc123',
            'matched_rules': ['calendar:meeting', 'actionable:reply_chain']
        }
    ],
    'INFORMATIONAL': [...],
    # ... other action levels
}
```

### 3. Single Email: `quick_classify()`

**Use when:** You need to classify just one email without maintaining a processor instance.

```python
from mail.processors.classifier import quick_classify

classification = quick_classify(
    email,
    address="user@example.com"
)

print(f"Action: {classification.action}")
print(f"Tracks: {classification.tracks}")
print(f"Priority: {classification.priority}")
print(f"Matched rules: {classification.matched_rules}")
```

**Returns:** `Classification` object with fields:
- `action`: ACTIONABLE, INFORMATIONAL, CC, SPAM, GITHUB
- `tracks`: List of categories (BUSINESS, RESEARCH, NEWSLETTER, etc.)
- `confidence`: 0.0-1.0
- `priority`: HIGH, MEDIUM, LOW
- `effort`: Quick, Moderate, Significant
- `suggested_title`: Recommended title for org entry
- `matched_rules`: List of rule patterns that triggered
- `processor`: Route to specialized processor ('github', 'accounting', None)
- `age_days`: Days since email received
- `is_stale`: True if > 30 days old
- `event_date`: Detected event date (for calendar emails)
- `event_passed`: True if event has passed

## Migration from Manual Setup

### Before (Complex Manual Setup):

```python
from mail.processors.classifier import ClassifierProcessor

# Manual processor initialization
classifier = ClassifierProcessor(
    {"destination": account.destination, "address": account.address},
    space_path=account.space_path
)

created_entries = []
for email in emails:
    classification = classifier.classify(email)

    if classification.action == 'ACTIONABLE':
        entry_path = classifier.process(email, account.space_path)
        if entry_path:
            created_entries.append(entry_path)
```

### After (One-Line Convenience):

```python
from mail.processors.classifier import batch_process

# Single line handles everything
result = batch_process(
    emails,
    space_path=account.space_path,
    address=account.address
)

created_entries = result['created_entries']
```

## When to Use Which Method

| Scenario | Use |
|----------|-----|
| Process inbox (classify + create org entries) | `batch_process()` |
| Email analytics/reporting (no org entries) | `batch_classify()` |
| Quick check of single email | `quick_classify()` |
| Need full control over processing flow | Manual `ClassifierProcessor` instance |

## Advanced: Space-Specific Rules

All three methods support space-specific rule merging (DIP-0002):

```python
# Rules are merged: base → space → local
result = batch_process(
    emails,
    space_path=Path('1-acme/'),  # Loads 1-acme/mail-rules.yaml
    address="user@example.com"
)
```

Rule layers:
1. **Base**: `.datacore/modules/mail/rules.base.yaml` (PUBLIC)
2. **Space**: `[space]/mail-rules.yaml` (SPACE)
3. **Local**: `.datacore/modules/mail/rules.local.yaml` (PRIVATE)

Later rules override/extend earlier ones.
