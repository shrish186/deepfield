"""The canonicalization core of the disagreement graph.

Promotes the per-report artifacts the pipeline already computes (the Layer-3
canonical claim map and the Layer-4 contradictions) into persistent, global,
cross-report entities:

  • canonical sources  — deduped by normalised URL,
  • canonical claims   — deduped *semantically* via embedding cosine similarity,
  • evidence edges      (claim → source),
  • disagreement edges  (claim ↔ claim) whose ``observed_count`` compounds every
    time an independent report surfaces the same contradiction.

Two helpers are deliberately pure (no DB, no embeddings) so they can be unit
tested in isolation: :func:`normalize_url`, :func:`order_pair`, and
:func:`format_prior_knowledge`.

Similarity thresholds are env-tunable:
  • ``DEEPFIELD_CLAIM_SIM`` (default 0.85) — merge a new claim into an existing
    canonical claim at/above this cosine similarity.
  • ``DEEPFIELD_RECALL_SIM`` (default 0.5) — surface a prior claim as relevant
    context for a new query at/above this similarity. Tuned well below CLAIM_SIM
    because recall compares a *query* embedding against stored *document*
    embeddings, and voyage-3 cross-input-type cosine similarities run lower than
    document-to-document ones: a broad question ("is X or Y better") against a
    narrow stored product statement lands around 0.50, so 0.6 was missing
    genuinely related prior research while unrelated queries still sit at 0.30–0.45.
"""
from __future__ import annotations

import os
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.credibility import _host
from db.models import (
    CanonicalClaim,
    CanonicalSource,
    ClaimEvidence,
    ClaimLink,
    ClaimSnapshot,
    Report,
)

CLAIM_SIM = float(os.getenv("DEEPFIELD_CLAIM_SIM", "0.85"))
RECALL_SIM = float(os.getenv("DEEPFIELD_RECALL_SIM", "0.5"))


# --- Pure helpers (no DB / no network) --------------------------------------

def normalize_url(url: str) -> str:
    """Collapse cosmetic URL variants to one key so the same page dedupes.

    Lowercases scheme + host, strips a leading ``www.``, drops the query string
    and fragment, and removes a trailing slash. Malformed input degrades to a
    lowercased, trimmed best-effort string rather than raising."""
    if not url:
        return ""
    raw = url.strip()
    try:
        parsed = urlparse(raw)
    except Exception:  # noqa: BLE001
        return raw.lower().rstrip("/")
    host = _host(raw)  # lowercased, www-stripped (reused from credibility.py)
    if not host:
        return raw.lower().rstrip("/")
    scheme = (parsed.scheme or "https").lower()
    path = (parsed.path or "").rstrip("/")
    return f"{scheme}://{host}{path}"


def order_pair(a_id: int, b_id: int) -> Tuple[int, int]:
    """Order a claim pair so an edge is direction-agnostic: (a,b) == (b,a)."""
    return (a_id, b_id) if a_id <= b_id else (b_id, a_id)


def _confidence(distinct_sources: int) -> float:
    """Saturating confidence curve: more independent sources backing a claim →
    higher confidence, with diminishing returns, approaching a ~0.97 ceiling.

    Monotonically increasing — one source → 0.30, and it never turns over or
    goes negative (the previous quadratic form did both past ~6 sources, which
    made well-supported claims look like they were *losing* confidence)."""
    if distinct_sources <= 0:
        return 0.0
    return round(0.97 - 0.67 * (0.7 ** (distinct_sources - 1)), 2)


def evolution_direction(series: List[Dict[str, Any]], *, eps: float = 0.05) -> str:
    """Classify how a claim's evidence has moved across its snapshot series by
    comparing the earliest and latest confidence:

      • fewer than 2 points → ``"new"`` (no history to judge yet)
      • rise  >  eps        → ``"strengthening"``
      • fall  < -eps        → ``"weakening"``
      • otherwise           → ``"stable"``

    Pure (no DB / no network) so it can be unit-tested in isolation."""
    points = [p for p in series if p is not None]
    if len(points) < 2:
        return "new"
    first = float(points[0].get("confidence", 0.0) or 0.0)
    last = float(points[-1].get("confidence", 0.0) or 0.0)
    delta = last - first
    if delta > eps:
        return "strengthening"
    if delta < -eps:
        return "weakening"
    return "stable"


def format_prior_knowledge(claims: List[Dict[str, Any]]) -> str:
    """Render recalled claims into a compact markdown block for the synthesis
    prompt and the report's prior-knowledge card. Empty input → empty string."""
    if not claims:
        return ""
    lines = [
        f"**What prior research already established** "
        f"(from {len(claims)} related finding(s) across earlier reports):",
    ]
    for c in claims:
        support = c.get("support_count", 0)
        reports = c.get("report_count", 0)
        lines.append(
            f"- {c['statement']} "
            f"_(backed by {support} source(s) across {reports} report(s))_"
        )
        for d in c.get("disagreements", []):
            seen = d.get("observed_count", 1)
            desc = d.get("description") or "sources disagree on this point"
            lines.append(f"  - ⚖️ Contested: {desc} _(seen in {seen} report(s))_")
    return "\n".join(lines)


# --- DB-bound canonicalization ----------------------------------------------

async def upsert_canonical_source(
    session: AsyncSession, url: str, title: str, credibility: float
) -> CanonicalSource:
    """Find-or-insert a source by normalised URL. Bumps ``times_cited`` and keeps
    the maximum credibility ever seen for it."""
    norm = normalize_url(url)
    existing = (
        await session.execute(
            select(CanonicalSource).where(CanonicalSource.url_normalized == norm)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.times_cited += 1
        if credibility and credibility > (existing.credibility_score or 0):
            existing.credibility_score = credibility
        if title and not existing.title:
            existing.title = title
        return existing
    row = CanonicalSource(
        url_normalized=norm,
        domain=_host(url),
        title=title or norm,
        credibility_score=credibility or 0.5,
        times_cited=1,
    )
    session.add(row)
    await session.flush()
    return row


async def _nearest_claim(
    session: AsyncSession, embedding: List[float]
) -> Optional[Tuple[CanonicalClaim, float]]:
    """Return the most similar existing canonical claim and its cosine
    similarity, or ``None`` if the graph is empty."""
    dist = CanonicalClaim.embedding.cosine_distance(embedding)
    row = (
        await session.execute(
            select(CanonicalClaim, dist.label("d"))
            .where(CanonicalClaim.embedding.isnot(None))
            .order_by(dist)
            .limit(1)
        )
    ).first()
    if row is None or row[1] is None:
        return None
    claim, distance = row[0], float(row[1])
    return claim, 1.0 - distance


async def upsert_canonical_claim(
    session: AsyncSession,
    statement: str,
    embedding: Optional[List[float]],
    report_id: Optional[int] = None,
) -> Optional[CanonicalClaim]:
    """Merge into the nearest existing claim above ``CLAIM_SIM`` (bumping report
    count + refreshing last_seen), else insert a new node. ``support_count`` is
    maintained by :func:`link_evidence` as distinct sources attach. Returns the
    node, or ``None`` when no embedding is available (caller skips the graph)."""
    if embedding is None:
        return None
    nearest = await _nearest_claim(session, embedding)
    if nearest is not None and nearest[1] >= CLAIM_SIM:
        claim = nearest[0]
        claim.report_count += 1
        claim.last_seen = func.now()
        return claim
    new = CanonicalClaim(
        statement=statement,
        embedding=embedding,
        support_count=0,
        report_count=1,
        confidence=0.0,
    )
    session.add(new)
    await session.flush()
    return new


async def link_evidence(
    session: AsyncSession,
    claim: CanonicalClaim,
    source: CanonicalSource,
    report_id: Optional[int] = None,
    stance: str = "supports",
) -> ClaimEvidence:
    """Upsert a claim→source evidence edge. A genuinely new edge bumps the
    claim's ``support_count`` (distinct sources) and recomputes confidence."""
    existing = (
        await session.execute(
            select(ClaimEvidence).where(
                ClaimEvidence.canonical_claim_id == claim.id,
                ClaimEvidence.canonical_source_id == source.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    edge = ClaimEvidence(
        canonical_claim_id=claim.id,
        canonical_source_id=source.id,
        stance=stance,
        report_id=report_id,
    )
    session.add(edge)
    claim.support_count = (claim.support_count or 0) + 1
    claim.confidence = _confidence(claim.support_count)
    await session.flush()
    return edge


async def upsert_disagreement(
    session: AsyncSession,
    a_id: int,
    b_id: int,
    description: str = "",
    report_id: Optional[int] = None,
    relation: str = "contradicts",
) -> Optional[ClaimLink]:
    """Find-or-insert a disagreement edge between two canonical claims. The pair
    is stored ordered so direction doesn't matter; a repeat observation bumps
    ``observed_count`` and refreshes the plain-language description. Self-pairs
    and missing ids are ignored."""
    if not a_id or not b_id or a_id == b_id:
        return None
    lo, hi = order_pair(a_id, b_id)
    existing = (
        await session.execute(
            select(ClaimLink).where(
                ClaimLink.claim_a_id == lo,
                ClaimLink.claim_b_id == hi,
                ClaimLink.relation == relation,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.observed_count += 1
        existing.last_seen = func.now()
        if description:
            existing.description = description
        return existing
    link = ClaimLink(
        claim_a_id=lo,
        claim_b_id=hi,
        relation=relation,
        observed_count=1,
        description=description or None,
    )
    session.add(link)
    await session.flush()
    return link


async def recall_prior_knowledge(
    session: AsyncSession, query_embedding: Optional[List[float]], k: int = 6
) -> Dict[str, Any]:
    """ANN top-K canonical claims related to a query (similarity ≥ RECALL_SIM),
    each with its support stats and any linked disagreements. Returns a
    structured dict plus a ready-to-inject markdown block."""
    empty: Dict[str, Any] = {"claims": [], "markdown": ""}
    if query_embedding is None:
        return empty
    dist = CanonicalClaim.embedding.cosine_distance(query_embedding)
    rows = (
        await session.execute(
            select(CanonicalClaim, dist.label("d"))
            .where(CanonicalClaim.embedding.isnot(None))
            .order_by(dist)
            .limit(k)
        )
    ).all()

    claims: List[Dict[str, Any]] = []
    for claim, distance in rows:
        if distance is None:
            continue
        if (1.0 - float(distance)) < RECALL_SIM:
            continue
        links = (
            await session.execute(
                select(ClaimLink)
                .where(or_(ClaimLink.claim_a_id == claim.id, ClaimLink.claim_b_id == claim.id))
                .order_by(ClaimLink.observed_count.desc())
                .limit(3)
            )
        ).scalars().all()
        disagreements = [
            {"observed_count": link.observed_count, "description": link.description}
            for link in links
        ]
        claims.append(
            {
                "id": claim.id,
                "statement": claim.statement,
                "support_count": claim.support_count,
                "report_count": claim.report_count,
                "confidence": claim.confidence,
                "disagreements": disagreements,
            }
        )

    return {"claims": claims, "markdown": format_prior_knowledge(claims)}


# --- Topic search over the global graph -------------------------------------

SEARCH_MIN_SIM = float(os.getenv("DEEPFIELD_SEARCH_SIM", "0.3"))


async def search_claims(
    session: AsyncSession,
    query_embedding: Optional[List[float]],
    k: int = 20,
    min_sim: float = SEARCH_MIN_SIM,
) -> List[Dict[str, Any]]:
    """Topic search across the whole graph: ANN the top-K canonical claims for a
    query embedding, returning lightweight briefs (statement, support/report
    counts, confidence, similarity, and how many disagreement edges touch each).

    Permissive ``min_sim`` (default 0.3) — this is exploratory navigation, not
    the strict merge/recall gate, so a user searching "creatine" should see the
    cluster even if no single claim is a near-paraphrase. Fail-soft: returns
    ``[]`` when no embedding is available (no Voyage key) or the graph is empty."""
    if query_embedding is None:
        return []
    dist = CanonicalClaim.embedding.cosine_distance(query_embedding)
    rows = (
        await session.execute(
            select(CanonicalClaim, dist.label("d"))
            .where(CanonicalClaim.embedding.isnot(None))
            .order_by(dist)
            .limit(k)
        )
    ).all()

    hits: List[Dict[str, Any]] = []
    for claim, distance in rows:
        if distance is None:
            continue
        sim = 1.0 - float(distance)
        if sim < min_sim:
            continue
        hits.append(
            {
                "id": claim.id,
                "statement": claim.statement,
                "support_count": claim.support_count,
                "report_count": claim.report_count,
                "confidence": claim.confidence,
                "similarity": round(sim, 3),
            }
        )
    if not hits:
        return []

    # One batched pass to count disagreement edges touching any matched claim,
    # so each brief can show whether the topic is contested.
    ids = [h["id"] for h in hits]
    link_rows = (
        await session.execute(
            select(ClaimLink.claim_a_id, ClaimLink.claim_b_id).where(
                or_(ClaimLink.claim_a_id.in_(ids), ClaimLink.claim_b_id.in_(ids))
            )
        )
    ).all()
    counts: Dict[int, int] = {i: 0 for i in ids}
    id_set = set(ids)
    for a_id, b_id in link_rows:
        if a_id in id_set:
            counts[a_id] += 1
        if b_id in id_set:
            counts[b_id] += 1
    for h in hits:
        h["disagreement_count"] = counts.get(h["id"], 0)
    return hits


# --- Grounding for the Explore (research-partner) mode -----------------------

async def gather_grounding(
    session: AsyncSession,
    query_embedding: Optional[List[float]],
    k: int = 8,
) -> Dict[str, Any]:
    """Assemble everything the Explore mode needs to answer *grounded in the
    graph* for a given query: the related canonical claims, the evidence backing
    each (sources + credibility), and the disagreement edges among them with
    *both* sides' statements spelled out.

    Returns a structured dict::

        {
          "claims": [{id, statement, support_count, report_count, confidence,
                      similarity, sources: [{title, domain, credibility, stance}]}],
          "disagreements": [{observed_count, description,
                             a: "<statement>", b: "<statement>"}],
          "markdown": "<compact grounding block for the prompt>",
          "is_empty": bool,
        }

    Fail-soft: a ``None`` embedding (no Voyage key) or an empty graph yields an
    empty, ``is_empty=True`` result so the caller can fall back to a plain answer.
    Built from a handful of batched queries (claims → evidence → links) rather
    than per-claim round-trips."""
    empty: Dict[str, Any] = {
        "claims": [],
        "disagreements": [],
        "markdown": "",
        "is_empty": True,
    }
    if query_embedding is None:
        return empty

    # Gate grounding at the recall bar, not the permissive search floor: a single
    # weak (~0.3) tangential match shouldn't flip Explore into "grounded" mode and
    # suppress the model's general knowledge. We only ground when the graph holds
    # something genuinely on-topic; otherwise the caller answers plainly.
    hits = await search_claims(session, query_embedding, k=k, min_sim=RECALL_SIM)
    if not hits:
        return empty

    ids = [h["id"] for h in hits]
    id_set = set(ids)
    by_id = {h["id"]: h for h in hits}

    # Evidence for all matched claims in one pass.
    ev_rows = (
        await session.execute(
            select(ClaimEvidence, CanonicalSource)
            .join(CanonicalSource, ClaimEvidence.canonical_source_id == CanonicalSource.id)
            .where(ClaimEvidence.canonical_claim_id.in_(ids))
        )
    ).all()
    sources_by_claim: Dict[int, List[Dict[str, Any]]] = {i: [] for i in ids}
    for ev, src in ev_rows:
        sources_by_claim.setdefault(ev.canonical_claim_id, []).append(
            {
                "title": src.title,
                "domain": src.domain,
                "credibility": src.credibility_score,
                "stance": ev.stance,
            }
        )
    # Keep the most credible few per claim for a tight prompt.
    for cid, srcs in sources_by_claim.items():
        srcs.sort(key=lambda s: s.get("credibility") or 0, reverse=True)
        sources_by_claim[cid] = srcs[:4]

    claims = [
        {
            "id": h["id"],
            "statement": h["statement"],
            "support_count": h["support_count"],
            "report_count": h["report_count"],
            "confidence": h["confidence"],
            "similarity": h["similarity"],
            "sources": sources_by_claim.get(h["id"], []),
        }
        for h in hits
    ]

    # Disagreement edges touching the matched claims. We surface an edge when at
    # least one endpoint is in the result set; the other side's statement is
    # pulled in so the model can describe both poles of the disagreement.
    link_rows = (
        await session.execute(
            select(ClaimLink)
            .where(
                or_(ClaimLink.claim_a_id.in_(ids), ClaimLink.claim_b_id.in_(ids))
            )
            .order_by(ClaimLink.observed_count.desc())
            .limit(12)
        )
    ).scalars().all()

    needed = {
        cid
        for link in link_rows
        for cid in (link.claim_a_id, link.claim_b_id)
        if cid not in by_id
    }
    extra: Dict[int, str] = {}
    if needed:
        rows = (
            await session.execute(
                select(CanonicalClaim.id, CanonicalClaim.statement).where(
                    CanonicalClaim.id.in_(needed)
                )
            )
        ).all()
        extra = {cid: stmt for cid, stmt in rows}

    def _stmt(cid: int) -> str:
        if cid in by_id:
            return by_id[cid]["statement"]
        return extra.get(cid, "(unknown claim)")

    disagreements = [
        {
            "observed_count": link.observed_count,
            "description": link.description,
            "a": _stmt(link.claim_a_id),
            "b": _stmt(link.claim_b_id),
        }
        for link in link_rows
    ]

    return {
        "claims": claims,
        "disagreements": disagreements,
        "markdown": format_grounding(claims, disagreements),
        "is_empty": False,
    }


def format_grounding(
    claims: List[Dict[str, Any]], disagreements: List[Dict[str, Any]]
) -> str:
    """Render gathered grounding into a compact, labelled markdown block for the
    Explore prompt. Pure (no DB) so it's unit-testable. Empty input → empty."""
    if not claims and not disagreements:
        return ""
    lines: List[str] = []
    if claims:
        lines.append("ESTABLISHED CLAIMS (from prior reports in the graph):")
        for c in claims:
            lines.append(
                f"- {c['statement']} "
                f"[backed by {c.get('support_count', 0)} source(s) across "
                f"{c.get('report_count', 0)} report(s); "
                f"confidence {c.get('confidence', 0)}]"
            )
            for s in c.get("sources", [])[:3]:
                dom = s.get("domain") or "source"
                cred = s.get("credibility")
                cred_txt = f", credibility {cred}" if cred is not None else ""
                lines.append(f"    • {s.get('stance', 'supports')}: {dom}{cred_txt}")
    if disagreements:
        lines.append("")
        lines.append("RECORDED DISAGREEMENTS (where prior reports conflicted):")
        for d in disagreements:
            seen = d.get("observed_count", 1)
            desc = d.get("description")
            head = f"- ⚖️ seen in {seen} report(s)"
            lines.append(f"{head}: {desc}" if desc else head)
            lines.append(f"    • Side A: {d['a']}")
            lines.append(f"    • Side B: {d['b']}")
    return "\n".join(lines)


# --- Claim evolution (snapshots over time) ----------------------------------

async def record_snapshot(
    session: AsyncSession, claim: CanonicalClaim, report_id: Optional[int] = None
) -> Optional[ClaimSnapshot]:
    """Append a point-in-time snapshot of a claim's current aggregate state.
    Called once per claim per contributing report so the evolution series grows
    as the graph does. No-op on a missing/unflushed claim."""
    if claim is None or claim.id is None:
        return None
    snap = ClaimSnapshot(
        canonical_claim_id=claim.id,
        support_count=claim.support_count or 0,
        report_count=claim.report_count or 0,
        confidence=claim.confidence or 0.0,
        report_id=report_id,
    )
    session.add(snap)
    await session.flush()
    return snap


async def get_claim_evolution(
    session: AsyncSession, claim_id: int
) -> List[Dict[str, Any]]:
    """Ordered snapshot series for one claim (oldest first), as plain dicts."""
    rows = (
        await session.execute(
            select(ClaimSnapshot)
            .where(ClaimSnapshot.canonical_claim_id == claim_id)
            .order_by(ClaimSnapshot.observed_at.asc(), ClaimSnapshot.id.asc())
        )
    ).scalars().all()
    return [
        {
            "observed_at": s.observed_at.isoformat() if s.observed_at else None,
            "support_count": s.support_count,
            "report_count": s.report_count,
            "confidence": s.confidence,
            "report_id": s.report_id,
        }
        for s in rows
    ]


async def backfill_claim_snapshots(session: AsyncSession) -> int:
    """One-time reconstruction of evolution history for claims that predate
    snapshot tracking. For each claim it replays its evidence edges in
    report-chronological order, recomputing the cumulative distinct-source
    support and confidence, and emits one snapshot per contributing report.

    Idempotent: does nothing if any snapshot already exists. Returns the number
    of rows inserted. Approximate (a merge that added no new source still bumped
    report_count but left no evidence row), but good enough to show direction."""
    existing = (
        await session.execute(select(func.count()).select_from(ClaimSnapshot))
    ).scalar() or 0
    if existing:
        return 0

    rows = (
        await session.execute(
            select(
                ClaimEvidence.canonical_claim_id,
                ClaimEvidence.canonical_source_id,
                ClaimEvidence.report_id,
                Report.created_at,
            )
            .outerjoin(Report, ClaimEvidence.report_id == Report.id)
            .order_by(
                ClaimEvidence.canonical_claim_id,
                Report.created_at.asc().nulls_first(),
                ClaimEvidence.id.asc(),
            )
        )
    ).all()

    by_claim: Dict[int, List[tuple]] = {}
    for cid, sid, rid, created in rows:
        by_claim.setdefault(cid, []).append((rid, created, sid))

    inserted = 0
    for cid, evs in by_claim.items():
        # Bucket this claim's evidence by contributing report, preserving the
        # chronological order the rows already arrived in.
        buckets: "OrderedDict[Any, Dict[str, Any]]" = OrderedDict()
        for rid, created, sid in evs:
            key = rid if rid is not None else "__null__"
            bucket = buckets.setdefault(
                key, {"ts": created, "rid": rid, "sources": set()}
            )
            bucket["sources"].add(sid)

        seen_sources: set = set()
        seen_reports = 0
        for bucket in buckets.values():
            seen_reports += 1
            seen_sources |= bucket["sources"]
            session.add(
                ClaimSnapshot(
                    canonical_claim_id=cid,
                    observed_at=bucket["ts"] if bucket["ts"] is not None else func.now(),
                    support_count=len(seen_sources),
                    report_count=seen_reports,
                    confidence=_confidence(len(seen_sources)),
                    report_id=bucket["rid"],
                )
            )
            inserted += 1

    await session.flush()
    return inserted
