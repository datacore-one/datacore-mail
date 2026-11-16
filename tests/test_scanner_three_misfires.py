"""Three misfires of the rule scanner, found in one triage (2026-11-14).

1. A GitHub notification addressed to ANOTHER account was classified as the
   owner's. A bot account's mail reached the owner's inbox through a
   plus-address, and its review requests, mentions and assignments became the
   owner's tasks: the scanner read why GitHub sent the mail
   (X-GitHub-Reason) and never to whom (X-GitHub-Recipient).
2. Any subject containing "reminder:" was treated as a calendar reminder for an
   event that has passed, so the nightly run would have archived an
   e-signature reminder that was waiting for a signature.
3. A newsletter with "payments" in its subject was routed to accounting as an
   invoice: finance subject words are checked before newsletter senders, and
   "payment" is a word newsletters use.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest
import yaml

MODULE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE / "lib"))
import email_scanner as s  # noqa: E402

GITHUB = "notifications@github.com"


@pytest.fixture(autouse=True)
def _no_local_model(monkeypatch):
    """An unmatched mail must reach the conservative default, not a model."""
    monkeypatch.setattr(s, "_ollama_classify", lambda *a, **k: None)


def _email(sender, subject, name="", **extra):
    return types.SimpleNamespace(id="x", sender=sender, sender_name=name, subject=subject,
                                 body_text="", snippet="", labels=[], thread_id="t", **extra)


def _base_rules():
    return yaml.safe_load((MODULE / "rules.base.yaml").read_text(encoding="utf-8"))


# ── 1. whose GitHub notification is it ────────────────────────────────────────

def _github_rules(**more):
    return {"github": {"notification_senders": [GITHUB],
                       "events": {"review_requested": {"action": "ACTIONABLE", "priority": "HIGH"}},
                       **more}}


def _review_request(recipient=None):
    extra = {"gh_reason": "review_requested"}
    if recipient is not None:
        extra["gh_recipient"] = recipient
    return _email(GITHUB, "Re: [org/repo] Add the importer (PR #7)", **extra)


def test_a_notification_for_another_account_is_not_the_owners_task():
    c = s._classify_by_rules(_review_request("helper-bot"), _github_rules(own_logins=["owner"]))
    assert c["action"] != "task", c
    assert (c["category"], c["action"], c["priority"]) == ("github", "review", "LOW")
    assert c["rule_name"] == "github_other_recipient" and "helper-bot" in c["reason"]


def test_the_owners_own_notification_is_still_a_task():
    c = s._classify_by_rules(_review_request("Owner"), _github_rules(own_logins=["owner"]))
    assert (c["action"], c["priority"], c["rule_name"]) == ("task", "HIGH", "github_review_requested")


def test_without_own_logins_nothing_changes():
    c = s._classify_by_rules(_review_request("helper-bot"), _github_rules())
    assert c["rule_name"] == "github_review_requested"


def test_a_notification_that_names_no_recipient_is_judged_as_before():
    c = s._classify_by_rules(_review_request(None), _github_rules(own_logins=["owner"]))
    assert c["rule_name"] == "github_review_requested"


def test_another_accounts_mail_is_archived_only_when_the_rules_say_so():
    rules = _github_rules(own_logins=["owner"], other_recipients="archive")
    c = s._classify_by_rules(_review_request("helper-bot"), rules)
    assert (c["category"], c["rule_name"]) == ("auto_archive", "github_other_recipient_arch")


def test_a_security_advisory_surfaces_whoever_it_was_sent_to():
    mail = _email(GITHUB, "A security advisory on left-pad affects org/repo",
                  gh_reason="security_advisory", gh_recipient="helper-bot")
    c = s._classify_by_rules(mail, _github_rules(own_logins=["owner"]))
    assert (c["action"], c["rule_name"]) == ("task", "github_security")


def test_the_adapter_carries_the_recipient_header():
    # Loaded by path: another test puts a different `adapters` package on sys.path.
    spec = importlib.util.spec_from_file_location("mail_gmail_adapter", MODULE / "adapters" / "gmail.py")
    gmail = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gmail  # dataclasses look their module up while the class is built
    spec.loader.exec_module(gmail)
    adapter = object.__new__(gmail.GmailAdapter)
    msg = {"id": "m1", "threadId": "t1", "labelIds": ["INBOX"], "snippet": "",
           "payload": {"headers": [
               {"name": "From", "value": "GitHub <notifications@github.com>"},
               {"name": "To", "value": "owner+helper@example.test"},
               {"name": "Subject", "value": "Re: [org/repo] Add the importer (PR #7)"},
               {"name": "Date", "value": "Sat, 14 Nov 2026 10:00:00 +0000"},
               {"name": "X-GitHub-Reason", "value": "review_requested"},
               {"name": "X-GitHub-Recipient", "value": "helper-bot"}]}}
    mail = adapter._parse_message(msg)
    assert (mail.gh_reason, mail.gh_recipient) == ("review_requested", "helper-bot")


# ── 2. a reminder is not always a calendar reminder ───────────────────────────

def test_a_signature_reminder_is_not_a_passed_calendar_event():
    mail = _email("noreply@mail.esign.example", "Reminder: Contract for signatures is awaiting your signature")
    c = s._classify_by_rules(mail, _base_rules())
    assert c["action"] != "check_event_passed", c
    assert c["category"] != "auto_archive", c


def test_a_calendar_reminder_from_the_calendar_sender_still_is_one():
    rules = _base_rules()
    sender = rules["calendar"]["notification_senders"][0]
    c = s._classify_by_rules(_email(sender, "Reminder: Standup @ Mon 16 Nov 10:00"), rules)
    assert (c["action"], c["rule_name"]) == ("check_event_passed", "cal_reminder")


# ── 3. a newsletter that writes about payments is a newsletter ────────────────

FINANCE = {"subjects": {"finance": [
               {"pattern": "unsuccessful", "action": "surface_actionable"},
               {"pattern": "invoice", "action": "route_to_accounting"},
               {"pattern": "payment", "not_from_newsletters": True}]},
           "domains": {"newsletter": ["news.example"]},
           "senders": {"newsletter": [
               {"pattern": "fintech weekly", "action": "aggregate_daily_news"},
               # A vendor listed for its product news also sends receipts.
               {"pattern": "cloudhost", "action": "check_product_update", "type": "service"},
               {"pattern": "bank.example", "action": "archive_only", "type": "service"}]}}


def test_a_newsletter_about_payments_is_not_an_invoice():
    by_domain = s._classify_by_rules(_email("hello@news.example", "This week: payments and fintech"), FINANCE)
    assert by_domain["rule_name"] == "newsletter_domain", by_domain
    by_name = s._classify_by_rules(
        _email("hi@platform.example", "Payments roundup", name="Fintech Weekly"), FINANCE)
    assert by_name["rule_name"] == "newsletter_sender", by_name


def test_a_receipt_from_anyone_else_still_goes_to_accounting():
    c = s._classify_by_rules(_email("billing@host.example", "Received $111.42 payment for Acme"), FINANCE)
    assert (c["category"], c["rule_name"]) == ("forward_accounting", "finance_subject")


@pytest.mark.parametrize("sender", ["support@cloudhost.example", "no-reply@bank.example"])
def test_a_receipt_from_a_vendor_listed_for_its_product_news_still_goes_to_accounting(sender):
    """Found with a real sample (a hosting provider's payment receipt) before
    this shipped: a sender listed under senders.newsletter for product updates
    or archiving is a vendor, not a publication, and its receipts are receipts."""
    c = s._classify_by_rules(_email(sender, "Received $111.42 payment for Acme"), FINANCE)
    assert (c["category"], c["rule_name"]) == ("forward_accounting", "finance_subject"), c


def test_an_invoice_from_a_newsletter_platform_still_goes_to_accounting():
    c = s._classify_by_rules(_email("billing@news.example", "Your invoice is attached"), FINANCE)
    assert c["category"] == "forward_accounting", c


def test_a_failed_charge_surfaces_even_from_a_newsletter_platform():
    c = s._classify_by_rules(_email("billing@news.example", "Your payment was unsuccessful"), FINANCE)
    assert (c["action"], c["rule_name"]) == ("task", "finance_actionable")


def test_without_the_flag_the_payment_rule_matches_as_before():
    rules = {**FINANCE, "subjects": {"finance": [{"pattern": "payment"}]}}
    c = s._classify_by_rules(_email("hello@news.example", "This week: payments and fintech"), rules)
    assert c["rule_name"] == "finance_subject"


def test_the_shipped_rules_carry_both_fixes():
    rules = _base_rules()
    calendar_subjects = [e.get("pattern") for e in rules["subjects"]["calendar"]]
    assert "reminder:" not in calendar_subjects
    payment = [e for e in rules["subjects"]["finance"] if e.get("pattern") == "payment"]
    assert payment and payment[0].get("not_from_newsletters") is True
