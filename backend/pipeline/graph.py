"""The 5-layer LangGraph chain — the heart of Deepfield.

Each layer is a node. Edges run them strictly in order, and because all nodes
read and write the same shared `PipelineState`, every layer's output is the next
layer's input:

    recall → search → summarise → crossref → conflict → graph → synthesis

    Layer 0 writes  state["prior_knowledge"]  ← consumed by Layer 5
    Layer 1 writes  state["sources"]          ← consumed by Layer 2
    Layer 2 writes  state["claims"]           ← consumed by Layer 3
    Layer 3 writes  state["claim_map"]        ← consumed by Layer 4, 5 & 6
    Layer 4 writes  state["conflicts"/"gaps"] ← consumed by Layer 5 & 6
    Layer 6 contributes claim_map + conflicts to the global disagreement graph
    Layer 5 writes  state["sections"]         ← the final report
"""
from __future__ import annotations

import asyncio
from typing import Any, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agents import (
    layer0_recall,
    layer1_search,
    layer2_summariser,
    layer3_crossref,
    layer4_conflict,
    layer5_synthesis,
    layer6_graph,
)
from agents.base import AgentContext, make_emit
from api.websocket import manager
from db.database import AsyncSessionLocal
from db.models import Report


class PipelineState(TypedDict, total=False):
    report_id: int
    query: str
    context: Optional[str]
    source_scope: str
    year_min: Optional[int]
    include_domains: Optional[str]
    exclude_domains: Optional[str]
    ctx: AgentContext
    prior_knowledge: dict
    sources: List[dict]
    claims: List[dict]
    claim_map: List[dict]
    conflicts: List[dict]
    gaps: List[dict]
    graph_contributed: dict
    sections: Any


def _build_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("layer0_recall", layer0_recall.run)
    graph.add_node("layer1_search", layer1_search.run)
    graph.add_node("layer2_summarise", layer2_summariser.run)
    graph.add_node("layer3_crossref", layer3_crossref.run)
    graph.add_node("layer4_conflict", layer4_conflict.run)
    graph.add_node("layer6_graph", layer6_graph.run)
    graph.add_node("layer5_synthesis", layer5_synthesis.run)

    graph.add_edge(START, "layer0_recall")
    graph.add_edge("layer0_recall", "layer1_search")
    graph.add_edge("layer1_search", "layer2_summarise")
    graph.add_edge("layer2_summarise", "layer3_crossref")
    graph.add_edge("layer3_crossref", "layer4_conflict")
    graph.add_edge("layer4_conflict", "layer6_graph")
    graph.add_edge("layer6_graph", "layer5_synthesis")
    graph.add_edge("layer5_synthesis", END)

    return graph.compile()


# Compiled once at import; reused across reports.
COMPILED_GRAPH = _build_graph()

# A run that hasn't finished in this many seconds is almost certainly wedged
# (a hung upstream call, a stalled layer). Fail it loudly rather than letting
# the report spin forever — the UI then shows a clean "didn't finish" state.
PIPELINE_TIMEOUT_SECONDS = 600


async def _set_status(report_id: int, status: str) -> None:
    async with AsyncSessionLocal() as session:
        report = await session.get(Report, report_id)
        if report is not None:
            report.status = status
            await session.commit()


async def run_pipeline(
    report_id: int,
    query: str,
    context: Optional[str] = None,
    mode: str = "deep",
    source_scope: str = "web",
    year_min: Optional[int] = None,
    include_domains: Optional[str] = None,
    exclude_domains: Optional[str] = None,
) -> None:
    """Execute a report. Designed to be launched as a background task; it owns
    the report's status lifecycle and the WS feed.

    `mode` selects the engine: "deep" runs the full 5-layer chain on Sonnet;
    "basic" runs one quick search + synthesis pass on the cheaper Haiku model.
    `context` carries follow-up background (prior question / the finding the user
    drilled into) so synthesis can answer in conversation."""
    emit = make_emit(report_id)
    ctx = AgentContext(report_id=report_id, emit=emit)

    await _set_status(report_id, "running")
    if mode == "chat":
        await emit(0, "orchestrator", "💬 Chat started")
    elif mode == "basic":
        await emit(0, "orchestrator", "🚀 Basic research started")
    else:
        await emit(0, "orchestrator", "🚀 Deepfield pipeline started — 5 layers queued")

    initial: PipelineState = {
        "report_id": report_id,
        "query": query,
        "context": context,
        "source_scope": source_scope,
        "year_min": year_min,
        "include_domains": include_domains,
        "exclude_domains": exclude_domains,
        "ctx": ctx,
    }

    try:
        if mode == "chat":
            # Lazy import keeps everything but a single LLM call off the chat path.
            from pipeline.chat import run_chat

            await asyncio.wait_for(
                run_chat(ctx, query, context or ""),
                timeout=PIPELINE_TIMEOUT_SECONDS,
            )
        elif mode == "basic":
            # Lazy import keeps the heavy LangGraph graph off the basic path.
            from pipeline.basic import run_basic

            await asyncio.wait_for(
                run_basic(
                    ctx, query, context or "", source_scope,
                    year_min, include_domains, exclude_domains,
                ),
                timeout=PIPELINE_TIMEOUT_SECONDS,
            )
        else:
            # Disable LangGraph's recursion cap concerns; fixed 5-step chain.
            await asyncio.wait_for(
                COMPILED_GRAPH.ainvoke(initial, config={"recursion_limit": 50}),
                timeout=PIPELINE_TIMEOUT_SECONDS,
            )
        await _set_status(report_id, "completed")
        await emit(0, "orchestrator", "🏁 Research complete")
    except asyncio.TimeoutError:
        await _set_status(report_id, "failed")
        await emit(
            0,
            "orchestrator",
            f"❌ Pipeline timed out after {PIPELINE_TIMEOUT_SECONDS // 60} minutes",
        )
    except Exception as exc:  # noqa: BLE001
        await _set_status(report_id, "failed")
        await emit(0, "orchestrator", f"❌ Pipeline failed: {exc}")
    finally:
        await manager.mark_complete(report_id)
