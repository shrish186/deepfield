"""Shared utilities for the five agent layers.

Holds the Claude client wrapper, a robust JSON extractor for tool-free LLM
output, and the AgentContext that threads the report id, the streaming `emit`
callback, and a DB session factory through every layer.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from anthropic import AsyncAnthropic

from api.websocket import manager
from db.database import AsyncSessionLocal
from db.models import AgentLog

MODEL = os.getenv("DEEPFIELD_MODEL", "claude-sonnet-4-6")
# Cheaper, faster model used by "basic" mode to keep per-question cost low.
BASIC_MODEL = os.getenv("DEEPFIELD_BASIC_MODEL", "claude-haiku-4-5")

# Stay safely under the account's input-tokens-per-minute tier limit. This key
# is on **Anthropic tier 2** (≈450k ITPM for Sonnet), so we budget 400k to leave
# headroom for burst + the SDK's own retries. Override with DEEPFIELD_INPUT_TPM
# if the account moves tiers (tier 1 ≈ 30k; tier 3/4 ≈ 800k–2M).
INPUT_TPM = int(os.getenv("DEEPFIELD_INPUT_TPM", "400000"))

# One client per distinct API key (env key, plus any bring-your-own-key callers).
_clients: dict[str, AsyncAnthropic] = {}


class _TokenRateLimiter:
    """Token-bucket limiter for *input* tokens per minute.

    Every Claude call reserves its estimated input-token cost before firing.
    When the bucket is empty, callers wait. This keeps our aggregate request
    rate under the Anthropic tier limit and prevents 429s instead of relying
    purely on retry-after backoff.
    """

    def __init__(self, tokens_per_min: int) -> None:
        self.capacity = float(tokens_per_min)
        self.tokens = float(tokens_per_min)
        self.refill_per_sec = tokens_per_min / 60.0
        self.updated = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self, amount: int) -> None:
        # Never let a single request deadlock by asking for more than capacity.
        amount = min(float(amount), self.capacity)
        async with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(
                    self.capacity, self.tokens + (now - self.updated) * self.refill_per_sec
                )
                self.updated = now
                if self.tokens >= amount:
                    self.tokens -= amount
                    return
                wait = (amount - self.tokens) / self.refill_per_sec
                await asyncio.sleep(min(wait, 5.0))


_limiter = _TokenRateLimiter(INPUT_TPM)


def get_client() -> AsyncAnthropic:
    # Resolve the active key (caller's BYOK key, else the server env key) and
    # reuse one client per key. max_retries gives the SDK room to back off on
    # any residual 429s (e.g. the separate output-tokens/min limit).
    from agents.keys import anthropic_key

    key = anthropic_key() or ""
    client = _clients.get(key)
    if client is None:
        client = AsyncAnthropic(api_key=key or None, max_retries=6)
        _clients[key] = client
    return client


def _estimate_input_tokens(prompt: str, system: str) -> int:
    # ~4 chars/token is a good rough heuristic for English text.
    return (len(prompt) + len(system)) // 4 + 16


async def claude_complete(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: int = 2000,
    temperature: float = 0.2,
    model: Optional[str] = None,
    cache_system: bool = True,
) -> str:
    """Single-turn Claude completion returning the concatenated text.

    Rate-limited against INPUT_TPM so concurrent layer-2 reads don't trip the
    account's per-minute token limit. `model` defaults to the deep-research
    model; basic mode passes BASIC_MODEL for a cheaper, faster answer.

    When `cache_system` is set (the default) the system prompt is sent as an
    ephemeral-cached block. Layers that fan out many calls with an identical
    system prompt (notably Layer 2's per-source reads) then pay full price only
    on the first call and read the cached prefix on the rest — lower latency and
    cost. Caching silently no-ops when the prefix is below the model's minimum,
    so it's always safe to leave on.
    """
    system = system or "You are a precise research analyst."
    await _limiter.acquire(_estimate_input_tokens(prompt, system))
    system_param = (
        [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if cache_system
        else system
    )
    resp = await get_client().messages.create(
        model=model or MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_param,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    ).strip()


async def build_search_query(query: str, context: str = "") -> str:
    """Turn a possibly-conversational follow-up into a standalone search query.

    A follow-up like "but does it really matter tho" is meaningless to a search
    engine on its own — without the thread's topic it returns unrelated sources.
    When `context` is present we cheaply rewrite the message into a self-contained
    query using the fast model. No-op (returns `query`) when there's no context.
    """
    if not context:
        return query
    try:
        rewritten = await claude_complete(
            f'Conversation context:\n{context}\n\nFollow-up message: "{query}"\n\n'
            "Rewrite the follow-up as a single, standalone web-search query that "
            "captures the real topic and intent. Output ONLY the query text — no "
            "quotes, no preamble.",
            system="You rewrite conversational follow-ups into standalone web-search queries.",
            max_tokens=60,
            model=BASIC_MODEL,
        )
        rewritten = rewritten.strip().strip('"').splitlines()[0].strip()
        return rewritten or query
    except Exception:  # noqa: BLE001
        # Fall back to appending the context so the search still has the topic.
        return f"{query} {context}"


def extract_json(text: str) -> Any:
    """Best-effort JSON extraction from an LLM response.

    Handles ```json fences, leading prose, and trailing commentary by locating
    the outermost JSON array or object.
    """
    if not text:
        raise ValueError("empty LLM response")

    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fall back to slicing the first balanced array/object.
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    # Last resort: salvage a truncated JSON array (common when the model hits
    # max_tokens mid-output) by keeping elements up to the last complete object.
    start = text.find("[")
    if start != -1:
        last_obj = text.rfind("}")
        if last_obj > start:
            salvaged = text[start : last_obj + 1] + "]"
            try:
                return json.loads(salvaged)
            except json.JSONDecodeError:
                pass

    raise ValueError(f"could not parse JSON from LLM response: {text[:200]}")


@dataclass
class AgentContext:
    """Threaded through every LangGraph node."""

    report_id: int
    emit: Callable[..., Awaitable[None]]


def make_emit(report_id: int) -> Callable[..., Awaitable[None]]:
    """Build an emit() bound to a report: persists a log row and broadcasts."""

    async def emit(layer: int, agent_name: str, message: str) -> None:
        ts = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as session:
            session.add(
                AgentLog(
                    report_id=report_id,
                    layer=layer,
                    agent_name=agent_name,
                    message=message,
                )
            )
            await session.commit()
        await manager.broadcast(
            report_id,
            {
                "type": "log",
                "report_id": report_id,
                "layer": layer,
                "agent": agent_name,
                "message": message,
                "timestamp": ts.isoformat(),
            },
        )

    return emit
