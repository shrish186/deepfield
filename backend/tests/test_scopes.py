"""Unit tests for the source-scope helpers (agents/scopes.py)."""
from agents.scopes import (
    ALLOWED_SCOPES,
    SCOPE_DOMAINS,
    SCOPE_LABELS,
    domains_for,
    label_for,
    normalise,
)


def test_normalise_coerces_unknown_to_web():
    assert normalise("web") == "web"
    assert normalise("pubmed") == "pubmed"
    assert normalise("garbage") == "web"
    assert normalise(None) == "web"
    assert normalise("") == "web"


def test_domains_for():
    assert domains_for("web") == []
    assert domains_for("garbage") == []
    assert len(domains_for("pubmed")) > 0
    # Scoped domains come straight from the single source of truth.
    assert domains_for("arxiv") == SCOPE_DOMAINS["arxiv"]


def test_label_for():
    assert label_for("pubmed") == SCOPE_LABELS["pubmed"]
    # Unknown scope falls back to the web label, not a crash.
    assert label_for("garbage") == SCOPE_LABELS["web"]


def test_internal_maps_are_consistent():
    # The three maps must describe the same set of scopes.
    assert ALLOWED_SCOPES == set(SCOPE_DOMAINS)
    assert set(SCOPE_LABELS) == set(SCOPE_DOMAINS)


def test_no_duplicate_domains_within_a_scope():
    for scope, domains in SCOPE_DOMAINS.items():
        assert len(domains) == len(set(domains)), f"duplicate domain in {scope}"
