"""Voyage AI embeddings — the semantic backbone of the disagreement graph.

This is the single chokepoint that decides whether the whole graph layer is
*live* or *dormant*. Everything here is lazy and fail-soft: if ``VOYAGE_API_KEY``
is absent, the client never initialises, every function returns empty/``None``,
and the callers (layer0 recall, layer6 graph writer, basic mode) treat that as
"skip the graph". Deep/basic reports then run exactly as they did before the
graph existed — no crashes, no hard dependency.

The dimension constant lives here because it's defined by the embedding model;
``db.models`` imports it for the ``Vector`` column so the schema and the vectors
can never drift apart.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

# voyage-3 emits 1024-dim vectors. Override both together if you swap models.
EMBED_MODEL = os.getenv("DEEPFIELD_EMBED_MODEL", "voyage-3")
EMBED_DIM = int(os.getenv("DEEPFIELD_EMBED_DIM", "1024"))

# Voyage caps a single request at 128 inputs; batch larger lists.
_MAX_BATCH = 128

_clients: dict = {}  # key -> voyageai.AsyncClient
_warned = False


def has_embeddings() -> bool:
    """True when a key is available (caller's BYOK key or the server env) — the
    cheap gate callers check first so they can skip the graph entirely."""
    from agents.keys import voyage_key

    return bool(voyage_key())


def _get_client():
    """Lazily build the async Voyage client for the active key. Returns ``None``
    (and warns once) when no key is set, mirroring ``agents/base.py``."""
    global _warned
    from agents.keys import voyage_key

    key = voyage_key()
    if not key:
        if not _warned:
            logger.info("VOYAGE_API_KEY not set — disagreement graph is dormant")
            _warned = True
        return None
    client = _clients.get(key)
    if client is None:
        # Imported lazily so a missing/broken voyageai install can never take
        # down model import or the rest of the app.
        import voyageai

        client = voyageai.AsyncClient(api_key=key)
        _clients[key] = client
    return client


async def embed_texts(
    texts: List[str], *, input_type: str = "document"
) -> List[List[float]]:
    """Embed a list of texts, batched. Returns vectors aligned 1:1 with ``texts``,
    or an empty list if embeddings are unavailable / the call failed — callers
    treat ``[]`` as "skip the graph"."""
    client = _get_client()
    if client is None or not texts:
        return []
    try:
        out: List[List[float]] = []
        for i in range(0, len(texts), _MAX_BATCH):
            batch = texts[i : i + _MAX_BATCH]
            resp = await client.embed(batch, model=EMBED_MODEL, input_type=input_type)
            out.extend(resp.embeddings)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Voyage embed_texts failed (%d texts): %s", len(texts), exc)
        return []


async def embed_query(text: str) -> Optional[List[float]]:
    """Embed a single query string for ANN recall. Returns ``None`` when
    unavailable so the recall layer can no-op."""
    vecs = await embed_texts([text], input_type="query")
    return vecs[0] if vecs else None
