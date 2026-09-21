---
summary: "Email integration — Gmail adapter, AI classification, routing, and task creation"
triggers: ["check email", "process inbox", "classify emails", "mails setup"]
context: on_match
---

# Mail Module

## Purpose

Pulls emails from Gmail via OAuth, classifies by action needed (ACTIONABLE/INFORMATIONAL/CC/SPAM) and track (BUSINESS/RESEARCH/NEWSLETTER/GITHUB/FINANCE), then routes to specialized processors. Creates GTD tasks in `inbox.org` with email metadata. Supports sending emails directly from Datacore.

## Quick Start
> Say "check email" to pull, classify, and process your inbox.

## How It Works

### Processing Pipeline
```
Gmail API -> GmailAdapter -> ClassifierProcessor -> Specialized Processors -> inbox.org
                                    |
                    GitHub / Newsletter / Accounting / Archive
```

### Classification
Each email gets an action class and a track. CC and SPAM auto-archive. ACTIONABLE emails are grouped by sender for batch processing. Newsletter track feeds into research module.

### Multi-Space Support
Each space can have independent `mail.yaml` config with different accounts and rules overlaying `rules.base.yaml`.

## Agents & Commands

| Name | Type | When to use |
|------|------|-------------|
| `/mails` | command | Interactive email processing workflow |
| `/mails setup` | command | OAuth setup for new Gmail account |
| `/mails scan` | command | Quick inbox summary without processing |
| `mail-classifier` | agent | AI-powered email classification |
| `/triage-email` | command | Automated daily email triage — auto-archive, forward invoices, create tasks |
| `mail-responder` | agent | Nightshift agent for :AI:mail: tasks — draft replies, CRM notes |

## Key Paths

| Path | Purpose |
|------|---------|
| `{space}/mail.yaml` | Space email account config |
| `{space}/mail-rules.yaml` | Space-specific routing rules |
| `.datacore/env/credentials/` | OAuth credentials and tokens |
| `.datacore/modules/mail/data/scan_cache.json` | Cached scan results (gitignored) |

## Setup

1. Enable Gmail API in Google Cloud Console
2. Create OAuth credentials (Desktop app)
3. Download `credentials.json` to `.datacore/env/credentials/`
4. Run `/mails setup` to complete OAuth flow

## Boundaries

- Cannot delete emails permanently -- only archives/labels
- Cannot access accounts without OAuth consent
- Tasks include `EXTERNAL_ID` and `EXTERNAL_URL` for Gmail deep links

---

*This file covers structure, capability, and stable configuration. Learned behavior, user corrections, and operational preferences live as engrams -- call `plur_recall_hybrid` for those.*
