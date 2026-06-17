"""Cost-control gate tests: per-user monthly cap, global daily ceiling, and the
basic-mode bypass. The pipeline is mocked (see conftest), and the caps are
monkeypatched to small values so we don't have to seed dozens of rows."""
import api.routes as routes


async def test_per_user_monthly_cap(client, monkeypatch):
    monkeypatch.setattr(routes, "FREE_DEEP_RUNS_PER_MONTH", 2)
    monkeypatch.setattr(routes, "GLOBAL_DAILY_DEEP_RUNS", None)  # isolate per-user

    for _ in range(2):
        r = await client.post("/reports", json={"query": "creatine safety"})
        assert r.status_code == 201

    blocked = await client.post("/reports", json={"query": "one too many"})
    assert blocked.status_code == 429
    assert "monthly limit" in blocked.json()["detail"].lower()


async def test_global_daily_ceiling(client, monkeypatch):
    # Generous per-user limit so the GLOBAL ceiling is what trips.
    monkeypatch.setattr(routes, "FREE_DEEP_RUNS_PER_MONTH", 100)
    monkeypatch.setattr(routes, "GLOBAL_DAILY_DEEP_RUNS", 1)

    first = await client.post("/reports", json={"query": "q1"})
    assert first.status_code == 201

    blocked = await client.post("/reports", json={"query": "q2"})
    assert blocked.status_code == 429
    assert "capacity" in blocked.json()["detail"].lower()


async def test_basic_mode_is_unmetered(client, monkeypatch):
    # Even with the deep allowance exhausted (limit 0), basic answers flow.
    monkeypatch.setattr(routes, "FREE_DEEP_RUNS_PER_MONTH", 0)
    monkeypatch.setattr(routes, "GLOBAL_DAILY_DEEP_RUNS", 1)

    deep = await client.post("/reports", json={"query": "x", "mode": "deep"})
    assert deep.status_code == 429

    basic = await client.post("/reports", json={"query": "x", "mode": "basic"})
    assert basic.status_code == 201
    assert basic.json()["mode"] == "basic"
