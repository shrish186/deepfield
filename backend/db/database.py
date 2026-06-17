"""Async SQLAlchemy engine, session factory, and Base."""
import os

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# Normalise the DATABASE_URL to the async driver. We accept the standard
# `postgresql://` form (e.g. from docker-compose / Heroku) and rewrite it to
# use asyncpg, which is what the async engine requires.
def normalise_db_url(raw: str) -> str:
    """Rewrite a sync Postgres URL to the asyncpg driver the async engine needs.

    `postgresql://` and the Heroku-style `postgres://` are rewritten to
    `postgresql+asyncpg://`. URLs that already name an async driver — or any
    non-postgres URL (e.g. `sqlite+aiosqlite://` in tests) — pass through
    untouched."""
    if raw.startswith("postgresql+asyncpg://"):
        return raw
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql+asyncpg://", 1)
    return raw


RAW_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:password@localhost:5432/deepfield"
)
DATABASE_URL = normalise_db_url(RAW_DATABASE_URL)


class Base(DeclarativeBase):
    pass


engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


async def init_db() -> None:
    """Create all tables. Called on application startup."""
    # Import models so they register on Base.metadata before create_all.
    from db import models  # noqa: F401
    from sqlalchemy import text

    async with engine.begin() as conn:
        # pgvector must exist before create_all so the Vector columns on the
        # disagreement-graph tables can be created. Harmless if already present.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight, idempotent migration for the thread/follow-up columns so
        # existing `reports` tables pick up the new fields without a drop.
        for stmt in (
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS thread_id INTEGER "
            "REFERENCES threads(id) ON DELETE CASCADE",
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS parent_report_id INTEGER "
            "REFERENCES reports(id) ON DELETE SET NULL",
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS context TEXT",
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS mode VARCHAR(16) "
            "DEFAULT 'deep'",
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS source_scope VARCHAR(16) "
            "DEFAULT 'web'",
            "CREATE INDEX IF NOT EXISTS ix_reports_thread_id ON reports(thread_id)",
            # Controversy label for grouping near-identical conflicts (Layer 4).
            "ALTER TABLE conflicts ADD COLUMN IF NOT EXISTS topic VARCHAR(120)",
            # Bibliographic / trust metadata on sources (academic upgrade).
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS source_type VARCHAR(16) "
            "DEFAULT 'web'",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS authors TEXT",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS year INTEGER",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS venue TEXT",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS doi TEXT",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS citation_count INTEGER",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS peer_reviewed BOOLEAN "
            "DEFAULT FALSE",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS retracted BOOLEAN "
            "DEFAULT FALSE",
            # Per-report search controls (date filter + domain allow/blocklist).
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS year_min INTEGER",
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS include_domains TEXT",
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS exclude_domains TEXT",
            # Report ownership — drives the per-user monthly deep-run credit gate.
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS user_id INTEGER "
            "REFERENCES users(id) ON DELETE SET NULL",
            "CREATE INDEX IF NOT EXISTS ix_reports_user_id ON reports(user_id)",
            # Thread ownership — scopes the history list/detail to the user.
            "ALTER TABLE threads ADD COLUMN IF NOT EXISTS user_id INTEGER "
            "REFERENCES users(id) ON DELETE CASCADE",
            "CREATE INDEX IF NOT EXISTS ix_threads_user_id ON threads(user_id)",
            # ANN index for cosine similarity over canonical claim embeddings.
            # Created outside create_all because it needs the pgvector opclass.
            "CREATE INDEX IF NOT EXISTS ix_canonical_claims_embedding "
            "ON canonical_claims USING hnsw (embedding vector_cosine_ops)",
        ):
            await conn.execute(text(stmt))


async def get_session() -> AsyncSession:
    """FastAPI dependency that yields a request-scoped async session."""
    async with AsyncSessionLocal() as session:
        yield session
