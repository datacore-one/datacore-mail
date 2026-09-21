#!/usr/bin/env python3
"""
Ollama-powered email classifier for unknown emails.

When the rule-based classifier in email_scanner.py returns "unknown",
this module classifies the email using a local Qwen3 4B model via Ollama.

Usage:
    from ollama_classify import classify_unknown
    result = classify_unknown(sender, sender_name, subject, snippet)
    # Returns: {"category": "...", "priority": "...", "reason": "...", "tags": [...]}

Standalone test:
    python3 ollama_classify.py
"""

import json
import urllib.request
import urllib.error
from typing import Dict, List, Optional

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3:4b"

VALID_CATEGORIES = [
    "auto_archive",
    "research",
    "newsletter",
    "forward_accounting",
    "actionable",
    "calendar",
    "review",
]

VALID_PRIORITIES = ["HIGH", "MEDIUM", "LOW"]

PROMPT_TEMPLATE = """You are an email classification assistant. Classify the following email into exactly one category.

Categories:
- auto_archive: CI notifications, social media notifications, promotional emails, receipts, spam — anything that doesn't need human attention
- research: Newsletters and content with research value (AI, tech, crypto, business strategy) — will be processed for knowledge extraction
- newsletter: General newsletters with low research value — aggregated into daily digest
- forward_accounting: Invoices, receipts, accounting-related emails — forwarded to accounting
- actionable: Emails requiring a human response or decision — from real people, business matters, partnership opportunities
- calendar: Calendar reminders, meeting notifications — check if event passed
- review: Genuinely ambiguous — human needs to decide

Email:
- From: {sender} ({sender_name})
- Subject: {subject}
- Snippet: {snippet}

Respond as JSON only, no other text:
{{"category": "<one category>", "priority": "<HIGH/MEDIUM/LOW>", "reason": "<one sentence>", "tags": ["<tag1>"]}}"""


def classify_unknown(
    sender: str,
    sender_name: str,
    subject: str,
    snippet: str,
) -> Dict:
    """
    Classify an unknown email using local Ollama model.

    Returns dict with: category, priority, reason, tags, model, latency_ms
    Falls back to {"category": "review", "priority": "MEDIUM"} on any error.
    """
    import time
    start = time.time()

    prompt = PROMPT_TEMPLATE.format(
        sender=sender[:200],
        sender_name=sender_name[:200],
        subject=subject[:300],
        snippet=snippet[:500],
    )

    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "think": False,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 200,
        },
    }).encode()

    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        latency_ms = int((time.time() - start) * 1000)

        # Parse the model's JSON response from chat API
        raw_text = data.get("message", {}).get("content", "").strip()
        result = json.loads(raw_text)

        # Validate and sanitize
        category = result.get("category", "review")
        if category not in VALID_CATEGORIES:
            category = "review"

        priority = result.get("priority", "MEDIUM").upper()
        if priority not in VALID_PRIORITIES:
            priority = "MEDIUM"

        tags = result.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        return {
            "category": category,
            "action": _category_to_action(category),
            "priority": priority,
            "reason": result.get("reason", "Ollama classification"),
            "tags": tags[:5],
            "rule_name": "ollama_qwen3_4b",
            "model": MODEL,
            "latency_ms": latency_ms,
        }

    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
        latency_ms = int((time.time() - start) * 1000)
        return {
            "category": "review",
            "action": "review",
            "priority": "MEDIUM",
            "reason": f"Ollama fallback (error: {type(e).__name__})",
            "tags": [],
            "rule_name": "ollama_fallback",
            "model": MODEL,
            "latency_ms": latency_ms,
        }


def _category_to_action(category: str) -> str:
    """Map category to action (matches email_scanner.py schema)."""
    mapping = {
        "auto_archive": "auto_archive",
        "research": "prepare_for_research",
        "newsletter": "aggregate_daily_news",
        "forward_accounting": "forward",
        "actionable": "review",
        "calendar": "check_event_passed",
        "review": "review",
    }
    return mapping.get(category, "review")


# --- Self-test with real unknown emails from the scan ---

TEST_EMAILS = [
    {
        "sender": "billing4@vendor.example.com",
        "sender_name": "Eleven Labs Inc.",
        "subject": "Your receipt from Eleven Labs Inc. #2604-8129-0374",
        "snippet": "Your receipt from Eleven Labs Inc. #2604-8129-0374",
        "expected": "auto_archive",
    },
    {
        "sender": "support2@vendor.example.com",
        "sender_name": "'Example, Dave' via Acme Info",
        "subject": "[support2@vendor.example.com] Invitation to Participate in the Data Altruism Consent Management System Project",
        "snippet": "Dear Sir/Madam, I hope this message finds you well. Deloitte is preparing a bid for the European Commission's call for tenders EC-CNECT-LUX/2026/OP/0004",
        "expected": "actionable",
    },
    {
        "sender": "walter@example.com",
        "sender_name": "Victor Example",
        "subject": "Meet up while I'm in Slovenia?",
        "snippet": "Hey the founder, I will be in Slovenia this summer, meeting with a few local businesses that are planning to expand their outreach efforts.",
        "expected": "auto_archive",
    },
    {
        "sender": "support6@vendor.example.com",
        "sender_name": "Neil @ Qdrant",
        "subject": "June Qdrant Updates: Vector Space Day on YouTube, Bulk Insert Tutorial, and More",
        "snippet": "Check out our latest product updates, resources, and events. June 2026 Newsletter.",
        "expected": "newsletter",
    },
    {
        "sender": "sybil@example.com",
        "sender_name": "Trent Fius",
        "subject": "Fwd: [support2@vendor.example.com] Invitation to Participate in the Data Altruism Consent Management System Project",
        "snippet": "---------- Forwarded message --------- From: 'Example, Dave' via Acme Info",
        "expected": "actionable",
    },
    {
        "sender": "trent@example.com",
        "sender_name": "Tina Jovović",
        "subject": "Re: E-racuni.com: RAČUN št. 2026-01119",
        "snippet": "the founder, ta račun je bil plačan, ampak vidim, da je to račun za paket do 21.6.",
        "expected": "forward_accounting",
    },
]


if __name__ == "__main__":
    print(f"Testing Ollama email classification with {MODEL}")
    print(f"Ollama URL: {OLLAMA_URL}")
    print("=" * 70)
    print()

    correct = 0
    total = len(TEST_EMAILS)

    for i, email in enumerate(TEST_EMAILS, 1):
        print(f"[{i}/{total}] {email['subject'][:60]}")
        print(f"  From: {email['sender_name'][:50]}")

        result = classify_unknown(
            sender=email["sender"],
            sender_name=email["sender_name"],
            subject=email["subject"],
            snippet=email["snippet"],
        )

        match = "OK" if result["category"] == email["expected"] else "MISMATCH"
        if result["category"] == email["expected"]:
            correct += 1

        print(f"  -> {result['category']} ({result['priority']}) [{match}]")
        print(f"     Reason: {result['reason']}")
        print(f"     Tags: {result['tags']}")
        print(f"     Latency: {result['latency_ms']}ms")
        print()

    print("=" * 70)
    print(f"Results: {correct}/{total} correct ({correct/total*100:.0f}%)")
