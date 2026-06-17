"""Route tests for the thread endpoints (history is scoped to the owner)."""
from db.models import Report, Thread


async def test_create_thread(client):
    r = await client.post("/threads")
    assert r.status_code == 201
    assert r.json()["title"] == "New research"


async def test_list_threads_newest_first(client, db_session, test_user):
    db_session.add_all(
        [
            Thread(title="oldest", user_id=test_user.id),
            Thread(title="newest", user_id=test_user.id),
        ]
    )
    await db_session.commit()

    r = await client.get("/threads")
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()]
    # Route orders by id descending.
    assert titles == ["newest", "oldest"]


async def test_get_missing_thread_404(client):
    assert (await client.get("/threads/99999")).status_code == 404


async def test_get_thread_includes_reports_with_mode_and_scope(
    client, db_session, test_user
):
    thread = Thread(title="t", user_id=test_user.id)
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


async def test_threads_are_scoped_to_owner(client, db_session, test_user):
    """A thread owned by another account must never be listed or fetchable."""
    others = Thread(title="someone else's thread", user_id=test_user.id + 999)
    db_session.add(others)
    await db_session.commit()
    await db_session.refresh(others)

    listed = (await client.get("/threads")).json()
    assert all(t["title"] != "someone else's thread" for t in listed)

    # And it can't be opened directly by id either (404, not 403).
    assert (await client.get(f"/threads/{others.id}")).status_code == 404
