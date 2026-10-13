import uuid

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy import delete, func, or_, select, update

from club.errors import fail
from club.initial_passwords import initial_password
from club.models import Activity, Audit, Club, Enrollment, Favorite, Idempotency, Job, User, utcnow
from club.schemas import ActivityInput, ActivityState, AdminInput, AdminRoleInput, ClubInput, StudentInput
from club.security import admin, set_password, public_user, super_admin
from club.services import activity_data, club_data, consistency, event, mutable_activity

router = APIRouter(dependencies=[Depends(admin)])


def audit(db, user, action, target, summary=None):
    db.add(Audit(actor_id=user.id, action=action, target=str(target), summary=summary or {}))


def changed(db):
    event(db, {"event": "catalog"})


@router.get("/students")
async def students(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    search: str = Query("", max_length=64),
    major: str = "",
    selected: str = "",
):
    conditions = [User.role == "student"]
    if search:
        pattern = f"%{search.replace('%', '').replace('_', '')}%"
        conditions.append(or_(User.username.like(pattern), User.name.like(pattern)))
    if major:
        conditions.append(User.major == major)
    if selected in {"yes", "no"}:
        # Correlate only User: the list query also outerjoins Enrollment, and auto-correlation
        # would otherwise strip the subquery's own FROM clause.
        exists = (
            select(Enrollment.student_id).where(Enrollment.student_id == User.id).correlate(User).exists()
        )
        conditions.append(exists if selected == "yes" else ~exists)
    async with request.app.state.sessions() as db:
        total = await db.scalar(select(func.count()).select_from(User).where(*conditions))
        rows = (
            await db.execute(
                select(User, Enrollment.club_id, Enrollment.source, Club.name)
                .outerjoin(Enrollment, Enrollment.student_id == User.id)
                .outerjoin(Club, Club.id == Enrollment.club_id)
                .where(*conditions)
                .order_by(User.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items = [
            {**public_user(u), "club_id": cid, "club_name": name, "source": source}
            for u, cid, source, name in rows
        ]
    return {"data": {"items": items, "total": total, "page": page, "page_size": page_size}}


@router.get("/clubs")
async def clubs(request: Request):
    async with request.app.state.sessions() as db:
        return {"data": [club_data(c, True) for c in await db.scalars(select(Club).order_by(Club.id))]}


@router.get("/overview")
async def overview(request: Request):
    async with request.app.state.sessions() as db:
        a = await db.get(Activity, 1)
        return {
            "data": {
                "activity": activity_data(a),
                "students": await db.scalar(
                    select(func.count()).select_from(User).where(User.role == "student")
                ),
                "enrolled": await db.scalar(select(func.count()).select_from(Enrollment)),
                "clubs": await db.scalar(select(func.count()).select_from(Club)),
                "inconsistencies": await consistency(db),
            }
        }


@router.put("/activity")
async def configure(body: ActivityInput, request: Request, user=Depends(super_admin)):
    async with request.app.state.sessions() as db, db.begin():
        a = await mutable_activity(db)
        for key, value in body.model_dump().items():
            setattr(a, key, value)
        a.state, a.version = "draft", a.version + 1
        audit(db, user, "activity.configure", 1)
        event(db, {"event": "activity", "version": a.version})
    return {"data": activity_data(a)}


@router.post("/activity/state")
async def state(body: ActivityState, request: Request, user=Depends(super_admin)):
    async with request.app.state.sessions() as db, db.begin():
        a = await db.get(Activity, 1, with_for_update=True)
        if body.state == "published":
            if not a.starts_at or not a.ends_at or a.ends_at <= utcnow():
                fail(422, "INVALID_WINDOW", "请先配置有效报名时间")
            if await consistency(db):
                fail(409, "QUOTA_MISMATCH", "名额与报名记录不一致，禁止发布")
            enrolled = (
                await db.execute(
                    select(Enrollment, User, Club)
                    .join(User, User.id == Enrollment.student_id)
                    .join(Club, Club.id == Enrollment.club_id)
                )
            ).all()
            if any(
                not u.active or not c.active or (c.allowed_majors and u.major not in c.allowed_majors)
                for e, u, c in enrolled
            ):
                fail(409, "INVALID_ENROLLMENT", "已有报名或预报名包含停用账号、隐藏社团或资格冲突，请先核对")
            if not await db.scalar(select(func.count()).select_from(Club).where(Club.active.is_(True))):
                fail(409, "NO_CLUBS", "请先添加社团")
        a.state, a.version = body.state, a.version + 1
        audit(db, user, "activity.state", 1, {"state": body.state})
        event(db, {"event": "activity", "version": a.version})
    return {"data": activity_data(a)}


@router.post("/clubs")
async def create_club(body: ClubInput, request: Request, user=Depends(admin)):
    async with request.app.state.sessions() as db, db.begin():
        await mutable_activity(db)
        c = Club(**body.model_dump(), remaining=body.capacity)
        db.add(c)
        await db.flush()
        audit(db, user, "club.create", c.id)
        changed(db)
    return {"data": club_data(c, True)}


@router.put("/clubs/{club_id}")
async def edit_club(club_id: int, body: ClubInput, request: Request, user=Depends(admin)):
    async with request.app.state.sessions() as db, db.begin():
        await mutable_activity(db)
        c = await db.get(Club, club_id, with_for_update=True)
        if not c:
            fail(404, "NOT_FOUND", "社团不存在")
        used = await db.scalar(
            select(func.count()).select_from(Enrollment).where(Enrollment.club_id == club_id)
        )
        if body.capacity < used:
            fail(409, "CAPACITY_TOO_SMALL", "总名额不能小于已报名人数")
        for key, value in body.model_dump().items():
            setattr(c, key, value)
        c.remaining, c.version = body.capacity - used, c.version + 1
        audit(db, user, "club.update", c.id)
        changed(db)
    return {"data": club_data(c, True)}


@router.delete("/clubs/{club_id}")
async def delete_club(club_id: int, request: Request, user=Depends(admin)):
    async with request.app.state.sessions() as db, db.begin():
        await mutable_activity(db)
        if await db.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.club_id == club_id)):
            fail(409, "CLUB_HAS_ENROLLMENTS", "社团已有报名，请先处理报名记录")
        await db.execute(delete(Favorite).where(Favorite.club_id == club_id))
        await db.execute(delete(Club).where(Club.id == club_id))
        audit(db, user, "club.delete", club_id)
        changed(db)
    return {"data": None}


async def save_student(db, body, password, user_id=None):
    u = await db.get(User, user_id, with_for_update=True) if user_id else None
    if user_id and (not u or u.role != "student"):
        fail(404, "NOT_FOUND", "学生不存在")
    if not u:
        password = password or initial_password(body.name)
        u = User(role="student")
        db.add(u)
    for key in ("username", "name", "major", "class_name", "active"):
        setattr(u, key, getattr(body, key))
    if password:
        set_password(u, password)
        u.must_change_password = True
    if user_id:
        u.token_version += 1
        event(db, {"event": "session_revoked", "user_id": u.id, "version": u.token_version})
    await db.flush()
    current = await db.get(Enrollment, u.id)
    if current and current.source == "normal" and body.reserved_club_id != current.club_id:
        fail(409, "ENROLLMENT_EXISTS", "学生已有普通报名，不能直接改为预报名")
    if current and current.source == "reserved" and current.club_id != body.reserved_club_id:
        await db.execute(
            update(Club)
            .where(Club.id == current.club_id)
            .values(remaining=Club.remaining + 1, version=Club.version + 1)
        )
        await db.delete(current)
        await db.flush()
        current = None
    if body.reserved_club_id and not current:
        c = await db.get(Club, body.reserved_club_id, with_for_update=True)
        if not c or not c.active or c.remaining <= 0:
            fail(409, "RESERVATION_UNAVAILABLE", "预报名社团不存在、未开放或已满")
        if c.allowed_majors and u.major not in c.allowed_majors:
            fail(409, "MAJOR_NOT_ALLOWED", "预报名不符合专业要求")
        c.remaining, c.version = c.remaining - 1, c.version + 1
        db.add(Enrollment(student_id=u.id, club_id=c.id, source="reserved"))
    return u


@router.post("/students")
async def create_student(body: StudentInput, request: Request, user=Depends(admin)):
    async with request.app.state.sessions() as db, db.begin():
        await mutable_activity(db)
        u = await save_student(db, body, body.password)
        audit(db, user, "student.create", u.id)
        changed(db)
    return {"data": public_user(u)}


@router.put("/students/{user_id}")
async def edit_student(user_id: int, body: StudentInput, request: Request, user=Depends(admin)):
    async with request.app.state.sessions() as db, db.begin():
        await mutable_activity(db)
        u = await save_student(db, body, body.password, user_id)
        audit(db, user, "student.update", u.id)
        changed(db)
    return {"data": public_user(u)}


@router.delete("/students/{user_id}")
async def delete_student(user_id: int, request: Request, user=Depends(admin)):
    async with request.app.state.sessions() as db, db.begin():
        await mutable_activity(db)
        u = await db.get(User, user_id, with_for_update=True)
        if not u or u.role != "student":
            fail(404, "NOT_FOUND", "学生不存在")
        enrolled = await db.get(Enrollment, user_id)
        if enrolled:
            await db.execute(
                update(Club)
                .where(Club.id == enrolled.club_id)
                .values(remaining=Club.remaining + 1, version=Club.version + 1)
            )
            await db.delete(enrolled)
        await db.execute(delete(Favorite).where(Favorite.student_id == user_id))
        await db.execute(delete(Idempotency).where(Idempotency.user_id == user_id))
        await db.delete(u)
        audit(db, user, "student.delete", user_id)
        event(db, {"event": "session_revoked", "user_id": user_id})
        changed(db)
    return {"data": None}


@router.post("/administrators")
async def create_admin(body: AdminInput, request: Request, user=Depends(super_admin)):
    async with request.app.state.sessions() as db, db.begin():
        u = User(
            username=body.username,
            name=body.name,
            password_plaintext=body.password or initial_password(body.name),
            role=body.role,
        )
        db.add(u)
        await db.flush()
        audit(db, user, "admin.create", u.id, {"role": u.role})
    return {"data": public_user(u)}


@router.get("/administrators")
async def administrators(request: Request, user=Depends(super_admin)):
    async with request.app.state.sessions() as db:
        return {
            "data": [
                public_user(u)
                for u in await db.scalars(
                    select(User).where(User.role.in_(["admin", "super_admin"])).order_by(User.id)
                )
            ]
        }


@router.put("/administrators/{user_id}")
async def admin_role(user_id: int, body: AdminRoleInput, request: Request, user=Depends(super_admin)):
    async with request.app.state.sessions() as db, db.begin():
        # Serialize role changes and prevent removal of the last active super admin.
        rows = list(
            await db.scalars(
                select(User)
                .where(User.role.in_(["admin", "super_admin"]))
                .order_by(User.id)
                .with_for_update()
            )
        )
        actor = next((u for u in rows if u.id == user.id), None)
        if (
            not actor
            or not actor.active
            or actor.role != "super_admin"
            or actor.token_version != user.token_version
        ):
            fail(401, "SESSION_EXPIRED", "登录已失效")
        u = next((u for u in rows if u.id == user_id), None)
        if not u:
            fail(404, "NOT_FOUND", "管理员不存在")
        if u.active and u.role == "super_admin" and (not body.active or body.role != "super_admin"):
            if sum(r.active and r.role == "super_admin" for r in rows) <= 1:
                fail(409, "LAST_SUPER_ADMIN", "必须保留一名启用的超级管理员")
        u.role, u.active = body.role, body.active
        u.token_version += 1
        event(db, {"event": "session_revoked", "user_id": u.id, "version": u.token_version})
        audit(db, user, "admin.role", u.id, body.model_dump())
    return {"data": public_user(u)}


@router.post("/jobs/import")
async def import_preview(request: Request, file: UploadFile = File(), user=Depends(admin)):
    from club.security import rate_limit

    await rate_limit(request, "import", user.id, 3, 60)
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        fail(413, "FILE_TOO_LARGE", "文件不能超过5MB")
    from club.jobs import persist_upload
    import asyncio

    job_id = str(uuid.uuid4())
    async with request.app.state.sessions() as db, db.begin():
        await mutable_activity(db)
    await asyncio.to_thread(persist_upload, job_id, content)
    async with request.app.state.sessions() as db, db.begin():
        await mutable_activity(db)
        job = Job(id=job_id, actor_id=user.id, kind="import_preview", state="queued")
        db.add(job)
    return {"data": {"id": job.id, "state": job.state}}


@router.post("/jobs/{job_id}/confirm")
async def confirm_job(job_id: str, request: Request, user=Depends(admin)):
    async with request.app.state.sessions() as db, db.begin():
        await mutable_activity(db)
        job = await db.get(Job, job_id, with_for_update=True)
        if not job or job.actor_id != user.id:
            fail(404, "NOT_FOUND", "任务不存在")
        if job.state != "preview":
            fail(409, "JOB_ALREADY_CONFIRMED", "任务已确认或结束")
        job.state = "queued"
        job.kind = "import_students"
        audit(db, user, "import.confirm", job.id)
    return {"data": {"id": job.id, "state": job.state}}


@router.post("/jobs/export")
async def export(request: Request, user=Depends(admin)):
    async with request.app.state.sessions() as db, db.begin():
        await mutable_activity(db)
        job = Job(id=str(uuid.uuid4()), actor_id=user.id, kind="export_students")
        db.add(job)
        audit(db, user, "export.request", job.id)
    return {"data": {"id": job.id}}


@router.get("/jobs/{job_id}")
async def job_status(job_id: str, request: Request, user=Depends(admin)):
    async with request.app.state.sessions() as db:
        job = await db.get(Job, job_id)
        if not job or job.actor_id != user.id:
            fail(404, "NOT_FOUND", "任务不存在")
        return {"data": {"id": job.id, "state": job.state, "result": job.result}}


@router.get("/jobs")
async def job_list(request: Request, user=Depends(admin)):
    async with request.app.state.sessions() as db:
        return {
            "data": [
                {"id": j.id, "state": j.state, "result": j.result}
                for j in await db.scalars(
                    select(Job).where(Job.actor_id == user.id).order_by(Job.created_at.desc()).limit(30)
                )
            ]
        }


@router.get("/jobs/{job_id}/download")
async def download(job_id: str, request: Request, user=Depends(admin)):
    from fastapi.responses import FileResponse
    from club.config import settings

    async with request.app.state.sessions() as db:
        job = await db.get(Job, job_id)
        if not job or job.actor_id != user.id or job.kind != "export_students" or job.state != "done":
            fail(404, "NOT_FOUND", "导出文件不可用")
    return FileResponse(settings().storage_dir / "private" / f"{job.id}.xlsx", filename="社团报名导出.xlsx")
