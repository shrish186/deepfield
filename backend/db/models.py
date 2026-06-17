"""SQLAlchemy ORM models for the Deepfield research pipeline."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agents.embeddings import EMBED_DIM
from db.database import Base

# pgvector's SQLAlchemy type. The column emits ``VECTOR(n)`` DDL; on Postgres it
# needs the ``vector`` extension (created in init_db). On SQLite (tests) the type
# name is accepted and stored loosely — the graph tables are never queried there.
try:  # pragma: no cover - import guard
    from pgvector.sqlalchemy import Vector
except Exception:  # noqa: BLE001 - keep model import working without the package
    Vector = None  # type: ignore


class Thread(Base):
    """A persistent research conversation. Holds an ordered series of reports —
    the first query plus any follow-ups or drill-downs the user runs."""

    __tablename__ = "threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # Owner of the conversation. Nullable so pre-auth threads stay valid; the
    # API scopes the history list and thread detail to the signed-in user.
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    reports: Mapped[List["Report"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="Report.id",
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    # pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # "deep" (full 5-layer chain, Sonnet) or "basic" (quick single-pass, Haiku).
    mode: Mapped[str] = mapped_column(String(16), default="deep")
    # Search corpus: "web" | "academic" | "pubmed" | "arxiv" (see agents/scopes).
    source_scope: Mapped[str] = mapped_column(String(16), default="web")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    thread_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Owner of this report. Nullable so the ~50 pre-auth historical reports stay
    # valid; every newly created report is now stamped with the signed-in user,
    # which is what the monthly deep-run credit count is measured against.
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # When this report is a follow-up / drill-down, the report it branched from.
    parent_report_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("reports.id", ondelete="SET NULL"), nullable=True
    )
    # Background context fed to the pipeline for follow-ups (prior question, the
    # specific finding the user chose to drill into, etc.).
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Search controls (power-user filters) -----------------------------
    # Only keep sources published in/after this year (None = no date filter).
    year_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Comma-joined domain allowlist / blocklist applied on top of the scope.
    include_domains: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exclude_domains: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    thread: Mapped[Optional["Thread"]] = relationship(back_populates="reports")

    sources: Mapped[List["Source"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    claims: Mapped[List["Claim"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    conflicts: Mapped[List["Conflict"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    gaps: Mapped[List["Gap"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    sections: Mapped[List["ReportSection"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    logs: Mapped[List["AgentLog"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Core argument extracted in Layer 2.
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    credibility_score: Mapped[float] = mapped_column(Float, default=0.5)

    # --- Bibliographic / trust metadata -----------------------------------
    # Kind of source: "journal" (peer-reviewed), "preprint", "medical"
    # (gov/clinical body), "news", "web", or "pdf" (user upload). Drives the
    # peer-review badge and citation formatting.
    source_type: Mapped[str] = mapped_column(String(16), default="web")
    # Semicolon-joined author list ("Smith, J.; Doe, A."), best-effort.
    authors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Publication year, when known.
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Journal / conference / preprint server name.
    venue: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Digital Object Identifier, when resolvable.
    doi: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Citation count from Semantic Scholar (proxy for influence/impact).
    citation_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # True when the source is from a peer-reviewed venue.
    peer_reviewed: Mapped[bool] = mapped_column(default=False)
    # Flagged if the paper appears to have been retracted.
    retracted: Mapped[bool] = mapped_column(default=False)

    report: Mapped["Report"] = relationship(back_populates="sources")
    claims: Mapped[List["Claim"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=True, index=True
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    # 0..1 confidence built from cross-referencing in Layer 3.
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    # How many distinct sources support this claim (Layer 3).
    support_count: Mapped[int] = mapped_column(Integer, default=1)
    layer_origin: Mapped[int] = mapped_column(Integer, default=2)

    report: Mapped["Report"] = relationship(back_populates="claims")
    source: Mapped[Optional["Source"]] = relationship(back_populates="claims")


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    claim_a_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL"), nullable=True
    )
    claim_b_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL"), nullable=True
    )
    # Short controversy label (≤8 words) so near-identical contradictions can be
    # grouped into a handful of distinct disagreements rather than a flat list of
    # restatements. Nullable for rows that predate consolidation.
    topic: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    report: Mapped["Report"] = relationship(back_populates="conflicts")


class Gap(Base):
    __tablename__ = "gaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # "gap" (nothing explains it) or "open_question" (research raises it).
    kind: Mapped[str] = mapped_column(String(32), default="gap")

    report: Mapped["Report"] = relationship(back_populates="gaps")


class ReportSection(Base):
    __tablename__ = "report_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    # executive_summary | key_findings | conflicts | open_questions | sources
    section_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0)

    report: Mapped["Report"] = relationship(back_populates="sections")


# ---------------------------------------------------------------------------
# The disagreement graph — global, cross-report entities (the accumulating moat)
#
# Unlike everything above, these tables are NOT report-scoped. A report id is
# kept only as provenance on the edges; the nodes (canonical claims/sources) and
# the contradiction edges persist and compound across every report anyone runs.
# ---------------------------------------------------------------------------

# Use the real pgvector type when available; fall back to Text so the model
# still imports (and SQLite tests still create the table) without the package.
_EmbeddingType = Vector(EMBED_DIM) if Vector is not None else Text


class CanonicalSource(Base):
    """A source deduplicated across all reports by its normalised URL."""

    __tablename__ = "canonical_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url_normalized: Mapped[str] = mapped_column(Text, unique=True, index=True)
    domain: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Highest credibility we've ever scored this source at.
    credibility_score: Mapped[float] = mapped_column(Float, default=0.5)
    times_cited: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CanonicalClaim(Base):
    """A canonical claim — the graph's nodes. Semantically-equivalent claims
    from different reports collapse into one row via embedding similarity."""

    __tablename__ = "canonical_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[list]] = mapped_column(_EmbeddingType, nullable=True)
    # Distinct canonical sources backing this claim.
    support_count: Mapped[int] = mapped_column(Integer, default=0)
    # How many distinct reports have surfaced this claim.
    report_count: Mapped[int] = mapped_column(Integer, default=1)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ClaimEvidence(Base):
    """Edge: a canonical claim is supported by a canonical source. ``report_id``
    is provenance only (plain int, no FK) so the graph outlives any report."""

    __tablename__ = "claim_evidence"
    __table_args__ = (
        UniqueConstraint(
            "canonical_claim_id", "canonical_source_id", name="uq_claim_source"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_claim_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_claims.id", ondelete="CASCADE"), index=True
    )
    canonical_source_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_sources.id", ondelete="CASCADE"), index=True
    )
    # "supports" today; refute/contradict stance is future work.
    stance: Mapped[str] = mapped_column(String(16), default="supports")
    report_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ClaimLink(Base):
    """Edge: two canonical claims disagree. THE core moat artifact — its
    ``observed_count`` grows every time an independent report surfaces the same
    disagreement. The pair is stored ordered (a_id <= b_id) so (a,b) == (b,a)."""

    __tablename__ = "claim_links"
    __table_args__ = (
        UniqueConstraint(
            "claim_a_id", "claim_b_id", "relation", name="uq_claim_pair_relation"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_a_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_claims.id", ondelete="CASCADE"), index=True
    )
    claim_b_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_claims.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(String(32), default="contradicts")
    observed_count: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ClaimSnapshot(Base):
    """A point-in-time snapshot of a canonical claim's aggregate state, written
    each time a report contributes to it. The ordered series *is* the claim's
    evolution — how support and confidence moved as evidence accumulated, which
    is what tells a researcher whether the evidence is strengthening or weakening.
    History is reconstructed once at startup (backfill) and appended live after."""

    __tablename__ = "claim_snapshots"
    __table_args__ = (
        Index("ix_claim_snapshots_claim_time", "canonical_claim_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_claim_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_claims.id", ondelete="CASCADE"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    support_count: Mapped[int] = mapped_column(Integer, default=0)
    report_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # Provenance: which report triggered this snapshot (nullable for backfill).
    report_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class Comment(Base):
    """A lightweight note/comment on a report — the demoable core of
    collaboration. No auth yet: ``author`` is a free-text name so labmates can
    annotate a shared report link. ``anchor`` optionally pins the comment to a
    section or source for in-context discussion."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    author: Mapped[str] = mapped_column(String(80), default="Anonymous")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional pin: e.g. "section:conflicts" or "source:42". Free-text.
    anchor: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Optional follow-up assignment ("@alex"): the assignee's free-text name.
    assigned_to: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    resolved: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    """A registered account. Passwords are never stored in the clear — only a
    bcrypt hash. ``plan`` tracks the subscription tier (free/pro/team) and
    ``stripe_customer_id`` is reserved for the Stripe integration (kept null
    until a real checkout happens)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    plan: Mapped[str] = mapped_column(String(16), default="free")
    # Reserved for Stripe — populated when a customer is created at checkout.
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    layer: Mapped[int] = mapped_column(Integer, default=0)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    report: Mapped["Report"] = relationship(back_populates="logs")
