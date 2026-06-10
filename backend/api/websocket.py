"""WebSocket connection manager + in-memory event bus.

The pipeline runs as a background task and emits events through this bus. Each
event is (1) persisted to `agent_logs` by the caller and (2) broadcast to every
WebSocket currently subscribed to that report.

Because a client may connect to the WS endpoint a moment *after* the pipeline
has already started, we keep a per-report buffer of events and replay it to any
newly-connected socket. This guarantees the live feed never drops the opening
"Layer 1" lines.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Dict, List, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: Dict[int, Set[WebSocket]] = defaultdict(set)
        self._buffers: Dict[int, List[dict]] = defaultdict(list)
        self._done: Set[int] = set()
        self._lock = asyncio.Lock()

    async def connect(self, report_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[report_id].add(websocket)
            backlog = list(self._buffers.get(report_id, []))
            already_done = report_id in self._done
        # Replay everything that happened before this socket connected.
        for event in backlog:
            await websocket.send_json(event)
        if already_done:
            await websocket.send_json({"type": "complete", "report_id": report_id})

    async def disconnect(self, report_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[report_id].discard(websocket)

    async def broadcast(self, report_id: int, event: dict) -> None:
        async with self._lock:
            self._buffers[report_id].append(event)
            targets = list(self._connections.get(report_id, set()))
        dead: List[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections[report_id].discard(ws)

    async def mark_complete(self, report_id: int) -> None:
        async with self._lock:
            self._done.add(report_id)
        await self.broadcast(
            report_id, {"type": "complete", "report_id": report_id}
        )

    def cleanup(self, report_id: int) -> None:
        """Drop buffered state for a report once nobody needs it."""
        self._buffers.pop(report_id, None)
        self._done.discard(report_id)
        self._connections.pop(report_id, None)


manager = ConnectionManager()


ws_router = APIRouter()


@ws_router.websocket("/ws/reports/{report_id}")
async def report_feed(websocket: WebSocket, report_id: int) -> None:
    """Live agent feed for a report. Replays any buffered events on connect,
    then streams new ones until the client disconnects."""
    await manager.connect(report_id, websocket)
    try:
        while True:
            # We don't expect client messages; this keeps the socket open and
            # lets us detect disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(report_id, websocket)
    except Exception:
        await manager.disconnect(report_id, websocket)
