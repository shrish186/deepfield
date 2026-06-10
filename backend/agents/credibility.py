"""Source credibility scoring.

A single flat prior (everything at 0.5) tells the reader nothing. This assigns a
graded, explainable score from several cheap signals available at fetch time —
no extra LLM call:

  • Domain reputation tier — a curated map from "trust first" (peer-reviewed
    journals, gov/health bodies) down to "treat with care" (social media,
    forums, content farms). Academic/PubMed/arXiv scope domains are folded in
    automatically so they always rank high.
  • TLD signal — .gov/.edu/.mil/.int and academic .ac.* get a bump; a bare .org
    a small one.
  • Content richness — a source we actually fetched a full article from is more
    useful than a bare snippet, so longer fetched content nudges the score up;
    an empty fetch nudges it down.

Scores are clamped to [0.2, 0.98]. The aim is a believable *ranking* so the
reader knows what to trust first — not a precise truth claim about any one page.
"""
from __future__ import annotations

from urllib.parse import urlparse

from agents.scopes import SCOPE_DOMAINS

# --- Reputation tiers -------------------------------------------------------
# Base score for a domain (or any parent of it). Most-specific match wins.

# Peer-reviewed journals, primary medical/scientific bodies — fold in every
# curated scope domain (academic + pubmed + arxiv) so they always score high.
_HIGH = {d: 0.92 for d in (SCOPE_DOMAINS["academic"]
                           + SCOPE_DOMAINS["pubmed"]
                           + SCOPE_DOMAINS["arxiv"])}

# Reputable wire services, major outlets, encyclopaedic & clinical references.
_REPUTABLE = {
    "reuters.com": 0.85,
    "apnews.com": 0.85,
    "bbc.com": 0.82,
    "bbc.co.uk": 0.82,
    "npr.org": 0.8,
    "nytimes.com": 0.8,
    "washingtonpost.com": 0.8,
    "theguardian.com": 0.78,
    "economist.com": 0.8,
    "wsj.com": 0.8,
    "ft.com": 0.8,
    "nationalgeographic.com": 0.78,
    "scientificamerican.com": 0.82,
    "mayoclinic.org": 0.85,
    "clevelandclinic.org": 0.82,
    "hopkinsmedicine.org": 0.85,
    "health.harvard.edu": 0.85,
    "britannica.com": 0.78,
    "wikipedia.org": 0.7,
    "ncbi.nlm.nih.gov": 0.92,
}

# General-interest / commercial publishers — fine, but not authoritative.
_MID = {
    "healthline.com": 0.6,
    "webmd.com": 0.62,
    "verywellhealth.com": 0.58,
    "medicalnewstoday.com": 0.6,
    "forbes.com": 0.55,
    "businessinsider.com": 0.5,
    "cnet.com": 0.55,
    "techcrunch.com": 0.55,
    "prevention.com": 0.55,
    "cosmopolitan.com": 0.45,
}

# User-generated, social, forums, content farms — lowest base; useful colour,
# weak as evidence.
_LOW = {
    "youtube.com": 0.3,
    "tiktok.com": 0.25,
    "reddit.com": 0.35,
    "quora.com": 0.3,
    "medium.com": 0.35,
    "substack.com": 0.4,
    "facebook.com": 0.25,
    "instagram.com": 0.25,
    "twitter.com": 0.3,
    "x.com": 0.3,
    "pinterest.com": 0.25,
    "linkedin.com": 0.4,
    "blogspot.com": 0.3,
    "wordpress.com": 0.35,
    "tumblr.com": 0.25,
}

# Merged lookup, most-trusted maps applied last so they win on overlap.
_DOMAIN_SCORES: dict[str, float] = {**_LOW, **_MID, **_REPUTABLE, **_HIGH}

# Default for a domain we have no opinion on — deliberately mid-low so an
# unknown site doesn't masquerade as trustworthy.
_DEFAULT_BASE = 0.5


def _host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _base_for_host(host: str) -> float:
    """Most-specific domain match wins: check the full host, then strip one
    label at a time so a subdomain inherits its parent's score."""
    if not host:
        return _DEFAULT_BASE
    parts = host.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in _DOMAIN_SCORES:
            return _DOMAIN_SCORES[candidate]
    return _DEFAULT_BASE


def _tld_bonus(host: str) -> float:
    if host.endswith((".gov", ".mil", ".int")):
        return 0.08
    if host.endswith(".edu") or ".ac." in host or host.endswith(".ac"):
        return 0.06
    if host.endswith(".org"):
        return 0.02
    return 0.0


def _content_adjust(content: str) -> float:
    """A fetched full article is worth more than a bare snippet."""
    n = len(content or "")
    if n >= 2000:
        return 0.05
    if n >= 500:
        return 0.02
    return -0.05  # empty / stub fetch — we couldn't actually read it


def score_source(url: str, content: str = "") -> float:
    """Graded credibility in [0.2, 0.98] from domain reputation + TLD + how much
    content we actually fetched. Transparent and deterministic — same inputs
    always give the same score."""
    host = _host(url)
    score = _base_for_host(host) + _tld_bonus(host) + _content_adjust(content)
    return round(max(0.2, min(0.98, score)), 2)
