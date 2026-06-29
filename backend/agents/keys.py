"""Per-request API key resolution — the core of bring-your-own-key (BYOK).

A pipeline run can carry the caller's own Anthropic / Tavily / Voyage keys so the
usage is billed to *them*, not the server. The keys are stashed in contextvars at
the top of ``run_pipeline`` and read wherever a client is constructed; when unset
we fall back to the server's environment keys.

Keys are held only in process memory for the life of the run — never logged,
never written to the database.
"""
from __future__ import annotations

import contextvars
import os
from typing import Optional

_anthropic: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "byok_anthropic", default=None
)
_tavily: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "byok_tavily", default=None
)
_voyage: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "byok_voyage", default=None
)


def set_request_keys(
    anthropic: Optional[str] = None,
    tavily: Optional[str] = None,
    voyage: Optional[str] = None,
) -> None:
    """Bind caller-supplied keys to the current async context (a no-op for any
    key left blank, which then falls back to the server env)."""
    if anthropic:
        _anthropic.set(anthropic)
    if tavily:
        _tavily.set(tavily)
    if voyage:
        _voyage.set(voyage)


def anthropic_key() -> Optional[str]:
    return _anthropic.get() or os.getenv("ANTHROPIC_API_KEY")


def tavily_key() -> Optional[str]:
    return _tavily.get() or os.getenv("TAVILY_API_KEY")


def voyage_key() -> Optional[str]:
    return _voyage.get() or os.getenv("VOYAGE_API_KEY")
