"""LAYER 1 — Breadth Sweep (search_agent).

Pulls sources from two complementary channels and merges them:
  • Tavily across web + news (broad coverage, fast).
  • Dedicated academic databases — arXiv, PubMed, Semantic Scholar — via the
    connectors in ``academic_sources``, which return real bibliographic metadata
    (authors, venue, year, DOI, citations) web scraping can't.

Every stored source carries trust metadata (source_type, peer_reviewed, etc.).
Power-user filters (date floor, domain allow/blocklist) are applied here so the
downstream layers only ever see in-scope evidence. Output: stored source dicts
in `state`.
"""
from __future__ import annotations

import os
from typing import List, Optional
from urllib.parse import urlparse

from tavily import AsyncTavilyClient

from agents.academic_sources import gather_academic
from agents.base import AgentContext, build_search_query
from agents.credibility import score_source
from agents.metadata import classify_source
from agents.scopes import domains_for, label_for, normalise
from db.database import AsyncSessionLocal
from db.models import Source

AGENT_NAME = "search_agent"
LAYER = 1

# Keep the total source count bounded so Layer 2 (which reads each source with an
# LLM) stays within a sane token/time budget. Academic + high-credibility first.
_MAX_SOURCES = 30


def _credibility_prior(url: str, content: str = "") -> float:
    """Graded credibility from domain reputation, TLD, and fetched content
    richness. See agents.credibility for the signals and tiers."""
    return score_source(url, content)


async def _tavily_search() -> AsyncTavilyClient:
    return AsyncTavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


def _host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        host = ""
    return host[4:] if host.startswith("www.") else host


def _split_domains(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [d.strip().lower().lstrip("@") for d in raw.replace("\n", ",").split(",") if d.strip()]


def _domain_blocked(host: str, blocklist: List[str]) -> bool:
    return any(host == b or host.endswith("." + b) for b in blocklist)


def _dedupe(results: List[dict]) -> List[dict]:
    """Drop duplicate URLs, preserving first-seen order."""
    seen, unique = set(), []
    for r in results:
        url = r.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(r)
    return unique


async def run(state: dict) -> dict:
    ctx: AgentContext = state["ctx"]
    query: str = state["query"]
    context: str = state.get("context") or ""
    scope = normalise(state.get("source_scope"))
    year_min: Optional[int] = state.get("year_min")
    include_user = _split_domains(state.get("include_domains"))
    exclude_user = _split_domains(state.get("exclude_domains"))

    scope_include = domains_for(scope)
    # User allowlist narrows further (union with scope so a scoped corpus still
    # works); when only a user allowlist is given it becomes the restriction.
    tavily_include = (scope_include or []) + include_user

    filt_bits = []
    if year_min:
        filt_bits.append(f"since {year_min}")
    if include_user:
        filt_bits.append(f"only {', '.join(include_user)}")
    if exclude_user:
        filt_bits.append(f"excluding {', '.join(exclude_user)}")
    filt_note = f" ({'; '.join(filt_bits)})" if filt_bits else ""

    if scope == "web":
        await ctx.emit(
            LAYER, AGENT_NAME,
            f"🔍 Searching the web, news, and academic databases (arXiv · PubMed · Semantic Scholar){filt_note}...",
        )
    else:
        await ctx.emit(
            LAYER, AGENT_NAME,
            f"🔍 Searching {label_for(scope)} via dedicated databases{filt_note}...",
        )

    search_query = await build_search_query(query, context)

    # --- Channel A: dedicated academic databases (rich metadata) ----------
    try:
        academic = await gather_academic(search_query, scope, year_min=year_min)
    except Exception as exc:  # noqa: BLE001
        await ctx.emit(LAYER, AGENT_NAME, f"⚠️ Academic database error: {exc}")
        academic = []
    if academic:
        from collections import Counter

        by_origin = Counter(a["origin"] for a in academic)
        nice = ", ".join(
            f"{n} from {ORIGIN_LABELS.get(o, o)}" for o, n in by_origin.items()
        )
        await ctx.emit(LAYER, AGENT_NAME, f"🎓 Retrieved {len(academic)} papers ({nice})")

    # --- Channel B: Tavily web + news -------------------------------------
    client = await _tavily_search()
    web_results: List[dict] = []
    try:
        web = await client.search(
            query=search_query,
            search_depth="advanced",
            max_results=20,
            include_raw_content=True,
            include_domains=tavily_include or None,
        )
        web_results.extend(web.get("results", []))
    except Exception as exc:  # noqa: BLE001
        await ctx.emit(LAYER, AGENT_NAME, f"⚠️ Web search error: {exc}")

    if scope == "web" and not include_user:
        try:
            news = await client.search(
                query=search_query,
                topic="news",
                max_results=10,
                include_raw_content=True,
            )
            web_results.extend(news.get("results", []))
        except Exception as exc:  # noqa: BLE001
            await ctx.emit(LAYER, AGENT_NAME, f"⚠️ News search error: {exc}")

    web_unique = _dedupe(web_results)

    # Fallback: a scoped corpus that came back empty (and no academic hits)
    # broadens to the open web so the user never gets a blank report.
    if scope != "web" and not web_unique and not academic:
        try:
            fb = await client.search(
                query=search_query, search_depth="advanced",
                max_results=20, include_raw_content=True,
            )
            web_unique = _dedupe(fb.get("results", []))
        except Exception as exc:  # noqa: BLE001
            await ctx.emit(LAYER, AGENT_NAME, f"⚠️ Web search error: {exc}")

    # Normalise Tavily rows into the same metadata shape as academic rows.
    web_norm: List[dict] = []
    for r in web_unique:
        url = r.get("url", "")
        content = r.get("raw_content") or r.get("content") or ""
        meta = classify_source(url, r.get("title") or "", content)
        web_norm.append(
            {
                "url": url,
                "title": r.get("title") or url,
                "snippet": r.get("content") or "",
                "content": content,
                "authors": None,
                "year": meta["year"],
                "venue": None,
                "doi": meta["doi"],
                "citation_count": None,
                "source_type": meta["source_type"],
                "peer_reviewed": meta["peer_reviewed"],
                "retracted": meta["retracted"],
                "credibility_score": _credibility_prior(url, content),
                "origin": "web",
            }
        )

    # --- Merge, filter, rank ---------------------------------------------
    # Academic first (richest, most trustworthy), then web; dedup across both on
    # host+path and DOI; apply exclude-list + year floor.
    merged: List[dict] = []
    seen_urls: set = set()
    seen_dois: set = set()
    for rec in academic + web_norm:
        url = rec.get("url") or ""
        host = _host(url)
        if not url:
            continue
        if exclude_user and _domain_blocked(host, exclude_user):
            continue
        if year_min and rec.get("year") and rec["year"] < year_min:
            continue
        path_key = (host, urlparse(url).path.rstrip("/"))
        if path_key in seen_urls:
            continue
        doi = (rec.get("doi") or "").lower()
        if doi and doi in seen_dois:
            continue
        seen_urls.add(path_key)
        if doi:
            seen_dois.add(doi)
        merged.append(rec)

    # Rank: peer-reviewed/credibility first so the cap keeps the best evidence.
    merged.sort(
        key=lambda r: (r.get("peer_reviewed", False), r.get("credibility_score", 0)),
        reverse=True,
    )
    merged = merged[:_MAX_SOURCES]

    # --- Persist ----------------------------------------------------------
    stored: List[dict] = []
    async with AsyncSessionLocal() as session:
        for r in merged:
            src = Source(
                report_id=ctx.report_id,
                url=r["url"],
                title=r["title"],
                snippet=r.get("snippet") or "",
                content=r.get("content") or "",
                credibility_score=r["credibility_score"],
                source_type=r.get("source_type", "web"),
                authors=r.get("authors"),
                year=r.get("year"),
                venue=r.get("venue"),
                doi=r.get("doi"),
                citation_count=r.get("citation_count"),
                peer_reviewed=bool(r.get("peer_reviewed")),
                retracted=bool(r.get("retracted")),
            )
            session.add(src)
            stored.append((src, r))
        await session.commit()
        source_dicts = []
        for src, r in stored:
            await session.refresh(src)
            source_dicts.append(
                {
                    "id": src.id,
                    "url": src.url,
                    "title": src.title,
                    "snippet": src.snippet,
                    "content": src.content,
                    "credibility_score": src.credibility_score,
                    "source_type": src.source_type,
                    "authors": src.authors,
                    "year": src.year,
                    "venue": src.venue,
                    "doi": src.doi,
                    "citation_count": src.citation_count,
                    "peer_reviewed": src.peer_reviewed,
                    "origin": r.get("origin", "web"),
                }
            )

    n_peer = sum(1 for s in source_dicts if s["peer_reviewed"])
    await ctx.emit(
        LAYER,
        AGENT_NAME,
        f"🔍 Assembled {len(source_dicts)} sources — {n_peer} peer-reviewed, "
        f"{len(academic)} from academic databases",
    )

    state["sources"] = source_dicts
    return state


ORIGIN_LABELS = {
    "arxiv": "arXiv",
    "pubmed": "PubMed",
    "semantic_scholar": "Semantic Scholar",
    "web": "the web",
}
