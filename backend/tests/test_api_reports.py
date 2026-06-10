"""Route tests for POST /reports and the report GETs — validation, mode/scope
coercion, thread auto-creation, and 404s. The pipeline is mocked (see conftest),
so these assert API behaviour only, never real research."""
import pytest


async def test_empty_query_rejected(client):
    r = await client.post("/reports", json={"query": "   "})
    assert r.status_code == 400


async def test_valid_deep_report_defaults(client):
    r = await client.post("/reports", json={"query": "what is creatine"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["mode"] == "deep"
    assert body["source_scope"] == "web"
    # A new thread is opened and returned when none is supplied.
    assert body["thread_id"] is not None


async def test_mode_and_scope_coercion(client):
    r = await client.post(
        "/reports",
        json={"query": "x", "mode": "garbage", "source_scope": "garbage"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["mode"] == "deep"  # invalid mode -> default
    assert body["source_scope"] == "web"  # invalid scope -> default


async def test_basic_pubmed_persisted_and_echoed(client):
    r = await client.post(
        "/reports",
        json={"query": "creatine safety", "mode": "basic", "source_scope": "pubmed"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["mode"] == "basic"
    assert body["source_scope"] == "pubmed"

    # And it round-trips through the full GET.
    full = await client.get(f"/reports/{body['id']}")
    assert full.status_code == 200
    fb = full.json()
    assert fb["mode"] == "basic"
    assert fb["source_scope"] == "pubmed"


async def test_unknown_thread_id_404(client):
    r = await client.post("/reports", json={"query": "x", "thread_id": 99999})
    assert r.status_code == 404


async def test_get_missing_report_and_subresources_404(client):
    assert (await client.get("/reports/99999")).status_code == 404
    assert (await client.get("/reports/99999/sources")).status_code == 404
    assert (await client.get("/reports/99999/conflicts")).status_code == 404
    assert (await client.get("/reports/99999/gaps")).status_code == 404


async def test_subresources_empty_for_fresh_report(client):
    created = (await client.post("/reports", json={"query": "x"})).json()
    rid = created["id"]
    # Pipeline is mocked, so no sources/conflicts/gaps were produced.
    assert (await client.get(f"/reports/{rid}/sources")).json() == []
    assert (await client.get(f"/reports/{rid}/conflicts")).json() == []
    assert (await client.get(f"/reports/{rid}/gaps")).json() == []
