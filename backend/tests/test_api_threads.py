"""Route tests for the thread endpoints."""
from db.models import Report, Thread


async def test_create_thread(client):
    r = await client.post("/threads")
    assert r.status_code == 201
    assert r.json()["title"] == "New research"


async def test_list_threads_newest_first(client, db_session):
    db_session.add_all([Thread(title="oldest"), Thread(title="newest")])
    await db_session.commit()

    r = await client.get("/threads")
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()]
    # Route orders by id descending.
    assert titles == ["newest", "oldest"]


async def test_get_missing_thread_404(client):
    assert (await client.get("/threads/99999")).status_code == 404


async def test_get_thread_includes_reports_with_mode_and_scope(client, db_session):
    thread = Thread(title="t")
    db_session.add(thread)
    await db_session.commit()
    await db_session.refresh(thread)

    db_session.add(
        Report(
            query="q1",
            status="completed",
            mode="basic",
            source_scope="arxiv",
            thread_id=thread.id,
        )
    )
    await db_session.commit()

    r = await client.get(f"/threads/{thread.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "t"
    assert len(body["reports"]) == 1
    rep = body["reports"][0]
    assert rep["query"] == "q1"
    assert rep["mode"] == "basic"
    assert rep["source_scope"] == "arxiv"
