"""Shared fixtures for API route tests.

The strategy keeps tests fast and offline:
  • an in-memory SQLite DB (StaticPool so every session shares one DB),
  • a fresh FastAPI app mounting ONLY the REST router — no lifespan, so the
    Postgres-only init_db migrations and orphan reconciler never run,
  • get_session overridden to hand out test sessions,
  • run_pipeline monkeypatched to an async no-op, so the BackgroundTasks kickoff
    in create_report never touches Tavily or Anthropic.
"""
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import api.routes as routes
from db.database import Base, get_session


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(session_factory, monkeypatch):
    # Inert pipeline: the background task runs but does nothing.
    async def _noop_pipeline(*args, **kwargs):
        return None

    monkeypatch.setattr(routes, "run_pipeline", _noop_pipeline)

    async def _override_get_session():
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_session] = _override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session(session_factory):
    """Direct DB access for seeding rows in tests."""
    async with session_factory() as session:
        yield session
