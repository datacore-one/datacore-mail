"""Triage archives. It does not delete, and it writes down what it did.

On 2026-09-17 important correspondence was found deleted. The nightly triage
script never deletes — but `/mails` listed "YOU CAN: Trash emails (moves to
Trash, 30-day retention)" as a permitted action, eight rules carried
`action: trash`, and the adapter exposed both `trash()` (a 30-day fuse) and
`delete()` ("immediate, no recovery"). The only thing between an agent and
permanent loss was a sentence in a prompt.

These tests make the capability unreachable rather than discouraged, and pin
the record that lets anyone ask what happened to a given message — the run-level
audit log could not answer that, and had no `trashed` counter at all, so it
positively implied nothing had been deleted.
"""
import json
import os
import sys
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE))

import mail_audit  # noqa: E402


def _adapter(tmp_path, monkeypatch):
    monkeypatch.setenv('DATACORE_ROOT', str(tmp_path))
    monkeypatch.delenv('DATACORE_MAIL_ALLOW_TRASH', raising=False)
    from gmail import GmailAdapter
    return GmailAdapter({'address': 'someone@example.com'})


def test_permanent_delete_is_always_refused(tmp_path, monkeypatch):
    assert _adapter(tmp_path, monkeypatch).delete('m-1') is False


def test_delete_stays_refused_even_with_the_trash_opt_in(tmp_path, monkeypatch):
    """The opt-in covers a supervised trash, never an unrecoverable delete."""
    adapter = _adapter(tmp_path, monkeypatch)
    monkeypatch.setenv('DATACORE_MAIL_ALLOW_TRASH', '1')
    assert adapter.delete('m-2') is False


def test_trash_is_refused_by_default(tmp_path, monkeypatch):
    assert _adapter(tmp_path, monkeypatch).trash('m-3') is False


def test_every_refusal_is_recorded(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path, monkeypatch)
    adapter.trash('m-4')
    adapter.delete('m-5')
    rows = [json.loads(l) for l in mail_audit._log_path().read_text(encoding='utf-8').splitlines() if l.strip()]
    actions = {(r['message_id'], r['action'], r['ok']) for r in rows}
    assert ('m-4', 'trash', False) in actions
    assert ('m-5', 'delete', False) in actions
    assert all(r.get('error') == 'refused by policy' for r in rows)


def test_a_message_can_be_asked_what_happened_to_it(tmp_path, monkeypatch):
    monkeypatch.setenv('DATACORE_ROOT', str(tmp_path))
    mail_audit.record('a@b.c', 'm-6', 'archive', True,
                      sender='Someone <s@e.test>', subject='Quarterly update')
    assert [r['action'] for r in mail_audit.history('m-6')] == ['archive']
    # and found by sender or subject, since nobody has the id to hand
    assert mail_audit.search('quarterly')[0]['message_id'] == 'm-6'
    assert mail_audit.search('s@e.test')[0]['message_id'] == 'm-6'


def test_no_rule_file_still_asks_for_a_trash(tmp_path):
    """The eight `action: trash` rules became `archive` on 2026-09-17."""
    root = MODULE.parents[2]
    for rules in root.glob('[0-9]-*/.datacore/mail-rules.yaml'):
        assert 'action: trash' not in rules.read_text(encoding='utf-8'), rules
