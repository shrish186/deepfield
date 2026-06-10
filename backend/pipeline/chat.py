"""EXPLORE mode — a fast, conversational research partner grounded in the graph.

Where deep mode runs a five-agent swarm and basic mode does one web sweep, Explore
does no new web research at all. Instead it answers *from what Deepfield already
knows*: it embeds the question, pulls the related canonical claims, their backing
evidence (sources + credibility), and the recorded disagreements between them out
of the accumulated disagreement graph, then has the fast Haiku model answer
grounded in that material — citing how many sources back a claim and how often a
disagreement has recurred.

This is the mode that makes the graph *feel* like an asset: you can interrogate
the accumulated knowledge conversationally ("why is creatine controversial?",
"what's the strongest evidence against the consensus?") and get an answer rooted
in real prior findings rather than a generic LLM riff.

It stays honest about its limits:
  • When the graph has nothing relevant, it falls back to a plain, helpful answer
    from general knowledge and *offers a Deep report* to actually research it.
  • Generated reasoning (e.g. "what would change the conclusion") is presented as
    inference, not as a stored fact.

It writes one ``executive_summary`` section, so the existing report view renders
it unchanged. Fail-soft throughout: no Voyage key / empty graph just means the
plain-answer path, never an error.
"""
from __future__ import annotations

from agents.base import AgentContext, BASIC_MODEL, claude_complete
from agents.embeddings import embed_query
from agents.graph_store import gather_grounding
from db.database import AsyncSessionLocal
from db.models import ReportSection

_SYSTEM_GROUNDED = (
    "You are Deepfield's research partner. Deepfield maintains a growing graph of "
    "scientific claims, the evidence backing them, and the disagreements between "
    "them — accumulated from every report users have run. You are given the slice "
    "of that graph relevant to the user's question.\n\n"
    "Answer grounded in that material. When you state something the graph "
    "establishes, cite it concretely — how many sources back it and across how "
    "many reports, and how many times a disagreement has recurred (e.g. \"5 "
    "sources across 3 reports\", \"this contradiction has shown up in 4 "
    "reports\"). Lead with the bottom line. Surface the genuine disagreements "
    "rather than papering over them — that's the whole point.\n\n"
    "Be rigorously honest about provenance. If you reason beyond what the graph "
    "stores — e.g. inferring what evidence *would* change a conclusion — say so "
    "plainly (\"the graph doesn't record this, but reasoning from the evidence "
    "above…\"). Never invent source names, statistics, or counts that aren't in "
    "the provided grounding. If the grounding only partly covers the question, "
    "answer what you can from it and note that a Deep report would dig further. "
    "Use light markdown (short paragraphs, occasional bullets) when it aids "
    "readability."
)

_SYSTEM_PLAIN = (
    "You are Deepfield's research partner: a sharp, friendly, honest conversational "
    "assistant. Deepfield's knowledge graph has nothing on this topic yet, so "
    "answer from your own general knowledge — directly and concisely, the way a "
    "knowledgeable friend would. When the question turns on recent events or exact "
    "figures, say plainly that a Deep research run would verify it. Never invent "
    "specific citations or statistics. Use light markdown only when it helps. End "
    "by noting they can run a Deep report to have Deepfield actually research this "
    "and add it to the graph."
)


def _context_block(context: str) -> str:
    return (
        f"This is a follow-up in an ongoing conversation. Background so far:\n"
        f"{context}\n\n"
        if context
        else ""
    )


def _grounded_prompt(query: str, grounding_md: str, context: str = "") -> str:
    return (
        f"{_context_block(context)}"
        "Here is the relevant slice of Deepfield's knowledge graph:\n\n"
        f"{grounding_md}\n\n"
        f"Question: {query}\n\n"
        "Answer grounded in the graph material above. Cite support counts and how "
        "often disagreements have recurred. Be honest about anything you infer "
        "beyond what's recorded."
    )


def _plain_prompt(query: str, context: str = "") -> str:
    return (
        f"{_context_block(context)}"
        f"Question: {query}\n\n"
        "Answer conversationally and directly. Lead with the bottom line, keep it "
        "tight, and don't pad with filler."
    )


async def run_chat(ctx: AgentContext, query: str, context: str = "") -> None:
    """Grounded Explore answer. Retrieves graph context, answers from it (or falls
    back to a plain answer when the graph is empty). Writes one executive_summary."""
    await ctx.emit(5, "explore_agent", "💭 Explore — checking what we already know")

    # 1) Embed the question (+ recent thread context) and gather graph grounding.
    grounding = {"is_empty": True, "markdown": "", "claims": [], "disagreements": []}
    try:
        probe = f"{query}\n{context}" if context else query
        emb = await embed_query(probe)
        if emb is not None:
            async with AsyncSessionLocal() as session:
                grounding = await gather_grounding(session, emb)
    except Exception as exc:  # noqa: BLE001 — grounding is best-effort
        await ctx.emit(5, "explore_agent", f"⚠️ Graph lookup skipped: {exc}")

    grounded = not grounding.get("is_empty")
    if grounded:
        n_claims = len(grounding.get("claims", []))
        n_dis = len(grounding.get("disagreements", []))
        await ctx.emit(
            5,
            "explore_agent",
            f"🧠 Grounding in {n_claims} related claim(s)"
            + (f" and {n_dis} recorded disagreement(s)" if n_dis else ""),
        )
    else:
        await ctx.emit(
            5,
            "explore_agent",
            "💭 Nothing in the graph yet on this — answering directly",
        )

    # 2) Answer — grounded when we have material, plain otherwise.
    answer = ""
    try:
        if grounded:
            prompt = _grounded_prompt(query, grounding["markdown"], context)
            system = _SYSTEM_GROUNDED
        else:
            prompt = _plain_prompt(query, context)
            system = _SYSTEM_PLAIN
        answer = (
            await claude_complete(
                prompt, system=system, max_tokens=1400, model=BASIC_MODEL
            )
        ).strip()
    except Exception as exc:  # noqa: BLE001
        await ctx.emit(5, "explore_agent", f"⚠️ Answer generation failed: {exc}")

    async with AsyncSessionLocal() as session:
        session.add(
            ReportSection(
                report_id=ctx.report_id,
                section_type="executive_summary",
                content=answer or "_Couldn't generate an answer._",
                position=0,
            )
        )
        await session.commit()

    await ctx.emit(5, "explore_agent", "💭 Answer ready")
