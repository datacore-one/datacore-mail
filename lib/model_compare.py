#!/usr/bin/env python3
"""
Head-to-head comparison: Qwen3 4B vs Gemma3 4B on email classification.
Tests both models on the same 6 unknown emails.
"""

import json
import urllib.request
import time

OLLAMA_URL = "http://localhost:11434/api/chat"

MODELS = ["qwen3:4b", "gemma3:4b"]

VALID_CATEGORIES = [
    "auto_archive", "research", "newsletter", "forward_accounting",
    "actionable", "calendar", "review",
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

TEST_EMAILS = [
    {
        "sender": "billing4@vendor.example.com",
        "sender_name": "Eleven Labs Inc.",
        "subject": "Your receipt from Eleven Labs Inc. #2604-8129-0374",
        "snippet": "Your receipt from Eleven Labs Inc. #2604-8129-0374",
        "expected": "auto_archive",
        "note": "SaaS receipt — auto_archive or forward_accounting both valid",
    },
    {
        "sender": "support2@vendor.example.com",
        "sender_name": "'Example, Dave' via Acme Info",
        "subject": "[support2@vendor.example.com] Invitation to Participate in the Data Altruism Consent Management System Project",
        "snippet": "Dear Sir/Madam, Deloitte is preparing a bid for the European Commission's call for tenders EC-CNECT-LUX/2026/OP/0004",
        "expected": "actionable",
        "note": "EC tender — clearly actionable",
    },
    {
        "sender": "walter@example.com",
        "sender_name": "Victor Example",
        "subject": "Meet up while I'm in Slovenia?",
        "snippet": "Hey the founder, I will be in Slovenia this summer, meeting with local businesses.",
        "expected": "auto_archive",
        "note": "Cold outreach — auto_archive or actionable (conservative)",
    },
    {
        "sender": "support6@vendor.example.com",
        "sender_name": "Neil @ Qdrant",
        "subject": "June Qdrant Updates: Vector Space Day on YouTube, Bulk Insert Tutorial, and More",
        "snippet": "Check out our latest product updates, resources, and events.",
        "expected": "newsletter",
        "note": "Product newsletter — newsletter or research (Qdrant is relevant to PLUR)",
    },
    {
        "sender": "sybil@example.com",
        "sender_name": "Trent Fius",
        "subject": "Fwd: Invitation to Participate in the Data Altruism Consent Management System Project",
        "snippet": "---------- Forwarded message --------- From: Example, Dave via Acme Info",
        "expected": "actionable",
        "note": "Forwarded EC tender — clearly actionable",
    },
    {
        "sender": "trent@example.com",
        "sender_name": "Tina Jovovicć",
        "subject": "Re: E-racuni.com: RAČUN št. 2026-01119",
        "snippet": "the founder, ta račun je bil plačan, ampak vidim, da je to račun za paket do 21.6.",
        "expected": "forward_accounting",
        "note": "Slovenian accounting email — forward_accounting",
    },
]


def classify(model, sender, sender_name, subject, snippet):
    prompt = PROMPT_TEMPLATE.format(
        sender=sender[:200], sender_name=sender_name[:200],
        subject=subject[:300], snippet=snippet[:500],
    )
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "format": "json",
        "stream": False,
        "think": False,  # Harmless for Gemma, required for Qwen3
        "options": {"temperature": 0.1, "num_predict": 200},
    }).encode()

    start = time.time()
    try:
        req = urllib.request.Request(OLLAMA_URL, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        latency = int((time.time() - start) * 1000)

        raw = data.get("message", {}).get("content", "").strip()
        result = json.loads(raw)

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
            "priority": priority,
            "reason": result.get("reason", ""),
            "tags": tags[:5],
            "latency_ms": latency,
            "json_valid": True,
        }
    except Exception as e:
        return {
            "category": "review",
            "priority": "MEDIUM",
            "reason": f"Error: {type(e).__name__}: {e}",
            "tags": [],
            "latency_ms": int((time.time() - start) * 1000),
            "json_valid": False,
        }


if __name__ == "__main__":
    print("HEAD-TO-HEAD: Qwen3 4B vs Gemma3 4B")
    print("=" * 80)
    print()

    results = {}
    for model in MODELS:
        print(f"--- {model} ---")
        results[model] = []
        for i, email in enumerate(TEST_EMAILS, 1):
            r = classify(model, email["sender"], email["sender_name"],
                        email["subject"], email["snippet"])
            results[model].append(r)
            match = "OK" if r["category"] == email["expected"] else "~"  # ~ = defensible
            print(f"  [{i}] {email['subject'][:55]}")
            print(f"      -> {r['category']} ({r['priority']}) [{match}] {r['latency_ms']}ms JSON:{r['json_valid']}")
            print(f"         {r['reason'][:100]}")
        print()

    # Summary table
    print("=" * 80)
    print("SUMMARY")
    print("-" * 80)
    print(f"{'Email':<45} {'Expected':<20} {'Qwen3':<20} {'Gemma3':<20}")
    print("-" * 80)
    for i, email in enumerate(TEST_EMAILS):
        q = results["qwen3:4b"][i]
        g = results["gemma3:4b"][i]
        q_match = "OK" if q["category"] == email["expected"] else "~"
        g_match = "OK" if g["category"] == email["expected"] else "~"
        print(f"  {email['subject'][:43]:<45} {email['expected']:<20} {q['category']+' ['+q_match+']':<20} {g['category']+' ['+g_match+']':<20}")

    print("-" * 80)
    q_exact = sum(1 for i, r in enumerate(results["qwen3:4b"]) if r["category"] == TEST_EMAILS[i]["expected"])
    g_exact = sum(1 for i, r in enumerate(results["gemma3:4b"]) if r["category"] == TEST_EMAILS[i]["expected"])
    q_json = sum(1 for r in results["qwen3:4b"] if r["json_valid"])
    g_json = sum(1 for r in results["gemma3:4b"] if r["json_valid"])
    q_avg_lat = sum(r["latency_ms"] for r in results["qwen3:4b"]) / len(results["qwen3:4b"])
    g_avg_lat = sum(r["latency_ms"] for r in results["gemma3:4b"]) / len(results["gemma3:4b"])

    print()
    print(f"  {'Metric':<25} {'Qwen3 4B':<20} {'Gemma3 4B':<20}")
    print(f"  {'-'*25} {'-'*20} {'-'*20}")
    print(f"  {'Exact matches':<25} {f'{q_exact}/6':<20} {f'{g_exact}/6':<20}")
    print(f"  {'Valid JSON':<25} {f'{q_json}/6':<20} {f'{g_json}/6':<20}")
    print(f"  {'Avg latency':<25} {f'{q_avg_lat:.0f}ms':<20} {f'{g_avg_lat:.0f}ms':<20}")
    print(f"  {'RAM footprint':<25} {'2.5GB':<20} {'3.3GB':<20}")
