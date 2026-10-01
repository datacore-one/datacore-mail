"""The morning briefing can tell mail that needs the owner from mail that does not (brief B4).

2026-10-01: the briefing's Actionable Mail listed "81 to close", led by team
GitHub notifications, event invites and a cold-intro bot; a declined payment
was one line among them. The briefing's section (chief-of-staff
cos_mail_section.py) now lists by priority and leaves GitHub to the GitHub
triage. For that it needs two things from this module:

  * The scan cache's queue (today_brief_section.actionable_items) carries each
    item's category, priority and tags -- it carried only sender and subject.
  * The rules can say "keep for review, but low": a sender under `senders.low`
    is classified actionable / review / LOW (no task is created). There was no
    such rule; a cold-intro bot fell through to the local model, which called
    it actionable MEDIUM.

With fixture rules shaped like the one rules file, the four kinds of mail land
where the brief says: team GitHub notification -> github; event invite (an
event-type newsletter sender) -> archived; cold-intro bot -> LOW; payment
declined -> actionable HIGH, urgent.

Senders, domains and subjects are invented. The real rules are data in
0-personal/.datacore/module-data/mail/rules.yaml, not here.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import email_scanner as es  # noqa: E402
import today_brief_section as tb  # noqa: E402

RULES = {
    "senders": {
        "newsletter": [{"pattern": "events.test", "action": "archive_only", "type": "event"}],
        "low": [{"pattern": "@intro-bot.test", "reason": "cold-intro bot"}],
    },
    "subjects": {"finance": [{"pattern": "declined", "action": "surface_actionable"}]},
    "github": {"notification_senders": ["notifications@github.test"],
               "events": {"assign": {"action": "ACTIONABLE", "priority": "HIGH"}}},
}


def _email(sender, name, subject, gh_reason=None):
    return types.SimpleNamespace(id="x", sender=sender, sender_name=name, subject=subject,
                                 body_text="", snippet="", labels=["INBOX"], thread_id="t",
                                 gh_reason=gh_reason)


def _classify(monkeypatch, email):
    monkeypatch.setattr(es, "_ollama_classify", lambda *a, **k: None)   # no network, no model
    return es.classify_email(email, RULES)


def test_the_four_kinds_land_where_the_brief_says(monkeypatch):
    gh = _classify(monkeypatch, _email("notifications@github.test", "Dev One",
                                       "Re: [acme/widget] fix the hook (PR #12)", "assign"))
    assert gh["category"] == "github"
    invite = _classify(monkeypatch, _email("calendar@user.events.test", "Some Meetup",
                                           "You are invited: founders evening"))
    assert invite["category"] == "auto_archive"
    bot = _classify(monkeypatch, _email("hello@intro-bot.test", "Intro Bot",
                                        "Open to an intro to a founder?"))
    assert (bot["category"], bot["action"], bot["priority"]) == ("actionable", "review", "LOW")
    pay = _classify(monkeypatch, _email("billing@saas.test", "Billing",
                                        "Action required: Payment declined for invoice 42"))
    assert (pay["category"], pay["priority"]) == ("actionable", "HIGH")
    assert "urgent" in pay["tags"]


def test_the_queue_carries_priority_and_tags():
    cache = {"emails": [
        {"category": "actionable", "sender": "billing@saas.test", "sender_name": "Billing",
         "subject": "Payment declined", "priority": "HIGH", "tags": ["finance", "urgent"],
         "action": "task", "id": "1"},
        {"category": "github", "sender": "notifications@github.test", "sender_name": "Dev One",
         "subject": "PR #12", "priority": "HIGH", "tags": ["github"], "action": "task", "id": "2"},
        {"category": "auto_archive", "sender": "x@events.test", "subject": "invite", "id": "3"},
    ]}
    items = tb.actionable_items(cache)
    assert [i["id"] for i in items] == ["1", "2"]
    assert items[0]["priority"] == "HIGH" and items[0]["tags"] == ["finance", "urgent"]
    assert items[1]["category"] == "github"
