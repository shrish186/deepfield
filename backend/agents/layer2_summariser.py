"""LAYER 2 — Deep Dives (summariser_agent).

For every source, reads the full content and extracts the core argument plus a
list of atomic key claims with their supporting evidence. Runs in parallel
across all sources. Output: stored Claim rows + per-source summaries in `state`.
"""
from __future__ import annotations

import asyncio
import os
from typing import List

from agents.base import AgentContext, claude_complete, extract_json
from db.database import AsyncSessionLocal
from db.models import Claim, Source

AGENT_NAME = "summariser_agent"
LAYER = 2

# Bound concurrency so we don't hammer the Anthropic API with 30 simultaneous
# calls. The token-rate limiter in base.py is the real guard against per-minute
# limits; this just caps in-flight requests. On tier 2 the limiter has ~16x more
# headroom than it did at tier 1, so we run more reads at once.
_MAX_CONCURRENCY = int(os.getenv("DEEPFIELD_L2_CONCURRENCY", "8"))

# Cap per-source content so a single huge page can't dominate the token budget.
# Tier-2 throughput makes a deeper read affordable: more of each source means
# better-grounded, less-truncated claim extraction.
_MAX_CONTENT_CHARS = int(os.getenv("DEEPFIELD_L2_CONTENT_CHARS", "10000"))

# All the stable task instructions live in the system prompt so they form one
# identical, cacheable prefix across every per-source call in a report (see
# base.claude_complete's cache_system). Only the per-source content varies.
#
# This prompt is deliberately detailed — a worked example plus explicit per-field
# guidance both sharpen extraction quality AND push the prefix past Anthropic's
# 1024-token cache-minimum, so the identical prefix is written once per report and
# read from cache on every subsequent per-source call (lower latency + cost).
# Keep the JSON shape below byte-for-byte in sync with extract_json's consumers.
_SYSTEM = (
    "You are a meticulous research analyst working inside a multi-source deep-"
    "research pipeline. Your job is to read ONE source in isolation and distil it "
    "into a faithful, machine-readable summary that downstream layers will cross-"
    "reference against every other source. Because later layers detect agreement, "
    "contradiction, and evidence gaps purely from your output, precision and "
    "fidelity to the text matter far more than coverage or eloquence. You never "
    "invent claims, never import outside knowledge, and never soften or strengthen "
    "what the source actually says.\n\n"
    "Return ONLY JSON of this exact shape (no prose, no markdown fences):\n"
    "{\n"
    '  "core_argument": "1-3 sentence summary of the source\'s central argument",\n'
    '  "authors": "author names if clearly stated, else null",\n'
    '  "year": publication year as an integer if clearly stated, else null,\n'
    '  "venue": "journal/publisher/outlet name if clearly stated, else null",\n'
    '  "claims": [\n'
    '    {"claim": "one atomic factual claim", "evidence": "the supporting evidence the source gives"}\n'
    "  ]\n"
    "}\n\n"
    "FIELD GUIDANCE\n"
    "- core_argument: Capture the source's central thesis or finding — the thing it "
    "is fundamentally arguing or reporting — not a table of contents. Neutral, "
    "declarative voice. If the source merely surveys others' views without taking a "
    "position, say so plainly.\n"
    "- authors: The people or organisation credited with writing the source. Copy "
    "names as written; do not normalise, reorder, or expand initials. Null if the "
    "text does not plainly state them. A site/brand name in a byline counts only if "
    "it is presented as the author.\n"
    "- year: A four-digit publication year as an integer (e.g. 2021), only when the "
    "text states it. Prefer an explicit publication/updated date over any year that "
    "merely appears inside the body. Null if uncertain; never guess from context.\n"
    "- venue: The journal, publisher, conference, or outlet that published the "
    "source (e.g. \"Nature\", \"The New York Times\", \"NBER Working Paper\"). Null if "
    "not plainly stated. Do not invent a venue from the URL or topic.\n\n"
    "WHAT MAKES A GOOD CLAIM\n"
    "- Atomic: exactly one assertion per claim. Split compound sentences ('X rose "
    "and Y fell') into separate claims.\n"
    "- Self-contained: resolve every pronoun and vague referent so the claim is "
    "intelligible with zero surrounding context. 'It reduced risk by 30%' becomes "
    "'Statin therapy reduced cardiovascular risk by 30% in the studied cohort'.\n"
    "- Checkable: a factual statement someone could in principle verify, not an "
    "opinion, exhortation, or rhetorical flourish.\n"
    "- Specific: preserve quantities, populations, timeframes, and qualifiers "
    "('in mice', 'over 12 weeks', 'among adults over 65') exactly as the source "
    "frames them. Do NOT round away hedges like 'may', 'suggests', or 'associated "
    "with' into hard causation.\n"
    "- Grounded: the matching evidence field must paraphrase the actual support the "
    "source offers for THAT claim — a statistic, a cited study, an experiment, an "
    "expert quote, a mechanism. If the source asserts something with no stated "
    "support, set evidence to \"asserted without stated evidence\".\n\n"
    "RULES\n"
    "- Extract 3-6 atomic claims, prioritising the load-bearing ones the source "
    "most depends on. Fewer high-fidelity claims beat many shallow ones.\n"
    "- Only include claims actually supported by the provided content. If the text "
    "is thin, return fewer claims rather than padding with inferred ones.\n"
    "- Never merge a claim with its counter-argument; if the source presents a "
    "tension, emit both sides as separate claims.\n"
    "- For authors/year/venue: fill them only when the text plainly states them; "
    "when in doubt, use null. A wrong value is worse than null.\n"
    "- If the content is empty or unusable, return an empty claims array and a "
    "best-effort core_argument inferred from the title alone.\n\n"
    "WORKED EXAMPLE\n"
    "Source title: Mediterranean diet and cardiovascular outcomes: a 5-year cohort\n"
    "Source content (excerpt): \"In our prospective study of 7,447 adults aged 55-80 "
    "at high cardiovascular risk, those assigned to a Mediterranean diet "
    "supplemented with extra-virgin olive oil showed a 30% relative reduction in "
    "major cardiovascular events versus the control diet over five years "
    "(Estruch et al., New England Journal of Medicine, 2018). The effect appeared "
    "driven by reduced stroke incidence; effects on myocardial infarction alone did "
    "not reach significance.\"\n"
    "Correct output:\n"
    "{\n"
    '  "core_argument": "A five-year cohort found that a Mediterranean diet with '
    'extra-virgin olive oil substantially lowered major cardiovascular events in '
    'high-risk older adults, mainly by reducing strokes.",\n'
    '  "authors": "Estruch et al.",\n'
    '  "year": 2018,\n'
    '  "venue": "New England Journal of Medicine",\n'
    '  "claims": [\n'
    '    {"claim": "A Mediterranean diet supplemented with extra-virgin olive oil '
    'reduced major cardiovascular events by 30% versus a control diet among '
    'high-risk adults aged 55-80 over five years.", "evidence": "Prospective cohort '
    'of 7,447 high-risk adults reporting a 30% relative risk reduction (Estruch et '
    'al., 2018)."},\n'
    '    {"claim": "The cardiovascular benefit of the Mediterranean diet appeared to '
    'be driven primarily by a reduction in stroke incidence.", "evidence": "Authors '
    'attribute the observed effect mainly to reduced stroke events."},\n'
    '    {"claim": "The Mediterranean diet did not produce a statistically '
    'significant reduction in myocardial infarction on its own.", "evidence": '
    '"Effects on myocardial infarction alone did not reach significance."}\n'
    "  ]\n"
    "}\n"
    "Note how each claim resolves its referents, keeps the source's exact "
    "quantities and hedges, and pairs with the specific evidence the source gave."
)


def _prompt(query: str, title: str, content: str) -> str:
    snippet = content[:_MAX_CONTENT_CHARS] if content else "(no full content available)"
    return f"""Research question: {query}

Source title: {title}
Source content:
\"\"\"
{snippet}
\"\"\"

Read the source and extract its substance as the JSON described in the system instructions."""


async def _process_source(
    ctx: AgentContext, query: str, source: dict, index: int, total: int
) -> List[dict]:
    title = source["title"]
    await ctx.emit(
        LAYER,
        AGENT_NAME,
        f"📝 Deep reading source {index}/{total}: {title[:60]} — extracting key claims...",
    )
    try:
        raw = await claude_complete(
            _prompt(query, title, source.get("content") or source.get("snippet") or ""),
            system=_SYSTEM,
            max_tokens=1500,
        )
        data = extract_json(raw)
    except Exception as exc:  # noqa: BLE001
        await ctx.emit(
            LAYER, AGENT_NAME, f"⚠️ Source {index}/{total} extraction failed: {exc}"
        )
        return []

    core_argument = (data or {}).get("core_argument", "")
    claims = (data or {}).get("claims", []) or []

    stored_claims: List[dict] = []
    async with AsyncSessionLocal() as session:
        # Persist the per-source summary, and backfill bibliographic metadata for
        # web sources (academic connectors already supply it; never overwrite).
        src = await session.get(Source, source["id"])
        if src is not None:
            src.summary = core_argument
            if not src.authors and (data or {}).get("authors"):
                src.authors = str(data["authors"])[:500]
            if not src.year:
                y = (data or {}).get("year")
                try:
                    if y and 1500 <= int(y) <= 2099:
                        src.year = int(y)
                except (TypeError, ValueError):
                    pass
            if not src.venue and (data or {}).get("venue"):
                src.venue = str(data["venue"])[:300]
        for c in claims:
            text = (c or {}).get("claim", "").strip()
            if not text:
                continue
            claim = Claim(
                report_id=ctx.report_id,
                source_id=source["id"],
                claim_text=text,
                confidence_score=0.0,
                support_count=1,
                layer_origin=LAYER,
            )
            session.add(claim)
            stored_claims.append(claim)
        await session.commit()
        for claim in stored_claims:
            await session.refresh(claim)
        result = [
            {
                "id": cl.id,
                "source_id": cl.source_id,
                "claim_text": cl.claim_text,
            }
            for cl in stored_claims
        ]
    return result


async def run(state: dict) -> dict:
    ctx: AgentContext = state["ctx"]
    query: str = state["query"]
    sources: List[dict] = state.get("sources", [])
    total = len(sources)

    await ctx.emit(
        LAYER, AGENT_NAME, f"📝 Deep reading {total} sources in parallel..."
    )

    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def guarded(source: dict, idx: int) -> List[dict]:
        async with sem:
            return await _process_source(ctx, query, source, idx, total)

    results = await asyncio.gather(
        *(guarded(s, i + 1) for i, s in enumerate(sources))
    )

    all_claims: List[dict] = [c for batch in results for c in batch]
    await ctx.emit(
        LAYER,
        AGENT_NAME,
        f"📝 Extracted {len(all_claims)} key claims from {total} sources",
    )

    state["claims"] = all_claims
    return state
