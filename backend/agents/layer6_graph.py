"""LAYER 6 — Graph Contribution (graph_writer).

Runs after Layer 4, before synthesis. This is where the disagreement graph
actually *accumulates*: it takes the Layer-3 canonical claim map and the Layer-4
contradictions — which until now were computed and thrown away at the end of
every run — and writes them into the global, cross-report graph.

For each canonical cluster it embeds the statement (one batched Voyage call),
upserts a canonical claim (merging into a semantically-equivalent existing one
when close enough), and links every backing source as evidence. It then maps
each report-local Conflict onto the matching pair of canonical claims and
upserts a contradiction edge — so the *same* disagreement found across two
independent reports collapses to one edge with ``observed_count`` 2.

Fail-soft: no Voyage key, an empty claim map, or any error → the layer no-ops
with a feed notice and the report finishes normally.
"""
from __future__ import annotations

from typing import Dict, List

from sqlalchemy import func, select

from agents.base import AgentContext
from agents.embeddings import embed_texts, has_embeddings
from agents.graph_store import (
    link_evidence,
    record_snapshot,
    upsert_canonical_claim,
    upsert_canonical_source,
    upsert_disagreement,
)
from db.database import AsyncSessionLocal
from db.models import CanonicalClaim, ClaimLink, Source

AGENT_NAME = "graph_writer"
LAYER = 6


async def run(state: dict) -> dict:
    ctx: AgentContext = state["ctx"]
    claim_map: List[dict] = state.get("claim_map", [])
    conflicts: List[dict] = state.get("conflicts", [])
    state.setdefault("graph_contributed", {"claims": 0, "disagreements": 0})

    if not has_embeddings() or not claim_map:
        return state

    try:
        await ctx.emit(
            LAYER, AGENT_NAME, "🧠 Contributing findings to the disagreement graph..."
        )

        statements = [c.get("canonical", "") for c in claim_map]
        embeddings = await embed_texts(statements)
        if len(embeddings) != len(statements):
            await ctx.emit(
                LAYER, AGENT_NAME, "🧠 Graph step skipped — embeddings unavailable"
            )
            return state

        new_claims = 0
        new_links = 0
        async with AsyncSessionLocal() as session:
            # Index this report's sources so cluster source_ids resolve to URLs.
            src_rows = (
                await session.execute(
                    select(Source).where(Source.report_id == ctx.report_id)
                )
            ).scalars().all()
            src_by_id = {s.id: s for s in src_rows}

            # report-local claim id -> canonical claim node.
            member_to_canonical: Dict[int, CanonicalClaim] = {}
            # Distinct canonical claims this report touched (several local
            # clusters can merge into one), so we snapshot each exactly once.
            touched: Dict[int, CanonicalClaim] = {}

            for cluster, embedding in zip(claim_map, embeddings):
                claim = await upsert_canonical_claim(
                    session, cluster.get("canonical", ""), embedding, ctx.report_id
                )
                if claim is None:
                    continue
                new_claims += 1
                for sid in cluster.get("source_ids", []):
                    src = src_by_id.get(sid)
                    if src is None:
                        continue
                    csrc = await upsert_canonical_source(
                        session, src.url, src.title, src.credibility_score
                    )
                    await link_evidence(session, claim, csrc, ctx.report_id)
                touched[claim.id] = claim
                for mid in cluster.get("member_claim_ids", []):
                    member_to_canonical[mid] = claim

            # One evolution point per claim per report, recorded after all of
            # this report's evidence is attached so support_count is final.
            for claim in touched.values():
                await record_snapshot(session, claim, ctx.report_id)

            for conf in conflicts:
                a = member_to_canonical.get(conf.get("claim_a_id"))
                b = member_to_canonical.get(conf.get("claim_b_id"))
                if a is None or b is None:
                    continue
                link = await upsert_disagreement(
                    session, a.id, b.id, conf.get("description", ""), ctx.report_id
                )
                if link is not None:
                    new_links += 1

            await session.commit()

            total_claims = (
                await session.execute(select(func.count()).select_from(CanonicalClaim))
            ).scalar() or 0
            total_links = (
                await session.execute(select(func.count()).select_from(ClaimLink))
            ).scalar() or 0

        await ctx.emit(
            LAYER,
            AGENT_NAME,
            f"🧠 Contributed {new_claims} claim(s) / {new_links} disagreement(s) — "
            f"graph now holds {total_claims} claims, {total_links} disagreements",
        )
        state["graph_contributed"] = {"claims": new_claims, "disagreements": new_links}
    except Exception as exc:  # noqa: BLE001
        await ctx.emit(LAYER, AGENT_NAME, f"⚠️ Graph contribution skipped: {exc}")

    return state
