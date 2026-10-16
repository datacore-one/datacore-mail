"""A newsletter with no article link is skipped, not an error.

Six to eight such mails a night put "errors=8" in the
Completed line and a chief-of-staff alert every morning, for mail the pipeline
was never going to handle differently."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processors.newsletter import NewsletterProcessor  # noqa: E402


def test_newsletter_without_a_link_is_skipped_not_an_error(tmp_path, monkeypatch):
    proc = NewsletterProcessor(space_path=tmp_path)
    monkeypatch.setattr(proc, "_extract_article_url", lambda email: None)
    email = SimpleNamespace(id="m1", subject="Revolut Wins Conditional US Bank Charter and more",
                            date=None, body="", sender="news@example.com")
    res = proc._process_research(email, "RESEARCH")
    assert res.action == "SKIPPED"
    assert res.should_archive is False
    assert res.summary.startswith("no article link in: Revolut Wins")
    assert res.inbox_entry is None


def test_batch_survives_a_skipped_newsletter(tmp_path, monkeypatch):
    """2026-10-13: batch_process_newsletters had no 'SKIPPED' bucket, so the
    first link-less newsletter raised KeyError and stopped the whole batch."""
    from processors import newsletter as nl
    monkeypatch.setattr(nl.NewsletterProcessor, "_extract_article_url", lambda self, email: None)
    email = SimpleNamespace(id="m1", subject="Digest with no link", date=None, body="", sender="n@example.com")
    cls = {"INFORMATIONAL": [{"external_id": "gmail/m1", "newsletter_action": "prepare_for_research"}]}
    res = nl.batch_process_newsletters([email], cls, tmp_path)
    assert [r.email_id for r in res["SKIPPED"]] == ["m1"]
