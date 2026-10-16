from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select, update

from club.jobs import parse_students
from club.models import Audit, Club, Enrollment, User
from club.schemas import ClubInput, normalize_label


def headers(tokens, uid):
    return {"Authorization": f"Bearer {tokens[uid]}"}


async def pause(client, tokens):
    r = await client.post(
        "/api/v1/admin/activity/state", json={"state": "paused"}, headers=headers(tokens, 101)
    )
    assert r.status_code == 200


def student(username, **extra):
    return {"username": username, "name": "New", "major": "CS", "class_name": "A", **extra}


def test_normalize_label():
    assert normalize_label(" 造价 2511 ") == "造价2511"
    assert normalize_label("大数据与会计(单)") == "大数据与会计（单）"
    assert normalize_label("电子　商务\t") == "电子商务"
    assert ClubInput(
        name="x", capacity=1, allowed_majors=["会计 ", "会计", " ", "电商(2)"]
    ).allowed_majors == [
        "会计",
        "电商（2）",
    ]


def test_import_normalizes_major_and_class():
    book = Workbook()
    book.active.append(["username", "name", "major", "class_name", "password", "reserved_club_id"])
    book.active.append(["s1", "张三", "大数据与会计 (单)", "会计 2512", None, None])
    buffer = BytesIO()
    book.save(buffer)
    [row] = parse_students(buffer.getvalue())
    assert (row["major"], row["class_name"]) == ("大数据与会计（单）", "会计2512")


async def test_admin_save_normalizes_labels(env):
    app, client, tokens = env
    await pause(client, tokens)
    r = await client.post(
        "/api/v1/admin/students",
        json=student("new1", major=" 工程 造价", class_name="造价 2511"),
        headers=headers(tokens, 100),
    )
    assert r.status_code == 200
    assert (r.json()["data"]["major"], r.json()["data"]["class_name"]) == ("工程造价", "造价2511")


async def test_options_lists_existing_majors_and_classes(env):
    app, client, tokens = env
    async with app.state.sessions() as db, db.begin():
        await db.execute(update(User).where(User.id <= 3).values(major="Math", class_name="B"))
        await db.execute(update(User).where(User.id == 4).values(major="", class_name=""))
        await db.execute(update(Club).where(Club.id == 2).values(allowed_majors=["Physics"]))
    r = await client.get("/api/v1/admin/options", headers=headers(tokens, 100))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["majors"] == [
        {"name": "CS", "count": 46},
        {"name": "Math", "count": 3},
        {"name": "Physics", "count": 0},
    ]
    assert {"name": "B", "count": 3} in data["classes"]
    assert all(item["name"] for item in data["majors"] + data["classes"])


async def test_super_admin_can_approve_exempt_reservation(env):
    app, client, tokens = env
    await pause(client, tokens)
    async with app.state.sessions() as db, db.begin():
        await db.execute(update(Club).where(Club.id == 2).values(allowed_majors=["Accounting"]))

    # Without approval the restriction still applies, for every role.
    r = await client.post(
        "/api/v1/admin/students", json=student("x1", reserved_club_id=2), headers=headers(tokens, 101)
    )
    assert r.json()["error"]["code"] == "MAJOR_NOT_ALLOWED"
    r = await client.post(
        "/api/v1/admin/students",
        json=student("x1", reserved_club_id=2, major_exempt=True),
        headers=headers(tokens, 100),
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "SUPER_ADMIN_REQUIRED"

    r = await client.post(
        "/api/v1/admin/students",
        json=student("x1", reserved_club_id=2, major_exempt=True),
        headers=headers(tokens, 101),
    )
    assert r.status_code == 200
    uid = r.json()["data"]["id"]
    async with app.state.sessions() as db:
        e = await db.get(Enrollment, uid)
        assert (e.source, e.major_exempt) == ("reserved", True)
        assert await db.scalar(select(Audit.action).where(Audit.action == "enrollment.major_exempt"))

    # A plain admin editing with the same club (field omitted) keeps the approval.
    r = await client.put(
        f"/api/v1/admin/students/{uid}",
        json=student("x1", name="Edited", reserved_club_id=2),
        headers=headers(tokens, 100),
    )
    assert r.status_code == 200
    # ...but may not revoke it.
    r = await client.put(
        f"/api/v1/admin/students/{uid}",
        json=student("x1", reserved_club_id=2, major_exempt=False),
        headers=headers(tokens, 100),
    )
    assert r.json()["error"]["code"] == "SUPER_ADMIN_REQUIRED"

    r = await client.get("/api/v1/admin/students", params={"search": "x1"}, headers=headers(tokens, 100))
    [item] = r.json()["data"]["items"]
    assert (item["source"], item["major_exempt"]) == ("reserved", True)

    # Revoking while the major still does not match is refused, so publishing never breaks.
    r = await client.put(
        f"/api/v1/admin/students/{uid}",
        json=student("x1", reserved_club_id=2, major_exempt=False),
        headers=headers(tokens, 101),
    )
    assert r.json()["error"]["code"] == "MAJOR_NOT_ALLOWED"
    r = await client.post(
        "/api/v1/admin/activity/state", json={"state": "published"}, headers=headers(tokens, 101)
    )
    assert r.status_code == 200


async def test_super_admin_can_revoke_exemption_when_major_matches(env):
    app, client, tokens = env
    await pause(client, tokens)
    async with app.state.sessions() as db, db.begin():
        await db.execute(update(Club).where(Club.id == 2).values(allowed_majors=["Accounting"]))
    r = await client.post(
        "/api/v1/admin/students",
        json=student("x2", reserved_club_id=2, major_exempt=True),
        headers=headers(tokens, 101),
    )
    uid = r.json()["data"]["id"]
    r = await client.put(
        f"/api/v1/admin/students/{uid}",
        json=student("x2", major="Accounting", reserved_club_id=2, major_exempt=False),
        headers=headers(tokens, 101),
    )
    assert r.status_code == 200
    async with app.state.sessions() as db:
        assert (await db.get(Enrollment, uid)).major_exempt is False
        assert (await db.get(Club, 2)).remaining == 19
