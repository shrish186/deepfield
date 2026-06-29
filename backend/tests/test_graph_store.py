"""Unit tests for the disagreement-graph canonicalization helpers.

These cover the pure, DB-free logic that decides how the graph dedupes and
accumulates — URL normalisation (so the same page collapses to one source),
direction-agnostic pair ordering (so a contradiction is one edge, not two), and
the prior-knowledge markdown formatter that feeds back into synthesis. They also
guard the fail-soft contract of the embeddings client: with no API key, every
call must no-op rather than raise, keeping the whole graph layer optional.
"""
import agents.embeddings as embeddings
from agents.graph_store import (
    _confidence,
    evolution_direction,
    format_grounding,
    format_prior_knowledge,
    gather_grounding,
    normalize_url,
    order_pair,
    search_claims,
)


# --- normalize_url ----------------------------------------------------------

def test_normalize_url_strips_query_fragment_and_trailing_slash():
    base = "https://example.com/path/to/article"
    assert normalize_url(base + "?utm=x&ref=y") == base
    assert normalize_url(base + "#section-2") == base
    assert normalize_url(base + "/") == base
    assert normalize_url(base + "/?a=1#frag") == base


def test_normalize_url_lowercases_host_and_strips_www():
    assert normalize_url("https://WWW.Example.COM/Path") == "https://example.com/Path"
    # Host case folds, but the path is left untouched (paths can be significant).
    assert normalize_url("HTTPS://Example.com/X") == "https://example.com/X"


def test_normalize_url_dedupe_key_is_stable_across_cosmetic_variants():
    a = normalize_url("https://www.nature.com/articles/x")
    b = normalize_url("https://nature.com/articles/x/")
    c = normalize_url("https://nature.com/articles/x?fbclid=123")
    assert a == b == c


def test_normalize_url_handles_empty_and_malformed():
    assert normalize_url("") == ""
    # Malformed input must not raise and must stay deterministic.
    out = normalize_url("not a url at all")
    assert isinstance(out, str)


# --- order_pair -------------------------------------------------------------

def test_order_pair_is_direction_agnostic():
    assert order_pair(7, 3) == (3, 7)
    assert order_pair(3, 7) == (3, 7)
    assert order_pair(3, 7) == order_pair(7, 3)


def test_order_pair_equal_ids():
    assert order_pair(5, 5) == (5, 5)


# --- format_prior_knowledge -------------------------------------------------

def test_format_prior_knowledge_empty_is_blank():
    assert format_prior_knowledge([]) == ""


def test_format_prior_knowledge_renders_claims_and_disagreements():
    claims = [
        {
            "statement": "Creatine is safe for healthy adults.",
            "support_count": 4,
            "report_count": 2,
            "disagreements": [
                {"observed_count": 3, "description": "Kidney-risk findings conflict."}
            ],
        },
        {
            "statement": "Loading doses speed saturation.",
            "support_count": 2,
            "report_count": 1,
            "disagreements": [],
        },
    ]
    md = format_prior_knowledge(claims)
    assert "Creatine is safe for healthy adults." in md
    assert "Loading doses speed saturation." in md
    # Support/report counts surface so the reader gauges weight.
    assert "4 source(s)" in md and "2 report(s)" in md
    # Linked disagreement is shown with its observation count.
    assert "Kidney-risk findings conflict." in md
    assert "seen in 3 report(s)" in md
    # Header counts the recalled claims.
    assert "2 related finding(s)" in md


# --- _confidence ------------------------------------------------------------

def test_confidence_is_monotonic_and_bounded():
    # No evidence → 0; a single source anchors at 0.3; the curve only ever rises
    # toward its ceiling and never goes negative (the old quadratic did both).
    assert _confidence(0) == 0.0
    assert _confidence(1) == 0.3
    prev = -1.0
    for n in range(1, 50):
        c = _confidence(n)
        assert 0.0 <= c <= 0.97
        assert c >= prev  # non-decreasing
        prev = c
    # Saturates near the ceiling for large source counts.
    assert _confidence(40) >= 0.95


# --- evolution_direction ----------------------------------------------------

def test_evolution_direction_needs_two_points():
    assert evolution_direction([]) == "new"
    assert evolution_direction([{"confidence": 0.9}]) == "new"


def test_evolution_direction_strengthening_and_weakening():
    rising = [{"confidence": 0.30}, {"confidence": 0.55}, {"confidence": 0.88}]
    falling = [{"confidence": 0.88}, {"confidence": 0.50}]
    assert evolution_direction(rising) == "strengthening"
    assert evolution_direction(falling) == "weakening"


def test_evolution_direction_stable_within_epsilon():
    # A change smaller than eps counts as stable, not a trend.
    flat = [{"confidence": 0.70}, {"confidence": 0.72}]
    assert evolution_direction(flat) == "stable"


def test_evolution_direction_compares_endpoints_not_dips():
    # Only first vs last matter, so a mid-series dip that recovers is rising.
    series = [{"confidence": 0.30}, {"confidence": 0.20}, {"confidence": 0.85}]
    assert evolution_direction(series) == "strengthening"


# --- search_claims fail-soft ------------------------------------------------

async def test_search_claims_noop_without_embedding():
    # No embedding (no Voyage key upstream) → empty result, no DB access. We pass
    # None for the session too: the guard must short-circuit before touching it.
    assert await search_claims(None, None) == []


# --- gather_grounding / format_grounding (Explore mode) ---------------------

async def test_gather_grounding_noop_without_embedding():
    # No embedding → empty, is_empty=True, and never touches the session, so the
    # Explore mode falls back to a plain answer.
    g = await gather_grounding(None, None)
    assert g["is_empty"] is True
    assert g["claims"] == [] and g["disagreements"] == []
    assert g["markdown"] == ""


def test_format_grounding_empty_is_blank():
    assert format_grounding([], []) == ""


def test_format_grounding_renders_claims_and_disagreements():
    claims = [
        {
            "statement": "Creatine is safe for healthy adults",
            "support_count": 5,
            "report_count": 3,
            "confidence": 0.9,
            "sources": [
                {"domain": "nih.gov", "credibility": 0.95, "stance": "supports"},
            ],
        }
    ]
    disagreements = [
        {
            "observed_count": 4,
            "description": "kidney risk in susceptible individuals",
            "a": "Creatine is safe for healthy adults",
            "b": "Creatine may stress compromised kidneys",
        }
    ]
    md = format_grounding(claims, disagreements)
    assert "ESTABLISHED CLAIMS" in md
    assert "5 source(s) across 3 report(s)" in md
    assert "RECORDED DISAGREEMENTS" in md
    assert "seen in 4 report(s)" in md
    assert "Side A:" in md and "Side B:" in md
    assert "nih.gov" in md


# --- embeddings fail-soft ---------------------------------------------------

async def test_embeddings_noop_without_key(monkeypatch):
    # No key configured: the client must never initialise and calls return
    # empty/None so the graph layer silently skips rather than crashing.
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.setattr(embeddings, "_clients", {})
    monkeypatch.setattr(embeddings, "_warned", False)

    assert embeddings.has_embeddings() is False
    assert await embeddings.embed_texts(["anything"]) == []
    assert await embeddings.embed_query("anything") is None


async def test_embed_texts_empty_input_is_noop(monkeypatch):
    # Even with a key, an empty batch shouldn't call the API.
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key-not-used")
    monkeypatch.setattr(embeddings, "_clients", {})
    assert await embeddings.embed_texts([]) == []
