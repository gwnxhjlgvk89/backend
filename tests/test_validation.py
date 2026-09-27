from io import BytesIO

from PIL import Image

from test_registration import headers


async def test_avatar_checks_bytes_size_and_authentication(env):
    app, client, tokens = env
    endpoint = "/api/v1/profile/avatar"
    assert (await client.post(endpoint, files={"file": ("avatar.png", b"not an image")})).status_code == 401
    r = await client.post(endpoint, files={"file": ("avatar.png", b"not an image")}, headers=headers(tokens))
    assert r.status_code == 422
    r = await client.post(
        endpoint, files={"file": ("large.jpg", b"a" * (2 * 1024 * 1024 + 1))}, headers=headers(tokens)
    )
    assert r.status_code == 413
    stream = BytesIO()
    Image.new("RGB", (20, 20), "blue").save(stream, "PNG")
    r = await client.post(
        endpoint, files={"file": ("avatar.jpg", stream.getvalue())}, headers=headers(tokens)
    )
    assert r.status_code == 200 and r.json()["data"]["avatar"].endswith(".jpg")
    name = r.json()["data"]["avatar"].rsplit("/", 1)[-1]
    image = await client.get("/api/v1/media/" + name)
    assert image.status_code == 200 and image.headers["content-type"].startswith("image/jpeg")


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
    assert not any(key in r.text for key in ("password_hash", "token_version"))


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
    assert "password" not in response.text
