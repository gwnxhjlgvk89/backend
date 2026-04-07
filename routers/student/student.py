from fastapi import APIRouter, HTTPException, Depends, Request, Body, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db
import models
import hashlib
from datetime import datetime
from schemas import ResponseSchema
from websocket_manager import manager
from auth import (
    get_current_student,
    get_current_admin,
    oauth2_scheme,
    admin_oauth2_scheme,
    hash_password,
    create_access_token,
    verify_password,
    decode_access_token,
)
from app.api.upload import upload_avatar

from crud import get_clubs_with_major_restrictions

router = APIRouter(prefix="/student", tags=["学生模块"])


# ─────────────────────────────────────────
# 学生个人信息
# GET /student/me
# ─────────────────────────────────────────
@router.get("/me", summary="获取学生个人信息")
def get_student_info(
    student: models.Students = Depends(get_current_student),
):
    return ResponseSchema(
        code=200,
        message="获取成功",
        data={
            "student": {
                "student_id": student.student_id,
                "name": student.name,
                "avatar": student.avatar,
                "email": student.email,
                "phone": student.phone,
                "class_name": student.class_name,
                "major_name": student.major_name,
                "department": student.department,
                "is_pwd_changed": bool(student.is_pwd_changed),
                "is_reserved": bool(student.is_reserved),
                "reserved_club_name": student.reserved_club_name,
                "has_selected": bool(student.has_selected),
                "selected_club_name": student.selected_club_name,
            },
        },
    )


# ─────────────────────────────────────────
# 获取社团列表
# GET /student/club
# ─────────────────────────────────────────


@router.get("/club", summary="获取单一社团信息")
def get_club(
    club_name: str,
    db: Session = Depends(get_db),
    student: models.Students = Depends(get_current_student),
):
    club = db.query(models.Clubs).filter(models.Clubs.club_name == club_name).first()
    if not club:
        raise HTTPException(status_code=404, detail="社团不存在")
    major_restrictions = (
        db.query(models.Club_Major_Restrictions)
        .filter(models.Club_Major_Restrictions.club_name == club_name)
        .all()
    )
    major_restrictions_list = [r.major_name for r in major_restrictions]

    return ResponseSchema(
        code=200,
        message="获取成功",
        data={
            "club_name": club.club_name,
            "teacher_advisor": club.teacher_advisor,
            "club_president": club.club_president,
            "description": club.description,
            "description_detail": club.description_detail,
            "cover_image": club.cover_image,
            "activity_position": club.activity_position,
            "activity_time": club.activity_time,
            "total_quota": club.total_quota,
            "reserved_quota": club.reserved_quota,
            "remaining_quota": club.remaining_quota,
            "has_major_limit": club.has_major_limit,
            "major_restrictions": major_restrictions_list,
            "club_status": club.club_status,
        },
    )


@router.get("/clubs", summary="获取社团列表")
def get_club_list(
    # 相当于登录校验
    student: models.Students = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    return ResponseSchema(
        code=200,
        message="获取成功",
        data=get_clubs_with_major_restrictions(db),
    )


# ─────────────────────────────────────────
# (含取消)收藏社团
# POST /student/favorites
# ─────────────────────────────────────────
@router.post("/favorites", summary="收藏/取消收藏社团")
def favorite_club(
    club_name: str = Body(..., embed=True),
    student: models.Students = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    # 1. 检查社团是否存在
    club = db.query(models.Clubs).filter(models.Clubs.club_name == club_name).first()
    if not club:
        raise HTTPException(status_code=404, detail="社团不存在")
    # 2. 查询是否已经收藏过
    existing = (
        db.query(models.Student_Favorites)
        .filter(
            models.Student_Favorites.student_id == student.student_id,
            models.Student_Favorites.club_name == club_name,
        )
        .first()
    )
    # 3. 已收藏 → 取消收藏
    if existing:
        db.delete(existing)
        db.commit()
        return ResponseSchema(code=200, message="已取消收藏", data=None)
    # 4. 未收藏 → 添加收藏
    new_favorite = models.Student_Favorites(
        student_id=student.student_id,
        club_name=club_name,
        # created_at 有 DEFAULT CURRENT_TIMESTAMP，不需要手动传
    )
    db.add(new_favorite)
    db.commit()
    return ResponseSchema(code=200, message="收藏成功", data=None)


# ─────────────────────────────────────────
# 获取收藏列表
# GET /student/favorites
# ─────────────────────────────────────────
@router.get("/favorites", summary="获取收藏列表")
def get_favorite_clubs(
    student: models.Students = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    favorites = (
        db.query(models.Student_Favorites)
        .filter(models.Student_Favorites.student_id == student.student_id)
        .all()
    )
    club_names = [fav.club_name for fav in favorites]
    return ResponseSchema(code=200, message="获取成功", data=club_names)


# -------------------------------------------------------
# POST /student/select  抢课 如果已抢课或者社团未开放，那么前端抢课按钮不会显示
# -------------------------------------------------------
@router.post("/select", summary="抢课")
async def select_club(
    club_name: str = Body(..., embed=True),
    student: models.Students = Depends(get_current_student),
    db: Session = Depends(get_db),
):

    # ✅ 新增：时间校验 - 本周四12点前不开放
    now = datetime.now()
    # weekday(): 周一=0, 周二=1, ..., 周四=3, ..., 周日=6
    current_weekday = now.weekday()
    current_hour = now.hour

    # 如果还没到周四，或者是周四但还没到12点，则拒绝
    if current_weekday < 3 or (current_weekday == 3 and current_hour < 12):
        return JSONResponse(
            status_code=403,
            content={"code": 403, "message": "选社开放时间为周四12:00-13:20，敬请期待"},
        )

    if student.has_selected:
        raise HTTPException(status_code=400, detail="你已经选择了社团，不能重复选择")
    if student.is_reserved:
        raise HTTPException(status_code=400, detail="你是预报名学生，不能抢课")
    # 查询目标社团，加行锁防止并发超卖
    #    with_for_update() → SELECT ... FOR UPDATE
    #    同一时刻只有一个事务能操作这一行
    club = (
        db.query(models.Clubs)
        .filter(models.Clubs.club_name == club_name)
        .with_for_update()
        .first()
    )
    if not club:
        return JSONResponse(
            status_code=404, content={"code": 404, "message": "社团不存在"}
        )
    # 校验名额
    if club.remaining_quota <= 0:
        return JSONResponse(
            status_code=409, content={"code": 409, "message": "社团名额已满"}
        )

    if club.has_major_limit:
        major_restrictions = (
            db.query(models.Club_Major_Restrictions)
            .filter(models.Club_Major_Restrictions.club_name == club_name)
            .all()
        )
        allowed_majors = {r.major_name for r in major_restrictions}
        if not any(major in student.major_name for major in allowed_majors):
            return JSONResponse(
                status_code=403,
                content={"code": 403, "message": "你的专业不符合社团要求"},
            )

    # 报名成功，更新数据库
    club.remaining_quota -= 1
    if club.remaining_quota == 0:
        club.club_status = 2  # 更新社团状态为已满员

    student.has_selected = True
    student.selected_club_name = club.club_name
    student.selected_at = datetime.now()

    db.commit()
    db.refresh(student)
    db.refresh(club)

    # 广播通知名额变化给所有人
    await manager.broadcast(
        {
            "event": "quota_update",
            "club_name": club.club_name,
            "remaining_quota": club.remaining_quota,  # 最新剩余名额
        }
    )
    # 单独推送成功消息给报名的学生，前端可以用这个消息弹窗提示
    await manager.send_to_student(
        student.student_id,
        {
            "event": "select_success",
            "message": f"🎉 成功加入 {club.club_name}！",
        },
    )

    return ResponseSchema(code=200, message="报名成功", data=None)


# -------------------------------------------------------
# POST /student/quit  退课
# -------------------------------------------------------
@router.post("/quit", summary="退课")
async def quit_club(
    student: models.Students = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    club = (
        db.query(models.Clubs)
        .filter(models.Clubs.club_name == student.selected_club_name)
        .with_for_update()
        .first()
    )
    if not club:
        raise HTTPException(status_code=404, detail="社团不存在")

    # 更新数据库
    club.remaining_quota += 1
    if club.club_status == 2:  # 如果之前是已满员，退课后要改回报名中
        club.club_status = 1

    student.has_selected = False
    student.selected_club_name = None
    student.selected_at = None

    db.commit()
    db.refresh(student)
    db.refresh(club)

    await manager.broadcast(
        {
            "event": "quota_update",
            "club_name": club.club_name,
            "remaining_quota": club.remaining_quota,  # 最新剩余名额
        }
    )
    await manager.send_to_student(
        student.student_id,
        {
            "event": "quit_success",
            "message": f"已退出 {club.club_name}，期待你下次加入！",
        },
    )

    return ResponseSchema(code=200, message="退课成功", data=None)


# ─────────────────────────────────────────
# 更新头像
# POST /student/avatar
# ─────────────────────────────────────────
@router.post("/avatar", summary="更新学生头像")
async def update_avatar(
    file: UploadFile = File(...),
    student: models.Students = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    try:
        avatar_url = await upload_avatar(file=file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")

    # 5️⃣ 更新数据库
    student.avatar = avatar_url
    db.commit()
    db.refresh(student)

    return ResponseSchema(
        code=200,
        message="头像更新成功",
        data={"avatar": avatar_url},
    )


# ─────────────────────────────────────────
# 更新联系方式
# PATCH /student/contact
# ─────────────────────────────────────────
@router.patch("/contact", summary="更新学生联系方式")
def update_contact(
    email: str = Body(None, embed=False),
    phone: str = Body(None, embed=False),
    student: models.Students = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    if email is None and phone is None:
        raise HTTPException(status_code=400, detail="email 和 phone 不能同时为空")

    if email is not None:
        student.email = email
    if phone is not None:
        student.phone = phone

    db.commit()
    db.refresh(student)

    return ResponseSchema(
        code=200,
        message="更新成功",
        data={
            "email": student.email,
            "phone": student.phone,
        },
    )
