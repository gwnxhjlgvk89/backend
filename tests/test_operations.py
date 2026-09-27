from copy import deepcopy

import pytest
from sqlalchemy import delete, select, func

from club.legacy import TABLES, plan_legacy, apply_legacy
from club.models import Activity, Club, Enrollment, User
from club.operations import reset_current, state_summary
from club.services import consistency


def legacy_snapshot():
    data = {t: [] for t in TABLES}
    hashed = "$2b$10$abcdefghijklmnopqrstuv1234567890123456789012345678901"
    data["admin_users"] = [
        {
            "admin_id": 1,
            "username": "super-old",
            "real_name": "Admin",
            "role": 2,
            "is_active": 1,
            "password_hash": hashed,
        }
    ]
    data["students"] = [
        {
            "student_id": "S1",
            "name": "Synthetic",
            "password_hash": hashed,
            "class_name": "A",
            "major_name": "CS",
            "account_status": 1,
            "is_pwd_changed": 1,
            "is_reserved": 1,
            "has_selected": 0,
            "reserved_club_name": "Chess",
        }
    ]
    data["clubs"] = [
        {
            "club_name": "Chess",
            "total_quota": 10,
            "remaining_quota": 9,
            "reserved_quota": 1,
            "has_major_limit": 1,
        }
    ]
    data["reserved_list"] = [{"student_id": "S1", "club_name": "Chess"}]
    data["club_major_restrictions"] = [{"club_name": "Chess", "major_name": "CS"}]
    data["student_favorites"] = [{"student_id": "S1", "club_name": "Chess"}]
    return data


def test_legacy_reports_conflicts_without_guessing():
    data = legacy_snapshot()
    assert plan_legacy(data)["issues"] == []
    bad = deepcopy(data)
    bad["students"][0].update(has_selected=1, selected_club_name="Chess")
    bad["clubs"][0]["remaining_quota"] = 10
    codes = {i["code"] for i in plan_legacy(bad)["issues"]}
    assert {"RESERVED_NORMAL_CONFLICT", "QUOTA_MISMATCH"} <= codes
    assert plan_legacy(bad)["fingerprint"] != plan_legacy(data)["fingerprint"]


async def test_legacy_apply_and_reset_preserve_clubs_admins(env):
    app, client, tokens = env
    data = legacy_snapshot()
    async with app.state.sessions() as db, db.begin():
        await db.execute(delete(User))
        await db.execute(delete(Club))
        await apply_legacy(db, data, plan_legacy(data)["fingerprint"])
        assert await consistency(db) == []
    async with app.state.sessions() as db:
        actor = await db.scalar(select(User).where(User.role == "super_admin"))
        summary = await state_summary(db)
        assert summary["students"] == summary["enrollments"] == summary["favorites"] == 1
    async with app.state.sessions() as db, db.begin():
        await reset_current(db, summary["fingerprint"], actor)
    async with app.state.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 1
        assert await db.scalar(select(func.count()).select_from(Club)) == 1
        assert await db.scalar(select(func.count()).select_from(Enrollment)) == 0
        assert (await db.get(Activity, 1)).state == "draft"
        assert await consistency(db) == []


async def test_reset_rejects_active_or_changed_data(env):
    app, client, tokens = env
    async with app.state.sessions() as db:
        actor = await db.get(User, 101)
        summary = await state_summary(db)
    with pytest.raises(ValueError, match="Pause"):
        async with app.state.sessions() as db, db.begin():
            await reset_current(db, summary["fingerprint"], actor)
    with pytest.raises(ValueError, match="Data changed"):
        async with app.state.sessions() as db, db.begin():
            (await db.get(Activity, 1)).state = "paused"
            await db.flush()
            await reset_current(db, "outdated-review", actor)
