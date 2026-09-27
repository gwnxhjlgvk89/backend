import asyncio
import pytest
from sqlalchemy import event
from club.errors import DomainError
from club.identity import IdentityReader
from club.models import User


async def test_identity_burst_batches_but_never_caches_account_state(env):
    app, _, _ = env
    reads = []

    def queried(conn, cursor, statement, parameters, context, many):
        if "v2_users.id IN" in statement:
            reads.append(statement)

    event.listen(app.state.read_engine.sync_engine, "before_cursor_execute", queried)
    try:
        users = await asyncio.gather(*(app.state.identities.get(i) for i in range(1, 31)))
        assert [u.id for u in users] == list(range(1, 31))
        assert len(reads) == 1
        async with app.state.sessions() as db, db.begin():
            u = await db.get(User, 1)
            u.active = False
            u.token_version += 1
        fresh = await app.state.identities.get(1)
        assert not fresh.active and fresh.token_version == 2
        assert len(reads) == 2
        assert await app.state.identities.get(9999) is None
    finally:
        event.remove(app.state.read_engine.sync_engine, "before_cursor_execute", queried)


async def test_cancelled_identity_request_does_not_cancel_other_users(env):
    app, _, _ = env
    cancelled = asyncio.create_task(app.state.identities.get(1))
    valid = asyncio.create_task(app.state.identities.get(2))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert (await valid).id == 2


async def test_shutdown_and_bounded_pending_identity_queue(env):
    app, _, _ = env
    reader = IdentityReader(app.state.read_sessions, max_pending=1)
    first = asyncio.create_task(reader.get(1))
    await asyncio.sleep(0)
    with pytest.raises(DomainError) as exc:
        await reader.get(2)
    assert exc.value.status == 503
    await reader.close()
    with pytest.raises(DomainError):
        await first
    with pytest.raises(DomainError):
        await reader.get(3)
