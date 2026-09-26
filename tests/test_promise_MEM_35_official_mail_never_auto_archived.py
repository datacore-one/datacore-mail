"""MEM-35: Mail from government, compliance, banking and company-registration
senders always stays in my inbox and is never auto-archived as promotion.

Kind: deterministic. The nightly path (email_scanner.scan_inbox +
execute_auto_actions, as server/triage-email.sh runs it with --execute) with
the shipped rules.base.yaml against a fake Gmail. Senders named in the saved
rules (ENG-2026-0504-020, ENG-2026-08-05-013): a Slovenian government payment
agency (ujp.gov.si), the tax office (fu.gov.si), Companies House, the UK
company-formation agent (1stformations.co.uk, a soft-sounding renewal), a
bank notification and a Revolut Business compliance alert. Several carry the
words that make a mail look like a promotion ("newsletter", "unsubscribe",
"check-in"). None of them may be archived by the nightly run.

Seeded failure: a rule that archives every mail whose body says "unsubscribe"
(a promotion heuristic) -- the official mail would then be archived.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "lib"))
sys.path.insert(0, str(MODULE))

import email_scanner as es  # noqa: E402

ME = "owner@example.com"
OFFICIAL = [
    ("ujperacun@ujp.gov.si", "UJP", "eRačun: novo obvestilo", "Prejeli ste nov e-račun."),
    ("obvestila@fu.gov.si", "FURS", "Obvestilo eDavki", "Novo sporočilo v eDavkih. Newsletter settings: unsubscribe"),
    ("noreply@companieshouse.gov.uk", "Companies House", "Your confirmation statement is due",
     "File by 14 October. To stop these emails, unsubscribe."),
    ("no-reply@1stformations.co.uk", "1st Formations", "A quick check-in on your address services",
     "We hope you are enjoying our services. Unsubscribe here."),
    ("obvestila@lon.si", "Hranilnica LON", "Obvestilo o stanju na računu", "Stanje na vašem računu."),
    ("no-reply@revolut.com", "Revolut Business", "Your expenses are missing some info",
     "3 expenses need receipts. Manage email preferences / unsubscribe."),
]


def _run(tmp_path, monkeypatch, rules_text: str) -> list[str]:
    _, Email = es._import_gmail_adapter()
    emails = [Email(id=f"of{i:04d}abcdef", thread_id=f"t{i}", subject=s, sender=a, sender_name=n,
                    recipients=[ME], date=datetime(2026, 9, 25, 9, 0), snippet=b[:80], body_text=b,
                    labels=["INBOX", "UNREAD"])
              for i, (a, n, s, b) in enumerate(OFFICIAL)]
    archived: list[str] = []

    class FakeGmail:
        def __init__(self, cfg):
            pass

        def is_configured(self):
            return True

        def pull_emails(self, days=3, max_results=200):
            return list(emails)

        def archive(self, msg_id):
            archived.append(msg_id)
            return True

        def mark_read(self, msg_id):
            return True

        def send_email(self, **kw):
            return None   # a forward never succeeds, so it never archives

    monkeypatch.setattr(es, "_import_gmail_adapter", lambda: (FakeGmail, Email))
    rf = tmp_path / "rules.yaml"
    rf.write_text(rules_text, encoding="utf-8")
    space = tmp_path / "0-personal"
    (space / "org").mkdir(parents=True)
    (space / "org" / "inbox.org").write_text("#+TITLE: Inbox\n\n* Inbox\n", encoding="utf-8")
    scan = es.scan_inbox(ME, days=3, rules_path=str(rf))
    es.execute_auto_actions(scan, ME, space_path=space)
    by_id = {e.id: e.sender for e in emails}
    return [by_id[i] for i in archived if i in by_id]


def test_official_senders_stay_in_the_inbox(tmp_path, monkeypatch):
    gone = _run(tmp_path, monkeypatch, (MODULE / "rules.base.yaml").read_text(encoding="utf-8"))
    assert not gone, f"the nightly run archived official mail: {gone}"
