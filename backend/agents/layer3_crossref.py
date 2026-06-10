"""LAYER 3 — Cross-Reference Synthesis (crossref_agent).

Semantically clusters the atomic claims from Layer 2 so that the same assertion
phrased differently across sources collapses into one canonical claim. The
number of *distinct sources* backing a cluster drives its confidence score:
appears-in-many = high confidence, appears-once = low confidence.

Output: a `claim_map` of canonical claims with member claim ids + supporting
source ids, and updated confidence_score / support_count on the Claim rows.
"""
from __future__ import annotations

from typing import Dict, List

from agents.base import AgentContext, claude_complete, extract_json
from db.database import AsyncSessionLocal
from db.models import Claim

AGENT_NAME = "crossref_agent"
LAYER = 3

_SYSTEM = (
    "You are a research synthesist. You group atomic claims that assert the "
    "same thing (even if worded differently) and keep genuinely different "
    "claims apart. You judge by meaning, not wording."
)


def _prompt(query: str, claims: List[dict]) -> str:
    lines = "\n".join(
        f'  [{c["id"]}] (source {c["source_id"]}) {c["claim_text"]}' for c in claims
    )
    return f"""Research question: {query}

Here are atomic claims extracted from many sources. Each is tagged [claim_id] (source source_id).

{lines}

Group claims that make the SAME assertion (semantic equivalence, not keyword overlap).
A claim asserting the opposite of another must NOT be grouped with it.

Return ONLY JSON of this exact shape:
{{
  "clusters": [
    {{
      "canonical": "a clear one-sentence statement of the shared claim",
      "member_ids": [list of claim_id integers that belong to this cluster]
    }}
  ]
}}

Every claim_id must appear in exactly one cluster. Singletons (claims that match no other) get their own cluster."""


def _confidence(distinct_sources: int) -> float:
    # Saturating curve: 1 src -> 0.3, 2 -> 0.55, 3 -> 0.7, 4 -> 0.8, 5+ -> ~0.9+
    if distinct_sources <= 1:
        return 0.3
    return min(0.97, 0.3 + 0.2 * (distinct_sources - 1) - 0.02 * (distinct_sources - 1) ** 2 + 0.15)


async def run(state: dict) -> dict:
    ctx: AgentContext = state["ctx"]
    query: str = state["query"]
    claims: List[dict] = state.get("claims", [])
    sources: List[dict] = state.get("sources", [])

    await ctx.emit(
        LAYER,
        AGENT_NAME,
        f"🔗 Cross-referencing {len(claims)} claims across {len(sources)} sources...",
    )

    if not claims:
        state["claim_map"] = []
        return state

    by_id = {c["id"]: c for c in claims}

    try:
        # Clustering 100+ claims yields a large JSON map; give it generous room
        # so the response isn't truncated mid-object (which would force the
        # singleton fallback and wipe out all cross-source corroboration).
        raw = await claude_complete(
            _prompt(query, claims), system=_SYSTEM, max_tokens=16000
        )
        clusters = (extract_json(raw) or {}).get("clusters", [])
    except Exception as exc:  # noqa: BLE001
        await ctx.emit(LAYER, AGENT_NAME, f"⚠️ Clustering failed, treating claims as singletons: {exc}")
        clusters = [{"canonical": c["claim_text"], "member_ids": [c["id"]]} for c in claims]

    claim_map: List[dict] = []
    updates: Dict[int, dict] = {}  # claim_id -> {confidence, support}

    for cluster in clusters:
        member_ids = [mid for mid in cluster.get("member_ids", []) if mid in by_id]
        if not member_ids:
            continue
        source_ids = {by_id[mid]["source_id"] for mid in member_ids}
        distinct = len(source_ids)
        conf = _confidence(distinct)
        entry = {
            "canonical": cluster.get("canonical", by_id[member_ids[0]]["claim_text"]),
            "member_claim_ids": member_ids,
            "source_ids": sorted(s for s in source_ids if s is not None),
            "support_count": distinct,
            "confidence": round(conf, 2),
        }
        claim_map.append(entry)
        for mid in member_ids:
            updates[mid] = {"confidence": conf, "support": distinct}

    # Persist confidence + support back onto each Claim.
    async with AsyncSessionLocal() as session:
        for cid, vals in updates.items():
            claim = await session.get(Claim, cid)
            if claim is not None:
                claim.confidence_score = round(vals["confidence"], 2)
                claim.support_count = vals["support"]
                claim.layer_origin = LAYER
        await session.commit()

    high = sum(1 for e in claim_map if e["support_count"] >= 2)
    await ctx.emit(
        LAYER,
        AGENT_NAME,
        f"🔗 Built confidence map: {len(claim_map)} distinct claims, "
        f"{high} corroborated by multiple sources",
    )

    state["claim_map"] = claim_map
    return state
