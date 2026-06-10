"""Unit tests for the source credibility scorer (agents/credibility.py).

These guard the *ranking* behaviour users see in the Sources list — a flat 0.5
for everything was the bug that prompted this scorer, so the key assertions are
about relative order and the curated tiers, not exact magic numbers.
"""
from agents.credibility import score_source
from agents.scopes import SCOPE_DOMAINS


def test_tiers_rank_in_the_expected_order():
    # Same fetched content so only the domain reputation differs.
    c = "x" * 1500
    tiktok = score_source("https://www.tiktok.com/@a/video/1", c)
    youtube = score_source("https://www.youtube.com/watch?v=1", c)
    reddit = score_source("https://www.reddit.com/r/x/comments/1", c)
    unknown = score_source("https://some-random-blog.example/post", c)
    wikipedia = score_source("https://en.wikipedia.org/wiki/X", c)
    journal = score_source("https://www.nature.com/articles/x", c)
    gov = score_source("https://www.cdc.gov/x", c)

    # Social / UGC sit below an unknown commercial site.
    assert tiktok < unknown
    assert youtube < unknown
    assert reddit < unknown
    # Reputable reference beats unknown; authoritative beats reputable.
    assert unknown < wikipedia < journal
    assert journal >= 0.9 and gov >= 0.9


def test_scores_are_clamped_to_range():
    urls = [
        "https://www.tiktok.com/@a",
        "https://www.nature.com/x",
        "https://pubmed.ncbi.nlm.nih.gov/1",
        "https://whatever.test/page",
        "not-even-a-url",
    ]
    for u in urls:
        for content in ("", "x" * 5000):
            s = score_source(u, content)
            assert 0.2 <= s <= 0.98, f"{u!r} -> {s} out of range"


def test_subdomain_inherits_parent_score():
    # pmc.* and the bare ncbi host should both land in the high tier.
    assert score_source("https://pmc.ncbi.nlm.nih.gov/articles/PMC1", "x" * 1500) >= 0.9
    # A wikipedia language subdomain inherits wikipedia.org's reputation.
    en = score_source("https://en.wikipedia.org/wiki/X", "x" * 1500)
    bare = score_source("https://wikipedia.org/wiki/X", "x" * 1500)
    assert en == bare


def test_every_curated_scope_domain_scores_high():
    # The scorer folds in academic/pubmed/arxiv scope domains; if scopes.py
    # gains a domain that the scorer doesn't trust, this fails loudly.
    for scope in ("academic", "pubmed", "arxiv"):
        for domain in SCOPE_DOMAINS[scope]:
            s = score_source(f"https://{domain}/some/article", "x" * 1500)
            assert s >= 0.9, f"{domain} ({scope}) scored only {s}"


def test_content_richness_is_monotonic_for_one_domain():
    # Thresholds: <500 chars is treated as a stub (penalised), >=500 a small
    # bonus, >=2000 a larger one. Pick lengths that cross each band.
    url = "https://www.prevention.com/article"
    stub = score_source(url, "")           # empty fetch -> penalised
    medium = score_source(url, "x" * 800)  # >= 500 -> small bonus
    long = score_source(url, "x" * 3000)   # >= 2000 -> larger bonus
    assert stub < medium < long


def test_tld_bonus_and_www_stripping_and_bad_url():
    # .gov gets a bump over a comparable non-gov unknown.
    gov = score_source("https://example.gov/report", "x" * 1500)
    com = score_source("https://example.com/report", "x" * 1500)
    assert gov > com
    # Leading www. must not change the domain match.
    assert score_source("https://www.nature.com/x", "x" * 1500) == score_source(
        "https://nature.com/x", "x" * 1500
    )
    # A malformed URL must not raise and must stay in range.
    s = score_source("not a url at all", "")
    assert 0.2 <= s <= 0.98
