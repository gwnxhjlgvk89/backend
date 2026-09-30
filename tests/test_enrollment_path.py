import asyncio
from datetime import timedelta

from sqlalchemy import event, func, select

from club import services
from club.models import Activity, Club, Enrollment, Outbox, utcnow
from club.services import consistency


def headers(tokens, uid=1, key="request-00000001"):
    return {"Authorization": f"Bearer {tokens[uid]}", "Idempotency-Key": key}


async def test_not_open_reports_wait(env):
    app, client, tokens = env
    async with app.state.sessions() as db, db.begin():
        (await db.get(Activity, 1)).starts_at = utcnow() + timedelta(seconds=2)
    r = await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens))
    assert r.status_code == 409
    error = r.json()["error"]
    assert error["code"] == "NOT_OPEN" and 0 < error["retry_after_ms"] <= 2000


async def test_concurrent_seats_and_exact_quota_events(env):
    app, client, tokens = env
    responses = await asyncio.gather(
        *(
            client.post(
                "/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens, i, f"request-{i:08d}")
            )
            for i in range(1, 51)
        )
    )
    assert sum(r.status_code == 200 for r in responses) == 20
    assert {r.json()["error"]["code"] for r in responses if r.status_code != 200} == {"CLUB_FULL"}
    async with app.state.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Enrollment)) == 20
        assert await consistency(db) == []
        payloads = [p for p in await db.scalars(select(Outbox.payload)) if p["event"] == "quota"]
    # One event per seat, each carrying that transaction's own remaining/version.
    assert sorted((p["remaining"], p["version"]) for p in payloads) == sorted((20 - v, 1 + v) for v in range(1, 21))


async def test_full_club_rejects_without_club_lock(env):
    app, client, tokens = env
    assert (
        await client.post("/api/v1/enrollment", json={"club_id": 1}, headers=headers(tokens, 1))
    ).status_code == 200
    statements = []

    def observed(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(app.state.engine.sync_engine, "before_cursor_execute", observed)
    try:
        r = await client.post("/api/v1/enrollment", json={"club_id": 1}, headers=headers(tokens, 2))
    finally:
        event.remove(app.state.engine.sync_engine, "before_cursor_execute", observed)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CLUB_FULL"
    assert not [s for s in statements if s.startswith(("UPDATE v2_clubs", "INSERT"))]


async def test_replay_after_club_fills_returns_original_result(env):
    app, client, tokens = env
    first = await client.post("/api/v1/enrollment", json={"club_id": 1}, headers=headers(tokens, 1))
    assert (
        await client.post("/api/v1/enrollment", json={"club_id": 1}, headers=headers(tokens, 2))
    ).status_code == 409
    replay = await client.post("/api/v1/enrollment", json={"club_id": 1}, headers=headers(tokens, 1))
    assert first.status_code == replay.status_code == 200 and first.json() == replay.json()


async def test_cancel_event_restores_quota(env):
    app, client, tokens = env
    await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens))
    r = await client.delete("/api/v1/enrollment", headers=headers(tokens, key="cancel-00000001"))
    assert r.status_code == 200 and r.json()["data"]["status"] == "cancelled"
    async with app.state.sessions() as db:
        assert (await db.get(Club, 2)).remaining == 20
        quotas = [p for p in await db.scalars(select(Outbox.payload).order_by(Outbox.id)) if p["event"] == "quota"]
    assert [(p["remaining"], p["version"]) for p in quotas] == [(19, 2), (20, 3)]


async def test_exhausted_slots_wait_then_report_busy(env, monkeypatch):
    app, client, tokens = env
    monkeypatch.setattr(services, "SLOT_WAIT_SECONDS", 0.2)
    slots = app.state.enrollment_slots
    held = 0
    while not slots.locked():
        await slots.acquire()
        held += 1
    try:
        r = await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens))
        assert r.status_code == 503 and r.json()["error"]["code"] == "DATABASE_BUSY"
    finally:
        for _ in range(held):
            slots.release()
    async with app.state.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Enrollment)) == 0
    assert (
        await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens))
    ).status_code == 200
