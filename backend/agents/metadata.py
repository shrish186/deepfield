"""Bibliographic classification for sources.

Turns a bare URL (plus optional title/content) into the trust metadata a
researcher actually reasons about — is this peer-reviewed or a blog? a preprint
or a clinical body? what year? — using cheap, deterministic signals at fetch
time. No LLM call. Academic connectors (academic_sources.py) supply richer
metadata directly; this fills the gaps for general web/Tavily results and
normalises everything into the same shape.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from agents.scopes import SCOPE_DOMAINS

# Domain → source_type. Most-specific parent wins (same matching as credibility).
_PREPRINT = {d: "preprint" for d in SCOPE_DOMAINS["arxiv"]}
_MEDICAL = {d: "medical" for d in SCOPE_DOMAINS["pubmed"]} | {
    "mayoclinic.org": "medical",
    "clevelandclinic.org": "medical",
    "hopkinsmedicine.org": "medical",
    "health.harvard.edu": "medical",
}
_JOURNAL = {d: "journal" for d in SCOPE_DOMAINS["academic"]}
_NEWS = {
    d: "news"
    for d in (
        "reuters.com",
        "apnews.com",
        "bbc.com",
        "bbc.co.uk",
        "npr.org",
        "nytimes.com",
        "washingtonpost.com",
        "theguardian.com",
        "economist.com",
        "wsj.com",
        "ft.com",
        "nationalgeographic.com",
        "businessinsider.com",
        "forbes.com",
    )
}

# Journal/preprint/medical sources are the "peer-reviewed or primary" tier.
_TYPE_MAP: dict[str, str] = {**_NEWS, **_MEDICAL, **_PREPRINT, **_JOURNAL}

_RETRACTION_RE = re.compile(
    r"\b(retracted|retraction|this article has been withdrawn|expression of concern)\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


def _host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        host = ""
    return host[4:] if host.startswith("www.") else host


def _type_for_host(host: str) -> Optional[str]:
    if not host:
        return None
    parts = host.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in _TYPE_MAP:
            return _TYPE_MAP[candidate]
    # TLD fallbacks: .edu/.ac.* lean academic, .gov leans medical/primary.
    if host.endswith(".edu") or ".ac." in host:
        return "journal"
    if host.endswith(".gov"):
        return "medical"
    return None


def classify_type(url: str) -> str:
    """Best-effort source kind from the URL alone: journal | preprint | medical
    | news | web."""
    return _type_for_host(_host(url)) or "web"


def is_peer_reviewed(source_type: str) -> bool:
    """Journals and primary medical bodies are treated as peer-reviewed; a
    preprint explicitly is NOT (that's the whole point of flagging it)."""
    return source_type in ("journal", "medical")


def detect_retraction(title: str = "", content: str = "") -> bool:
    """Heuristic retraction flag. A real retraction database (Retraction Watch /
    Crossref) is future work; this catches the common in-text markers so an
    obviously-withdrawn paper is surfaced rather than silently trusted."""
    head = f"{title}\n{(content or '')[:1500]}"
    return bool(_RETRACTION_RE.search(head))


def extract_year(*texts: str) -> Optional[int]:
    """Pull the most recent plausible publication year from any of the texts."""
    years: list[int] = []
    for t in texts:
        if not t:
            continue
        years.extend(int(m) for m in _YEAR_RE.findall(t[:4000]))
    if not years:
        return None
    # Prefer the most recent year that isn't in the future.
    plausible = [y for y in years if y <= 2099]
    return max(plausible) if plausible else None


def extract_doi(*texts: str) -> Optional[str]:
    for t in texts:
        if not t:
            continue
        m = _DOI_RE.search(t)
        if m:
            return m.group(0).rstrip(".,;)")
    return None


def classify_source(url: str, title: str = "", content: str = "") -> dict:
    """Full classification bundle for a general (non-connector) source."""
    stype = classify_type(url)
    return {
        "source_type": stype,
        "peer_reviewed": is_peer_reviewed(stype),
        "retracted": detect_retraction(title, content),
        "year": extract_year(title, content),
        "doi": extract_doi(content, url),
    }
