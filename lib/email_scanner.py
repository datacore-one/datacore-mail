#!/usr/bin/env python3
"""
Email Scanner — Core triage classification engine for the mail module.

Pulls emails from Gmail, classifies them against rules.base.yaml, groups them
into categories, optionally executes auto-actions, and generates markdown
summaries for /today briefings.

Usage:
    python3 email_scanner.py --account grace@example.com --days 3 \
        --cache data/scan_cache.json --format json

    python3 email_scanner.py --account grace@example.com --days 3 \
        --execute --forward-to billing2@vendor.example.com --format summary
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

# Module root: .datacore/modules/mail/
MODULE_ROOT = Path(__file__).parent.parent
RULES_DEFAULT = MODULE_ROOT / "rules.base.yaml"

# ---------------------------------------------------------------------------
# Adapter import (relative, works when run from repo root or directly)
# ---------------------------------------------------------------------------

def _import_gmail_adapter():
    """Lazy-import GmailAdapter so the file can be imported without google-api."""
    import importlib.util
    adapter_path = MODULE_ROOT / "adapters" / "gmail.py"
    spec = importlib.util.spec_from_file_location("gmail_adapter", adapter_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.GmailAdapter, mod.Email


# ---------------------------------------------------------------------------
# 1. load_rules
# ---------------------------------------------------------------------------

def load_rules(rules_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load classification rules from YAML.

    Supports layered overrides: base → local (rules.local.yaml).

    Args:
        rules_path: Path to rules YAML. Defaults to rules.base.yaml.

    Returns:
        Merged rules dict.
    """
    path = Path(rules_path) if rules_path else RULES_DEFAULT
    with open(path) as f:
        rules = yaml.safe_load(f)

    # Apply local overlay if it exists (rules.local.yaml, gitignored)
    local_path = path.parent / "rules.local.yaml"
    if local_path.exists():
        with open(local_path) as f:
            local = yaml.safe_load(f) or {}
        rules = _deep_merge(rules, local)

    return rules


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Merge override into base, lists are extended (not replaced)."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        elif key in result and isinstance(result[key], list) and isinstance(val, list):
            result[key] = result[key] + val
        else:
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# 2. classify_email
# ---------------------------------------------------------------------------

def classify_email(email: Any, rules: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classify a single email against the rules.

    Priority order (highest → lowest):
      1. CI noise (GitHub Actions failures/cancels, npm publishes)
      2. Ignore/spam senders
      3. GitHub notifications (general)
      4. Calendar notifications
      5. LinkedIn / explicit newsletter spam
      6. n8n notifications
      7. Research senders
      8. Actionable senders
      9. Finance subjects
     10. Newsletter domains
     11. Body-based detection (unsubscribe links etc.)
     12. Unknown → conservative "review"

    Args:
        email: Email dataclass instance (from GmailAdapter).
        rules: Loaded rules dict from load_rules().

    Returns:
        dict with keys:
          category  — auto_archive | forward_accounting | research | newsletter |
                      actionable | calendar | github | n8n | unknown
          action    — auto_archive | forward | review | task | aggregate_daily_news |
                      prepare_for_research | check_calendar_sync | check_event_passed |
                      update_task | check_involvement
          priority  — HIGH | MEDIUM | LOW | None
          reason    — human-readable explanation
          tags      — list of topic tags
          rule_name — name of the matching rule (for debugging)
    """
    sender = (email.sender or "").lower()
    sender_name = (email.sender_name or "").lower()
    subject = (email.subject or "").lower()
    body = (email.body_text or "").lower()
    snippet = (email.snippet or "").lower()

    def _pattern_matches(pattern: str, text: str) -> bool:
        return pattern.lower() in text

    # ------------------------------------------------------------------
    # 1. CI noise — GitHub Actions run failures / cancels
    # ------------------------------------------------------------------
    if sender == "noreply6@service.example.com":
        if "run failed:" in subject or "run cancelled:" in subject or "run canceled:" in subject:
            return _result("auto_archive", "auto_archive", "LOW",
                           "CI notification (run failure/cancel)", [], "ci_noise")

    # ------------------------------------------------------------------
    # 1b. npm publishes
    # ------------------------------------------------------------------
    if sender == "support4@vendor.example.com" and "successfully published" in subject:
        return _result("auto_archive", "auto_archive", "LOW",
                       "npm package publish notification", [], "npm_publish")

    # ------------------------------------------------------------------
    # 1c. GA4 / analytics reports
    # ------------------------------------------------------------------
    if "noreply-analytics@google" in sender:
        return _result("auto_archive", "auto_archive", "LOW",
                       "GA4 analytics report", [], "ga4_report")

    # ------------------------------------------------------------------
    # 1d. Dependabot
    # ------------------------------------------------------------------
    if "dependabot" in sender_name or "chore(deps)" in subject:
        return _result("auto_archive", "auto_archive", "LOW",
                       "Dependabot dependency update", [], "dependabot")

    # ------------------------------------------------------------------
    # 2. Ignore / explicit spam senders
    # ------------------------------------------------------------------
    for entry in (rules.get("senders", {}).get("ignore") or []):
        pattern = entry.get("pattern", "") if isinstance(entry, dict) else entry
        if _pattern_matches(pattern, sender) or _pattern_matches(pattern, sender_name):
            return _result("auto_archive", "auto_archive", "LOW",
                           f"Ignored sender: {pattern}", [], "ignore_sender")

    # ------------------------------------------------------------------
    # 3. GitHub notifications (non-CI)
    #
    # GitHub subject lines mirror the issue/PR title — they do NOT contain
    # event-type keywords like "merged" or "commented". So subject-keyword
    # matching never fires in practice and everything falls through to
    # "review". The authoritative signal is the X-GitHub-Reason header,
    # which the gmail adapter now exposes as Email.gh_reason. We route by
    # that against the events config in rules.base.yaml.
    # ------------------------------------------------------------------
    gh_config = rules.get("github", {})
    gh_senders = [s.lower() for s in (gh_config.get("notification_senders") or [])]
    if sender in gh_senders:
        # Security advisories → task. Match the advisory phrasing, not bare
        # "security" — issue/PR titles like "open for security review" mirror
        # into every thread email and mass-misfire (2026-07-14: 138 bot pushes
        # classified HIGH). Real advisories say "A security advisory on X…".
        if "security advisory" in subject or "vulnerability" in subject:
            return _result("github", "task", "HIGH",
                           "GitHub security advisory", ["security", "github"], "github_security")

        # Header-based event routing (the real fix)
        gh_reason = (getattr(email, "gh_reason", None) or "").lower()
        events = gh_config.get("events") or {}
        if gh_reason and gh_reason in events:
            cfg = events[gh_reason] or {}
            action = (cfg.get("action") or "").upper()
            archive = bool(cfg.get("archive", False))
            priority = (cfg.get("priority") or "MEDIUM").upper()

            if action == "ACTIONABLE":
                return _result("github", "task", priority,
                               f"GitHub {gh_reason}", ["github"], f"github_{gh_reason}")
            if action == "INFORMATIONAL" or archive:
                return _result("auto_archive", "auto_archive", "LOW",
                               f"GitHub {gh_reason} (auto-archive)", ["github"], f"github_{gh_reason}_arch")
            if action == "UPDATE_TASK":
                # merged/closed — informational unless I'm involved
                return _result("auto_archive", "auto_archive", "LOW",
                               f"GitHub {gh_reason}", ["github"], f"github_{gh_reason}")
            if action == "CHECK_INVOLVEMENT":
                # Plain comments — archive unless I'm @-mentioned in body
                # (the @ check is conservative; mention emails come with
                # reason=mention, not comment)
                body_check = body or snippet
                if "@" + "user" in body_check or "@user" in body_check:
                    return _result("github", "task", "MEDIUM",
                                   f"GitHub comment with @-mention", ["github"], "github_comment_mention")
                return _result("auto_archive", "auto_archive", "LOW",
                               f"GitHub comment (no involvement)", ["github"], "github_comment_skip")

        # Legacy actionable keywords (still useful for body matches)
        body_check = body or snippet
        for kw in (gh_config.get("actionable_keywords") or []):
            if kw.lower() in subject or kw.lower() in body_check:
                return _result("github", "task", "HIGH",
                               f"GitHub actionable: {kw}", ["github"], "github_actionable")

        # Subscribed without explicit event mapping → archive (you opted into
        # the repo, you don't need every push notification clogging the inbox).
        if gh_reason == "subscribed":
            return _result("auto_archive", "auto_archive", "LOW",
                           "GitHub subscribed (informational)", ["github"], "github_subscribed")

        # Default GitHub (no header, no rule) → review
        return _result("github", "review", "MEDIUM",
                       "GitHub notification (no X-GitHub-Reason)", ["github"], "github_default")

    # ------------------------------------------------------------------
    # 4. Calendar notifications
    # ------------------------------------------------------------------
    cal_config = rules.get("calendar", {})
    cal_senders = [s.lower() for s in (cal_config.get("notification_senders") or [])]
    if sender in cal_senders:
        # Check subject patterns for each event type
        for event_type, event_cfg in (cal_config.get("events") or {}).items():
            patterns = event_cfg.get("patterns") or []
            for pat in patterns:
                if pat.lower() in subject:
                    if event_type in ("accepted", "declined"):
                        return _result("auto_archive", "auto_archive", "LOW",
                                       f"Calendar RSVP: {event_type}", ["calendar"], f"cal_{event_type}")
                    elif event_type == "canceled":
                        return _result("calendar", "check_calendar_remove", "LOW",
                                       "Calendar event canceled", ["calendar"], "cal_canceled")
                    elif event_type in ("invitation", "updated_invitation"):
                        return _result("calendar", "check_calendar_sync", "MEDIUM",
                                       f"Calendar {event_type}", ["calendar"], f"cal_{event_type}")
                    elif event_type == "reminder":
                        return _result("calendar", "check_event_passed", "LOW",
                                       "Calendar reminder", ["calendar"], "cal_reminder")

        # Calendar sender but no pattern matched
        return _result("calendar", "review", "MEDIUM",
                       "Calendar notification (unclassified)", ["calendar"], "calendar_default")

    # Also check subject-level calendar rules
    for subj_rule in (rules.get("subjects", {}).get("calendar") or []):
        pattern = subj_rule.get("pattern", "") if isinstance(subj_rule, dict) else subj_rule
        if _pattern_matches(pattern, subject):
            action = subj_rule.get("action", "review") if isinstance(subj_rule, dict) else "review"
            if action == "archive_only":
                return _result("auto_archive", "auto_archive", "LOW",
                               f"Calendar subject match: {pattern}", ["calendar"], "cal_subject")
            return _result("calendar", action, "MEDIUM",
                           f"Calendar subject: {pattern}", ["calendar"], "cal_subject")

    # ------------------------------------------------------------------
    # 5. LinkedIn spam / explicit newsletter spam
    # ------------------------------------------------------------------
    for entry in (rules.get("senders", {}).get("newsletter") or []):
        if not isinstance(entry, dict):
            continue
        pattern = entry.get("pattern", "")
        entry_type = entry.get("type", "")
        entry_action = entry.get("action", "")
        if entry_type == "spam" or "linkedin" in pattern or "(via" in pattern:
            if _pattern_matches(pattern, sender) or _pattern_matches(pattern, sender_name):
                return _result("auto_archive", "auto_archive", "LOW",
                               f"LinkedIn/spam sender: {pattern}", [], "linkedin_spam")

    # ------------------------------------------------------------------
    # 6. n8n notifications
    # ------------------------------------------------------------------
    n8n_config = rules.get("n8n", {})
    n8n_senders = [s.lower() for s in (n8n_config.get("notification_senders") or [])]
    if sender in n8n_senders:
        for event_type, event_cfg in (n8n_config.get("events") or {}).items():
            patterns = event_cfg.get("patterns") or []
            for pat in patterns:
                if pat.lower() in subject:
                    action = event_cfg.get("action", "review")
                    archive = event_cfg.get("archive", False)
                    priority = event_cfg.get("priority", "LOW")
                    if archive or action == "INFORMATIONAL":
                        return _result("auto_archive", "auto_archive", priority,
                                       f"n8n {event_type}", ["n8n"], f"n8n_{event_type}")
                    return _result("n8n", "task", priority,
                                   f"n8n {event_type}", ["n8n"], f"n8n_{event_type}")
        # Default n8n (no pattern matched)
        return _result("n8n", "review", "MEDIUM",
                       "n8n notification (unclassified)", ["n8n"], "n8n_default")

    # ------------------------------------------------------------------
    # 7. Research senders
    # ------------------------------------------------------------------
    for entry in (rules.get("senders", {}).get("research") or []):
        if not isinstance(entry, dict):
            continue
        pattern = entry.get("pattern", "")
        if _pattern_matches(pattern, sender) or _pattern_matches(pattern, sender_name):
            topics = entry.get("topics", [])
            action = entry.get("action", "prepare_for_research")
            return _result("research", action, "MEDIUM",
                           f"Research sender: {pattern}", topics, "research_sender")

    # ------------------------------------------------------------------
    # 8. Actionable senders
    # ------------------------------------------------------------------
    for entry in (rules.get("senders", {}).get("actionable") or []):
        if not isinstance(entry, dict):
            continue
        pattern = entry.get("pattern", "")
        if _pattern_matches(pattern, sender) or _pattern_matches(pattern, sender_name):
            priority = entry.get("priority", "MEDIUM")
            tags = entry.get("tags", [])
            return _result("actionable", "task", priority,
                           f"Actionable sender: {pattern}", tags, "actionable_sender")

    # ------------------------------------------------------------------
    # 9. Finance subjects
    # ------------------------------------------------------------------
    for entry in (rules.get("subjects", {}).get("finance") or []):
        pattern = entry.get("pattern", "") if isinstance(entry, dict) else entry
        if _pattern_matches(pattern, subject):
            action = entry.get("action", "route_to_accounting") if isinstance(entry, dict) else "route_to_accounting"
            if action == "route_to_accounting":
                return _result("forward_accounting", "forward", "HIGH",
                               f"Finance subject: {pattern}", ["finance"], "finance_subject")
            if action == "surface_actionable":
                # Tax notices, overdue payments, dunning — user must see, not just forward.
                return _result("actionable", "task", "HIGH",
                               f"Finance/tax notice: {pattern}", ["finance", "urgent"], "finance_actionable")
            return _result("actionable", "task", "HIGH",
                           f"Finance subject: {pattern}", ["finance"], "finance_subject")

    # ------------------------------------------------------------------
    # 10. Newsletter domains
    # ------------------------------------------------------------------
    sender_domain = sender.split("@")[-1] if "@" in sender else ""
    for domain in (rules.get("domains", {}).get("newsletter") or []):
        if domain.lower() in sender_domain:
            return _result("newsletter", "aggregate_daily_news", "LOW",
                           f"Newsletter domain: {domain}", ["newsletter"], "newsletter_domain")

    # 10b. Newsletter senders (non-spam entries not already matched)
    for entry in (rules.get("senders", {}).get("newsletter") or []):
        if not isinstance(entry, dict):
            continue
        pattern = entry.get("pattern", "")
        entry_type = entry.get("type", "")
        entry_action = entry.get("action", "archive_only")
        # Skip spam — already handled in step 5
        if entry_type == "spam" or "linkedin" in pattern or "(via" in pattern:
            continue
        if _pattern_matches(pattern, sender) or _pattern_matches(pattern, sender_name):
            if entry_action == "prepare_for_research" or entry_type == "competitor":
                return _result("research", entry_action, "MEDIUM",
                               f"Newsletter/research sender: {pattern}",
                               entry.get("topics", []), "newsletter_sender_research")
            if entry_action in ("aggregate_daily_news", "check_product_update"):
                return _result("newsletter", entry_action, "LOW",
                               f"Newsletter sender: {pattern}", [], "newsletter_sender")
            # archive_only / event / promo / service / automated_report
            return _result("auto_archive", "auto_archive", "LOW",
                           f"Newsletter sender (archive): {pattern}", [], "newsletter_archive")

    # ------------------------------------------------------------------
    # 11. Body-based newsletter detection
    # ------------------------------------------------------------------
    body_or_snippet = body if body else snippet
    for entry in (rules.get("body", {}).get("newsletter") or []):
        pattern = entry.get("pattern", "") if isinstance(entry, dict) else entry
        if _pattern_matches(pattern, body_or_snippet):
            return _result("newsletter", "aggregate_daily_news", "LOW",
                           f"Newsletter body pattern: {pattern}", ["newsletter"], "body_newsletter")

    # ------------------------------------------------------------------
    # 12. Unknown — try Ollama local model, then conservative default
    # ------------------------------------------------------------------
    ollama_result = _ollama_classify(sender, sender_name, subject, snippet)
    if ollama_result:
        return ollama_result

    return _result("unknown", "review", "MEDIUM",
                   "No matching rule — needs manual review", [], "unknown")


def _ollama_classify(sender: str, sender_name: str, subject: str, snippet: str):
    """
    Classify unknown email using local Qwen3 4B via Ollama.
    Returns a result dict matching _result() schema, or None on failure.
    """
    import json as _json
    import os as _os
    import urllib.request as _urlreq

    # Model SELECTION follows the enforced per-task router (task: mail-processing).
    # The local model is a single swappable knob (OLLAMA_MODEL) — NEVER hardcoded
    # per task, so a gemma->qwen swap is one env change. triage-email.sh resolves
    # mail-processing via cos_route and exports OLLAMA_MODEL; we read it here.
    # Fall back to qwen3:4b only if the knob is unset (pre-router behaviour).
    # The router (cos_route) resolves mail-processing to a provider, but this
    # function only ever spoke Ollama — so setting provider=openrouter in
    # model_routing.yaml changed the log line and nothing else. The routing
    # table was decorative here. Honour COS_ROUTE_PROVIDER for real.
    provider = (_os.environ.get("COS_ROUTE_PROVIDER") or "ollama").strip().lower()
    use_openrouter = provider == "openrouter"

    if use_openrouter:
        # Egress note: this sends subject + snippet off the box. mail-processing
        # was deliberately local ("email bodies never leave the box"); routing
        # it to a cloud model reverses that on purpose, per an explicit
        # decision. Only sender/subject/snippet are sent — never the full body.
        api_key = (_os.environ.get("OPENROUTER_API_KEY") or "").strip()
        if not api_key:
            # Fail to local rather than silently classifying nothing.
            use_openrouter = False
        else:
            OLLAMA_URL = "https://openrouter.ai/api/v1/chat/completions"
            MODEL = (_os.environ.get("OPENROUTER_MODEL")
                     or _os.environ.get("COS_ROUTE_MODEL")
                     or "qwen/qwen3.8-27b").strip()

    if not use_openrouter:
        OLLAMA_URL = _os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/") + "/api/chat"
        MODEL = (_os.environ.get("OLLAMA_MODEL") or "qwen3:4b").strip()

    VALID_CATEGORIES = {
        "auto_archive": "auto_archive",
        "research": "prepare_for_research",
        "newsletter": "aggregate_daily_news",
        "forward_accounting": "forward",
        "actionable": "review",
        "calendar": "check_event_passed",
        "review": "review",
    }

    prompt = (
        "You are an email classification assistant. Classify the following email into exactly one category.\n\n"
        "Categories:\n"
        "- auto_archive: CI notifications, social media, promotional, receipts, spam — no human attention needed\n"
        "- research: Newsletters/content with research value (AI, tech, crypto, strategy) — for knowledge extraction\n"
        "- newsletter: General newsletters with low research value — daily digest\n"
        "- forward_accounting: Invoices, receipts, accounting — forwarded to accounting\n"
        "- actionable: Requires human response or decision — real people, business, partnerships\n"
        "- calendar: Calendar reminders, meeting notifications\n"
        "- review: Genuinely ambiguous — human decides\n\n"
        f"Email:\n- From: {sender[:200]} ({sender_name[:200]})\n"
        f"- Subject: {subject[:300]}\n"
        f"- Snippet: {snippet[:500]}\n\n"
        'Respond as JSON only: {"category": "...", "priority": "HIGH/MEDIUM/LOW", "reason": "...", "tags": ["..."]}'
    )

    headers = {"Content-Type": "application/json"}
    if use_openrouter:
        # OpenAI-compatible shape — Ollama's `think`/`format`/`options` keys
        # are not understood here and the reply nests under choices[].
        payload = _json.dumps({
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            # 200 (the local budget) truncates this model mid-JSON: it writes a
            # pretty-printed object with a discursive "reason" and hits the cap
            # before the closing brace, so json.loads fails and the email falls
            # back to unclassified. finish_reason was "length", not an error —
            # the call looked successful. 400 clears it; at $3.20/M output the
            # extra headroom costs fractions of a cent per run.
            "max_tokens": 400,
            "response_format": {"type": "json_object"},
        }).encode()
        headers["Authorization"] = f"Bearer {api_key}"
        headers["HTTP-Referer"] = "https://datacore.one"
        headers["X-Title"] = "datacore-mail-triage"
        timeout_s = 60
    else:
        payload = _json.dumps({
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "think": False,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 200},
        }).encode()
        timeout_s = 30

    try:
        req = _urlreq.Request(OLLAMA_URL, data=payload, headers=headers)
        with _urlreq.urlopen(req, timeout=timeout_s) as resp:
            data = _json.loads(resp.read())

        if use_openrouter:
            choice = (data.get("choices") or [{}])[0]
            raw = (choice.get("message") or {}).get("content", "").strip()
            if choice.get("finish_reason") == "length":
                # Truncated JSON parses as garbage or, worse, as a partial
                # object. Say why rather than letting it look like a bad model.
                raise ValueError(
                    f"{MODEL} hit the token cap mid-JSON (finish_reason=length); "
                    "raise max_tokens"
                )
        else:
            raw = data.get("message", {}).get("content", "").strip()
        # Some models fence their JSON even when asked not to.
        if raw.startswith("```"):
            raw = raw.split("```")[1] if "```" in raw[3:] else raw[3:]
            raw = raw.removeprefix("json").strip()
        result = _json.loads(raw)

        category = result.get("category", "review")
        if category not in VALID_CATEGORIES:
            category = "review"

        priority = result.get("priority", "MEDIUM").upper()
        if priority not in ("HIGH", "MEDIUM", "LOW"):
            priority = "MEDIUM"

        tags = result.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        return _result(
            category,
            VALID_CATEGORIES[category],
            priority,
            f"Ollama: {result.get('reason', 'local model classification')}",
            tags[:5],
            f"ollama:{MODEL}",
        )
    except Exception:
        return None


def _result(
    category: str,
    action: str,
    priority: Optional[str],
    reason: str,
    tags: List[str],
    rule_name: str
) -> Dict[str, Any]:
    return {
        "category": category,
        "action": action,
        "priority": priority,
        "reason": reason,
        "tags": tags,
        "rule_name": rule_name,
    }


# ---------------------------------------------------------------------------
# 3. scan_inbox
# ---------------------------------------------------------------------------

def scan_inbox(
    account_address: str,
    days: int = 3,
    max_results: int = 200,
    rules_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pull emails from INBOX and classify each one.

    Args:
        account_address: Gmail account to scan.
        days:            Days to look back.
        max_results:     Max emails to fetch.
        rules_path:      Path to rules YAML (default: rules.base.yaml).

    Returns:
        dict with keys:
          account      — scanned account address
          scanned_at   — ISO timestamp
          total        — total emails fetched
          inbox_count  — emails in INBOX
          categories   — {category: [classified_email, ...]}
          emails       — flat list of all classified emails (for JSON export)
    """
    GmailAdapter, Email = _import_gmail_adapter()
    adapter = GmailAdapter({"address": account_address})

    rules = load_rules(rules_path)

    if not adapter.is_configured():
        raise RuntimeError(
            f"Gmail not configured for {account_address}. "
            "Run: python authorize_gmail.py --account <address>"
        )

    raw_emails = adapter.pull_emails(days=days, max_results=max_results)

    # Only process INBOX emails
    inbox_emails = [e for e in raw_emails if "INBOX" in e.labels]

    categories: Dict[str, List[Dict]] = {
        "auto_archive": [],
        "forward_accounting": [],
        "research": [],
        "newsletter": [],
        "actionable": [],
        "calendar": [],
        "github": [],
        "n8n": [],
        "unknown": [],
    }

    all_classified = []

    for email in inbox_emails:
        classification = classify_email(email, rules)
        classified = {
            "id": email.id,
            "thread_id": email.thread_id,
            "subject": email.subject,
            "sender": email.sender,
            "sender_name": email.sender_name,
            "date": email.date.isoformat() if hasattr(email.date, "isoformat") else str(email.date),
            "snippet": email.snippet,
            "labels": email.labels,
            "is_unread": email.is_unread,
            "gmail_url": email.gmail_url,
            "category": classification["category"],
            "action": classification["action"],
            "priority": classification["priority"],
            "reason": classification["reason"],
            "tags": classification["tags"],
            "rule_name": classification["rule_name"],
        }
        cat = classification["category"]
        if cat not in categories:
            cat = "unknown"
        categories[cat].append(classified)
        all_classified.append(classified)

    # Build an id→Email map so execute_auto_actions can call processors that
    # need the full Email object (newsletter URL extraction, research task
    # creation). The map is intentionally not serialized to the JSON output.
    emails_by_id = {e.id: e for e in inbox_emails}

    return {
        "account": account_address,
        "scanned_at": datetime.now().isoformat(),
        "total": len(raw_emails),
        "inbox_count": len(inbox_emails),
        "categories": categories,
        "emails": all_classified,
        "_emails_by_id": emails_by_id,  # in-memory only; not serialized
    }


# ---------------------------------------------------------------------------
# 4. execute_auto_actions
# ---------------------------------------------------------------------------

def execute_auto_actions(
    scan_results: Dict[str, Any],
    account_address: str,
    forward_to: Optional[str] = None,
    space_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Execute auto-actions for classified emails. Aim is inbox zero from cron.

    Handled action types:
      - auto_archive          → archive + mark read
      - forward_accounting    → forward to accounting, then archive
      - aggregate_daily_news  → record for digest, archive
      - prepare_for_research  → newsletter processor (URL + research task), archive
      - check_product_update  → newsletter processor (relevance check), archive
      - check_event_passed    → archive (event is in the past)
      - check_calendar_sync   → archive (calendar already synced via Google)

    After processing the daily-news bucket, a single digest task is created
    in `{space_path}/org/daily_news.org` (via newsletter._create_daily_digest_task).

    Args:
        scan_results:    Output of scan_inbox().
        account_address: Gmail account to act on.
        forward_to:      Email address to forward accounting emails to.
        space_path:      Path to the space where inbox/digest tasks land
                         (defaults to ~/Data/0-personal).

    Returns:
        dict with keys:
          archived        — list of message IDs successfully archived
          forwarded       — list of message IDs successfully forwarded
          processed       — {action_type: [msg_id, ...]} for processor-backed actions
          errors          — list of {id, action, error}
          skipped_forward — message IDs skipped because forward_to is None
    """
    GmailAdapter, _ = _import_gmail_adapter()
    adapter = GmailAdapter({"address": account_address})

    if space_path is None:
        space_path = Path.home() / "Data" / "0-personal"
    else:
        space_path = Path(space_path)

    emails_by_id = scan_results.get("_emails_by_id", {})

    archived: List[str] = []
    forwarded: List[str] = []
    skipped_forward: List[str] = []
    skipped: List[dict] = []          # newsletters with nothing to queue (no article link)
    errors: List[Dict[str, Any]] = []
    processed: Dict[str, List[str]] = {}

    def _archive_msg(msg_id: str, action: str) -> bool:
        """Archive + mark read. Records errors. Returns True on success."""
        try:
            if adapter.archive(msg_id):
                adapter.mark_read(msg_id)
                processed.setdefault(action, []).append(msg_id)
                return True
            errors.append({"id": msg_id, "action": action, "error": "archive() returned False"})
        except Exception as exc:
            errors.append({"id": msg_id, "action": action, "error": str(exc)})
        return False

    # --- Auto-archive ---
    for classified in scan_results["categories"].get("auto_archive", []):
        msg_id = classified["id"]
        try:
            ok = adapter.archive(msg_id)
            if ok:
                adapter.mark_read(msg_id)
                archived.append(msg_id)
            else:
                errors.append({"id": msg_id, "action": "archive", "error": "archive() returned False"})
        except Exception as exc:
            errors.append({"id": msg_id, "action": "archive", "error": str(exc)})

    # --- Forward accounting emails ---
    for classified in scan_results["categories"].get("forward_accounting", []):
        msg_id = classified["id"]
        if not forward_to:
            skipped_forward.append(msg_id)
            continue
        try:
            subject = classified.get("subject", "No Subject")
            sender = classified.get("sender", "unknown")
            fwd_subject = f"FWD (accounting): {subject}"
            fwd_body = (
                f"Forwarded from: {sender}\n"
                f"Original subject: {subject}\n"
                f"Gmail: {classified.get('gmail_url', '')}\n\n"
                f"{classified.get('snippet', '')}"
            )
            sent_id = adapter.send_email(
                to=[forward_to],
                subject=fwd_subject,
                body=fwd_body,
            )
            if sent_id:
                adapter.archive(msg_id)
                adapter.mark_read(msg_id)
                forwarded.append(msg_id)
            else:
                errors.append({"id": msg_id, "action": "forward", "error": "send_email() returned None"})
        except Exception as exc:
            errors.append({"id": msg_id, "action": "forward", "error": str(exc)})

    # --- Calendar (passed event / sync notification) ---
    # No dedicated processor; design intent is "info-only, archive".
    for cat_key in ("calendar",):
        for classified in scan_results["categories"].get(cat_key, []):
            if classified.get("action") in ("check_event_passed", "check_calendar_sync"):
                _archive_msg(classified["id"], classified["action"])

    # --- Newsletter / research (processor-backed: digest, URL extraction) ---
    # All three actions live in processors/newsletter.py::NewsletterProcessor.
    # We instantiate once, dispatch by action, archive on success.
    nl_actions = ("aggregate_daily_news", "prepare_for_research", "check_product_update")
    newsletter_candidates: List[Dict[str, Any]] = []
    for cat_key in ("newsletter", "research"):
        for classified in scan_results["categories"].get(cat_key, []):
            if classified.get("action") in nl_actions:
                newsletter_candidates.append(classified)

    daily_news_results: List[Any] = []
    if newsletter_candidates:
        try:
            from processors.newsletter import NewsletterProcessor, _create_daily_digest_task
        except ImportError:
            # Try the module-relative import path
            import importlib.util
            nl_path = Path(__file__).parent.parent / "processors" / "newsletter.py"
            spec = importlib.util.spec_from_file_location("newsletter_processor", nl_path)
            nl_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(nl_mod)
            NewsletterProcessor = nl_mod.NewsletterProcessor
            _create_daily_digest_task = nl_mod._create_daily_digest_task

        processor = NewsletterProcessor(space_path=space_path)

        for classified in newsletter_candidates:
            msg_id = classified["id"]
            action = classified["action"]
            email = emails_by_id.get(msg_id)
            if email is None:
                errors.append({"id": msg_id, "action": action, "error": "Email object missing from scan_results"})
                continue
            try:
                # NewsletterProcessor.process() needs an action key in classification.
                # Map our scanner action → processor action vocabulary (they overlap).
                nl_classification = {
                    "action": action,
                    "type": "daily_news" if action == "aggregate_daily_news" else "",
                    "category": classified.get("category", ""),
                }
                result = processor.process(email, nl_classification)
                if result.action == "ERROR":
                    errors.append({"id": msg_id, "action": action, "error": result.summary})
                    continue
                if result.action == "SKIPPED":
                    skipped.append({"id": msg_id, "action": action, "reason": result.summary})
                    continue
                if result.action == "DAILY_NEWS_ITEM":
                    daily_news_results.append(result)
                if result.should_archive:
                    _archive_msg(msg_id, action)
            except Exception as exc:
                errors.append({"id": msg_id, "action": action, "error": str(exc)})

        # Aggregate daily-news into a single digest task in the space.
        if daily_news_results:
            try:
                _create_daily_digest_task(daily_news_results, space_path)
            except Exception as exc:
                errors.append({"id": "digest", "action": "daily_news_digest", "error": str(exc)})

    return {
        "archived": archived,
        "forwarded": forwarded,
        "errors": errors,
        "skipped_forward": skipped_forward,
        "skipped": skipped,
        "processed": processed,
    }


# ---------------------------------------------------------------------------
# 5. format_summary
# ---------------------------------------------------------------------------

def format_summary(
    scan_results: Dict[str, Any],
    action_results: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate a markdown summary of scan results for the /today briefing.

    Args:
        scan_results:   Output of scan_inbox().
        action_results: Output of execute_auto_actions() (optional).

    Returns:
        Markdown string.
    """
    account = scan_results.get("account", "unknown")
    scanned_at = scan_results.get("scanned_at", "")
    total = scan_results.get("total", 0)
    inbox_count = scan_results.get("inbox_count", 0)
    categories = scan_results.get("categories", {})

    lines = []
    lines.append(f"## Email: {account}")
    lines.append(f"*Scanned {inbox_count} inbox emails (of {total} total) at {scanned_at[:16]}*")
    lines.append("")

    # Actions executed
    if action_results:
        archived_n = len(action_results.get("archived", []))
        forwarded_n = len(action_results.get("forwarded", []))
        errors_n = len(action_results.get("errors", []))
        # Errors were reported as a bare count while the messages themselves —
        # already collected as {id, action, error} — were discarded. Every
        # overnight run for months said "8 errors during auto-processing" and
        # nothing else, so the one thing needed to fix them never left the
        # process. Print them.
        if archived_n or forwarded_n or errors_n:
            lines.append("### Auto-processed")
            if archived_n:
                lines.append(f"- Archived {archived_n} noise emails (CI, newsletters, spam)")
            if forwarded_n:
                lines.append(f"- Forwarded {forwarded_n} invoices to accounting")
            skipped_n = len(action_results.get("skipped", []))
            if skipped_n:
                lines.append(f"- {skipped_n} newsletter(s) without an article link left in the inbox")
            if errors_n:
                lines.append(f"- **{errors_n} errors during auto-processing:**")
                # Identical failures repeat per-message; collapse so one broken
                # scope does not print forty times and bury the other causes.
                by_cause: Dict[str, List[str]] = {}
                for err in action_results.get("errors", []):
                    key = f"{err.get('action', '?')}: {err.get('error', 'unknown')}"
                    by_cause.setdefault(key, []).append(str(err.get("id", "?")))
                for cause, ids in sorted(by_cause.items(), key=lambda kv: -len(kv[1])):
                    shown = ", ".join(ids[:3])
                    more = f" +{len(ids) - 3} more" if len(ids) > 3 else ""
                    lines.append(f"  - ({len(ids)}×) {cause}  [{shown}{more}]")
            lines.append("")

    # Actionable
    actionable = categories.get("actionable", [])
    if actionable:
        lines.append(f"### Actionable ({len(actionable)})")
        for e in sorted(actionable, key=lambda x: _priority_sort_key(x.get("priority"))):
            priority_badge = f"[{e['priority']}] " if e.get("priority") else ""
            sender_display = e.get("sender_name") or e.get("sender", "unknown")
            lines.append(f"- {priority_badge}**{sender_display}**: {e['subject']}")
            lines.append(f"  {e.get('gmail_url', '')}")
        lines.append("")

    # Calendar
    calendar = categories.get("calendar", [])
    if calendar:
        lines.append(f"### Calendar ({len(calendar)})")
        for e in calendar:
            lines.append(f"- **{e['subject']}** — {e.get('reason', '')}")
        lines.append("")

    # GitHub
    github = categories.get("github", [])
    if github:
        actionable_gh = [e for e in github if e.get("action") in ("task",)]
        info_gh = [e for e in github if e.get("action") not in ("task",)]
        if actionable_gh:
            lines.append(f"### GitHub — Needs attention ({len(actionable_gh)})")
            for e in actionable_gh:
                lines.append(f"- {e['subject']}")
            lines.append("")
        if info_gh:
            lines.append(f"### GitHub — Informational ({len(info_gh)})")
            for e in info_gh:
                lines.append(f"- {e['subject']}")
            lines.append("")

    # n8n
    n8n = categories.get("n8n", [])
    if n8n:
        lines.append(f"### n8n ({len(n8n)})")
        for e in n8n:
            lines.append(f"- {e['subject']} — {e.get('reason', '')}")
        lines.append("")

    # Research
    research = categories.get("research", [])
    if research:
        lines.append(f"### Research / Newsletters ({len(research)})")
        for e in research:
            sender_display = e.get("sender_name") or e.get("sender", "unknown")
            lines.append(f"- **{sender_display}**: {e['subject']}")
        lines.append("")

    # Newsletter
    newsletter = categories.get("newsletter", [])
    if newsletter:
        lines.append(f"### Daily digests / newsletters ({len(newsletter)}) — archived")
        # Group by sender
        by_sender: Dict[str, int] = {}
        for e in newsletter:
            key = e.get("sender_name") or e.get("sender", "unknown")
            by_sender[key] = by_sender.get(key, 0) + 1
        for sender, count in sorted(by_sender.items()):
            lines.append(f"- {sender}: {count}")
        lines.append("")

    # Finance (forwarded)
    fwd_accounting = categories.get("forward_accounting", [])
    if fwd_accounting:
        lines.append(f"### Finance / Invoices ({len(fwd_accounting)})")
        for e in fwd_accounting:
            lines.append(f"- **{e['subject']}** from {e.get('sender', '')}")
        lines.append("")

    # Unknown
    unknown = categories.get("unknown", [])
    if unknown:
        lines.append(f"### Unknown — needs review ({len(unknown)})")
        for e in unknown:
            sender_display = e.get("sender_name") or e.get("sender", "unknown")
            lines.append(f"- **{sender_display}**: {e['subject']}")
        lines.append("")

    return "\n".join(lines)


def _priority_sort_key(priority: Optional[str]) -> int:
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, None: 3}
    return order.get(priority, 3)


# ---------------------------------------------------------------------------
# 6. main (CLI)
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Email scanner — classify and triage Gmail inbox.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan and print JSON:
  python3 email_scanner.py --account grace@example.com --days 3 --format json

  # Scan, execute auto-actions, print summary:
  python3 email_scanner.py --account grace@example.com --days 3 \\
      --execute --forward-to billing2@vendor.example.com --format summary

  # Scan live + write results to cache (production daemon pattern):
  python3 email_scanner.py --account grace@example.com \\
      --cache data/scan_cache.json --format summary

  # Replay/debug: load pre-scanned results without hitting Gmail:
  python3 email_scanner.py --account grace@example.com \\
      --load-cache data/scan_cache.json --format summary
        """,
    )
    parser.add_argument("--account", required=True,
                        help="Gmail account address to scan")
    parser.add_argument("--days", type=int, default=3,
                        help="Days to look back (default: 3)")
    parser.add_argument("--max-results", type=int, default=200,
                        help="Max emails to fetch (default: 200)")
    parser.add_argument("--rules", default=None,
                        help="Path to rules YAML (default: rules.base.yaml)")
    parser.add_argument("--cache", default=None,
                        help="Path to WRITE scan cache JSON (live scan results are persisted here)")
    parser.add_argument("--load-cache", default=None,
                        help="Path to READ pre-scanned cache JSON from (skips live scan). "
                             "Use only for debugging or replaying a prior scan — production "
                             "calls should use --cache (write) and a fresh live scan.")
    parser.add_argument("--execute", action="store_true",
                        help="Execute auto-actions (archive noise, forward invoices)")
    parser.add_argument("--forward-to", default=None,
                        help="Accounting email address for forwarding invoices")
    parser.add_argument("--format", choices=["json", "summary", "categories"], default="summary",
                        help="Output format (default: summary)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without executing actions")

    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load from --load-cache, OR scan live + optionally --cache (write)
    #
    # --cache is WRITE-ONLY: live scan results are persisted to this path.
    # --load-cache is READ-ONLY: skips live scan, loads pre-scanned JSON.
    # Old --cache <path> double-duty (read-if-exists, then write) was a
    # cache-poisoning footgun for daemon callers — split intentionally.
    # See org-20260603-email-scanner-cache-bug.
    # ------------------------------------------------------------------
    scan_results = None
    load_cache_path = Path(args.load_cache) if args.load_cache else None
    write_cache_path = Path(args.cache) if args.cache else None

    if load_cache_path:
        if not load_cache_path.exists():
            print(f"ERROR: --load-cache path does not exist: {load_cache_path}", file=sys.stderr)
            sys.exit(1)
        print(f"[email_scanner] Loading cached results from {load_cache_path}", file=sys.stderr)
        with open(load_cache_path) as f:
            scan_results = json.load(f)
    else:
        print(f"[email_scanner] Scanning {args.account} ({args.days}d, max {args.max_results})...",
              file=sys.stderr)
        try:
            scan_results = scan_inbox(
                account_address=args.account,
                days=args.days,
                max_results=args.max_results,
                rules_path=args.rules,
            )
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

        print(f"[email_scanner] Found {scan_results['inbox_count']} inbox emails", file=sys.stderr)

        if write_cache_path:
            write_cache_path.parent.mkdir(parents=True, exist_ok=True)
            # Strip the in-memory Email object map before serializing — it
            # contains non-JSON-friendly types and is only needed within
            # the same process invocation.
            cacheable = {k: v for k, v in scan_results.items() if k != "_emails_by_id"}
            with open(write_cache_path, "w") as f:
                json.dump(cacheable, f, indent=2, default=str)
            print(f"[email_scanner] Results cached to {write_cache_path}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Execute auto-actions
    # ------------------------------------------------------------------
    action_results = None
    if args.execute and not args.dry_run:
        print("[email_scanner] Executing auto-actions...", file=sys.stderr)
        action_results = execute_auto_actions(
            scan_results=scan_results,
            account_address=args.account,
            forward_to=args.forward_to,
        )
        processed_total = sum(len(v) for v in action_results.get("processed", {}).values())
        processed_breakdown = ", ".join(
            f"{k}={len(v)}" for k, v in action_results.get("processed", {}).items()
        )
        print(
            f"[email_scanner] Archived: {len(action_results['archived'])}, "
            f"Forwarded: {len(action_results['forwarded'])}, "
            f"Processed: {processed_total}"
            + (f" ({processed_breakdown})" if processed_breakdown else "")
            + f", Errors: {len(action_results['errors'])}",
            file=sys.stderr,
        )
    elif args.execute and args.dry_run:
        # Dry-run: show what would happen
        auto_archive = scan_results["categories"].get("auto_archive", [])
        fwd_accounting = scan_results["categories"].get("forward_accounting", [])
        print(f"[dry-run] Would archive {len(auto_archive)} emails", file=sys.stderr)
        print(f"[dry-run] Would forward {len(fwd_accounting)} invoices to {args.forward_to}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    if args.format == "json":
        # Strip Email object map (not JSON-serializable, in-memory only)
        scan_clean = {k: v for k, v in scan_results.items() if k != "_emails_by_id"}
        output = {
            "scan": scan_clean,
            "actions": action_results,
        }
        print(json.dumps(output, indent=2, default=str))

    elif args.format == "categories":
        # Compact per-category count table
        categories = scan_results.get("categories", {})
        print(f"\nEmail scan: {args.account}")
        print(f"Period: {args.days} days | Inbox: {scan_results.get('inbox_count', 0)} emails\n")
        col_w = 25
        print(f"{'Category':<{col_w}} {'Count':>6}  {'Example subjects'}")
        print("-" * 70)
        for cat, emails in sorted(categories.items()):
            count = len(emails)
            if count == 0:
                continue
            examples = " | ".join(e["subject"][:30] for e in emails[:2])
            print(f"{cat:<{col_w}} {count:>6}  {examples}")

    else:  # summary
        print(format_summary(scan_results, action_results))


if __name__ == "__main__":
    main()
