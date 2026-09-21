---
name: nightshift-hook
description: nightshift-hook command
recall:
  # DIP-0029 default — engrams scoped to this command + tag-matched.
  scopes:
    - command:nightshift-hook
  tags:
    - nightshift-hook
---

# Mail Nightshift Hook

## Purpose

Runs during nightshift overnight execution to triage email inboxes.
Creates :AI:mail: tasks in next_actions.org for actionable items.

## Behavior

1. Scan configured Gmail accounts for unread emails (past 3 days)
2. Classify each email (ACTIONABLE/INFORMATIONAL/CC/SPAM)
3. Auto-archive CC and SPAM
4. Create GTD tasks for ACTIONABLE items in inbox.org
5. Write summary to nightshift output

## Implementation

```bash
python3 .datacore/modules/mail/server/triage-mail.sh
```

Or via Claude:
```
Scan email accounts configured in 0-personal/.datacore/mail.yaml.
For each account:
1. Pull unread emails from past 3 days
2. Classify by action needed
3. Auto-archive newsletters, CC, and spam
4. Create inbox.org tasks for actionable items
5. Report summary
```
