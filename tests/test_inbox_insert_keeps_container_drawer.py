"""A new capture goes below the `* Inbox` heading's property drawer, not above it.

Inserting right after the heading line moved the container's :ID: drawer under
the new capture's body. The capture then carried the container's ID wherever it
was filed (daily_news.org, research_learning.org, inbox_archive.org), and one ID
ended up in 21 places across 0-personal. The duplicate makes every
org_workspace_adapter `move` out of the inbox refuse to load, so the nightly
inbox run could route nothing for weeks (2026-10-30).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processors.newsletter import insert_under_inbox

HEAD = "#+TITLE: Inbox\n\n* Inbox\n"
DRAWER = "  :PROPERTIES:\n  :ID: container-id\n  :END:\n"
OLD = "** TODO older capture\n"
NEW = "** TODO new capture :research:\nbody line\n"


def test_capture_goes_below_the_container_drawer():
    out = insert_under_inbox(HEAD + DRAWER + OLD, NEW)
    assert out == HEAD + DRAWER + NEW + OLD


def test_container_without_a_drawer_still_takes_the_capture_first():
    assert insert_under_inbox(HEAD + OLD, NEW) == HEAD + NEW + OLD


def test_no_inbox_heading_returns_none():
    assert insert_under_inbox("#+TITLE: x\n* Other\n", NEW) is None
