import asyncio
import random

from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from club.errors import fail
from club.models import Activity, Club, Enrollment, Idempotency, Outbox, User, utcnow


def iso(value):
    return value.isoformat() + "Z" if value else None


def activity_data(a):
    now = utcnow()
    state = a.state
    if state == "published":
        state = "upcoming" if now < a.starts_at else "ended" if now >= a.ends_at else "open"
    return {"name": a.name, "state": state, "configured_state": a.state,
            "starts_at": iso(a.starts_at), "ends_at": iso(a.ends_at),
            "allow_cancel": a.allow_cancel, "cancel_until": iso(a.cancel_until), "version": a.version}


def club_data(c, detail=False):
    keys = ["id", "name", "category", "location", "schedule", "cover", "capacity", "remaining",
            "active", "allowed_majors", "version"]
    if detail:
        keys.append("description")
    return {k: getattr(c, k) for k in keys}


async def enrollment_data(db, user_id):
    row = (await db.execute(select(Enrollment, Club.name).join(Club).where(Enrollment.student_id == user_id))).first()
    if not row:
        return None
    e, name = row
    return {"club_id": e.club_id, "club_name": name, "source": e.source, "created_at": iso(e.created_at)}


async def mutable_activity(db):
    # Administrative writes serialize on this row. Registrations use a shared lock.
    a = await db.get(Activity, 1, with_for_update=True)
    if not a:
        fail(503, "NOT_INITIALIZED", "活动尚未初始化")
    if a.state == "published" and a.starts_at <= utcnow() < a.ends_at:
        fail(409, "ACTIVITY_OPEN", "报名期间禁止修改，请先暂停活动")
    return a


def event(db, payload):
    db.add(Outbox(payload=payload))


async def mutate_enrollment(factory, user_id, token_version, key, club_id=None, cancel=False):
    if not 8 <= len(key) <= 64 or not key.isascii():
        fail(422, "INVALID_IDEMPOTENCY_KEY", "请提供8至64位请求标识")
    fingerprint = f"{'cancel' if cancel else 'select'}:{club_id}"
    for attempt in range(3):
        try:
            async with asyncio.timeout(6):
                async with factory() as db, db.begin():
                    # Lock order: activity(shared), user(exclusive), club(exclusive).
                    a = await db.get(Activity, 1, with_for_update={"read": True})
                    u = await db.get(User, user_id, with_for_update=True)
                    if not u or not u.active or u.role != "student" or u.token_version != token_version:
                        fail(401, "SESSION_EXPIRED", "登录已失效")
                    previous = await db.scalar(select(Idempotency).where(Idempotency.user_id == user_id, Idempotency.key == key))
                    if previous:
                        if previous.fingerprint != fingerprint:
                            fail(409, "IDEMPOTENCY_CONFLICT", "请求标识已用于另一项操作")
                        return previous.response
                    if u.must_change_password:
                        fail(403, "PASSWORD_CHANGE_REQUIRED", "请先修改初始密码")
                    current = await db.get(Enrollment, user_id)
                    now = utcnow()
                    if not a or a.state != "published":
                        fail(409, "ACTIVITY_CLOSED", "当前未开放报名")
                    if cancel:
                        if not current:
                            fail(409, "NOT_ENROLLED", "你尚未报名")
                        if current.source == "reserved":
                            fail(403, "RESERVED", "预报名学生不能自行退选")
                        if not a.allow_cancel or not a.cancel_until or now >= a.cancel_until or now < a.starts_at:
                            fail(403, "CANCEL_CLOSED", "当前不允许退选")
                        club_id = current.club_id
                        await db.execute(update(Club).where(Club.id == club_id).values(remaining=Club.remaining + 1, version=Club.version + 1))
                        await db.delete(current)
                        result = {"status": "cancelled", "enrollment": None}
                    else:
                        if not a.starts_at <= now < a.ends_at:
                            fail(409, "OUTSIDE_WINDOW", "当前不在报名时间内")
                        if current:
                            fail(409, "ALREADY_ENROLLED", "你已经选定社团，请先查看报名结果")
                        club = await db.get(Club, club_id)
                        if not club or not club.active:
                            fail(404, "CLUB_UNAVAILABLE", "社团不存在或未开放")
                        if club.allowed_majors and u.major not in club.allowed_majors:
                            fail(403, "MAJOR_NOT_ALLOWED", "你的专业不符合报名要求")
                        changed = await db.execute(update(Club).where(Club.id == club_id, Club.remaining > 0, Club.active.is_(True))
                                                   .values(remaining=Club.remaining - 1, version=Club.version + 1))
                        if changed.rowcount != 1:
                            fail(409, "CLUB_FULL", "该社团名额已满")
                        db.add(Enrollment(student_id=user_id, club_id=club_id, created_at=now))
                        result = {"status": "enrolled", "enrollment": {"club_id": club_id, "club_name": club.name,
                                  "source": "normal", "created_at": iso(now)}}
                    await db.flush()
                    c = await db.get(Club, club_id, populate_existing=True)
                    event(db, {"event": "quota", "club_id": c.id, "remaining": c.remaining, "version": c.version})
                    event(db, {"event": "enrollment", "user_id": user_id})
                    db.add(Idempotency(user_id=user_id, key=key, fingerprint=fingerprint, response=result))
                return result
        except OperationalError as exc:
            code = getattr(exc.orig, "args", [None])[0]
            if code == 1213 and attempt < 2:
                await asyncio.sleep(random.uniform(0.01, 0.05))
                continue
            fail(503, "DATABASE_BUSY", "提交繁忙，请先查询报名结果再重试")
        except TimeoutError:
            fail(503, "RESULT_UNCERTAIN", "请查询报名结果后再重试")


async def consistency(db):
    rows = (await db.execute(select(Club.id, Club.capacity, Club.remaining, func.count(Enrollment.student_id))
             .outerjoin(Enrollment).group_by(Club.id))).all()
    return [{"club_id": cid, "capacity": cap, "remaining": rem, "enrolled": count}
            for cid, cap, rem, count in rows if rem != cap - count]
