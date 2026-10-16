import pytest
from sqlalchemy import update

from club.admin import exempt_reserve
from club.errors import DomainError
from club.models import Club, Enrollment


def headers(tokens, uid):
    return {"Authorization": f"Bearer {tokens[uid]}"}


async def set_state(client, tokens, state):
    r = await client.post("/api/v1/admin/activity/state", json={"state": state}, headers=headers(tokens, 101))
    return r


async def reserve(app, username, club_id, actor="super"):
    async with app.state.sessions() as db, db.begin():
        return await exempt_reserve(db, username, club_id, actor)


async def restrict(app, club_id, majors):
    async with app.state.sessions() as db, db.begin():
        await db.execute(update(Club).where(Club.id == club_id).values(allowed_majors=majors))


async def test_exempt_reservation_bypasses_major_only_for_that_student(env):
    app, client, tokens = env
    assert (await set_state(client, tokens, "paused")).status_code == 200
    await restrict(app, 2, ["Accounting"])

    await reserve(app, "user1", 2)  # user1 studies CS, outside the restriction
    async with app.state.sessions() as db:
        e = await db.get(Enrollment, 1)
        assert (e.club_id, e.source, e.major_exempt) == (2, "reserved", True)
        assert (await db.get(Club, 2)).remaining == 19
    assert (await set_state(client, tokens, "published")).status_code == 200

    # The same mismatch without the exemption still blocks publishing.
    assert (await set_state(client, tokens, "paused")).status_code == 200
    async with app.state.sessions() as db, db.begin():
        db.add(Enrollment(student_id=2, club_id=2, source="reserved"))
        await db.execute(update(Club).where(Club.id == 2).values(remaining=18))
    r = await set_state(client, tokens, "published")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_ENROLLMENT"


async def test_exempt_reservation_rejections(env):
    app, client, tokens = env
    with pytest.raises(DomainError) as exc:
        await reserve(app, "user1", 2)
    assert exc.value.code == "ACTIVITY_OPEN"

    assert (await set_state(client, tokens, "paused")).status_code == 200
    with pytest.raises(DomainError) as exc:
        await reserve(app, "user1", 2, actor="admin")
    assert exc.value.code == "SUPER_ADMIN_REQUIRED"

    await reserve(app, "user3", 1)  # club 1 has a single seat
    with pytest.raises(DomainError) as exc:
        await reserve(app, "user4", 1)
    assert exc.value.code == "RESERVATION_UNAVAILABLE"
    with pytest.raises(DomainError) as exc:
        await reserve(app, "user3", 2)
    assert exc.value.code == "ENROLLMENT_EXISTS"
    with pytest.raises(DomainError) as exc:
        await reserve(app, "nobody", 2)
    assert exc.value.code == "NOT_FOUND"


async def test_admin_edit_with_same_club_keeps_exemption(env):
    app, client, tokens = env
    assert (await set_state(client, tokens, "paused")).status_code == 200
    await restrict(app, 2, ["Accounting"])
    await reserve(app, "user1", 2)

    r = await client.put(
        "/api/v1/admin/students/1",
        json={"username": "user1", "name": "Renamed", "major": "CS", "class_name": "A", "reserved_club_id": 2},
        headers=headers(tokens, 100),
    )
    assert r.status_code == 200
    async with app.state.sessions() as db:
        e = await db.get(Enrollment, 1)
        assert (e.club_id, e.major_exempt) == (2, True)
        assert (await db.get(Club, 2)).remaining == 19
    assert (await set_state(client, tokens, "published")).status_code == 200
