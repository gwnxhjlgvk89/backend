import asyncio
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text, inspect, select
from alembic.migration import MigrationContext
from alembic.operations import Operations
from club import security
from club.models import User, Activity
from club.initial_passwords import initial_password
from club.errors import DomainError


async def test_direct_password_match_without_native_threads(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Password comparison must not create a worker thread")

    monkeypatch.setattr(asyncio, "to_thread", forbidden)
    for password in ("SyntheticPass2026!", "zhangsan", "测试口令", "$argon2id$literal-password"):
        assert await security.verify_password(password, password)
        assert not await security.verify_password("incorrect", password)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("张三", "zhangsan"),
        ("李雷", "lilei"),
        ("吕布", "lvbu"),
        (" 张 三 ", "zhangsan"),
        ("Alice Smith", "alicesmith"),
        ("单田芳", "shantianfang"),
        ("曾小贤", "zengxiaoxian"),
        ("解晓东", "xiexiaodong"),
        ("尉迟明", "yuchiming"),
    ],
)
def test_initial_name_password(name, expected):
    assert initial_password(name) == expected


def test_unconvertible_name_is_rejected():
    with pytest.raises(DomainError):
        initial_password("☃")


async def test_plaintext_login_change_password_and_old_session_revocation(env):
    app, client, tokens = env

    good = await client.post(
        "/api/v1/auth/login", json={"username": "user1", "password": "SyntheticPass2026!"}
    )
    assert good.status_code == 200
    token = good.json()["data"]["token"]
    assert (
        await client.get("/api/v1/bootstrap", headers={"Authorization": "Bearer " + tokens[1]})
    ).status_code == 401
    changed = await client.post(
        "/api/v1/auth/password",
        headers={"Authorization": "Bearer " + token},
        json={"old_password": "SyntheticPass2026!", "new_password": "SyntheticChanged2026!"},
    )
    assert changed.status_code == 200
    assert "SyntheticChanged2026!" not in changed.text
    async with app.state.sessions() as db:
        user = await db.get(User, 1)
        assert user.password_plaintext == "SyntheticChanged2026!"
        assert not user.must_change_password
    assert (
        await client.get("/api/v1/bootstrap", headers={"Authorization": "Bearer " + token})
    ).status_code == 401
    bad = await client.post(
        "/api/v1/auth/login", json={"username": "user1", "password": "SyntheticPass2026!"}
    )
    assert bad.status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login", json={"username": "user1", "password": "SyntheticChanged2026!"}
        )
    ).status_code == 200


async def test_admin_creation_and_reset_store_plaintext_without_exposing_it(env):
    from sqlalchemy import select
    from club.models import Activity

    app, client, tokens = env
    headers = {"Authorization": "Bearer " + tokens[101]}
    async with app.state.sessions() as db, db.begin():
        (await db.get(Activity, 1)).state = "paused"
    for path, username in (("students", "new-student"), ("administrators", "new-admin")):
        response = await client.post(
            "/api/v1/admin/" + path,
            headers=headers,
            json={
                "username": username,
                "name": "Synthetic",
                "password": "SyntheticInitial2026!",
            },
        )
        assert response.status_code == 200
        assert "SyntheticInitial2026!" not in response.text and "password_plaintext" not in response.text
        async with app.state.sessions() as db:
            user = await db.scalar(select(User).where(User.username == username))
            assert user.password_plaintext == "SyntheticInitial2026!"
    response = await client.put(
        "/api/v1/admin/students/1",
        headers=headers,
        json={
            "username": "user1",
            "name": "Synthetic",
            "password": "SyntheticReset2026!",
        },
    )
    assert response.status_code == 200
    async with app.state.sessions() as db:
        user = await db.get(User, 1)
        assert user.password_plaintext == "SyntheticReset2026!"
        assert user.must_change_password
    assert (
        await client.get("/api/v1/bootstrap", headers={"Authorization": "Bearer " + tokens[1]})
    ).status_code == 401


def migration(number):
    file = next((Path(__file__).parents[1] / "migrations/versions").glob(number + "_*.py"))
    spec = importlib.util.spec_from_file_location("migration_" + number, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_full_migration_resets_every_account_and_removes_hash_column(env):
    app, client, tokens = env
    async with app.state.engine.begin() as connection:
        await connection.execute(text("ALTER TABLE v2_users DROP COLUMN password_plaintext"))
        await connection.execute(
            text(
                "ALTER TABLE v2_users ADD COLUMN password_hash VARCHAR(255) NOT NULL DEFAULT 'synthetic-legacy-hash'"
            )
        )

        def upgrade(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration("0003").upgrade()
                migration("0004").upgrade()
            columns = {c["name"]: c for c in inspect(sync_connection).get_columns("v2_users")}
            assert "password_hash" not in columns
            assert not columns["password_plaintext"]["nullable"]

        await connection.run_sync(upgrade)
    async with app.state.sessions() as db:
        for user in await db.scalars(select(User)):
            assert user.password_plaintext == initial_password(user.name)
            assert user.must_change_password and user.token_version == 2
    assert (
        await client.get("/api/v1/bootstrap", headers={"Authorization": "Bearer " + tokens[1]})
    ).status_code == 401
    assert (
        await client.post("/api/v1/auth/login", json={"username": "user1", "password": "test1"})
    ).status_code == 200
    with pytest.raises(RuntimeError, match="reviewed"):
        migration("0004").downgrade()


async def test_migration_validates_all_names_before_resetting_passwords(env):
    app, _, _ = env
    async with app.state.sessions() as db, db.begin():
        (await db.get(User, 2)).name = "☃"
    async with app.state.engine.begin() as connection:

        def upgrade(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration("0004").upgrade()

        with pytest.raises(DomainError):
            await connection.run_sync(upgrade)
    async with app.state.sessions() as db:
        assert (await db.get(User, 1)).password_plaintext == "SyntheticPass2026!"
        assert (await db.get(User, 1)).token_version == 1


async def test_new_student_and_admin_default_to_name_pinyin(env):
    app, client, tokens = env
    headers = {"Authorization": "Bearer " + tokens[101]}
    async with app.state.sessions() as db, db.begin():
        (await db.get(Activity, 1)).state = "paused"
    for path, username in (("students", "pinyin-student"), ("administrators", "pinyin-admin")):
        response = await client.post(
            "/api/v1/admin/" + path, headers=headers, json={"username": username, "name": "李雷"}
        )
        assert response.status_code == 200
        assert "password_plaintext" not in response.text and "lilei" not in response.text
        async with app.state.sessions() as db:
            user = await db.scalar(select(User).where(User.username == username))
            assert user.password_plaintext == "lilei" and user.must_change_password
