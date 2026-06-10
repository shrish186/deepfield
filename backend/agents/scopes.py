"""Source-scope definitions shared by the deep and basic search paths.

A "scope" constrains the Tavily search to a curated set of domains so a user can
research against academic literature instead of the open web. `web` (the default)
applies no restriction and preserves the original behaviour.

Note on Google Scholar: deliberately omitted. Scholar is a search *index*, not
fetchable content — filtering to scholar.google.com returns almost nothing
useful. The `academic` and `pubmed` scopes cover the same intent with real,
retrievable sources.
"""
from __future__ import annotations

from typing import Dict, List

# Ordered so the UI can render them predictably. Keys are the stored values.
SCOPE_DOMAINS: Dict[str, List[str]] = {
    "web": [],  # no restriction — general web + news
    "academic": [
        "nature.com",
        "science.org",
        "sciencedirect.com",
        "springer.com",
        "link.springer.com",
        "onlinelibrary.wiley.com",
        "plos.org",
        "journals.plos.org",
        "cell.com",
        "pnas.org",
        "jamanetwork.com",
        "nejm.org",
        "thelancet.com",
        "bmj.com",
        "academic.oup.com",
        "frontiersin.org",
        "mdpi.com",
        "semanticscholar.org",
    ],
    "pubmed": [
        "pubmed.ncbi.nlm.nih.gov",
        "ncbi.nlm.nih.gov",
        "pmc.ncbi.nlm.nih.gov",
        "nih.gov",
        "who.int",
        "cochranelibrary.com",
        "medlineplus.gov",
        "cdc.gov",
    ],
    "arxiv": [
        "arxiv.org",
        "biorxiv.org",
        "medrxiv.org",
        "ssrn.com",
        "papers.ssrn.com",
        "osf.io",
    ],
}

# Human-readable labels (also used in streamed status messages).
SCOPE_LABELS: Dict[str, str] = {
    "web": "All sources",
    "academic": "Academic journals",
    "pubmed": "PubMed / medical",
    "arxiv": "arXiv / preprints",
}

ALLOWED_SCOPES = set(SCOPE_DOMAINS)


def normalise(scope: str | None) -> str:
    """Coerce an arbitrary input to a known scope, defaulting to ``web``."""
    return scope if scope in ALLOWED_SCOPES else "web"


def domains_for(scope: str | None) -> List[str]:
    """Return the include-domains list for a scope (empty list = unrestricted)."""
    return SCOPE_DOMAINS.get(normalise(scope), [])


def label_for(scope: str | None) -> str:
    return SCOPE_LABELS.get(normalise(scope), SCOPE_LABELS["web"])
