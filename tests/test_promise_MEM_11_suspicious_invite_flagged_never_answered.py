"""MEM-11: A suspicious calendar invite is flagged to me as phishing and never answered, not even
with a decline.

Kind: deterministic. (1) The real mail triage classifier (email_scanner.classify_email with the
module's own rules.base.yaml, copied to tmp so no local overlay applies) on invitation mails.
(2) The real calendar write helpers (.datacore/lib/sync/calendar_admin.py) against a recording
fake Google service -- no call may notify the organiser. (3) The real in-flight policy
(tool_policy.decide) for the agent principals that handle mail and calendars.

Seeded failure: a calendar invitation from the calendar notification sender whose organiser is a
look-alike domain and whose body is a credential-harvest lure ("verify your account", a login
link). The promise holds when triage flags it as phishing for the owner (a phishing category or
tag, never the routine "check_calendar_sync"), an ordinary invite from a known colleague is still
routine (not a vacuous flag), no calendar helper sends updates, and an agent's RSVP (accept,
decline, tentative) through the calendar tools is refused.
Red today: triage has no phishing class -- the lure is routed as a routine invitation to sync --
and an agent's calendar RSVP is not covered by any policy effect.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("DATACORE_ROOT", str(MODULE.parents[2])))
sys.path.insert(0, str(MODULE / "lib"))
sys.path.insert(0, str(MODULE))
import email_scanner as es  # noqa: E402

ROOT_LIB = ROOT / ".datacore" / "lib"


@pytest.fixture
def rules(tmp_path):
    base = tmp_path / "rules.base.yaml"
    shutil.copy(MODULE / "rules.base.yaml", base)     # no rules.local.yaml beside it
    r = es.load_rules(str(base))
    senders = (r.get("calendar") or {}).get("notification_senders") or []
    assert senders, "rules.base.yaml has no calendar notification sender (fixture would be vacuous)"
    return r, senders[0]


def _mail(sender, subject, body, organiser):
    _, Email = es._import_gmail_adapter()
    return Email(id="msg0001abcdef", thread_id="t1", subject=subject, sender=sender,
                 sender_name=organiser, recipients=["owner@example.com"],
                 date=datetime(2026, 9, 25, 9, 0), snippet=body[:120], body_text=body,
                 labels=["INBOX", "UNREAD"])


LURE_BODY = ("IT Security has scheduled a mandatory account verification.\n"
             "Your mailbox will be suspended in 24 hours unless you verify your password:\n"
             "https://login-microsoftonline.verify-account-secure.example/owa\n"
             "Organizer: it-security@micros0ft-support.example\n")


def test_suspicious_invite_is_flagged_as_phishing(rules):
    r, cal_sender = rules
    res = es.classify_email(_mail(cal_sender, "Invitation: Urgent account verification @ Fri Sep 26, 2026",
                                  LURE_BODY, "IT Security"), r)
    flagged = "phish" in (res.get("category") or "") or any("phish" in t for t in res.get("tags") or [])
    assert flagged, f"a credential-harvest invite was not flagged as phishing: {res}"
    assert res.get("action") not in ("check_calendar_sync", "auto_archive"), (
        f"the lure was routed as routine ({res.get('action')}) instead of flagged to the owner")


def test_ordinary_invite_stays_routine(rules):
    r, cal_sender = rules
    res = es.classify_email(_mail(cal_sender, "Invitation: Weekly sync @ Mon Sep 28, 2026",
                                  "Weekly sync with the team.\nOrganizer: colleague@example.com\n",
                                  "Colleague"), r)
    assert res.get("category") == "calendar", res


class _Recorder:
    """Fake googleapiclient service: records every events() call's kwargs."""

    def __init__(self):
        self.calls = []

    def events(self):
        rec = self

        class _E:
            def __getattr__(self, name):
                def call(**kw):
                    rec.calls.append((name, kw))

                    class _X:
                        def execute(self_inner):
                            return {"id": "e1", "items": []}
                    return _X()
                return call
        return _E()


def test_calendar_helpers_never_notify_the_organiser():
    sys.path.insert(0, str(ROOT_LIB / "sync"))
    sys.path.insert(0, str(ROOT_LIB / "sync" / "adapters"))
    import calendar_admin as ca
    svc = _Recorder()
    ca.delete_event(svc, "primary", "e1")
    ca.patch_event(svc, "primary", "e1", start="2026-09-28T10:00:00", end="2026-09-28T10:30:00")
    writes = [(n, kw) for n, kw in svc.calls if n in ("delete", "patch", "update", "insert")]
    assert writes, "no calendar write was exercised (vacuous)"
    for name, kw in writes:
        assert kw.get("sendUpdates") == "none", f"calendar {name} notifies the organiser: {kw}"


RSVP = [
    ("mcp__claude_ai_Google_Calendar__respond_to_event", {"eventId": "e1", "response": "declined"}),
    ("mcp__claude_ai_Google_Calendar__update_event",
     {"eventId": "e1", "attendees": [{"email": "owner@example.com", "responseStatus": "declined"}],
      "sendUpdates": "all"}),
    ("Bash", {"command": "gcalcli respond --response declined 'Urgent account verification'"}),
]


@pytest.mark.parametrize("principal", ["winston", "miles"])
@pytest.mark.parametrize("tool,tool_input", RSVP, ids=["respond", "update-attendee", "gcalcli"])
def test_an_agent_rsvp_is_refused(principal, tool, tool_input, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT_LIB))
    import tool_policy
    d = tool_policy.decide(principal, tool, tool_input)
    assert not d.allow, f"{principal} may answer a calendar invite: {tool} {tool_input}"
