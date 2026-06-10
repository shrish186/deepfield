"""Both search paths dedupe Tavily results before persisting. They must drop
duplicate and empty URLs while preserving first-seen order."""
import pytest

from agents.layer1_search import _dedupe as dedupe_deep
from pipeline.basic import _dedupe as dedupe_basic


@pytest.mark.parametrize("dedupe", [dedupe_deep, dedupe_basic])
def test_drops_duplicates_preserving_order(dedupe):
    results = [
        {"url": "https://a.test", "title": "first"},
        {"url": "https://b.test", "title": "second"},
        {"url": "https://a.test", "title": "dupe of first"},
        {"url": "https://c.test", "title": "third"},
    ]
    out = dedupe(results)
    assert [r["url"] for r in out] == [
        "https://a.test",
        "https://b.test",
        "https://c.test",
    ]
    # First-seen wins — the later duplicate is discarded, not merged.
    assert out[0]["title"] == "first"


@pytest.mark.parametrize("dedupe", [dedupe_deep, dedupe_basic])
def test_drops_missing_and_empty_urls(dedupe):
    results = [
        {"url": "https://a.test"},
        {"url": ""},
        {"title": "no url key"},
        {"url": None},
    ]
    out = dedupe(results)
    assert [r.get("url") for r in out] == ["https://a.test"]


@pytest.mark.parametrize("dedupe", [dedupe_deep, dedupe_basic])
def test_empty_input(dedupe):
    assert dedupe([]) == []
