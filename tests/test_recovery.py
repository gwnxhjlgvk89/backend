import asyncio
from datetime import timedelta
from io import BytesIO
from unittest.mock import AsyncMock

from openpyxl import Workbook
from redis.exceptions import ConnectionError
from sqlalchemy import func, select

from club.jobs import run_one
from club.models import Activity, Club, Enrollment, Job, User, utcnow
from club.realtime import Hub
from club.services import consistency
from test_registration import headers


async def pause(client, tokens):
    assert (
        await client.post(
            "/api/v1/admin/activity/state", json={"state": "paused"}, headers=headers(tokens, 101)
        )
    ).status_code == 200


async def test_redis_outage_preserves_committed_result(env, monkeypatch):
    app, client, tokens = env
    assert (
        await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens))
    ).status_code == 200
    monkeypatch.setattr(app.state.redis, "eval", AsyncMock(side_effect=ConnectionError("test unavailable")))
    r = await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens, 2))
    assert r.status_code == 503
    r = await client.get("/api/v1/enrollment", headers=headers(tokens))
    assert r.json()["data"]["club_id"] == 2
    async with app.state.sessions() as db:
        assert await db.get(Enrollment, 2) is None
        assert await consistency(db) == []


async def test_reserved_cannot_cancel_and_role_guard(env):
    app, client, tokens = env
    async with app.state.sessions() as db, db.begin():
        db.add(Enrollment(student_id=1, club_id=1, source="reserved"))
        (await db.get(Club, 1)).remaining = 0
    assert (await client.delete("/api/v1/enrollment", headers=headers(tokens))).status_code == 403
    assert (
        await client.put(
            "/api/v1/admin/administrators/100", json={"role": "super_admin"}, headers=headers(tokens, 100)
        )
    ).status_code == 403
    assert (
        await client.put(
            "/api/v1/admin/administrators/101", json={"role": "admin"}, headers=headers(tokens, 101)
        )
    ).status_code == 409
    r = await client.put(
        "/api/v1/admin/administrators/100",
        json={"role": "admin", "active": False},
        headers=headers(tokens, 101),
    )
    assert r.status_code == 200
    assert (await client.get("/api/v1/admin/students", headers=headers(tokens, 100))).status_code == 401


async def test_login_logout_versions_and_password_bytes(env):
    app, client, tokens = env
    r = await client.post("/api/v1/auth/login", json={"username": "user1", "password": "SyntheticPass2026!"})
    new = {"Authorization": "Bearer " + r.json()["data"]["token"]}
    assert (await client.post("/api/v1/auth/logout", headers=headers(tokens))).status_code == 401
    assert (await client.get("/api/v1/bootstrap", headers=new)).status_code == 200
    assert (await client.post("/api/v1/auth/logout", headers=new)).status_code == 200
    assert (await client.get("/api/v1/bootstrap", headers=new)).status_code == 401
    r = await client.post(
        "/api/v1/admin/students",
        json={"username": "new", "name": "New", "password": "密" * 30},
        headers=headers(tokens, 101),
    )
    assert r.status_code == 422 and "密" not in r.text


async def test_cancel_and_select_race(env):
    app, client, tokens = env
    assert (
        await client.post("/api/v1/enrollment", json={"club_id": 1}, headers=headers(tokens))
    ).status_code == 200
    rs = await asyncio.gather(
        client.delete("/api/v1/enrollment", headers=headers(tokens, key="cancel-race-0001")),
        client.post(
            "/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens, key="select-race-0002")
        ),
    )
    assert rs[0].status_code == 200
    assert rs[1].status_code in (200, 409)
    async with app.state.sessions() as db:
        assert await consistency(db) == []
        assert (await db.get(Club, 1)).remaining == 1


async def test_time_boundaries(env, monkeypatch):
    app, client, tokens = env
    now = utcnow()
    async with app.state.sessions() as db, db.begin():
        a = await db.get(Activity, 1)
        a.starts_at, a.ends_at = now, now + timedelta(hours=1)
    monkeypatch.setattr("club.services.utcnow", lambda: now)
    assert (
        await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens))
    ).status_code == 200
    monkeypatch.setattr("club.services.utcnow", lambda: now + timedelta(hours=1))
    r = await client.post("/api/v1/enrollment", json={"club_id": 2}, headers=headers(tokens, 2))
    assert r.status_code == 409 and r.json()["error"]["code"] == "OUTSIDE_WINDOW"


def workbook(rows):
    w = Workbook()
    w.active.append(["username", "name", "major", "class_name", "password", "reserved_club_id"])
    for row in rows:
        w.active.append(row)
    out = BytesIO()
    w.save(out)
    return out.getvalue()


async def test_import_preview_atomic_rollback(env):
    app, client, tokens = env
    await pause(client, tokens)
    data = workbook(
        [
            ["new1", "Test 1", "CS", "A", "SyntheticPass2026!", 1],
            ["new2", "Test 2", "CS", "A", "SyntheticPass2026!", 2],
        ]
    )
    r = await client.post(
        "/api/v1/admin/jobs/import", files={"file": ("test.xlsx", data)}, headers=headers(tokens, 100)
    )
    assert r.status_code == 200 and r.json()["data"]["state"] == "queued"
    jid = r.json()["data"]["id"]
    await run_one(app.state.sessions)
    async with app.state.sessions() as db:
        j = await db.get(Job, jid)
        assert j.state == "preview" and "SyntheticPass2026!" not in str(j.payload)
    assert (
        await client.post(f"/api/v1/admin/jobs/{jid}/confirm", headers=headers(tokens, 100))
    ).status_code == 200
    # Conflict introduced after preview must roll back *all* imported students.
    async with app.state.sessions() as db, db.begin():
        (await db.get(Club, 2)).active = False
    await run_one(app.state.sessions)
    async with app.state.sessions() as db:
        assert (await db.get(Job, jid)).state == "failed"
        assert await db.scalar(select(func.count()).select_from(User).where(User.username.like("new%"))) == 0
        assert await consistency(db) == []


async def test_import_success_and_private_export(env):
    app, client, tokens = env
    await pause(client, tokens)
    data = workbook([["new1", "Test 1", "CS", "A", "SyntheticPass2026!", 1]])
    r = await client.post(
        "/api/v1/admin/jobs/import", files={"file": ("test.xlsx", data)}, headers=headers(tokens, 100)
    )
    jid = r.json()["data"]["id"]
    await run_one(app.state.sessions)
    await client.post(f"/api/v1/admin/jobs/{jid}/confirm", headers=headers(tokens, 100))
    await run_one(app.state.sessions)
    async with app.state.sessions() as db:
        assert (await db.get(Job, jid)).state == "done"
        assert await consistency(db) == []
    r = await client.post("/api/v1/admin/jobs/export", headers=headers(tokens, 100))
    jid = r.json()["data"]["id"]
    await run_one(app.state.sessions)
    assert (
        await client.get(f"/api/v1/admin/jobs/{jid}/download", headers=headers(tokens))
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/admin/jobs/{jid}/download", headers=headers(tokens, 101))
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/admin/jobs/{jid}/download", headers=headers(tokens, 100))
    ).status_code == 200


async def test_hub_deduplicates_events_and_preserves_new_session():
    hub = Hub()
    ws = AsyncMock()
    queue = asyncio.Queue(16)
    hub.add(ws, 1, 3, queue)
    hub.dispatch({"event": "session_revoked", "user_id": 1, "version": 3, "event_id": 1})
    assert queue.empty()
    event = {"event": "quota", "club_id": 1, "version": 2, "event_id": 2}
    hub.dispatch(event)
    hub.dispatch(event)
    assert queue.qsize() == 1
    hub.dispatch({"event": "session_revoked", "user_id": 1, "version": 4, "event_id": 3})
    assert queue.qsize() == 2
