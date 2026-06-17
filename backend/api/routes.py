"""REST API for Deepfield reports."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_user
from db.database import get_session
from db.models import User
from agents import citations as citation_fmt
from agents.base import claude_complete, extract_json
from agents.metadata import detect_retraction, extract_doi, extract_year
from agents.embeddings import embed_query
from agents.graph_store import evolution_direction, get_claim_evolution, search_claims
from agents.scopes import normalise as normalise_scope
from db.models import (
    CanonicalClaim,
    CanonicalSource,
    Claim,
    ClaimEvidence,
    ClaimLink,
    Comment,
    Conflict,
    Gap,
    Report,
    ReportSection,
    Source,
    Thread,
)
from pipeline.graph import run_pipeline

router = APIRouter()


# ---- Usage caps (cost control) --------------------------------------------
# Two independent limits guard against runaway API spend on DEEP runs (the
# expensive multi-layer chain). Basic and chat answers are unmetered.
#
#   1. Per-user monthly cap — each account gets a fixed allowance that resets
#      on the 1st (UTC). Stops any single user from draining the budget.
#   2. Global daily ceiling — a hard cap on total deep runs across ALL users
#      per day. This is the wallet protector: even if someone scripts a flood
#      of accounts, the app stops spending once the daily ceiling is hit.
#
# Both are env-tunable. A value <= 0 disables that limit.
FREE_DEEP_RUNS_PER_MONTH = int(os.getenv("DEEPFIELD_FREE_DEEP_RUNS", "3"))
_GLOBAL_DAILY = int(os.getenv("DEEPFIELD_GLOBAL_DAILY_DEEP_RUNS", "50"))
GLOBAL_DAILY_DEEP_RUNS: Optional[int] = _GLOBAL_DAILY if _GLOBAL_DAILY > 0 else None

# Accounts on these plans skip the *per-user* cap (the owner can self-grant by
# setting their plan in the DB). The global daily ceiling still applies to
# everyone — it is the absolute spend backstop.
UNLIMITED_PLANS = {"pro", "team"}


def _deep_limit(plan: str) -> Optional[int]:
    """Monthly per-user deep-run cap for a plan; None means uncapped."""
    return None if plan in UNLIMITED_PLANS else FREE_DEEP_RUNS_PER_MONTH


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def _deep_runs_this_month(session: AsyncSession, user_id: int) -> int:
    return (
        await session.execute(
            select(func.count(Report.id)).where(
                Report.user_id == user_id,
                Report.mode == "deep",
                Report.created_at >= _month_start(),
            )
        )
    ).scalar_one()


async def _global_deep_runs_today(session: AsyncSession) -> int:
    return (
        await session.execute(
            select(func.count(Report.id)).where(
                Report.mode == "deep",
                Report.created_at >= _day_start(),
            )
        )
    ).scalar_one()


class UsageOut(BaseModel):
    plan: str
    used: int
    limit: Optional[int] = None  # None = unlimited
    remaining: Optional[int] = None  # None = unlimited
    period: str = "month"


@router.get("/usage", response_model=UsageOut)
async def get_usage(
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> UsageOut:
    """Current user's deep-run consumption for the calendar month."""
    used = await _deep_runs_this_month(session, user.id)
    limit = _deep_limit(user.plan)
    remaining = None if limit is None else max(0, limit - used)
    return UsageOut(plan=user.plan, used=used, limit=limit, remaining=remaining)


# ---- Schemas ---------------------------------------------------------------

class CreateReportRequest(BaseModel):
    query: str
    # "deep" (5-layer Sonnet chain) or "basic" (quick single-pass Haiku answer).
    mode: str = "deep"
    # Search corpus: "web" | "academic" | "pubmed" | "arxiv".
    source_scope: str = "web"
    # Attach to an existing conversation; omit to start a new thread.
    thread_id: Optional[int] = None
    # The report this one branches from (free-text follow-up or "research deeper").
    parent_report_id: Optional[int] = None
    # Extra background for the pipeline (e.g. the finding being drilled into).
    context: Optional[str] = None
    # Power-user search controls.
    year_min: Optional[int] = None
    include_domains: Optional[str] = None
    exclude_domains: Optional[str] = None


class ReportSummary(BaseModel):
    id: int
    query: str
    status: str
    mode: str = "deep"
    source_scope: str = "web"
    thread_id: Optional[int] = None
    parent_report_id: Optional[int] = None

    class Config:
        from_attributes = True


class ThreadSummary(BaseModel):
    id: int
    title: str

    class Config:
        from_attributes = True


class ThreadDetail(BaseModel):
    id: int
    title: str
    reports: List[ReportSummary]


class SectionOut(BaseModel):
    section_type: str
    content: str
    position: int

    class Config:
        from_attributes = True


class ClaimOut(BaseModel):
    id: int
    source_id: Optional[int]
    claim_text: str
    confidence_score: float
    support_count: int

    class Config:
        from_attributes = True


class SourceOut(BaseModel):
    id: int
    url: str
    title: str
    summary: Optional[str]
    credibility_score: float
    source_type: str = "web"
    authors: Optional[str] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    citation_count: Optional[int] = None
    peer_reviewed: bool = False
    retracted: bool = False
    claims: List[ClaimOut] = []

    class Config:
        from_attributes = True


class ConflictOut(BaseModel):
    id: int
    claim_a_id: Optional[int]
    claim_b_id: Optional[int]
    topic: Optional[str] = None
    description: str

    class Config:
        from_attributes = True


class GapOut(BaseModel):
    id: int
    description: str
    kind: str

    class Config:
        from_attributes = True


class FullReportOut(BaseModel):
    id: int
    query: str
    status: str
    mode: str = "deep"
    source_scope: str = "web"
    sections: List[SectionOut]


# ---- Routes ----------------------------------------------------------------

@router.post("/reports", response_model=ReportSummary, status_code=201)
async def create_report(
    payload: CreateReportRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> Report:
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty")

    mode = payload.mode if payload.mode in ("deep", "basic", "chat") else "deep"
    source_scope = normalise_scope(payload.source_scope)

    # Usage gate (cost control): DEEP runs are capped per-user-per-month and by
    # a global daily ceiling. Both return 429 (a quota limit, not a payment
    # wall). Basic/chat are unmetered and fall straight through. Checked before
    # any pipeline spawns, so a blocked run costs nothing.
    if mode == "deep":
        limit = _deep_limit(user.plan)
        if limit is not None:
            used = await _deep_runs_this_month(session, user.id)
            if used >= limit:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"You've reached your monthly limit of {limit} deep research "
                        "runs. Your allowance resets on the 1st."
                    ),
                )
        if GLOBAL_DAILY_DEEP_RUNS is not None:
            today = await _global_deep_runs_today(session)
            if today >= GLOBAL_DAILY_DEEP_RUNS:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "Deepfield has reached today's research capacity. "
                        "Please try again tomorrow."
                    ),
                )

    # Resolve the thread: reuse the given one, or open a new conversation whose
    # title is the first question asked.
    thread_id = payload.thread_id
    if thread_id is not None:
        thread = await session.get(Thread, thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="thread not found")
    else:
        title = query if len(query) <= 120 else query[:117] + "…"
        thread = Thread(title=title)
        session.add(thread)
        await session.commit()
        await session.refresh(thread)
        thread_id = thread.id

    report = Report(
        query=query,
        status="pending",
        mode=mode,
        source_scope=source_scope,
        thread_id=thread_id,
        parent_report_id=payload.parent_report_id,
        context=payload.context,
        year_min=payload.year_min,
        include_domains=payload.include_domains,
        exclude_domains=payload.exclude_domains,
        user_id=user.id,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)

    # Kick off the pipeline in the background; the client connects to the WS
    # feed using the returned id.
    background_tasks.add_task(
        run_pipeline,
        report.id,
        query,
        payload.context,
        mode,
        source_scope,
        payload.year_min,
        payload.include_domains,
        payload.exclude_domains,
    )
    return report


@router.post("/threads", response_model=ThreadSummary, status_code=201)
async def create_thread(
    session: AsyncSession = Depends(get_session),
) -> Thread:
    thread = Thread(title="New research")
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return thread


@router.get("/threads", response_model=List[ThreadSummary])
async def list_threads(
    session: AsyncSession = Depends(get_session),
) -> List[Thread]:
    return (
        await session.execute(select(Thread).order_by(Thread.id.desc()))
    ).scalars().all()


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def get_thread(
    thread_id: int, session: AsyncSession = Depends(get_session)
) -> ThreadDetail:
    thread = await session.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    reports = (
        await session.execute(
            select(Report)
            .where(Report.thread_id == thread_id)
            .order_by(Report.id)
        )
    ).scalars().all()
    return ThreadDetail(
        id=thread.id,
        title=thread.title,
        reports=[ReportSummary.model_validate(r) for r in reports],
    )


@router.get("/reports/{report_id}", response_model=FullReportOut)
async def get_report(
    report_id: int, session: AsyncSession = Depends(get_session)
) -> FullReportOut:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    sections = (
        await session.execute(
            select(ReportSection)
            .where(ReportSection.report_id == report_id)
            .order_by(ReportSection.position)
        )
    ).scalars().all()
    return FullReportOut(
        id=report.id,
        query=report.query,
        status=report.status,
        mode=report.mode,
        source_scope=report.source_scope,
        sections=[SectionOut.model_validate(s) for s in sections],
    )


@router.get("/reports/{report_id}/sources", response_model=List[SourceOut])
async def get_sources(
    report_id: int, session: AsyncSession = Depends(get_session)
) -> List[SourceOut]:
    if await session.get(Report, report_id) is None:
        raise HTTPException(status_code=404, detail="report not found")
    sources = (
        await session.execute(
            select(Source).where(Source.report_id == report_id)
        )
    ).scalars().all()
    out: List[SourceOut] = []
    for s in sources:
        claims = (
            await session.execute(
                select(Claim)
                .where(Claim.source_id == s.id)
                .order_by(Claim.confidence_score.desc())
            )
        ).scalars().all()
        out.append(
            SourceOut(
                id=s.id,
                url=s.url,
                title=s.title,
                summary=s.summary,
                credibility_score=s.credibility_score,
                source_type=s.source_type,
                authors=s.authors,
                year=s.year,
                venue=s.venue,
                doi=s.doi,
                citation_count=s.citation_count,
                peer_reviewed=s.peer_reviewed,
                retracted=s.retracted,
                claims=[ClaimOut.model_validate(c) for c in claims],
            )
        )
    return out


@router.get("/reports/{report_id}/conflicts", response_model=List[ConflictOut])
async def get_conflicts(
    report_id: int, session: AsyncSession = Depends(get_session)
) -> List[Conflict]:
    if await session.get(Report, report_id) is None:
        raise HTTPException(status_code=404, detail="report not found")
    return (
        await session.execute(
            select(Conflict).where(Conflict.report_id == report_id)
        )
    ).scalars().all()


@router.get("/reports/{report_id}/gaps", response_model=List[GapOut])
async def get_gaps(
    report_id: int, session: AsyncSession = Depends(get_session)
) -> List[Gap]:
    if await session.get(Report, report_id) is None:
        raise HTTPException(status_code=404, detail="report not found")
    return (
        await session.execute(select(Gap).where(Gap.report_id == report_id))
    ).scalars().all()


# ---- Disagreement graph (read-only explorer) -------------------------------

@router.get("/graph/stats")
async def graph_stats(session: AsyncSession = Depends(get_session)) -> dict:
    """Totals for the accumulating graph — the headline numbers of the moat."""

    async def _count(model) -> int:
        return (
            await session.execute(select(func.count()).select_from(model))
        ).scalar() or 0

    return {
        "canonical_claims": await _count(CanonicalClaim),
        "canonical_sources": await _count(CanonicalSource),
        "disagreements": await _count(ClaimLink),
        "evidence_edges": await _count(ClaimEvidence),
    }


@router.get("/graph/search")
async def graph_search(
    q: str = "", limit: int = 20, session: AsyncSession = Depends(get_session)
) -> dict:
    """Topic search across the whole graph. Embeds the query and ANN-ranks the
    canonical claims most related to it, each with support stats and how many
    disagreements touch it. Fail-soft: an empty query, no Voyage key, or an empty
    graph all return ``{"query": q, "results": []}`` rather than erroring."""
    query = (q or "").strip()
    if not query:
        return {"query": "", "results": []}
    limit = max(1, min(limit, 50))
    embedding = await embed_query(query)
    results = await search_claims(session, embedding, k=limit)
    return {"query": query, "results": results}


@router.get("/graph/disagreements")
async def graph_disagreements(
    limit: int = 30, session: AsyncSession = Depends(get_session)
) -> List[dict]:
    """The most-contested claims first — edges ranked by how many independent
    reports have observed the same disagreement."""
    limit = max(1, min(limit, 100))
    links = (
        await session.execute(
            select(ClaimLink)
            .order_by(ClaimLink.observed_count.desc(), ClaimLink.id.desc())
            .limit(limit)
        )
    ).scalars().all()

    # Batch-load the claims referenced by these edges.
    claim_ids = {link.claim_a_id for link in links} | {link.claim_b_id for link in links}
    claims = {}
    if claim_ids:
        rows = (
            await session.execute(
                select(CanonicalClaim).where(CanonicalClaim.id.in_(claim_ids))
            )
        ).scalars().all()
        claims = {c.id: c for c in rows}

    def _claim_brief(cid: int) -> dict:
        c = claims.get(cid)
        if c is None:
            return {"id": cid, "statement": "(unknown)", "support_count": 0}
        return {
            "id": c.id,
            "statement": c.statement,
            "support_count": c.support_count,
            "confidence": c.confidence,
        }

    return [
        {
            "id": link.id,
            "relation": link.relation,
            "observed_count": link.observed_count,
            "description": link.description,
            "claim_a": _claim_brief(link.claim_a_id),
            "claim_b": _claim_brief(link.claim_b_id),
        }
        for link in links
    ]


@router.get("/graph/claims/{claim_id}")
async def graph_claim(
    claim_id: int, session: AsyncSession = Depends(get_session)
) -> dict:
    """A single canonical claim with its supporting sources and the
    disagreements it participates in."""
    claim = await session.get(CanonicalClaim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")

    evidence = (
        await session.execute(
            select(ClaimEvidence, CanonicalSource)
            .join(CanonicalSource, ClaimEvidence.canonical_source_id == CanonicalSource.id)
            .where(ClaimEvidence.canonical_claim_id == claim_id)
        )
    ).all()
    sources = [
        {
            "id": src.id,
            "url": src.url_normalized,
            "title": src.title,
            "domain": src.domain,
            "credibility_score": src.credibility_score,
            "stance": ev.stance,
        }
        for ev, src in evidence
    ]

    links = (
        await session.execute(
            select(ClaimLink)
            .where(or_(ClaimLink.claim_a_id == claim_id, ClaimLink.claim_b_id == claim_id))
            .order_by(ClaimLink.observed_count.desc())
        )
    ).scalars().all()
    other_ids = {
        (link.claim_b_id if link.claim_a_id == claim_id else link.claim_a_id)
        for link in links
    }
    others = {}
    if other_ids:
        rows = (
            await session.execute(
                select(CanonicalClaim).where(CanonicalClaim.id.in_(other_ids))
            )
        ).scalars().all()
        others = {c.id: c for c in rows}
    disagreements = []
    for link in links:
        other_id = link.claim_b_id if link.claim_a_id == claim_id else link.claim_a_id
        other = others.get(other_id)
        disagreements.append(
            {
                "id": link.id,
                "observed_count": link.observed_count,
                "description": link.description,
                "other_claim": {
                    "id": other_id,
                    "statement": other.statement if other else "(unknown)",
                },
            }
        )

    evolution = await get_claim_evolution(session, claim_id)

    return {
        "id": claim.id,
        "statement": claim.statement,
        "support_count": claim.support_count,
        "report_count": claim.report_count,
        "confidence": claim.confidence,
        "sources": sources,
        "disagreements": disagreements,
        "evolution": evolution,
        "direction": evolution_direction(evolution),
    }


# ---- Citation export -------------------------------------------------------

@router.get("/reports/{report_id}/citations")
async def export_citations(
    report_id: int,
    format: str = "apa",
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Formatted citations (BibTeX / APA / MLA) for every source in a report."""
    fmt = format.lower()
    if fmt not in ("bibtex", "apa", "mla"):
        raise HTTPException(status_code=400, detail="format must be bibtex|apa|mla")
    if await session.get(Report, report_id) is None:
        raise HTTPException(status_code=404, detail="report not found")
    sources = (
        await session.execute(
            select(Source).where(Source.report_id == report_id).order_by(Source.id)
        )
    ).scalars().all()
    return {
        "format": fmt,
        "count": len(sources),
        "content": citation_fmt.format_all(sources, fmt),
        "items": [
            {"id": s.id, "title": s.title, "citation": citation_fmt.format_citation(s, fmt)}
            for s in sources
        ],
    }


# ---- Compare two sources head-to-head --------------------------------------

class CompareRequest(BaseModel):
    source_a_id: int
    source_b_id: int


_COMPARE_SYSTEM = (
    "You are a meticulous research analyst. You compare two sources head-to-head "
    "for a researcher, fairly and concretely. You ground every statement in the "
    "provided material and never invent findings. Plain language, no jargon."
)


@router.post("/compare")
async def compare_sources(
    payload: CompareRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Direct head-to-head of two sources/papers: where they agree, where they
    conflict, and which rests on stronger evidence."""
    a = await session.get(Source, payload.source_a_id)
    b = await session.get(Source, payload.source_b_id)
    if a is None or b is None:
        raise HTTPException(status_code=404, detail="source not found")

    def _block(s: Source) -> str:
        meta = " · ".join(
            x for x in [
                s.venue, str(s.year) if s.year else None,
                "peer-reviewed" if s.peer_reviewed else s.source_type,
                f"{s.citation_count} citations" if s.citation_count is not None else None,
            ] if x
        )
        body = (s.summary or s.snippet or s.content or "")[:2000]
        return f"TITLE: {s.title}\nMETADATA: {meta}\nCONTENT:\n{body}"

    prompt = f"""Compare these two sources for a researcher.

=== SOURCE A ===
{_block(a)}

=== SOURCE B ===
{_block(b)}

Return ONLY JSON of this exact shape:
{{
  "agreements": ["points where both sources agree"],
  "conflicts": ["specific points where they disagree, naming each side's position"],
  "stronger_evidence": "A" or "B" or "comparable",
  "stronger_reason": "one plain-language sentence on why",
  "verdict": "2-3 sentence bottom-line a researcher can act on"
}}"""
    try:
        from agents.base import extract_json

        raw = await claude_complete(prompt, system=_COMPARE_SYSTEM, max_tokens=1200)
        data = extract_json(raw) or {}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"comparison failed: {exc}")

    return {
        "source_a": {"id": a.id, "title": a.title, "url": a.url},
        "source_b": {"id": b.id, "title": b.title, "url": b.url},
        "agreements": data.get("agreements", []) or [],
        "conflicts": data.get("conflicts", []) or [],
        "stronger_evidence": data.get("stronger_evidence", "comparable"),
        "stronger_reason": data.get("stronger_reason", ""),
        "verdict": data.get("verdict", ""),
    }


# ---- Comments / annotations (lightweight collaboration) --------------------

class CommentIn(BaseModel):
    body: str
    author: str = "Anonymous"
    anchor: Optional[str] = None
    assigned_to: Optional[str] = None


class CommentOut(BaseModel):
    id: int
    report_id: int
    author: str
    body: str
    anchor: Optional[str] = None
    assigned_to: Optional[str] = None
    resolved: bool = False

    class Config:
        from_attributes = True


class CommentPatch(BaseModel):
    resolved: Optional[bool] = None
    assigned_to: Optional[str] = None


@router.get("/reports/{report_id}/comments", response_model=List[CommentOut])
async def list_comments(
    report_id: int, session: AsyncSession = Depends(get_session)
) -> List[Comment]:
    if await session.get(Report, report_id) is None:
        raise HTTPException(status_code=404, detail="report not found")
    return (
        await session.execute(
            select(Comment).where(Comment.report_id == report_id).order_by(Comment.id)
        )
    ).scalars().all()


@router.post("/reports/{report_id}/comments", response_model=CommentOut, status_code=201)
async def add_comment(
    report_id: int, payload: CommentIn, session: AsyncSession = Depends(get_session)
) -> Comment:
    if await session.get(Report, report_id) is None:
        raise HTTPException(status_code=404, detail="report not found")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="comment body must not be empty")
    comment = Comment(
        report_id=report_id,
        author=(payload.author or "Anonymous").strip()[:80] or "Anonymous",
        body=body,
        anchor=payload.anchor,
        assigned_to=payload.assigned_to,
    )
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return comment


@router.patch("/comments/{comment_id}", response_model=CommentOut)
async def update_comment(
    comment_id: int, payload: CommentPatch, session: AsyncSession = Depends(get_session)
) -> Comment:
    comment = await session.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="comment not found")
    if payload.resolved is not None:
        comment.resolved = payload.resolved
    if payload.assigned_to is not None:
        comment.assigned_to = payload.assigned_to or None
    await session.commit()
    await session.refresh(comment)
    return comment


# ---- PDF upload: include the user's own papers as a source -----------------

_MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB cap
_PDF_EXTRACT_CHARS = 6000  # cap text fed to the LLM

_PAPER_SYSTEM = (
    "You are a meticulous research analyst reading a single uploaded paper. You "
    "extract its actual argument and atomic, checkable claims. You never invent "
    "claims unsupported by the text."
)


def _paper_prompt(title: str, content: str) -> str:
    snippet = content[:_PDF_EXTRACT_CHARS] if content else "(no extractable text)"
    return f"""Uploaded paper title: {title}
Paper content:
\"\"\"
{snippet}
\"\"\"

Read the paper and extract its substance. Return ONLY JSON of this exact shape:
{{
  "title": "the paper's actual title if discernible, else null",
  "core_argument": "1-3 sentence summary of the paper's central argument",
  "authors": "author names if clearly stated, else null",
  "year": publication year as an integer if clearly stated, else null,
  "venue": "journal/conference/publisher if clearly stated, else null",
  "claims": [
    {{"claim": "one atomic factual claim", "evidence": "the supporting evidence the paper gives"}}
  ]
}}

Rules:
- Extract 3-6 atomic claims. Each must stand alone (resolve pronouns).
- Only include claims actually supported by the content above.
- For authors/year/venue/title: only fill them if the text plainly states them; never guess."""


def _extract_pdf_text(data: bytes) -> str:
    """Parse PDF bytes to plain text. Returns '' on any failure (fail-soft)."""
    import io

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        parts: List[str] = []
        for page in reader.pages[:40]:  # cap pages so a huge PDF can't stall us
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(p for p in parts if p).strip()
    except Exception:  # noqa: BLE001
        return ""


@router.post("/reports/{report_id}/papers", response_model=SourceOut, status_code=201)
async def upload_paper(
    report_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> SourceOut:
    """Attach a user-uploaded PDF as a first-class Source on an existing report.

    The paper is parsed, its metadata inferred, and its key claims extracted by
    the same analyst prompt Layer 2 uses — so an uploaded paper participates in
    the report exactly like a retrieved source. Fail-soft: a PDF we cannot read
    still produces a source row (with whatever metadata we could infer) rather
    than erroring out."""
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")

    filename = (file.filename or "uploaded.pdf").strip()
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only .pdf files are supported")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    if len(data) > _MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds 20 MB limit")

    text = _extract_pdf_text(data)

    # Best-effort title from the filename; the LLM may override with the real one.
    fallback_title = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()

    core_argument = ""
    authors: Optional[str] = None
    year: Optional[int] = extract_year(text[:_PDF_EXTRACT_CHARS])
    venue: Optional[str] = None
    title = fallback_title or "Uploaded paper"
    claims_data: List[dict] = []
    if text:
        try:
            raw = await claude_complete(
                _paper_prompt(fallback_title, text),
                system=_PAPER_SYSTEM,
                max_tokens=1500,
            )
            data_json = extract_json(raw) or {}
            core_argument = data_json.get("core_argument", "") or ""
            if data_json.get("title"):
                title = str(data_json["title"])[:300]
            if data_json.get("authors"):
                authors = str(data_json["authors"])[:500]
            if data_json.get("venue"):
                venue = str(data_json["venue"])[:300]
            y = data_json.get("year")
            try:
                if y and 1500 <= int(y) <= 2099:
                    year = int(y)
            except (TypeError, ValueError):
                pass
            claims_data = data_json.get("claims", []) or []
        except Exception:  # noqa: BLE001
            core_argument = ""

    doi = extract_doi(text[:_PDF_EXTRACT_CHARS]) if text else None
    retracted = detect_retraction(title, text[:_PDF_EXTRACT_CHARS]) if text else False

    source = Source(
        report_id=report_id,
        url=f"upload://{filename}",
        title=title,
        snippet=(text[:500] if text else None),
        content=(text[:_PDF_EXTRACT_CHARS] if text else None),
        summary=core_argument or None,
        credibility_score=0.7,  # user-curated: trusted but not peer-review verified here
        source_type="uploaded",
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        peer_reviewed=False,
        retracted=retracted,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)

    stored_claims: List[Claim] = []
    for c in claims_data:
        ctext = (c or {}).get("claim", "").strip()
        if not ctext:
            continue
        claim = Claim(
            report_id=report_id,
            source_id=source.id,
            claim_text=ctext,
            confidence_score=0.0,
            support_count=1,
            layer_origin=2,
        )
        session.add(claim)
        stored_claims.append(claim)
    await session.commit()
    for claim in stored_claims:
        await session.refresh(claim)

    # Build the response explicitly — the ORM `claims` relationship is lazy and
    # would trigger IO during async serialization.
    return SourceOut(
        id=source.id,
        url=source.url,
        title=source.title,
        summary=source.summary,
        credibility_score=source.credibility_score,
        source_type=source.source_type,
        authors=source.authors,
        year=source.year,
        venue=source.venue,
        doi=source.doi,
        citation_count=source.citation_count,
        peer_reviewed=source.peer_reviewed,
        retracted=source.retracted,
        claims=[ClaimOut.model_validate(c) for c in stored_claims],
    )
