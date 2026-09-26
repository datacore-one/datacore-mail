"""Promise CAP-5:

    An email that needs action becomes an inbox task linked to the original
    email. Newsletters, CCs and spam never become tasks.

Kind: deterministic. Runs the nightly path the box cron uses
(`email_scanner.scan_inbox` + `execute_auto_actions`, as triage-email.sh
calls with --execute) against a fake Gmail at the adapter seam, with a tmp
rules file and a tmp space:
  - a mail from an actionable sender addressed to me -> one TODO in the
    space's org/inbox.org carrying the Gmail link of that message;
  - a newsletter, a spam mail, and a mail from the same actionable sender on
    which I am only CC'd (not in To) -> no inbox task.

Seeded failure: the actionable branch writes nothing (today's state:
execute_auto_actions has no branch for category "actionable"), or the task
lacks the message link.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "lib"))
sys.path.insert(0, str(MODULE))

import email_scanner as es  # noqa: E402

ME = "owner@example.com"
RULES = """
senders:
  ignore:
    - pattern: "promo@junk.example"
  actionable:
    - pattern: "alice@partner.example"
      priority: HIGH
domains:
  newsletter:
    - "news.example"
"""


def _fixture(tmp_path, monkeypatch):
    _, Email = es._import_gmail_adapter()

    def mail(i, sender, name, subject, to):
        return Email(id=f"msg{i:04d}abcdef", thread_id=f"t{i}", subject=subject, sender=sender,
                     sender_name=name, recipients=to, date=datetime(2026, 9, 25, 9, 0),
                     snippet=subject, body_text=subject, labels=["INBOX", "UNREAD"])

    emails = [
        mail(1, "alice@partner.example", "Alice", "Please sign the renewal by Friday", [ME]),
        mail(2, "digest@news.example", "Weekly News", "This week in data", [ME]),
        mail(3, "promo@junk.example", "Promo", "WIN A PRIZE", [ME]),
        mail(4, "alice@partner.example", "Alice", "FYI: minutes for the team", ["bob@partner.example"]),
    ]
    archived: list[str] = []

    class FakeGmail:
        def __init__(self, cfg):
            self.address = cfg.get("address")

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
            return None

    monkeypatch.setattr(es, "_import_gmail_adapter", lambda: (FakeGmail, Email))
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, encoding="utf-8")
    space = tmp_path / "0-personal"
    (space / "org").mkdir(parents=True)
    (space / "org" / "inbox.org").write_text("#+TITLE: Inbox\n\n* Inbox\n", encoding="utf-8")
    scan = es.scan_inbox(ME, days=3, rules_path=str(rules))
    es.execute_auto_actions(scan, ME, space_path=space)
    return space, emails


def _tasks(inbox_text: str) -> list[str]:
    """Each open heading with its body, as one block."""
    blocks, cur = [], None
    for line in inbox_text.splitlines():
        if line.startswith("*"):
            cur = [line]
            if " TODO " in f" {line} " or line.split(" ", 2)[1:2] == ["TODO"]:
                blocks.append(cur)
            continue
        if cur is not None:
            cur.append(line)
    return ["\n".join(b) for b in blocks]


def test_an_actionable_email_becomes_one_linked_inbox_task(tmp_path, monkeypatch):
    space, emails = _fixture(tmp_path, monkeypatch)
    tasks = _tasks((space / "org" / "inbox.org").read_text(encoding="utf-8"))
    mine = [t for t in tasks if "Please sign the renewal" in t]
    assert len(mine) == 1, f"the actionable email became {len(mine)} inbox task(s): {tasks}"
    assert emails[0].gmail_url in mine[0] or emails[0].id in mine[0], \
        "the inbox task does not link to the original email"


def test_newsletters_ccs_and_spam_never_become_tasks(tmp_path, monkeypatch):
    space, _ = _fixture(tmp_path, monkeypatch)
    text = "\n".join(_tasks((space / "org" / "inbox.org").read_text(encoding="utf-8")))
    for subject in ("This week in data", "WIN A PRIZE", "FYI: minutes for the team"):
        assert subject not in text, f"{subject!r} became an inbox task"
