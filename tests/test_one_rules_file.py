"""All mail rules live in one file outside the module (owner, 2026-09-29).

That file is `0-personal/.datacore/module-data/mail/rules.yaml`. /mails
(processors/classifier.py) and the nightly triage (lib/email_scanner.py) both
load it through one loader (lib/mail_rules.py), so the two can no longer read
different rule sets. The module ships only its generic example
(rules.base.yaml, used when no rules file exists). Each space's account config
(mail.yaml) sits beside it, in `<space>/.datacore/module-data/mail/`.

Before this, the classifier merged three files and the triage two, and the
GitHub, npm and Google Analytics senders were hard-coded as scrubbed
placeholder addresses that never matched real mail: on 2026-09-29, 86 GitHub
emails went down the newsletter path.
"""
import re
import sys
import types
from pathlib import Path

import yaml

MODULE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE / "lib"))
sys.path.insert(0, str(MODULE.parent))

import mail_rules  # noqa: E402
import email_scanner as es  # noqa: E402

RULES = {
    "senders": {"ignore": [{"pattern": "@noise.test"}], "research": []},
    "github": {"notification_senders": ["notifications@gh.test"], "events": {}},
    "notifications": {
        "npm_publish": {"senders": ["support@pkg.test"], "subject_contains": ["successfully published"],
                        "reason": "npm package publish notification"},
        "ga4_report": {"senders": ["analytics@stats.test"], "reason": "GA4 analytics report"},
    },
    "spaces": {"1-team": {"senders": {"actionable": [{"pattern": "@team.test"}]}}},
}


def _root(tmp_path, rules=RULES):
    f = tmp_path / "0-personal" / mail_rules.RULES_REL
    f.parent.mkdir(parents=True)
    f.write_text(yaml.safe_dump(rules), encoding="utf-8")
    return tmp_path, f


def test_the_rules_file_is_the_personal_module_data_file(tmp_path):
    root, f = _root(tmp_path)
    assert mail_rules.rules_file(root) == f


def test_without_a_rules_file_the_generic_example_applies(tmp_path):
    assert mail_rules.rules_file(tmp_path) == MODULE / "rules.base.yaml"


def test_space_section_applies_only_to_that_space(tmp_path):
    root, _ = _root(tmp_path)
    plain = mail_rules.load_rules(root=root)
    team = mail_rules.load_rules(root=root, space="1-team")
    assert "spaces" not in plain and "spaces" not in team
    assert not plain["senders"].get("actionable")
    assert team["senders"]["actionable"] == [{"pattern": "@team.test"}]
    assert team["senders"]["ignore"] == [{"pattern": "@noise.test"}]


def test_no_overlay_file_is_read_any_more(tmp_path):
    """rules.local.yaml beside the file is not merged: one file is the whole truth."""
    root, f = _root(tmp_path)
    (f.parent / "rules.local.yaml").write_text("senders: {ignore: [{pattern: '@extra.test'}]}")
    assert mail_rules.load_rules(root=root)["senders"]["ignore"] == [{"pattern": "@noise.test"}]


def test_triage_and_classifier_read_the_same_file(tmp_path, monkeypatch):
    root, _ = _root(tmp_path)
    monkeypatch.setenv("DATACORE_ROOT", str(root))
    triage = es.load_rules()
    from mail.processors.classifier import RulesLoader
    merged = RulesLoader(MODULE, tmp_path / "0-personal").load()
    assert triage["senders"]["ignore"] == [{"pattern": "@noise.test"}]
    assert [r["pattern"] for r in merged.senders_ignore] == ["@noise.test"]
    team = RulesLoader(MODULE, tmp_path / "1-team").load()
    assert [r["pattern"] for r in team.senders_actionable] == ["@team.test"]


def _email(sender, subject="hello"):
    return types.SimpleNamespace(id="x", sender=sender, sender_name="", subject=subject,
                                 body_text="", snippet="", labels=[], thread_id="t")


def test_notification_senders_come_from_the_rules(tmp_path):
    root, _ = _root(tmp_path)
    rules = mail_rules.load_rules(root=root)
    assert es.classify_email(_email("support@pkg.test", "Successfully published x@1.0"), rules)["rule_name"] == "npm_publish"
    assert es.classify_email(_email("analytics@stats.test", "Weekly report"), rules)["rule_name"] == "ga4_report"
    ci = es.classify_email(_email("notifications@gh.test", "[a/b] Run failed: ci - main"), rules)
    assert ci["rule_name"] == "ci_noise"


def test_classifier_detects_github_from_the_rules(tmp_path, monkeypatch):
    root, _ = _root(tmp_path)
    monkeypatch.setenv("DATACORE_ROOT", str(root))
    from mail.processors.classifier import ClassifierProcessor
    c = ClassifierProcessor.__new__(ClassifierProcessor)
    from mail.processors.classifier import RulesLoader
    c.rules = RulesLoader(MODULE, tmp_path / "0-personal").load()
    assert c._is_github_notification(types.SimpleNamespace(sender="Someone <notifications@gh.test>"))
    assert not c._is_github_notification(types.SimpleNamespace(sender="friend@elsewhere.test"))


_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z.]+")
_DOC_EXAMPLES = ("@example.com", "@vendor.example.com")  # usage strings in docstrings and --help


def test_no_sender_address_is_hard_coded_in_classifier_code():
    for rel in ("lib/email_scanner.py", "processors/classifier.py"):
        src = (MODULE / rel).read_text(encoding="utf-8")
        code = [m.group(0) for m in _ADDRESS.finditer(src)
                if not m.group(0).endswith(_DOC_EXAMPLES)]
        assert not code, f"{rel} hard-codes sender addresses {code}; they belong in the rules file"
        assert "service.example.com" not in src, f"{rel} still matches a scrubbed placeholder sender"


def test_account_config_is_found_beside_the_rules(tmp_path):
    from mail.module import MailModule
    space = tmp_path / "1-team"
    cfg = space / ".datacore" / "module-data" / "mail" / "mail.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("accounts:\n  - name: info\n    address: info@team.test\n")
    accounts = MailModule(data_root=tmp_path).discover_configs()
    assert [(a.address, a.space_path.name) for a in accounts] == [("info@team.test", "1-team")]
    assert mail_rules.account_config(space) == cfg
