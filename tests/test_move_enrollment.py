from sqlalchemy import select, update

from club.models import Audit, Club, Enrollment


def headers(tokens, uid=100):
    return {"Authorization": f"Bearer {tokens[uid]}"}


async def set_state(client, tokens, state):
    r = await client.post("/api/v1/admin/activity/state", json={"state": state}, headers=headers(tokens, 101))
    assert r.status_code == 200


async def seed(app, *rows, clubs=()):
    async with app.state.sessions() as db, db.begin():
        db.add_all(clubs)
        for student_id, club_id, source in rows:
            db.add(Enrollment(student_id=student_id, club_id=club_id, source=source))
            await db.execute(update(Club).where(Club.id == club_id).values(remaining=Club.remaining - 1))


async def move(client, tokens, user_id, club_id):
    return await client.put(
        f"/api/v1/admin/students/{user_id}/enrollment", json={"club_id": club_id}, headers=headers(tokens)
    )


async def remaining(app):
    async with app.state.sessions() as db:
        return dict((await db.execute(select(Club.id, Club.remaining))).all())


async def test_move_normal_enrollment_shifts_seat_and_audits(env):
    app, client, tokens = env
    await set_state(client, tokens, "paused")
    # Club 3 was dissolved: hidden, but its existing enrollment must still move out.
    await seed(app, (5, 3, "normal"), clubs=[Club(id=3, name="Gone", capacity=5, remaining=5, active=False)])

    r = await move(client, tokens, 5, 2)
    assert r.status_code == 200
    assert r.json()["data"] == {"club_id": 2, "club_name": "Two", "source": "normal"}
    assert await remaining(app) == {1: 1, 2: 19, 3: 5}
    async with app.state.sessions() as db:
        e = await db.get(Enrollment, 5)
        assert (e.club_id, e.source) == (2, "normal")
        a = await db.scalar(select(Audit).where(Audit.action == "enrollment.move"))
        assert (a.actor_id, a.target) == (100, "5")
        assert a.summary == {"from_club_id": 3, "from_club": "Gone", "to_club_id": 2, "to_club": "Two"}

    r = await client.get("/api/v1/admin/students", params={"search": "user5"}, headers=headers(tokens))
    item = next(s for s in r.json()["data"]["items"] if s["id"] == 5)
    assert (item["club_id"], item["club_name"], item["source"]) == (2, "Two", "normal")


async def test_move_enrollment_rejections(env):
    app, client, tokens = env
    await seed(app, (1, 2, "normal"), (2, 2, "reserved"), (3, 1, "normal"))

    # Admin edits are refused while registration is open.
    assert (await move(client, tokens, 1, 1)).json()["error"]["code"] == "ACTIVITY_OPEN"
    await set_state(client, tokens, "paused")

    cases = [
        (999, 1, 404, "NOT_FOUND"),
        (100, 1, 404, "NOT_FOUND"),
        (4, 1, 409, "NOT_NORMAL_ENROLLMENT"),  # not enrolled
        (2, 1, 409, "NOT_NORMAL_ENROLLMENT"),  # reservation
        (1, 2, 409, "SAME_CLUB"),
        (1, 1, 409, "CLUB_UNAVAILABLE"),  # club 1 is full
        (1, 99, 409, "CLUB_UNAVAILABLE"),
    ]
    for user_id, club_id, status, code in cases:
        r = await move(client, tokens, user_id, club_id)
        assert (r.status_code, r.json()["error"]["code"]) == (status, code), (user_id, club_id)

    async with app.state.sessions() as db, db.begin():
        await db.execute(update(Club).where(Club.id == 1).values(remaining=1, allowed_majors=["Math"]))
    r = await move(client, tokens, 1, 1)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "MAJOR_NOT_ALLOWED")

    async with app.state.sessions() as db, db.begin():
        await db.execute(update(Club).where(Club.id == 1).values(active=False, allowed_majors=[]))
    assert (await move(client, tokens, 1, 1)).json()["error"]["code"] == "CLUB_UNAVAILABLE"

    # Nothing moved and no seat leaked.
    assert await remaining(app) == {1: 1, 2: 18}
    async with app.state.sessions() as db:
        assert (await db.get(Enrollment, 1)).club_id == 2
        assert not await db.scalar(select(Audit).where(Audit.action == "enrollment.move"))
