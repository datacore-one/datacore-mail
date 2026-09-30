"""The morning mail section lists the accounts the installation declares.

today_brief_section.py defaulted to two scrubbed placeholder addresses
(grace@/heidi@example.com). The chief-of-staff briefing calls it without
--accounts, so on 2026-09-30 Winston's "Actionable Mail" said both
placeholders had "no scan yet" while the two real inboxes had been scanned.
The accounts are the ones each space declares in its mail.yaml
(mail_rules.account_config), the same config the rest of the module reads.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

MODULE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE / "lib"))

import today_brief_section as tbs  # noqa: E402

PLACEHOLDER = ("example.com", "example.org", "example.net")


def _root(tmp_path: Path) -> Path:
    for space, addrs in (("0-personal", ["me@work.test", "me@other.test"]),
                         ("1-team", ["team@work.test"])):
        d = tmp_path / space / ".datacore" / "module-data" / "mail"
        d.mkdir(parents=True)
        (d / "mail.yaml").write_text(yaml.safe_dump(
            {"accounts": {a.split("@")[0] + a[-8:]: {"address": a} for a in addrs}}, sort_keys=False))
    (tmp_path / "3-empty").mkdir()
    return tmp_path


def test_default_accounts_are_the_declared_ones(tmp_path):
    root = _root(tmp_path)
    assert tbs.declared_accounts(root) == ["me@work.test", "me@other.test", "team@work.test"]


def test_no_placeholder_is_ever_a_default():
    src = (MODULE / "lib" / "today_brief_section.py").read_text()
    assert not any(p in src for p in PLACEHOLDER)


def test_the_cli_reports_declared_accounts_only(tmp_path):
    root = _root(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    out = subprocess.run(
        [sys.executable, str(MODULE / "lib" / "today_brief_section.py"), "--json",
         "--state-dir", str(state)],
        env={**os.environ, "DATACORE_ROOT": str(root)},
        capture_output=True, text=True, check=True).stdout
    accounts = list(json.loads(out)["accounts"])
    assert accounts == ["me@work.test", "me@other.test", "team@work.test"]
