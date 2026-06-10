"""Deepfield — FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import update

from api.auth import router as auth_router
from api.routes import router as rest_router
from api.websocket import ws_router
from db.database import AsyncSessionLocal, init_db
from db.models import Report


async def _backfill_claim_history() -> None:
    """Reconstruct claim-evolution snapshots for claims that predate snapshot
    tracking. Idempotent (no-ops once snapshots exist) and fail-soft so a
    backfill hiccup never blocks startup."""
    try:
        from agents.graph_store import backfill_claim_snapshots

        async with AsyncSessionLocal() as session:
            inserted = await backfill_claim_snapshots(session)
            if inserted:
                await session.commit()
    except Exception:  # noqa: BLE001 — backfill is best-effort
        pass


async def _fail_orphaned_reports() -> None:
    """A report's pipeline runs as an in-process background task, so it cannot
    survive a restart. Any report still 'pending' or 'running' at startup is
    therefore stale — mark it 'failed' so the UI never shows a perpetual spinner."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Report)
            .where(Report.status.in_(["pending", "running"]))
            .values(status="failed")
        )
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _fail_orphaned_reports()
    await _backfill_claim_history()
    yield


app = FastAPI(title="Deepfield", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest_router)
app.include_router(ws_router)
app.include_router(auth_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
