"""LAYER 4 — Conflict + Gap Detection (conflict_agent).

The most valuable layer. Using the canonical claim map from Layer 3, it asks
Claude to reason *semantically* about the body of claims and surface:
  (a) direct contradictions between sources,
  (b) gaps — things no source explains,
  (c) open questions the research raises but does not answer.

This is explicitly NOT keyword matching: the LLM compares the meaning of claims
to find disagreements, including subtle ones.

Output: persisted Conflict + Gap rows, and `conflicts` / `gaps` in `state`.
"""
from __future__ import annotations

import re
from typing import Dict, List

from agents.base import AgentContext, claude_complete, extract_json
from db.database import AsyncSessionLocal
from db.models import Conflict, Gap

AGENT_NAME = "conflict_agent"
LAYER = 4

# Safety net for stray internal references the model may leave in human-readable
# text. The prompt is the primary fix (it asks for plain prose); this only strips
# the *enclosed* forms — "(claims 415, 416)", "[#357 ↔ #352]", a trailing "#123"
# — which can be removed without harming the surrounding sentence grammar.
_CLAIM_REF_ENCLOSED = re.compile(
    r"\s*[\(\[]\s*(?:claims?\s*)?#?\d+(?:\s*(?:,|and|&|↔|vs\.?)\s*#?\d+)*\s*[\)\]]",
    re.IGNORECASE,
)
_CLAIM_REF_HASH = re.compile(r"\s*#\d+")


def _clean(text: str) -> str:
    cleaned = _CLAIM_REF_ENCLOSED.sub("", text or "")
    cleaned = _CLAIM_REF_HASH.sub("", cleaned)
    # Tidy up doubled spaces / stranded punctuation left behind.
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
    return cleaned.strip()

def _clean_topic(text: str) -> str:
    """Tidy a short controversy label: strip claim refs, collapse whitespace, drop
    a trailing period, and cap length so it reads as a heading not a sentence."""
    t = _clean(text or "")
    t = t.rstrip(".").strip()
    return t[:120]


_SYSTEM = (
    "You are an adversarial research auditor. Your job is to find where sources "
    "disagree and where the collective research is silent. You compare claims "
    "by meaning. You do not manufacture conflicts that aren't real. You write "
    "for a general reader: plain, clear language with NO internal reference "
    "numbers, claim ids, or jargon."
)


def _prompt(query: str, claim_map: List[dict]) -> str:
    lines = []
    for e in claim_map:
        srcs = ", ".join(str(s) for s in e["source_ids"]) or "?"
        lines.append(
            f'  [claims {e["member_claim_ids"]}] (sources {srcs}, '
            f'support={e["support_count"]}): {e["canonical"]}'
        )
    body = "\n".join(lines)
    return f"""Research question: {query}

Below is the full set of canonical claims gathered from all sources, tagged with
the claim ids and source ids that back each one:

{body}

Analyze the claims SEMANTICALLY (by meaning, not keywords). Produce:

1. CONTRADICTIONS: the DISTINCT controversies in this body of research — the
   genuinely separate axes on which sources disagree.
2. GAPS: important aspects of the research question that NO claim addresses or
   explains. Be concrete about what is missing.
3. OPEN_QUESTIONS: questions this body of research raises but does not answer.

CRITICAL — CONSOLIDATE the contradictions (this is the most important rule):
- Identify only the genuinely DISTINCT disagreements. Most research has just
  2–5 real controversies, not a dozen.
- Do NOT list the same disagreement multiple times with different wording or
  different example studies. If three claims all bear on "does X work better
  than Y," that is ONE controversy — merge them into a single entry whose
  description names the strongest evidence on each side.
- Each entry must be a DIFFERENT axis of disagreement from every other entry.
- Give each one a short "topic" label (2–6 words, e.g. "Mechanism beyond
  calorie deficit", "Weight-loss advantage", "Cardiovascular effects").
- Pick claim_a_id and claim_b_id as the single clearest claim representing each
  opposing side (these ids are for internal linking only). The two claims you
  pick must genuinely oppose each other.

How to write every "description":
- Write for a curious general reader, in clear plain English.
- State what the sources actually say, e.g. "One line of research finds X,
  while other studies conclude the opposite — Y."
- NEVER write claim ids or numbers in the description (no "Claim 765", no
  "claim 602", no "#357"). Describe the substance, not the bookkeeping.

Return ONLY JSON of this exact shape:
{{
  "contradictions": [
    {{"topic": "2-6 word controversy label", "claim_a_id": int, "claim_b_id": int, "description": "plain-language explanation of what the two sides disagree on, with no claim numbers"}}
  ],
  "gaps": [
    {{"description": "a specific thing no source explains, in plain language"}}
  ],
  "open_questions": [
    {{"description": "a question raised but unanswered, in plain language"}}
  ]
}}

If a category is genuinely empty, return an empty list for it."""


async def run(state: dict) -> dict:
    ctx: AgentContext = state["ctx"]
    query: str = state["query"]
    claim_map: List[dict] = state.get("claim_map", [])

    await ctx.emit(
        LAYER,
        AGENT_NAME,
        f"⚠️ Hunting for contradictions and gaps across {len(claim_map)} claims...",
    )

    if not claim_map:
        state["conflicts"] = []
        state["gaps"] = []
        return state

    # Valid claim ids for sanitising LLM references.
    valid_ids = set()
    for e in claim_map:
        valid_ids.update(e["member_claim_ids"])

    try:
        raw = await claude_complete(
            _prompt(query, claim_map), system=_SYSTEM, max_tokens=3000, temperature=0.3
        )
        data = extract_json(raw) or {}
    except Exception as exc:  # noqa: BLE001
        await ctx.emit(LAYER, AGENT_NAME, f"⚠️ Conflict analysis failed: {exc}")
        state["conflicts"] = []
        state["gaps"] = []
        return state

    contradictions = data.get("contradictions", []) or []
    gaps = data.get("gaps", []) or []
    open_qs = data.get("open_questions", []) or []

    stored_conflicts: List[dict] = []
    stored_gaps: List[dict] = []

    # Belt-and-suspenders dedup: even with the consolidation prompt, the model
    # occasionally restates one controversy. Drop entries whose topic (or, absent
    # a topic, whose opposing claim pair) we've already stored this run.
    seen_topics: set = set()
    seen_pairs: set = set()

    async with AsyncSessionLocal() as session:
        for c in contradictions:
            a = c.get("claim_a_id")
            b = c.get("claim_b_id")
            desc = _clean(c.get("description") or "")
            if not desc:
                continue
            topic = _clean_topic(c.get("topic") or "")
            tkey = topic.lower()
            a_valid = a if a in valid_ids else None
            b_valid = b if b in valid_ids else None
            pkey = tuple(sorted(x for x in (a_valid, b_valid) if x is not None))
            if tkey and tkey in seen_topics:
                continue
            if pkey and pkey in seen_pairs:
                continue
            if tkey:
                seen_topics.add(tkey)
            if pkey:
                seen_pairs.add(pkey)
            conflict = Conflict(
                report_id=ctx.report_id,
                claim_a_id=a_valid,
                claim_b_id=b_valid,
                topic=topic or None,
                description=desc,
            )
            session.add(conflict)
            stored_conflicts.append(conflict)

        for g in gaps:
            desc = _clean(g.get("description") or "")
            if not desc:
                continue
            row = Gap(report_id=ctx.report_id, description=desc, kind="gap")
            session.add(row)
            stored_gaps.append(row)

        for q in open_qs:
            desc = _clean(q.get("description") or "")
            if not desc:
                continue
            row = Gap(report_id=ctx.report_id, description=desc, kind="open_question")
            session.add(row)
            stored_gaps.append(row)

        await session.commit()
        for row in stored_conflicts + stored_gaps:
            await session.refresh(row)

    # Stream the headline findings — this is the "wow" moment in the feed.
    for c in stored_conflicts:
        head = f"{c.topic} — " if c.topic else ""
        await ctx.emit(
            LAYER, AGENT_NAME, f"⚠️ Conflict detected: {head}{c.description[:160]}"
        )
    for g in stored_gaps:
        icon = "🕳️ Gap" if g.kind == "gap" else "❓ Open question"
        await ctx.emit(LAYER, AGENT_NAME, f"{icon}: {g.description[:140]}")

    await ctx.emit(
        LAYER,
        AGENT_NAME,
        f"⚠️ Detection complete: {len(stored_conflicts)} conflicts, "
        f"{sum(1 for g in stored_gaps if g.kind == 'gap')} gaps, "
        f"{sum(1 for g in stored_gaps if g.kind == 'open_question')} open questions",
    )

    state["conflicts"] = [
        {
            "id": c.id,
            "claim_a_id": c.claim_a_id,
            "claim_b_id": c.claim_b_id,
            "topic": c.topic,
            "description": c.description,
        }
        for c in stored_conflicts
    ]
    state["gaps"] = [
        {"id": g.id, "description": g.description, "kind": g.kind}
        for g in stored_gaps
    ]
    return state
