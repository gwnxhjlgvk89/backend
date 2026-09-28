import asyncio

import pytest
from club.models import User


@pytest.mark.parametrize("change", [None, "disable", "password"])
async def test_password_work_releases_connection_and_rechecks_account(env, monkeypatch, change):
    app, client, _ = env
    verifying = asyncio.Event()
    release = asyncio.Event()

    async def slow_verify(*_):
        verifying.set()
        await release.wait()
        return True

    monkeypatch.setattr("club.api.verify_password", slow_verify)
    task = asyncio.create_task(
        client.post(
            "/api/v1/auth/login",
            json={
                "username": "user1",
                "password": "SyntheticPass2026!",
            },
        )
    )
    try:
        await asyncio.wait_for(verifying.wait(), 2)
        assert app.state.engine.pool.checkedout() == 0
        if change:
            async with app.state.sessions() as db, db.begin():
                user = await db.get(User, 1, with_for_update=True)
                if change == "disable":
                    user.active = False
                else:
                    user.password_plaintext = "changed-while-verifying"
        release.set()
        response = await task
        assert response.status_code == (401 if change else 200)
    finally:
        release.set()
        await task
