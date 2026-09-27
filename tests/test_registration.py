import asyncio
from datetime import timedelta

from sqlalchemy import func, select

from club.models import Activity, Club, Enrollment, Idempotency, Outbox, utcnow
from club.services import consistency


def headers(tokens, uid=1, key="request-00000001"):
    return {"Authorization": f"Bearer {tokens[uid]}", "Idempotency-Key": key}


async def test_last_seat_only_one(env):
    app, client, tokens = env
    responses = await asyncio.gather(
        *(
            client.post(
                "/api/v1/enrollment", json={"club_id": 1}, headers=headers(tokens, i, f"request-{i:08d}")
            )
            for i in range(1, 51)
        )
    )
    assert sum(r.status_code == 200 for r in responses) == 1
    assert all(r.status_code in (200, 409) for r in responses)
    async with app.state.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Enrollment)) == 1
        assert await consistency(db) == []


async def test_same_student_two_clubs(env):
    app, client, tokens = env
    responses = await asyncio.gather(
        *(
            client.post(
                "/api/v1/enrollment", json={"club_id": i}, headers=headers(tokens, 1, f"request-{i:08d}")
            )
            for i in (1, 2)
        )
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    async with app.state.sessions() as db:
        assert await consistency(db) == []


async def test_replay_and_payload_conflict(env):
    app, client, tokens = env
    a = await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens))
    b = await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens))
    c = await client.post("/api/v1/enrollment", json={"club_id": 1}, headers=headers(tokens))
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert c.status_code == 409
    async with app.state.sessions() as db:
        assert (await db.get(Club, 2)).remaining == 19
        assert await db.scalar(select(func.count()).select_from(Idempotency)) == 1


async def test_cancel_replay_does_not_inflate_quota(env):
    app, client, tokens = env
    await client.post("/api/v1/enrollment", json={"club_id": 1}, headers=headers(tokens))
    hs = headers(tokens, key="cancel-00000001")
    a = await client.delete("/api/v1/enrollment", headers=hs)
    b = await client.delete("/api/v1/enrollment", headers=hs)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    async with app.state.sessions() as db:
        assert await consistency(db) == []


async def test_time_major_and_reserved(env):
    app, client, tokens = env
    async with app.state.sessions() as db, db.begin():
        c = await db.get(Club, 1)
        c.allowed_majors = ["Arts"]
    assert (
        await client.post("/api/v1/enrollment", json={"club_id": 1}, headers=headers(tokens))
    ).status_code == 403
    async with app.state.sessions() as db, db.begin():
        a = await db.get(Activity, 1)
        a.ends_at = utcnow() - timedelta(seconds=1)
    assert (
        await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens))
    ).status_code == 409


async def test_permissions_and_no_sensitive_fields(env):
    app, client, tokens = env
    assert (await client.get("/api/v1/admin/students")).status_code == 401
    assert (await client.get("/api/v1/admin/students", headers=headers(tokens))).status_code == 403
    r = await client.get("/api/v1/admin/students", headers=headers(tokens, 100))
    assert r.status_code == 200
    assert len(r.json()["data"]["items"]) == 30
    assert "password_hash" not in r.text and "token_version" not in r.text
    assert (
        await client.post(
            "/api/v1/admin/activity/state", json={"state": "paused"}, headers=headers(tokens, 100)
        )
    ).status_code == 403
    assert (await client.delete("/api/v1/admin/students/1", headers=headers(tokens, 101))).status_code == 409
    assert (await client.post("/admin/create")).status_code == 426


async def test_pause_then_edit_and_ticket_single_use(env):
    app, client, tokens = env
    r = await client.post(
        "/api/v1/admin/activity/state", json={"state": "paused"}, headers=headers(tokens, 101)
    )
    assert r.status_code == 200
    r = await client.put(
        "/api/v1/admin/clubs/1", json={"name": "Renamed", "capacity": 5}, headers=headers(tokens, 100)
    )
    assert r.status_code == 200
    ticket = (await client.post("/api/v1/auth/ws-ticket", headers=headers(tokens))).json()["data"]["ticket"]
    key = f"club:test:ticket:{ticket}"
    assert await app.state.redis.getdel(key)
    assert await app.state.redis.getdel(key) is None


async def test_outbox_and_committed_status(env):
    app, client, tokens = env
    r = await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens))
    assert r.status_code == 200
    assert (await client.get("/api/v1/enrollment", headers=headers(tokens))).json()["data"]["club_id"] == 2
    async with app.state.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Outbox)) == 2


async def test_login_and_password_validation_redacts_input(env):
    app, client, tokens = env
    r = await client.post("/api/v1/auth/login", json={"username": "user1", "password": "SyntheticPass2026!"})
    assert r.status_code == 200
    assert (await client.get("/api/v1/bootstrap", headers=headers(tokens))).status_code == 401
    r = await client.post(
        "/api/v1/auth/login", json={"username": "user1", "password": "sensitive", "unexpected": True}
    )
    assert r.status_code == 422 and "sensitive" not in r.text
