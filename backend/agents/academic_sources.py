"""Dedicated academic-database connectors.

This is what turns Deepfield from "a web search wrapper" into a research tool:
it queries arXiv, PubMed, and Semantic Scholar *directly* — getting real
bibliographic metadata (authors, venue, year, DOI, citation counts) that web
scraping can't reliably give us — and normalises every hit into the same dict
shape Layer 1 stores.

Design rules:
  • Fully fail-soft. Every connector is wrapped so a timeout, a 429, or malformed
    XML returns ``[]`` and the pipeline carries on with whatever else it found.
  • No API keys required. arXiv and PubMed E-utilities are open; Semantic Scholar
    is used on its keyless tier (heavily rate-limited, so treated as a bonus).
  • Short timeouts. We never let a slow scholarly endpoint stall a report.
"""
from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from typing import List, Optional
from urllib.parse import quote_plus

from agents.credibility import score_source

try:  # pragma: no cover - httpx ships with the anthropic SDK
    import httpx
except Exception:  # noqa: BLE001
    httpx = None  # type: ignore

_TIMEOUT = 12.0
_UA = {"User-Agent": "Deepfield-Research/1.0 (academic aggregator)"}


def _norm(
    *,
    url: str,
    title: str,
    abstract: str,
    authors: List[str],
    year: Optional[int],
    venue: Optional[str],
    doi: Optional[str],
    citation_count: Optional[int],
    source_type: str,
    peer_reviewed: bool,
    origin: str,
) -> dict:
    authors_str = "; ".join(a.strip() for a in authors if a and a.strip()) or None
    content = abstract or ""
    return {
        "url": url,
        "title": (title or url).strip(),
        "snippet": (abstract or "")[:400],
        "content": content,
        "authors": authors_str,
        "year": year,
        "venue": venue,
        "doi": doi,
        "citation_count": citation_count,
        "source_type": source_type,
        "peer_reviewed": peer_reviewed,
        "retracted": False,
        "credibility_score": score_source(url, content),
        "origin": origin,
    }


# --- arXiv -----------------------------------------------------------------

_ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


async def fetch_arxiv(query: str, limit: int = 6) -> List[dict]:
    if httpx is None or not query.strip():
        return []
    url = (
        "http://export.arxiv.org/api/query?search_query="
        f"all:{quote_plus(query)}&start=0&max_results={limit}"
        "&sortBy=relevance&sortOrder=descending"
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
    except Exception:  # noqa: BLE001
        return []

    out: List[dict] = []
    for entry in root.findall("a:entry", _ATOM):
        title = (entry.findtext("a:title", default="", namespaces=_ATOM) or "").strip()
        summary = (
            entry.findtext("a:summary", default="", namespaces=_ATOM) or ""
        ).strip()
        link = entry.findtext("a:id", default="", namespaces=_ATOM) or ""
        published = entry.findtext("a:published", default="", namespaces=_ATOM) or ""
        year = None
        if len(published) >= 4 and published[:4].isdigit():
            year = int(published[:4])
        authors = [
            (a.findtext("a:name", default="", namespaces=_ATOM) or "")
            for a in entry.findall("a:author", _ATOM)
        ]
        doi = entry.findtext("arxiv:doi", default=None, namespaces=_ATOM)
        if not title:
            continue
        out.append(
            _norm(
                url=link,
                title=title,
                abstract=summary,
                authors=authors,
                year=year,
                venue="arXiv",
                doi=doi,
                citation_count=None,
                source_type="preprint",
                peer_reviewed=False,
                origin="arxiv",
            )
        )
    return out


# --- Semantic Scholar ------------------------------------------------------


async def fetch_semantic_scholar(query: str, limit: int = 6) -> List[dict]:
    if httpx is None or not query.strip():
        return []
    fields = "title,abstract,year,authors,venue,citationCount,externalIds,url,publicationTypes"
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search?"
        f"query={quote_plus(query)}&limit={limit}&fields={fields}"
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:  # 429 on the keyless tier — skip quietly
                return []
            data = resp.json()
    except Exception:  # noqa: BLE001
        return []

    out: List[dict] = []
    for p in data.get("data", []) or []:
        title = p.get("title") or ""
        if not title:
            continue
        ext = p.get("externalIds") or {}
        doi = ext.get("DOI")
        landing = p.get("url") or (
            f"https://doi.org/{doi}" if doi else "https://www.semanticscholar.org"
        )
        ptypes = p.get("publicationTypes") or []
        peer = bool(p.get("venue")) and "Review" not in (ptypes or [])
        authors = [a.get("name", "") for a in (p.get("authors") or [])]
        out.append(
            _norm(
                url=landing,
                title=title,
                abstract=p.get("abstract") or "",
                authors=authors,
                year=p.get("year"),
                venue=p.get("venue") or None,
                doi=doi,
                citation_count=p.get("citationCount"),
                source_type="journal",
                peer_reviewed=peer,
                origin="semantic_scholar",
            )
        )
    return out


# --- PubMed (NCBI E-utilities) ---------------------------------------------

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


async def fetch_pubmed(query: str, limit: int = 6) -> List[dict]:
    if httpx is None or not query.strip():
        return []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA, follow_redirects=True) as client:
            search = await client.get(
                f"{_EUTILS}/esearch.fcgi",
                params={
                    "db": "pubmed",
                    "term": query,
                    "retmax": limit,
                    "retmode": "json",
                    "sort": "relevance",
                },
            )
            search.raise_for_status()
            ids = (
                search.json().get("esearchresult", {}).get("idlist", []) or []
            )
            if not ids:
                return []
            # Abstracts + rich metadata in one efetch XML call.
            fetch = await client.get(
                f"{_EUTILS}/efetch.fcgi",
                params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
            )
            fetch.raise_for_status()
            root = ET.fromstring(fetch.text)
    except Exception:  # noqa: BLE001
        return []

    out: List[dict] = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        title = "".join(art.find(".//ArticleTitle").itertext()).strip() if art.find(
            ".//ArticleTitle"
        ) is not None else ""
        if not title:
            continue
        abstract = " ".join(
            "".join(node.itertext()).strip()
            for node in art.findall(".//Abstract/AbstractText")
        ).strip()
        journal = art.findtext(".//Journal/Title") or None
        year_txt = (
            art.findtext(".//JournalIssue/PubDate/Year")
            or art.findtext(".//JournalIssue/PubDate/MedlineDate")
            or ""
        )
        year = int(year_txt[:4]) if year_txt[:4].isdigit() else None
        authors = []
        for a in art.findall(".//AuthorList/Author"):
            last = a.findtext("LastName") or ""
            initials = a.findtext("Initials") or ""
            name = f"{last}, {initials}".strip().strip(",").strip()
            if name:
                authors.append(name)
        doi = None
        for idn in art.findall(".//ArticleIdList/ArticleId"):
            if idn.get("IdType") == "doi":
                doi = (idn.text or "").strip() or None
        retracted = any(
            "retract" in (pt.text or "").lower()
            for pt in art.findall(".//PublicationTypeList/PublicationType")
        )
        rec = _norm(
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            title=title,
            abstract=abstract,
            authors=authors,
            year=year,
            venue=journal,
            doi=doi,
            citation_count=None,
            source_type="medical",
            peer_reviewed=True,
            origin="pubmed",
        )
        rec["retracted"] = retracted
        out.append(rec)
    return out


# --- Aggregator ------------------------------------------------------------

# How many results to pull from each connector, per search scope. The matching
# connector dominates a scoped search; a general web search gets a smaller
# scholarly boost across all three.
_PLAN: dict[str, dict[str, int]] = {
    "web": {"arxiv": 4, "semantic_scholar": 5, "pubmed": 4},
    "academic": {"semantic_scholar": 10, "arxiv": 4, "pubmed": 2},
    "pubmed": {"pubmed": 10, "semantic_scholar": 4},
    "arxiv": {"arxiv": 12, "semantic_scholar": 3},
}

_FETCHERS = {
    "arxiv": fetch_arxiv,
    "semantic_scholar": fetch_semantic_scholar,
    "pubmed": fetch_pubmed,
}


async def gather_academic(
    query: str, scope: str = "web", year_min: Optional[int] = None
) -> List[dict]:
    """Run the connectors appropriate for ``scope`` concurrently and return a
    flat, de-duplicated list of normalised academic sources. Never raises."""
    plan = _PLAN.get(scope, _PLAN["web"])
    tasks = [
        _FETCHERS[name](query, limit) for name, limit in plan.items() if name in _FETCHERS
    ]
    if not tasks:
        return []
    try:
        batches = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:  # noqa: BLE001
        return []

    merged: List[dict] = []
    seen_keys: set = set()
    for batch in batches:
        if isinstance(batch, Exception) or not batch:
            continue
        for rec in batch:
            if year_min and rec.get("year") and rec["year"] < year_min:
                continue
            # Dedup on DOI first (most reliable), then normalised title.
            key = (rec.get("doi") or "").lower() or _title_key(rec.get("title", ""))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(rec)
    return merged


def _title_key(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum())[:80]
