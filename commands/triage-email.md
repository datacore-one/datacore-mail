---
name: triage-email
description: triage-email command
recall:
  # DIP-0029 default — engrams scoped to this command + tag-matched.
  scopes:
    - command:triage-email
  tags:
    - triage-email
---

# /triage-email

Scan the Gmail inbox for activity, execute auto-actions, generate a summary, and create actionable GTD tasks.

## Trigger

- Standalone: `/triage-email`
- Called by `/today` hook
- Called by nightshift fallback when overnight scan did not run

## Behavior

Execute these steps in order:

### Step 1: Scan Inbox

Run the inbox scanner (uses cache if already run today):

```bash
python3 .datacore/modules/mail/lib/email_scanner.py \
  --account grace@example.com \
  --days 3 \
  --cache .datacore/modules/mail/data/scan_cache.json \
  --format json
```

Parse the JSON output to get the list of emails, classifications, and auto-action candidates.

### Step 2: Execute Auto-Actions

Run the scanner again in execute mode to apply auto-actions (archive, label, forward):

```bash
python3 .datacore/modules/mail/lib/email_scanner.py \
  --account grace@example.com \
  --days 3 \
  --cache .datacore/modules/mail/data/scan_cache.json \
  --execute \
  --forward-to billing2@vendor.example.com
```

### Step 3: Create Tasks

If `auto_task_create` is enabled (default: true), create tasks from actionable emails:

```bash
python3 .datacore/modules/mail/lib/task_creator.py \
  --scan-file .datacore/modules/mail/data/scan_cache.json \
  --data-dir ~/Data
```

### Step 4: Generate Summary

Use the scan results to produce a markdown summary:

```bash
python3 .datacore/modules/mail/lib/email_scanner.py \
  --account grace@example.com \
  --days 3 \
  --cache .datacore/modules/mail/data/scan_cache.json \
  --format summary
```

**NEEDS ATTENTION section** (full structured detail for emails requiring a reply or decision):

```markdown
### Email: Needs Attention

- From: sender@example.com — "Subject line"
  Reason: reply requested | decision needed | deadline
  [View](gmail-url)
```

**AUTO-PROCESSED section** (compact counts by action taken):

```markdown
### Email: Auto-Processed

| Action | Count |
|--------|-------|
| Archived (newsletters) | N |
| Labeled (receipts) | N |
| Forwarded to accounting | N |
```

**TASKS CREATED section** (audit trail):

```markdown
### Email: Tasks Created

- N new tasks created in next_actions.org
- N items skipped (already tracked)
- Tasks tagged :AI:mail: for nightshift processing
```

### Step 5: Display or Return

If called standalone: display the full summary to the user.
If called by /today hook: return the summary for insertion into the daily briefing.

## Settings

Read from `.datacore/modules/mail/module.yaml`:

| Setting | Key | Default |
|---------|-----|---------|
| Gmail account | `account` | grace@example.com |
| Scan window (days) | `scan_days` | 3 |
| Auto-create tasks | `auto_task_create` | true |
| Accounting forward address | `forward_accounting` | billing2@vendor.example.com |
| Excluded senders | `exclude_senders` | [] |

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Gmail not authenticated | Show error: "Run `python3 authorize_gmail.py` first" |
| API quota exceeded | Use cached data, show warning |
| No emails in scan window | Show "No new email activity in the last 3 days" |
| scan_cache.json missing | Run fresh scan, create cache |
| task_creator fails | Log warning, skip task creation, continue with summary |
