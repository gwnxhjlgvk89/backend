import asyncio
import threading

import bcrypt
import pytest
from club import security
from club.models import User


async def test_argon2_unique_salt_and_invalid_password():
    a = await security.hash_password("SyntheticPass2026!")
    b = await security.hash_password("SyntheticPass2026!")
    assert a != b and a.startswith("$argon2id$v=19$m=7168,t=5,p=1$")
    assert await security.verify_password("SyntheticPass2026!", a)
    assert not await security.verify_password("wrong", a)
    assert not await security.verify_password("anything", "$argon2id$malformed")
    assert not security.password_needs_upgrade(a)


async def test_legacy_login_upgrades_only_after_success(env):
    app, client, _ = env
    old = bcrypt.hashpw(b"SyntheticPass2026!", bcrypt.gensalt(rounds=10)).decode()
    async with app.state.sessions() as db, db.begin():
        (await db.get(User, 1)).password_hash = old
    bad = await client.post("/api/v1/auth/login", json={"username": "user1", "password": "incorrect"})
    assert bad.status_code == 401
    async with app.state.sessions() as db:
        assert (await db.get(User, 1)).password_hash == old
    good = await client.post(
        "/api/v1/auth/login", json={"username": "user1", "password": "SyntheticPass2026!"}
    )
    assert good.status_code == 200
    async with app.state.sessions() as db:
        upgraded = (await db.get(User, 1)).password_hash
    assert upgraded.startswith("$argon2id$")
    assert await security.verify_password("SyntheticPass2026!", upgraded)


async def test_cancelled_request_keeps_native_password_slot_until_done(monkeypatch):
    gate = asyncio.Semaphore(1)
    monkeypatch.setattr(security, "password_slots", gate)
    started = threading.Event()
    release = threading.Event()

    def native():
        started.set()
        release.wait(2)
        return True

    task = asyncio.create_task(security.password_work("test", native))
    try:
        await asyncio.wait_for(asyncio.to_thread(started.wait), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.locked()
        release.set()
        await asyncio.wait_for(gate.acquire(), 1)
        gate.release()
    finally:
        release.set()


def test_existing_stronger_argon_profile_is_not_rehashed_downward():
    from argon2 import PasswordHasher, Type

    for memory, passes in ((19456, 2), (32768, 3)):
        hashed = PasswordHasher(memory_cost=memory, time_cost=passes, parallelism=1, type=Type.ID).hash(
            "SyntheticPass2026!"
        )
        assert not security.password_needs_upgrade(hashed)
