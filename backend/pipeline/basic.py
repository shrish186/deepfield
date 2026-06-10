"""BASIC mode — a quick, cheap, single-pass research answer.

Where the deep pipeline runs five cooperating agents on the Sonnet model, basic
mode does the minimum that still counts as *research*: one web sweep, then one
synthesis pass on the cheaper Haiku model. It produces a clear, conversational
answer with a short list of takeaways and the sources it leaned on — no claim
extraction, cross-referencing, or conflict analysis.

It writes the same `report_sections` rows the deep report uses (executive_summary
+ key_findings + sources) so the existing report UI renders it unchanged.
"""
from __future__ import annotations

import os
from typing import List

from tavily import AsyncTavilyClient

from agents.base import (
    AgentContext,
    BASIC_MODEL,
    build_search_query,
    claude_complete,
    extract_json,
)
from agents.academic_sources import gather_academic
from agents.embeddings import embed_query, has_embeddings
from agents.graph_store import recall_prior_knowledge
from agents.layer1_search import _credibility_prior, _split_domains, _domain_blocked, _host
from agents.metadata import classify_source
from agents.scopes import domains_for, label_for, normalise
from db.database import AsyncSessionLocal
from db.models import ReportSection, Source

_SYSTEM = (
    "You are a sharp, trustworthy research assistant. You answer the user's "
    "question directly and honestly using ONLY the provided sources. You write "
    "in plain, friendly language a busy person can skim in under a minute. You "
    "never invent facts, never cite internal numbers, and you are upfront when "
    "the sources are thin or disagree."
)


def _prompt(
    query: str, sources: List[dict], context: str = "", prior_md: str = ""
) -> str:
    blocks = []
    for i, s in enumerate(sources, 1):
        text = (s.get("snippet") or s.get("content") or "")[:1200]
        blocks.append(f"[Source {i}] {s.get('title')}\n{text}")
    body = "\n\n".join(blocks) or "(no sources found)"
    context_block = (
        f"This is a follow-up in an ongoing conversation. Background:\n{context}\n\n"
        if context
        else ""
    )
    prior_block = (
        f"Established context from prior research (background only — defer to "
        f"the sources below where they conflict):\n{prior_md}\n\n"
        if prior_md
        else ""
    )
    return f"""{prior_block}{context_block}Question: {query}

Here is what the web search turned up:

{body}

Write a concise, easy-to-read answer. Return ONLY JSON of this exact shape:
{{
  "answer": "2-4 short sentences that directly answer the question in plain language. Lead with the bottom line.",
  "key_points": ["a short, scannable takeaway", "another", "3-5 total, each one line"]
}}

Rules:
- Ground every statement in the sources above. If they don't cover something,
  say so plainly rather than guessing.
- No jargon, no source numbers, no hedging filler. Write like you're explaining
  it to a smart friend."""


def _dedupe(results: List[dict]) -> List[dict]:
    seen, unique = set(), []
    for r in results:
        url = r.get("url")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)
    return unique


async def run_basic(
    ctx: AgentContext,
    query: str,
    context: str = "",
    source_scope: str = "web",
    year_min=None,
    include_domains=None,
    exclude_domains=None,
) -> None:
    """Quick single-pass answer. Mirrors the deep pipeline's section output so the
    report view renders identically, just lighter."""
    await ctx.emit(0, "basic_agent", "⚡ Basic mode — quick search + answer")

    # Basic mode *consumes* the disagreement graph but never contributes to it
    # (it extracts no claim map). Recall prior knowledge so the quick answer is
    # still grounded in what earlier deep reports established. Fail-soft.
    prior_md = ""
    if has_embeddings():
        try:
            emb = await embed_query(query)
            if emb is not None:
                async with AsyncSessionLocal() as session:
                    prior = await recall_prior_knowledge(session, emb)
                prior_md = prior.get("markdown", "")
                if prior.get("claims"):
                    await ctx.emit(
                        0,
                        "basic_agent",
                        f"🧠 Recalled {len(prior['claims'])} related claim(s) from "
                        f"prior research (basic mode reads the graph but doesn't add to it)",
                    )
        except Exception as exc:  # noqa: BLE001
            await ctx.emit(0, "basic_agent", f"⚠️ Prior-knowledge recall skipped: {exc}")

    scope = normalise(source_scope)
    include_user = _split_domains(include_domains)
    exclude_user = _split_domains(exclude_domains)
    tavily_include = (domains_for(scope) or []) + include_user

    # --- 1. One web sweep + a small academic-database boost.
    if scope == "web":
        await ctx.emit(1, "basic_agent", "🔍 Searching the web + academic databases...")
    else:
        await ctx.emit(1, "basic_agent", f"🔍 Searching {label_for(scope)} via dedicated databases...")
    # Fold the thread topic into follow-up searches so a vague follow-up doesn't
    # pull unrelated sources. Original query is kept for the answer prompt.
    search_query = await build_search_query(query, context)

    try:
        academic = await gather_academic(search_query, scope, year_min=year_min)
    except Exception:  # noqa: BLE001
        academic = []
    academic = academic[:5]  # basic mode stays light

    client = AsyncTavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    results: List[dict] = []
    try:
        web = await client.search(
            query=search_query,
            search_depth="advanced",
            max_results=8,
            include_raw_content=True,
            include_domains=tavily_include or None,
        )
        results = web.get("results", [])
    except Exception as exc:  # noqa: BLE001
        await ctx.emit(1, "basic_agent", f"⚠️ Search error: {exc}")

    unique = _dedupe(results)

    # Broaden to the open web if a scoped corpus turned up nothing.
    if scope != "web" and not unique and not academic:
        try:
            fb = await client.search(
                query=search_query,
                search_depth="advanced",
                max_results=8,
                include_raw_content=True,
            )
            unique = _dedupe(fb.get("results", []))
        except Exception as exc:  # noqa: BLE001
            await ctx.emit(1, "basic_agent", f"⚠️ Search error: {exc}")

    # Normalise web rows into the academic metadata shape.
    web_norm = []
    for r in unique:
        url = r.get("url", "")
        content = r.get("raw_content") or r.get("content") or ""
        meta = classify_source(url, r.get("title") or "", content)
        web_norm.append(
            {
                "url": url, "title": r.get("title") or url,
                "snippet": r.get("content") or "", "content": content,
                "credibility_score": _credibility_prior(url, content),
                "authors": None, "year": meta["year"], "venue": None,
                "doi": meta["doi"], "citation_count": None,
                "source_type": meta["source_type"],
                "peer_reviewed": meta["peer_reviewed"], "retracted": meta["retracted"],
            }
        )

    # Merge academic + web, filter, cap.
    merged, seen = [], set()
    for rec in academic + web_norm:
        url = rec.get("url") or ""
        host = _host(url)
        if not url or url in seen:
            continue
        if exclude_user and _domain_blocked(host, exclude_user):
            continue
        if year_min and rec.get("year") and rec["year"] < year_min:
            continue
        seen.add(url)
        merged.append(rec)
    merged.sort(key=lambda r: (r.get("peer_reviewed", False), r.get("credibility_score", 0)), reverse=True)
    merged = merged[:10]

    sources: List[dict] = []
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
            sources.append(src)
        await session.commit()
        for src in sources:
            await session.refresh(src)
        source_dicts = [
            {
                "id": s.id,
                "url": s.url,
                "title": s.title,
                "snippet": s.snippet,
                "content": s.content,
                "credibility_score": s.credibility_score,
            }
            for s in sources
        ]

    n_peer = sum(1 for s in merged if s.get("peer_reviewed"))
    await ctx.emit(
        1, "basic_agent",
        f"🔍 Read {len(source_dicts)} sources ({n_peer} peer-reviewed, {len(academic)} from academic databases)",
    )

    # --- 2. One cheap synthesis pass on Haiku.
    await ctx.emit(5, "basic_agent", "✍️ Writing a clear answer...")
    answer, key_points = "", []
    try:
        raw = await claude_complete(
            _prompt(query, source_dicts, context, prior_md),
            system=_SYSTEM,
            max_tokens=1200,
            model=BASIC_MODEL,
        )
        data = extract_json(raw) or {}
        answer = (data.get("answer") or "").strip()
        key_points = data.get("key_points") or []
    except Exception as exc:  # noqa: BLE001
        await ctx.emit(5, "basic_agent", f"⚠️ Answer generation failed: {exc}")

    findings_md = "\n".join(f"- {p}" for p in key_points if p) or ""
    sources_md = (
        "\n".join(
            f"- **[{s['title']}]({s['url']})** — credibility "
            f"{s['credibility_score']:.2f}"
            for s in source_dicts
        )
        or "_No sources found._"
    )

    async with AsyncSessionLocal() as session:
        rows = [
            ("executive_summary", answer or "_Couldn't generate an answer._", 0),
        ]
        if findings_md:
            rows.append(("key_findings", findings_md, 1))
        rows.append(("sources", sources_md, 4))
        if prior_md:
            rows.append(("prior_knowledge", prior_md, -1))
        for section_type, content, position in rows:
            session.add(
                ReportSection(
                    report_id=ctx.report_id,
                    section_type=section_type,
                    content=content,
                    position=position,
                )
            )
        await session.commit()

    await ctx.emit(
        5,
        "basic_agent",
        f"⚡ Answer ready — {len(key_points)} key points from "
        f"{len(source_dicts)} sources",
    )
