import asyncio
import math
import random
import time
from club.metrics import POOL_WAIT

from sqlalchemy import func, insert, select, text, update, and_
from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeout

from club.errors import fail
from club.models import Activity, Club, Enrollment, Idempotency, Outbox, User, utcnow


def iso(value):
    return value.isoformat() + "Z" if value else None


def activity_data(a):
    now = utcnow()
    state = a.state
    if state == "published":
        state = "upcoming" if now < a.starts_at else "ended" if now >= a.ends_at else "open"
    return {
        "name": a.name,
        "state": state,
        "configured_state": a.state,
        "starts_at": iso(a.starts_at),
        "ends_at": iso(a.ends_at),
        "allow_cancel": a.allow_cancel,
        "cancel_until": iso(a.cancel_until),
        "version": a.version,
    }


CLUB_KEYS = (
    "id",
    "name",
    "category",
    "location",
    "schedule",
    "cover",
    "capacity",
    "remaining",
    "active",
    "allowed_majors",
    "version",
)


def club_data(c, detail=False):
    keys = CLUB_KEYS + ("description",) if detail else CLUB_KEYS
    return {k: getattr(c, k) for k in keys}


async def enrollment_data(db, user_id):
    row = (
        await db.execute(select(Enrollment, Club.name).join(Club).where(Enrollment.student_id == user_id))
    ).first()
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


SLOT_WAIT_SECONDS = 8

# Both notifications in one statement; the quota row reads this transaction's
# own update, so remaining/version are exact without a separate locked read.
OUTBOX_AFTER_CHANGE = text(
    "INSERT INTO v2_outbox (payload, delivered, created_at) "
    "SELECT JSON_OBJECT('event', 'quota', 'club_id', id, 'remaining', remaining, 'version', version), 0, :now "
    "FROM v2_clubs WHERE id = :club_id "
    "UNION ALL SELECT JSON_OBJECT('event', 'enrollment', 'user_id', :user_id), 0, :now"
)


async def enrollment_transaction(factory, user_id, token_version, key, fingerprint, club_id, cancel):
    async with factory() as db, db.begin():
        waiting = time.perf_counter()
        try:
            await db.connection()
        finally:
            POOL_WAIT.observe(time.perf_counter() - waiting)
        # Lock order: activity(shared), user(exclusive), club(exclusive, last and briefest).
        a = (
            await db.execute(
                select(
                    Activity.state, Activity.starts_at, Activity.ends_at, Activity.allow_cancel, Activity.cancel_until
                )
                .where(Activity.id == 1)
                .with_for_update(read=True)
            )
        ).first()
        u = (
            await db.execute(
                select(
                    User.active,
                    User.token_version,
                    User.role,
                    User.major,
                    User.must_change_password,
                    Enrollment.club_id.label("current_club"),
                    Enrollment.source.label("current_source"),
                    Idempotency.fingerprint,
                    Idempotency.response,
                )
                .select_from(User)
                .outerjoin(Enrollment, Enrollment.student_id == User.id)
                .outerjoin(Idempotency, and_(Idempotency.user_id == User.id, Idempotency.key == key))
                .where(User.id == user_id)
                .with_for_update()
            )
        ).first()
        if not u or not u.active or u.token_version != token_version:
            fail(401, "SESSION_EXPIRED", "登录已失效")
        if u.role != "student":
            fail(403, "STUDENT_REQUIRED", "此功能仅供学生使用")
        if u.fingerprint is not None:
            if u.fingerprint != fingerprint:
                fail(409, "IDEMPOTENCY_CONFLICT", "请求标识已用于另一项操作")
            return u.response
        if u.must_change_password:
            fail(403, "PASSWORD_CHANGE_REQUIRED", "请先修改初始密码")
        now = utcnow()
        if not a or a.state != "published":
            fail(409, "ACTIVITY_CLOSED", "当前未开放报名")
        if cancel:
            if u.current_club is None:
                fail(409, "NOT_ENROLLED", "你尚未报名")
            if u.current_source == "reserved":
                fail(403, "RESERVED", "预报名学生不能自行退选")
            if not a.allow_cancel or not a.cancel_until or now >= a.cancel_until or now < a.starts_at:
                fail(403, "CANCEL_CLOSED", "当前不允许退选")
            club_id = u.current_club
            result = {"status": "cancelled", "enrollment": None}
            await db.execute(
                insert(Idempotency).values(
                    user_id=user_id, key=key, fingerprint=fingerprint, response=result, created_at=now
                )
            )
            await db.execute(
                update(Club)
                .where(Club.id == club_id)
                .values(remaining=Club.remaining + 1, version=Club.version + 1)
            )
            await db.execute(Enrollment.__table__.delete().where(Enrollment.student_id == user_id))
        else:
            if now < a.starts_at:
                wait = (a.starts_at - now).total_seconds()
                fail(409, "NOT_OPEN", "报名还没开始，请稍候", retry_after_ms=math.ceil(wait * 1000))
            if now >= a.ends_at:
                fail(409, "OUTSIDE_WINDOW", "当前不在报名时间内")
            if u.current_club is not None:
                fail(409, "ALREADY_ENROLLED", "你已经选定社团，请先查看报名结果")
            # Static club fields cannot change while open (admin edits require a paused
            # activity). A committed zero is final for this request: reject without
            # queueing on the club row lock.
            club = (
                await db.execute(
                    select(Club.name, Club.active, Club.allowed_majors, Club.remaining).where(Club.id == club_id)
                )
            ).first()
            if not club or not club.active:
                fail(404, "CLUB_UNAVAILABLE", "社团不存在或未开放")
            if club.allowed_majors and u.major not in club.allowed_majors:
                fail(403, "MAJOR_NOT_ALLOWED", "你的专业不符合报名要求")
            if club.remaining <= 0:
                fail(409, "CLUB_FULL", "该社团名额已满")
            result = {
                "status": "enrolled",
                "enrollment": {
                    "club_id": club_id,
                    "club_name": club.name,
                    "source": "normal",
                    "created_at": iso(now),
                },
            }
            await db.execute(
                insert(Idempotency).values(
                    user_id=user_id, key=key, fingerprint=fingerprint, response=result, created_at=now
                )
            )
            # The club row lock is taken here and held only for the next three
            # round-trips. The enrollment insert must follow it: its foreign-key
            # check takes a shared lock on the same row.
            changed = await db.execute(
                update(Club)
                .where(Club.id == club_id, Club.remaining > 0, Club.active.is_(True))
                .values(remaining=Club.remaining - 1, version=Club.version + 1)
            )
            if changed.rowcount != 1:
                fail(409, "CLUB_FULL", "该社团名额已满")
            await db.execute(
                insert(Enrollment).values(student_id=user_id, club_id=club_id, source="normal", created_at=now)
            )
        await db.execute(OUTBOX_AFTER_CHANGE, {"now": now, "club_id": club_id, "user_id": user_id})
    return result


async def mutate_enrollment(factory, user_id, token_version, key, club_id=None, cancel=False, slots=None):
    if not 8 <= len(key) <= 64 or not key.isascii():
        fail(422, "INVALID_IDEMPOTENCY_KEY", "请提供8至64位请求标识")
    fingerprint = f"{'cancel' if cancel else 'select'}:{club_id}"
    # Queue in order for a transaction slot instead of failing after the pool's
    # 3-second checkout timeout; nothing has executed if this wait expires.
    if slots is not None:
        try:
            async with asyncio.timeout(SLOT_WAIT_SECONDS):
                await slots.acquire()
        except TimeoutError:
            fail(503, "DATABASE_BUSY", "提交繁忙，请先查询报名结果再重试")
    try:
        for attempt in range(3):
            try:
                async with asyncio.timeout(6):
                    return await enrollment_transaction(
                        factory, user_id, token_version, key, fingerprint, club_id, cancel
                    )
            except OperationalError as exc:
                code = getattr(exc.orig, "args", [None])[0]
                if code == 1213 and attempt < 2:
                    await asyncio.sleep(random.uniform(0.01, 0.05))
                    continue
                fail(503, "DATABASE_BUSY", "提交繁忙，请先查询报名结果再重试")
            except PoolTimeout:
                fail(503, "DATABASE_BUSY", "提交繁忙，请先查询报名结果再重试")
            except TimeoutError:
                fail(503, "RESULT_UNCERTAIN", "请查询报名结果后再重试")
    finally:
        if slots is not None:
            slots.release()


async def consistency(db):
    rows = (
        await db.execute(
            select(Club.id, Club.capacity, Club.remaining, func.count(Enrollment.student_id))
            .outerjoin(Enrollment)
            .group_by(Club.id)
        )
    ).all()
    return [
        {"club_id": cid, "capacity": cap, "remaining": rem, "enrolled": count}
        for cid, cap, rem, count in rows
        if rem != cap - count
    ]
