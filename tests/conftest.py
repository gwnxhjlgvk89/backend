import os
from datetime import timedelta

os.environ.update(
    CLUB_ENV="test",
    DATABASE_URL="mysql+asyncmy://club:club-local-only@127.0.0.1:13306/club_test?charset=utf8mb4",
    REDIS_URL="redis://127.0.0.1:16379/15",
    REDIS_PREFIX="club:test",
    JWT_SECRET="synthetic-test-secret-not-a-production-credential",
)

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from club.api import app
from club.models import Activity, Base, Club, User, utcnow
from club.security import hash_password, token


@pytest_asyncio.fixture
async def env():
    async with app.router.lifespan_context(app):
        async with app.state.engine.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
            await c.run_sync(Base.metadata.create_all)
        await app.state.redis.flushdb()  # fixed local database 15, never production
        hashed = await hash_password("SyntheticPass2026!")
        async with app.state.sessions() as db, db.begin():
            db.add(
                Activity(
                    id=1,
                    starts_at=utcnow() - timedelta(hours=1),
                    ends_at=utcnow() + timedelta(hours=1),
                    cancel_until=utcnow() + timedelta(hours=1),
                    allow_cancel=True,
                    state="published",
                )
            )
            users = [
                User(
                    id=i,
                    username=f"user{i}",
                    name=f"Test {i}",
                    role="student",
                    major="CS",
                    password_hash=hashed,
                    must_change_password=False,
                )
                for i in range(1, 51)
            ]
            users += [
                User(
                    id=100,
                    username="admin",
                    name="Admin",
                    role="admin",
                    password_hash=hashed,
                    must_change_password=False,
                ),
                User(
                    id=101,
                    username="super",
                    name="Super",
                    role="super_admin",
                    password_hash=hashed,
                    must_change_password=False,
                ),
            ]
            db.add_all(users)
            db.add_all(
                [
                    Club(id=1, name="One", capacity=1, remaining=1),
                    Club(id=2, name="Two", capacity=20, remaining=20),
                ]
            )
        tokens = {u.id: token(u) for u in users}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield app, client, tokens
