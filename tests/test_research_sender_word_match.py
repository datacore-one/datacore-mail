"""Research sender patterns match whole words, not substrings.

2026-09-29: the AVC rule (pattern "avc") matched the owner's own name,
"Gregor Žavcer", as a substring. Every email showing that name — the owner's
own replies and every GitHub CI notification sent in his name — was classified
as research and archived by the nightly triage, including the thread with a
prospective pilot partner.
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
    c = s._classify_by_rules(_email("gregor@datafund.io", "Gregor Žavcer"), rules)
    assert c.get("rule_name") != "research_sender"


def test_avc_sender_still_matches():
    rules = s.load_rules()
    c = s._classify_by_rules(_email("avc@paragraph.com", "AVC"), rules)
    assert c.get("rule_name") == "research_sender"
