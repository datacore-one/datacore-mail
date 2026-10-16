"""Research sender patterns match whole words, not substrings.

The AVC rule (pattern "avc") once matched an owner's own name as a substring.
Every email showing that name — the owner's own replies and every GitHub CI
notification sent in their name — was classified as research and archived by
the nightly triage, including threads that needed a reply.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import email_scanner as s  # noqa: E402


def _email(sender, name, subject="Re: something"):
    return types.SimpleNamespace(id="x", sender=sender, sender_name=name, subject=subject,
                                 body_text="", snippet="", labels=[], thread_id="t")


def test_owner_name_containing_avc_is_not_research():
    rules = s.load_rules()
    c = s._classify_by_rules(_email("alex@example.test", "Alex Havcroft"), rules)
    assert c.get("rule_name") != "research_sender"


def test_avc_sender_still_matches():
    rules = s.load_rules()
    c = s._classify_by_rules(_email("avc@paragraph.com", "AVC"), rules)
    assert c.get("rule_name") == "research_sender"
