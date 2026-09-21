---
name: today-hook
description: today-hook command
recall:
  # DIP-0029 default — engrams scoped to this command + tag-matched.
  scopes:
    - command:today-hook
  tags:
    - today-hook
---

# Email Hook: /today Integration

## Command Context

### When to Reference Mail Module

**Always reference when:**
- /today command is invoked (automatic hook)
- User requests daily briefing or morning summary
- User asks about email activity or inbox status

**Key decisions the module informs:**
- Which emails need user attention vs agent handling
- Whether nightshift ran and processed email tasks overnight
- What auto-actions were applied (forwarded, archived, labeled)

### Quick Reference

| Question | Answer |
|----------|--------|
| What format? | NEEDS ATTENTION (structured) + AUTO-PROCESSED (table) |
| What window? | Past 3 days of inbox activity |
| When to run live scan? | If nightshift didn't run overnight |
| What tone? | Factual, concise, action-oriented |

### Agents This Command Invokes

| Agent | Purpose |
|-------|---------|
| (None directly) | Reads scan cache or runs scanner scripts |

### Integration Points

- **/today command** — parent command that calls this hook
- **/triage-email** — can run full triage if nightshift missed
- **scan caches** — per-account JSON at `.datacore/state/mail/scan_cache_<account>.json`
- **audit log** — append-only JSONL at `.datacore/state/mail/audit.jsonl` (one line per triage run)
- **next_actions.org** — where tasks are created

### Easy Path (recommended)

`today_brief_section.py` produces the full Email section as markdown — `/today` should call it directly and embed the output:

```bash
python3 ~/Data/.datacore/modules/mail/lib/today_brief_section.py
```

This reads the latest audit-log line + per-account scan caches and produces a ready-to-paste markdown block with:
- Overnight triage table (per-account counts + totals)
- Per-account "Left for you" tables with Sender + Subject
- Audit log pointers

If the helper exists and a cache is fresh, use this — skip Paths 1/2 below.

---

This hook adds an Email activity summary to the daily briefing.

## Trigger

Called by `/today` command when mail module is installed.

## Behavior

### Path 1: Nightshift Ran Overnight

Check if nightshift ran by looking for output files:

```python
from pathlib import Path
import sys

sys.path.insert(0, str(Path.home() / "Data" / ".datacore" / "lib"))
from triage_utils import check_nightshift_ran

data_dir = Path.home() / "Data"
nightshift_ran = check_nightshift_ran(data_dir)
```

If nightshift ran:

1. **Check for cached scan results** — look for `scan_cache.json` with today's timestamp:
   - If cache is from today: use it directly, skip re-scan
   - If cache is stale or missing: run `/triage-email` fresh

2. **Show agent report** — scan next_actions.org for recently completed :AI:mail: tasks:
   - Tasks marked DONE today/yesterday with :AI:mail: tag
   - Extract LOGBOOK entries for what the agent did
   - Show count + action types (replied, archived, forwarded)

3. **Run fresh triage** — execute `/triage-email` to get current state:
   - New emails needing attention, auto-processed counts
   - Create new tasks for items not yet tracked

Output format:
```markdown
### Email

**Agent Report** (overnight):
- 3 newsletters archived automatically
- 2 receipts labeled and forwarded to accounting
- 1 reply drafted: [View thread](gmail-url)

**New Activity** (last 3 days):
[/triage-email summary output here]
```

### Path 2: Nightshift Did NOT Run

If nightshift didn't run:

1. **Flag the issue**:
```markdown
> ⚠ Nightshift did not run overnight. Running email triage live.
```

2. **Run `/triage-email` live** — full scan + auto-actions + task creation during /today

3. **Create tasks** — so nightshift picks them up next cycle

Output format:
```markdown
### Email

> ⚠ Nightshift did not run overnight. Running email triage live.

[/triage-email full summary output here]
```

## Section to Generate

The hook produces a `### Email` section containing:

1. **Agent Report** (if nightshift ran) — what was auto-processed overnight
2. **Needs Attention** — emails requiring a reply, decision, or action
3. **Auto-Processed** — compact table of actions taken (archived, labeled, forwarded)
4. **Tasks Created** — count of new :AI:mail: tasks

## Conditions

| Condition | Behavior |
|-----------|----------|
| Gmail not authenticated | Skip section, show warning with auth instructions |
| No email activity | Show "No email activity in the last 3 days" |
| Nightshift didn't run | Flag it, run triage live |
| API quota exceeded during /today | Use cached data from last scan |
| Scan cache exists from today | Use cache, don't re-scan |

## Tone

- Factual, action-oriented
- Lead with what needs attention
- Agent report first (what was done for you), then new items requiring action
