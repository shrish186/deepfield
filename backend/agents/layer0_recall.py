"""LAYER 0 — Prior-Knowledge Recall (recall_agent).

Runs *before* the search sweep. Embeds the research question and asks the
disagreement graph what earlier reports already established about this topic —
the related canonical claims, how well-supported they are, and where prior
research found them contested. That structured memory is written to
``state["prior_knowledge"]`` for the synthesis layer to fold into its answer.

Entirely fail-soft: if no Voyage key is configured, the graph is empty, or
anything errors, the layer quietly leaves ``prior_knowledge`` empty and the
pipeline proceeds exactly as it did before the graph existed.
"""
from __future__ import annotations

from agents.base import AgentContext
from agents.embeddings import embed_query, has_embeddings
from agents.graph_store import recall_prior_knowledge
from db.database import AsyncSessionLocal

AGENT_NAME = "recall_agent"
LAYER = 0


async def run(state: dict) -> dict:
    ctx: AgentContext = state["ctx"]
    query: str = state["query"]
    state.setdefault("prior_knowledge", {"claims": [], "markdown": ""})

    if not has_embeddings():
        return state

    try:
        embedding = await embed_query(query)
        if embedding is None:
            return state
        async with AsyncSessionLocal() as session:
            prior = await recall_prior_knowledge(session, embedding)
        state["prior_knowledge"] = prior
        n = len(prior.get("claims", []))
        if n:
            await ctx.emit(
                LAYER,
                AGENT_NAME,
                f"🧠 Recalled {n} related claim(s) from prior research",
            )
    except Exception as exc:  # noqa: BLE001
        await ctx.emit(LAYER, AGENT_NAME, f"⚠️ Prior-knowledge recall skipped: {exc}")

    return state
