"""MEM-33: Mail from my personal accounts is filed in my personal space. Mail
to a team mailbox (info@, accounting@) goes to that team's space.

Kind: deterministic + production contract (read-only config).
  * the space an account belongs to is declared by which space's
    .datacore/mail.yaml lists it (MailModule.discover_configs);
  * the nightly cron path (email_scanner.py --execute, as server/triage-email.sh
    runs it per account) must hand execute_auto_actions the space that owns the
    scanned account -- not the 0-personal default for every account;
  * the task creator (lib/task_creator.py, /triage-email step 3) must put a task
    for a team-mailbox email in that team's space;
  * production: in the real spaces' mail.yaml, a role mailbox (info@,
    accounting@, support@ ...) is never declared in 0-personal.

Seeded failure: every account resolved to 0-personal (today's default in
email_scanner.main and task_creator._resolve_org_file).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1]
MODULES = MODULE.parent
ROOT = MODULES.parents[1]
sys.path.insert(0, str(MODULE / "lib"))
sys.path.insert(0, str(MODULES))

PERSONAL = "owner@personal.example"
TEAM = "info@team.example"
ROLE_LOCALS = {"info", "accounting", "support", "billing", "hello", "office", "admin", "contact", "team", "sales"}


def _mail_yaml(space: Path, name: str, address: str) -> None:
    (space / ".datacore").mkdir(parents=True, exist_ok=True)
    (space / "org").mkdir(parents=True, exist_ok=True)
    (space / "org" / "inbox.org").write_text("* Inbox\n", encoding="utf-8")
    (space / "org" / "next_actions.org").write_text("* Work\n", encoding="utf-8")
    (space / ".datacore" / "mail.yaml").write_text(
        f"accounts:\n  - name: {name}\n    address: {address}\n    provider: gmail\n"
        f"    processor: classifier\n    destination: org/inbox.org\n", encoding="utf-8")


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "Data"
    _mail_yaml(d / "0-personal", "me", PERSONAL)
    _mail_yaml(d / "1-team", "info", TEAM)
    return d


def _scan(account: str) -> dict:
    return {"account": account, "inbox_count": 1, "scanned_at": "2026-09-26T08:00:00",
            "categories": {"actionable": [{
                "id": "msg0000001", "sender": "alice@partner.example", "sender_name": "Alice",
                "subject": f"Question for {account}", "gmail_url": "https://mail.google.com/x",
                "snippet": "hi", "priority": "HIGH", "reason": "rule"}]}}


def test_accounts_belong_to_the_space_that_declares_them(data):
    from mail.module import MailModule
    accounts = {a.address: a.space_path.name for a in MailModule(data_root=data).discover_configs()}
    assert accounts == {PERSONAL: "0-personal", TEAM: "1-team"}, accounts


@pytest.mark.parametrize("account,space", [(PERSONAL, "0-personal"), (TEAM, "1-team")])
def test_nightly_scan_files_into_the_accounts_space(data, tmp_path, monkeypatch, account, space):
    import email_scanner as es
    monkeypatch.setenv("HOME", str(tmp_path))            # Path.home()/"Data" == data
    cache = tmp_path / "scan.json"
    cache.write_text(json.dumps(_scan(account)), encoding="utf-8")
    seen = {}

    def fake_execute(scan_results, account_address, forward_to=None, space_path=None, **kw):
        seen["space_path"] = space_path
        return {"archived": [], "forwarded": [], "processed": {}, "errors": []}

    monkeypatch.setattr(es, "execute_auto_actions", fake_execute)
    monkeypatch.setattr(sys, "argv", ["email_scanner.py", "--account", account, "--load-cache",
                                      str(cache), "--execute", "--format", "json"])
    es.main()
    effective = Path(seen["space_path"]) if seen.get("space_path") else Path.home() / "Data" / "0-personal"
    assert effective.name == space, (
        f"mail for {account} is filed in {effective.name}, not {space} "
        f"(execute_auto_actions got space_path={seen.get('space_path')})")


@pytest.mark.parametrize("account,space", [(PERSONAL, "0-personal"), (TEAM, "1-team")])
def test_task_creator_files_into_the_accounts_space(data, monkeypatch, account, space):
    import task_creator as tc
    targets = []

    def fake_create(org_file, heading, tags, properties, **kw):
        targets.append(Path(org_file))
        return {"success": True, "id": properties.get("TRIAGE_ID"), "heading": heading}

    monkeypatch.setattr(tc, "create_triage_task", fake_create)
    tc.create_tasks_from_scan(_scan(account), data)
    assert targets, "no task was attempted for an actionable email"
    got = {t.relative_to(data).parts[0] if data in t.parents else str(t) for t in targets}
    assert got == {space}, f"task for mail to {account} went to {got}, not {space}"


@pytest.mark.production
def test_real_config_keeps_team_mailboxes_out_of_personal():
    from mail.module import MailModule
    accounts = MailModule(data_root=ROOT).discover_configs()
    assert accounts, "no mail.yaml accounts discovered in the real spaces"
    wrong = [f"{a.name} ({a.address.split('@')[0]}@...) in {a.space_path.name}" for a in accounts
             if a.address.split("@")[0].lower() in ROLE_LOCALS and a.space_path.name.startswith("0-")]
    assert not wrong, f"team mailboxes declared in the personal space: {wrong}"
