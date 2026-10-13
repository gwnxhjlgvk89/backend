import asyncio
from datetime import timedelta
from io import BytesIO
from unittest.mock import AsyncMock

from openpyxl import Workbook
from redis.exceptions import ConnectionError
from sqlalchemy import func, select, text

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
        user = await db.scalar(select(User).where(User.username == "new1"))
        assert user.password_plaintext == "SyntheticPass2026!"
        assert (await db.get(Job, jid)).payload == {}
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


async def test_old_import_preview_requires_reupload_without_partial_users(env):
    from club.jobs import upload_cipher

    app, client, tokens = env
    await pause(client, tokens)
    common = {"name": "Synthetic", "major": "CS", "class_name": "A", "reserved_club_id": None}
    async with app.state.sessions() as db, db.begin():
        job = Job(
            id="synthetic-old-preview",
            actor_id=100,
            kind="import_students",
            state="queued",
            payload={
                "rows": [
                    {
                        **common,
                        "username": "pending-new",
                        "password_ciphertext": upload_cipher().encrypt(b"SyntheticPass2026!").decode(),
                    },
                    {**common, "username": "pending-old", "password_hash": "$argon2id$old-preview"},
                ]
            },
        )
        db.add(job)
    await run_one(app.state.sessions)
    async with app.state.sessions() as db:
        job = await db.get(Job, "synthetic-old-preview")
        assert job.state == "failed" and job.payload == {}
        assert "重新上传" in job.result["message"]
        assert (
            await db.scalar(select(func.count()).select_from(User).where(User.username.like("pending-%")))
            == 0
        )


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


async def test_broadcast_encodes_once_for_all_recipients():
    import json

    hub = Hub()
    queues = [asyncio.Queue(16) for _ in range(1500)]
    for i, queue in enumerate(queues):
        hub.add(AsyncMock(), i, 1, queue)
    event = {"event": "quotas", "items": [{"club_id": 1, "version": 4, "remaining": 9}]}
    hub.dispatch(event)
    messages = [queue.get_nowait() for queue in queues]
    assert all(message is messages[0] for message in messages)
    assert json.loads(messages[0].encoded) == event


async def test_outbox_batches_quota_and_retries_without_losing_events(env):
    import json
    from unittest.mock import MagicMock
    from club.models import Outbox
    from club.worker import deliver

    app, client, tokens = env
    async with app.state.sessions() as db, db.begin():
        db.add_all(
            [
                Outbox(payload={"event": "quota", "club_id": i, "remaining": 10, "version": 1})
                for i in range(1, 43)
            ]
        )
        db.add(Outbox(payload={"event": "enrollment", "user_id": 1}))
    pipe = MagicMock()
    pipe.execute = AsyncMock(side_effect=ConnectionError("synthetic outage"))
    redis = MagicMock()
    redis.pipeline.return_value = pipe
    import pytest

    with pytest.raises(ConnectionError):
        await deliver(app.state.sessions, redis)
    async with app.state.sessions() as db:
        assert (
            await db.scalar(select(func.count()).select_from(Outbox).where(Outbox.delivered.is_(False))) == 43
        )
    pipe.reset_mock()
    pipe.execute = AsyncMock()
    await deliver(app.state.sessions, redis, publish_quotas=False)
    messages = [json.loads(call.args[1]) for call in pipe.publish.call_args_list]
    assert len(messages) == 1 and messages[0]["event"] == "enrollment"
    async with app.state.sessions() as db:
        assert (
            await db.scalar(select(func.count()).select_from(Outbox).where(Outbox.delivered.is_(False))) == 42
        )
    pipe.reset_mock()
    await deliver(app.state.sessions, redis)
    messages = [json.loads(call.args[1]) for call in pipe.publish.call_args_list]
    assert len(messages) == 1
    batch = next(m for m in messages if m["event"] == "quota_delta")
    assert batch["rows"] == [[i, 10, 1] for i in range(1, 43)]
    async with app.state.sessions() as db:
        assert (
            await db.scalar(select(func.count()).select_from(Outbox).where(Outbox.delivered.is_(False))) == 0
        )


async def test_batched_ws_validation_recovers_missed_revocation(env):
    app, _, _ = env
    from club.models import User
    from sqlalchemy import update

    hub = Hub()
    good, stale, disabled, missing = (AsyncMock() for _ in range(4))
    hub.add(good, 1, 1, asyncio.Queue(16))
    hub.add(stale, 2, 1, asyncio.Queue(16))
    hub.add(disabled, 3, 1, asyncio.Queue(16))
    hub.add(missing, 999, 1, asyncio.Queue(16))
    async with app.state.sessions() as db, db.begin():
        await db.execute(update(User).where(User.id == 2).values(token_version=2))
        await db.execute(update(User).where(User.id == 3).values(active=False))
    await hub.revalidate(app.state.sessions)
    good.close.assert_not_awaited()
    for socket in (stale, disabled, missing):
        socket.close.assert_awaited_once_with(code=1008, reason="session expired")


async def test_large_import_payload_does_not_block_job_queue(env):
    # A queued payload above MySQL's default 256KB sort buffer once failed the
    # filesort in run_one forever and starved every later job.
    from club.jobs import upload_cipher

    app, client, tokens = env
    await pause(client, tokens)
    secret = upload_cipher().encrypt(b"SyntheticPass2026!").decode()
    rows = [
        {
            "username": f"bulk{i:05d}",
            "name": "Synthetic",
            "major": "CS",
            "class_name": "A",
            "reserved_club_id": None,
            "password_ciphertext": secret,
        }
        for i in range(1600)
    ]
    async with app.state.sessions() as db, db.begin():
        db.add(Job(id="synthetic-large-import", actor_id=100, kind="import_students", payload={"rows": rows}))
        db.add(
            Job(
                id="synthetic-later-export",
                actor_id=100,
                kind="export_students",
                created_at=utcnow() + timedelta(seconds=1),
            )
        )
        sort_buffer = await db.scalar(select(text("@@sort_buffer_size")))
    async with app.state.sessions() as db:
        size = await db.scalar(
            select(func.length(Job.payload)).where(Job.id == "synthetic-large-import")
        )
        assert size > max(256 * 1024, sort_buffer)
    await run_one(app.state.sessions)
    await run_one(app.state.sessions)
    async with app.state.sessions() as db:
        assert (await db.get(Job, "synthetic-large-import")).state == "done"
        assert (await db.get(Job, "synthetic-later-export")).state == "done"
        assert (
            await db.scalar(select(func.count()).select_from(User).where(User.username.like("bulk%")))
            == 1600
        )
