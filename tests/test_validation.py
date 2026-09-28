from club.models import User
from test_registration import headers


async def test_avatar_feature_removed_even_for_existing_users(env):
    app, client, tokens = env
    async with app.state.sessions() as db, db.begin():
        user = await db.get(User, 1)
        user.avatar = "https://old.invalid/private.jpg"
    for auth in ({}, headers(tokens)):
        response = await client.post(
            "/api/v1/profile/avatar", files={"file": ("a.jpg", b"image")}, headers=auth
        )
        assert response.status_code == 404
    assert (await client.get("/api/v1/media/" + "a" * 32 + ".jpg")).status_code == 404
    response = await client.get("/api/v1/bootstrap", headers=headers(tokens))
    assert response.status_code == 200
    assert "avatar" not in response.json()["data"]["user"]
    assert "old.invalid" not in response.text
    login = await client.post(
        "/api/v1/auth/login", json={"username": "user1", "password": "SyntheticPass2026!"}
    )
    assert login.status_code == 200
    assert "avatar" not in login.json()["data"]["user"]
    assert "/api/v1/profile/avatar" not in app.openapi()["paths"]


async def test_response_contract_legacy_and_shared_network_limits(env):
    app, client, tokens = env
    for uid in range(1, 16):
        r = await client.post(
            "/api/v1/auth/login", json={"username": f"user{uid}", "password": "SyntheticPass2026!"}
        )
        assert r.status_code == 200  # same source IP, distinct accounts must not collide
    r = await client.get("/api/v1/unknown", headers=headers(tokens, 100))
    assert r.status_code == 404
    for method, path in [
        ("post", "/student/select-club"),
        ("post", "/admin/create"),
        ("delete", "/admin/delete"),
    ]:
        r = await getattr(client, method)(path)
        assert r.status_code == 426 and r.json()["error"]["code"] == "UPGRADE_REQUIRED"
    r = await client.get("/api/v1/bootstrap", headers=headers(tokens, 100))
    assert r.status_code == 200
    assert "Server-Timing" in r.headers and "X-Request-ID" in r.headers
    assert not any(key in r.text for key in ("password_hash", "password_plaintext", "token_version"))


async def test_metrics_report_durable_backlog_without_personal_data(env):
    from club.models import Outbox

    app, client, _ = env
    async with app.state.sessions() as db, db.begin():
        db.add(Outbox(payload={"event": "catalog"}))
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "club_outbox_pending 1" in response.text
    assert "club_database_available 1" in response.text
    assert "club_redis_available 1" in response.text
    assert "SyntheticPass2026!" not in response.text
    assert "password_hash" not in response.text and "password_plaintext" not in response.text
