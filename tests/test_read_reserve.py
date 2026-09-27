import asyncio

import pytest

from club.config import settings


@pytest.mark.asyncio
async def test_result_query_survives_exhausted_write_pool(env):
    app, client, tokens = env
    held = []
    try:
        # Occupy every write connection as an overload burst would. The result
        # lookup must still authenticate against MySQL and return promptly.
        for _ in range(settings().pool_size + settings().pool_overflow):
            held.append(await app.state.engine.connect())
        response = await asyncio.wait_for(
            client.get("/api/v1/enrollment", headers={"Authorization": f"Bearer {tokens[1]}"}),
            timeout=2,
        )
        assert response.status_code == 200
        assert response.json() == {"data": None}
        async with app.state.read_sessions() as db, db.begin():
            from club.models import User

            user = await db.get(User, 1)
            user.active = False
        denied = await asyncio.wait_for(
            client.get("/api/v1/enrollment", headers={"Authorization": f"Bearer {tokens[1]}"}),
            timeout=2,
        )
        assert denied.status_code == 401
    finally:
        for connection in held:
            await connection.close()
