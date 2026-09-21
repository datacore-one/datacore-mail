"""A newsletter with no article link is skipped, not an error.

2026-09-06/07: six to eight such mails a night put "errors=8" in the
Completed line and a Winston alert every morning, for mail the pipeline
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
