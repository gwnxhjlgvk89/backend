from club.models import Enrollment


def headers(tokens, uid=100):
    return {"Authorization": f"Bearer {tokens[uid]}"}


async def test_students_selected_filter(env):
    app, client, tokens = env
    async with app.state.sessions() as db, db.begin():
        db.add(Enrollment(student_id=1, club_id=2, source="reserved"))
    query = {"search": "user1", "page_size": 100}  # user1, user10-19; user1 reserved, rest unenrolled

    r = await client.get(
        "/api/v1/admin/students", params={**query, "selected": "yes"}, headers=headers(tokens)
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 1
    assert [(s["id"], s["club_id"], s["club_name"], s["source"]) for s in data["items"]] == [
        (1, 2, "Two", "reserved")
    ]

    r = await client.get(
        "/api/v1/admin/students", params={**query, "selected": "no"}, headers=headers(tokens)
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 10
    assert [s["id"] for s in data["items"]] == list(range(10, 20))
    assert all(s["club_id"] is None and s["club_name"] is None and s["source"] is None for s in data["items"])
    assert set(data) == {"items", "total", "page", "page_size"}
