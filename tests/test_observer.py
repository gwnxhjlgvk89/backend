from club.api import Observe


async def test_observer_preserves_request_id_errors_and_cache_headers(env):
    _, client, tokens = env
    response = await client.post("/api/v1/auth/login", json={"password": "must-not-be-echoed"})
    assert response.status_code == 422
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["server-timing"].startswith("app;dur=")
    assert "must-not-be-echoed" not in response.text
    response = await client.get("/api/v1/enrollment", headers={"Authorization": "Bearer " + tokens[1]})
    assert response.status_code == 200 and response.json() == {"data": None}
    assert response.headers["x-request-id"]


async def test_non_http_lifecycle_is_passed_through_without_extra_tasks():
    received = []
    marker = {"type": "websocket.accept"}

    async def app(scope, receive, send):
        assert "state" not in scope
        await send(marker)

    async def receive():
        raise AssertionError("Observer must not consume websocket input")

    async def send(message):
        received.append(message)

    await Observe(app)({"type": "websocket"}, receive, send)
    assert received == [marker]
