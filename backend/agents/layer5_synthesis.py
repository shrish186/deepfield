"""LAYER 5 — Structured Report Generation (synthesis_agent).

Consumes the outputs of all four prior layers and emits the final report with
the exact required sections:
  1. Executive Summary       2. Key Findings (confidence-rated)
  3. Conflicts & Uncertainties   4. Open Questions & Gaps
  5. Sources (title, url, credibility, key claim)

Sections are persisted to `report_sections`. The Executive Summary and Key
Findings are LLM-authored from the confidence map; the remaining sections are
assembled deterministically from the structured data the earlier layers stored.
"""
from __future__ import annotations

from typing import List

from sqlalchemy import select

from agents.base import AgentContext, claude_complete, extract_json
from db.database import AsyncSessionLocal
from db.models import Claim, ReportSection, Source

AGENT_NAME = "synthesis_agent"
LAYER = 5

_SYSTEM = (
    "You are a senior research editor. You write tight, confidence-aware "
    "research summaries grounded strictly in the provided claims. You never "
    "overstate certainty for weakly-supported claims. You write for a general "
    "reader in plain language and NEVER cite internal claim numbers or ids."
)


def _findings_prompt(
    query: str, claim_map: List[dict], context: str = "", prior_md: str = ""
) -> str:
    lines = []
    for e in sorted(claim_map, key=lambda x: x["confidence"], reverse=True):
        lines.append(
            f'- ({e["confidence"]:.2f} confidence, {e["support_count"]} source(s)) {e["canonical"]}'
        )
    body = "\n".join(lines)
    context_block = (
        f"This is a follow-up in an ongoing research conversation. Background:\n"
        f"{context}\n\nAnswer the new question with that context in mind.\n\n"
        if context
        else ""
    )
    # Prior knowledge accumulated by earlier reports in the disagreement graph.
    # Use it to ground and contextualise the answer, not to override the fresh
    # evidence below.
    prior_block = (
        f"Established context from prior research (treat as background, defer to "
        f"the fresh claims below where they conflict):\n{prior_md}\n\n"
        if prior_md
        else ""
    )
    return f"""{prior_block}{context_block}Research question: {query}

Confidence-ranked claims:
{body}

Write the report's opening. Return ONLY JSON:
{{
  "executive_summary": "3-5 sentence executive summary answering the research question, calibrated to the evidence",
  "key_findings": [
    {{"finding": "a key finding", "confidence": "High|Medium|Low"}}
  ],
  "evidence_test": [
    "a specific, concrete piece of evidence or result that — if it existed — would meaningfully change or overturn the current conclusion"
  ]
}}

Produce 5-8 key findings, ordered most-to-least confident. Confidence label must
reflect how many sources back the finding (>=3 sources High, 2 Medium, 1 Low).

For evidence_test, give 2-4 items. Each must name a concrete, falsifiable thing
(e.g. "a large randomized controlled trial showing X", "replication failures of
the key study Y") — NOT vague calls for 'more research'. This is what tells a
reader how robust the conclusion really is."""


async def run(state: dict) -> dict:
    ctx: AgentContext = state["ctx"]
    query: str = state["query"]
    context: str = state.get("context") or ""
    claim_map: List[dict] = state.get("claim_map", [])
    conflicts: List[dict] = state.get("conflicts", [])
    gaps_all: List[dict] = state.get("gaps", [])
    prior_md: str = (state.get("prior_knowledge") or {}).get("markdown", "")

    await ctx.emit(LAYER, AGENT_NAME, "✅ Generating final structured report...")

    gaps = [g for g in gaps_all if g["kind"] == "gap"]
    open_qs = [g for g in gaps_all if g["kind"] == "open_question"]

    # 1 + 2: LLM-authored summary and findings.
    exec_summary = ""
    key_findings: List[dict] = []
    evidence_test: List[str] = []
    if claim_map:
        try:
            raw = await claude_complete(
                _findings_prompt(query, claim_map, context, prior_md),
                system=_SYSTEM,
                max_tokens=2000,
            )
            data = extract_json(raw) or {}
            exec_summary = data.get("executive_summary", "")
            key_findings = data.get("key_findings", []) or []
            evidence_test = [e for e in (data.get("evidence_test") or []) if e]
        except Exception as exc:  # noqa: BLE001
            await ctx.emit(LAYER, AGENT_NAME, f"⚠️ Summary generation failed: {exc}")

    # Build markdown for each section.
    findings_md = "\n".join(
        f'- **[{f.get("confidence", "?")}]** {f.get("finding", "")}'
        for f in key_findings
    ) or "_No findings extracted._"

    if conflicts:
        conflicts_md = "\n".join(
            f'- {c["description"]}' for c in conflicts
        )
    else:
        conflicts_md = "_No direct contradictions detected across sources._"

    parts = []
    if gaps:
        parts.append(
            "**Gaps (unexplained):**\n"
            + "\n".join(f"- {g['description']}" for g in gaps)
        )
    if open_qs:
        parts.append(
            "**Open questions:**\n"
            + "\n".join(f"- {g['description']}" for g in open_qs)
        )
    open_questions_md = "\n\n".join(parts) or "_No open questions or gaps flagged._"

    # "What would change this conclusion" — the robustness test. Concrete,
    # falsifiable evidence that would move the needle, so the reader can judge
    # how settled the answer really is.
    evidence_test_md = (
        "\n".join(f"- {e}" for e in evidence_test)
        or "_No decisive evidence test identified._"
    )

    # 5: Sources section — title, url, credibility, bibliographic metadata, top
    # extracted claim (claim-level attribution: which source said what).
    async with AsyncSessionLocal() as session:
        src_rows = (
            await session.execute(
                select(Source).where(Source.report_id == ctx.report_id)
            )
        ).scalars().all()

        sources_lines = []
        for s in src_rows:
            top_claim = (
                await session.execute(
                    select(Claim)
                    .where(Claim.source_id == s.id)
                    .order_by(Claim.confidence_score.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            key_claim = top_claim.claim_text if top_claim else (s.summary or "")
            tags = []
            if s.peer_reviewed:
                tags.append("peer-reviewed")
            elif s.source_type == "preprint":
                tags.append("preprint")
            if s.retracted:
                tags.append("⚠️ RETRACTED")
            meta_bits = []
            if s.authors:
                first = s.authors.split(";")[0].strip()
                meta_bits.append(f"{first} et al." if ";" in s.authors else first)
            if s.year:
                meta_bits.append(str(s.year))
            if s.venue:
                meta_bits.append(s.venue)
            if s.citation_count is not None:
                meta_bits.append(f"{s.citation_count} citations")
            meta_str = " · ".join(meta_bits)
            tag_str = f" _({', '.join(tags)})_" if tags else ""
            head = f"- **[{s.title}]({s.url})**{tag_str}"
            if meta_str:
                head += f"\n  - {meta_str}"
            head += f"\n  - Key claim: {key_claim}"
            sources_lines.append(head)
        sources_md = "\n".join(sources_lines) or "_No sources stored._"

        # Persist all sections. The prior-knowledge card (position -1) sorts
        # above the answer when the graph had relevant context to offer.
        sections = [
            ("executive_summary", exec_summary or "_No summary generated._", 0),
            ("key_findings", findings_md, 1),
            ("evidence_test", evidence_test_md, 2),
            ("conflicts", conflicts_md, 3),
            ("open_questions", open_questions_md, 4),
            ("sources", sources_md, 5),
        ]
        if prior_md:
            sections.append(("prior_knowledge", prior_md, -1))
        for section_type, content, position in sections:
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
        LAYER,
        AGENT_NAME,
        f"✅ Report complete — {len(key_findings)} key findings, "
        f"{len(conflicts)} conflicts flagged, {len(open_qs)} open questions identified",
    )

    state["sections"] = {
        "executive_summary": exec_summary,
        "key_findings": key_findings,
    }
    return state
