# Mail Processing Workflow

**Version:** 2.0 (Updated 2026-01-29)
**Applies to:** user@organization.example.com and all configured accounts

## Core Principle

**PROCESS, DON'T DELETE**
Emails contain information that should be captured into the GTD system or archived for reference. Deletion should be rare and deliberate.

---

## Processing Categories

### 1. NEWSLETTERS & SUBSCRIPTIONS

**Rule:** Extract value, then archive. Never delete without processing.

**Process:**
```
Newsletter arrives
    ↓
Read subject + snippet
    ↓
Is content relevant to current work/projects?
    ↓
YES → Create research task in inbox.org with link
    NO → Is source occasionally valuable?
        ↓
        YES → Archive for reference
        NO → Unsubscribe, THEN delete
```

**Task Template for Research:**
```org
* TODO Read: [Newsletter Subject]
  :PROPERTIES:
  :CREATED: [timestamp]
  :EXTERNAL_ID: gmail:user@organization.example.com/[message_id]
  :EXTERNAL_URL: [gmail_url]
  :END:

  From: [Newsletter name]
  Key topics: [brief note on why relevant]

  Link: [[EXTERNAL_URL]]
```

**Examples by Newsletter:**

| Newsletter | Process |
|------------|---------|
| **The Defiant** | Archive (crypto market context) |
| **CoinDesk Daybook** | Archive (market updates) |
| **Berkeley RDI** | Create task if agent-related |
| **The Rundown AI** | Create task if agent/AI infrastructure |
| **Superhuman AI** | Create task if tool/workflow related |
| **Not Boring** | Archive (business strategy) |
| **HBR** | Create task if management-related |
| **Ben's Bites** | Archive (AI landscape) |

**Special Cases:**
- **AgentX/Agent competitions** → ALWAYS create task (networking/partnership opportunities)
- **API updates** (HackMD, CoinGecko, etc.) → Create task if we use that API
- **Event newsletters** (TOKEN2049, EthCC, etc.) → Review dates, create calendar task if attending

### 2. SOCIAL MEDIA NOTIFICATIONS

**Rule:** Batch process weekly, prioritize real connections.

**LinkedIn:**
- **Connection requests** → Accept/decline immediately (keep inbox clean)
- **Mentions in posts** → Review if from key contacts, else archive
- **Job changes** → Archive (CRM will track if important)
- **Learning/promotional** → Delete (spam)

**Discord/Community:**
- **Payment confirmations** → Archive (receipts)
- **Event notifications** → Create calendar task if relevant
- **Promotional** → Delete

**Process:** Archive all social notifications, review batch weekly during GTD review.

### 3. BOOKING/TRAVEL EMAILS

**Rule:** NEVER auto-delete. Always contains time-sensitive info.

**Process:**
```
Booking.com/Travel email arrives
    ↓
Check subject for keywords:
  - "question" → READ IMMEDIATELY (action needed)
  - "message from [hotel]" → READ IMMEDIATELY
  - "cancellation" → READ IMMEDIATELY
  - "confirmation" → Archive (reference)
  - "rate your stay" → Archive (low priority)
    ↓
If action needed → Create task in inbox.org
If reference → Archive, do NOT delete
```

**Examples:**
- ✅ "We have a question about your booking" → **URGENT TASK**
- ✅ "You have a message from [hotel]" → **URGENT TASK**
- ✅ "Cancellation confirmation" → **Archive (receipt)**
- ✅ "Rate your stay" → **Archive (can delete after 90 days)**

### 4. PAYMENT/FINANCIAL EMAILS

**Rule:** Archive all, forward to accounting@organization.example.com if business expense.

**Types:**
- **Invoices/Receipts** → Archive + forward to accounting
- **Payment failures** → CREATE URGENT TASK
- **Renewal reminders** → Create task 7 days before renewal
- **T&C updates** → Archive (legal reference)

**Process:**
```
Payment email arrives
    ↓
Is payment FAILED?
    YES → Create urgent task (fix within 24h)
    NO → Is business expense?
        YES → Forward to accounting@organization.example.com + archive
        NO → Archive
```

### 5. GITHUB NOTIFICATIONS

**Rule:** Filter by type, don't flood inbox.

**Auto-delete (set up Gmail filter):**
- CI/CD run failures (check GitHub directly)
- Workflow run notifications
- Weekly digest summaries

**Process manually:**
- @mentions in issues/PRs → Create task
- Security alerts (Dependabot) → Create task
- PR reviews requested → Create task
- Issue assignments → Create task

**Gmail Filter Setup:**
```
From: noreply6@service.example.com
Subject: "Run failed" OR "Run cancelled" OR "workflow run"
Action: Delete (skip inbox)
```

### 6. TEAM/INTERNAL EMAILS

**Rule:** Always process, never auto-delete.

**From team members (Alice, Bob, Carol):**
- Read immediately
- Create task if action needed
- Archive for reference

**Calendar invites:**
- Accept/decline immediately
- Archive after meeting completes
- Keep only UPCOMING meetings in inbox

### 7. PARTNERSHIP/BUSINESS INQUIRIES

**Rule:** All partnership emails get CRM note + task.

**Process:**
```
Business inquiry arrives
    ↓
Is sender known contact?
    YES → Reply + archive
    NO → Is opportunity relevant?
        YES → Create CRM note + task in inbox.org
        NO → Polite decline + archive
```

**Examples:**
- Mayur Vastari (Qubit Capital) → CRM note + task
- Mario Paladini (Club Globals) → CRM note + task
- Lyudmil Stoyanov (CloudOpsters) → Review, decide, then CRM note OR decline

### 8. EVENT FOLLOW-UPS (Davos, conferences)

**Rule:** Process within 48 hours while connections are warm.

**Process:**
```
Post-event email arrives
    ↓
Is it from a 1:1 conversation?
    YES → Reply within 24h + create CRM note
    NO → Is it event photos/recordings?
        YES → Archive (reference)
        NO → Mass email/newsletter → Archive
```

**Priority levels:**
- **Direct follow-up request** (coffee, meeting) → REPLY WITHIN 24H
- **Thank you + photos** → Archive, optional reply
- **Event newsletter** → Archive

---

## Daily Processing Routine

**Morning (10 min):**
1. Scan for URGENT (payment failures, booking issues, team escalations)
2. Process partnership/business inquiries
3. Accept/decline calendar invites
4. Archive newsletters (batch process during weekly review)

**Weekly Review (30 min):**
1. Process archived newsletters → Create research tasks for relevant content
2. Review social notifications → Archive or create tasks
3. Clean up GitHub notifications
4. Unsubscribe from consistently irrelevant sources

---

## Gmail Filters to Set Up

### Auto-Archive (Don't Delete)
```
From: (newsletter3@newsletter.example.com OR newsletter4@newsletter.example.com)
Label: newsletters
Skip inbox: Yes
```

### Auto-Delete (Only for noise)
```
From: noreply6@service.example.com
Subject: (Run failed OR Run cancelled OR workflow run)
Delete: Yes
```

### Priority Inbox
```
From: (alice@organization.example.com OR bob@organization.example.com OR carol@organization.example.com)
Mark as important: Yes
```

---

## Archive vs Delete Decision Tree

```
Should I delete this email?
    ↓
Has financial/legal value? → NO DELETE (archive)
    ↓
From business contact? → NO DELETE (archive)
    ↓
Contains booking/travel confirmation? → NO DELETE (archive)
    ↓
Newsletter with research value? → NO DELETE (archive + task)
    ↓
Pure spam (no info value)? → YES DELETE
```

**Only delete:**
- Pure spam (promotional emails with no information)
- Duplicate emails (same content sent twice)
- After unsubscribing from irrelevant source
- Old GitHub CI notifications (>30 days, checked GitHub directly)

---

## Task Creation Templates

### Research Task (Newsletter)
```org
* TODO Read: [Subject]
  :PROPERTIES:
  :CREATED: [timestamp]
  :CATEGORY: Research
  :EXTERNAL_ID: gmail:user@organization.example.com/[id]
  :EXTERNAL_URL: [url]
  :END:

  From: [Newsletter]
  Why relevant: [1 sentence]
```

### Follow-up Task (Partnership)
```org
* TODO Follow up with [[Name]] re: [Topic]
  :PROPERTIES:
  :CREATED: [timestamp]
  :CATEGORY: Outreach
  :EXTERNAL_ID: gmail:user@organization.example.com/[id]
  :EXTERNAL_URL: [url]
  :CONTACT: [Name]
  :ORGANIZATION: [Company]
  :END:

  Context: [Brief summary of conversation/email]
  Next action: [Specific action needed]
```

### Urgent Task (Payment/Booking)
```org
* TODO [#A] [Action needed]
  SCHEDULED: <[today]>
  :PROPERTIES:
  :CREATED: [timestamp]
  :CATEGORY: Admin
  :EXTERNAL_ID: gmail:user@organization.example.com/[id]
  :EXTERNAL_URL: [url]
  :END:

  Issue: [Brief description]
  Deadline: [If time-sensitive]
```

---

## Audit & Recovery

**If something was deleted by mistake:**
1. Check Gmail Trash (30-day retention)
2. Search by sender or subject
3. Restore to inbox: Remove TRASH label, add INBOX + UNREAD
4. Process properly according to this workflow

**Quarterly cleanup:**
- Review archived newsletters (older than 90 days) → Batch delete if never referenced
- Unsubscribe from sources with 0% read rate
- Update this workflow based on patterns

---

## Version History

- **v2.0 (2026-01-29):** Updated after aggressive deletion incident
  - Added "PROCESS, DON'T DELETE" principle
  - Added newsletter research task workflow
  - Added booking/travel safety checks
  - Added specific newsletter handling rules

- **v1.0 (2025-12-10):** Initial workflow

---

## See Also

- `.datacore/modules/mail/README.md` - Technical documentation
- `1-teamspace/.datacore/mail.yaml` - Account configuration
- `0-personal/.datacore/mail-rules.yaml` - Personal sender rules
