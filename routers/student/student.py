from fastapi import APIRouter, HTTPException, Depends, Request, Body, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db
import models
import hashlib
from typing import Optional
from datetime import datetime, timedelta
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


def format_time_delta(days: int, hours: int, minutes: int, seconds: int = 0) -> str:
    """格式化时间差（精确到秒）"""
    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分钟")
    if seconds > 0:
        parts.append(f"{seconds}秒")
    return "".join(parts) if parts else "即将开放"


def calculate_time_until_window(
    start_weekday: int,
    start_hour: int,
    start_minute: int = 0,
    start_second: int = 0,
) -> str:
    """计算距离时间窗口开始还有多久（精确到秒）"""
    now = datetime.now()
    current_weekday = now.weekday()
    current_hour = now.hour
    current_minute = now.minute
    current_second = now.second

    # 计算目标时间
    days_until_start = (start_weekday - current_weekday) % 7
    if days_until_start == 0:
        # 同一天
        if (
            current_hour < start_hour
            or (current_hour == start_hour and current_minute < start_minute)
            or (
                current_hour == start_hour
                and current_minute == start_minute
                and current_second < start_second
            )
        ):
            hours_until = start_hour - current_hour
            minutes_until = start_minute - current_minute
            seconds_until = start_second - current_second
            if seconds_until < 0:
                minutes_until -= 1
                seconds_until += 60
            if minutes_until < 0:
                hours_until -= 1
                minutes_until += 60
            return format_time_delta(0, hours_until, minutes_until, seconds_until)
        else:
            # 已经超过了这个时间，目标是下周
            days_until_start = 7

    if days_until_start > 0:
        hours_until = start_hour - current_hour
        minutes_until = start_minute - current_minute
        seconds_until = start_second - current_second
        if seconds_until < 0:
            minutes_until -= 1
            seconds_until += 60
        if minutes_until < 0:
            hours_until -= 1
            minutes_until += 60
        if hours_until < 0:
            days_until_start -= 1
            hours_until += 24
        return format_time_delta(
            days_until_start, hours_until, minutes_until, seconds_until
        )

    return ""


def is_within_time_window(
    start_weekday: int,
    start_hour: int,
    start_minute: int = 0,
    start_second: int = 0,
    end_weekday: Optional[int] = None,
    end_hour: Optional[int] = None,
    end_minute: int = 0,
    end_second: int = 0,
) -> bool:
    """
    检查当前时间是否在指定的时间窗口内（精确到秒）

    参数：
    - start_weekday: 开始日期（0=周一, 6=周日）
    - start_hour: 开始小时
    - start_minute: 开始分钟
    - start_second: 开始秒数
    - end_weekday: 结束日期（如果为None则使用start_weekday）
    - end_hour: 结束小时（如果为None则表示不限制）
    - end_minute: 结束分钟
    - end_second: 结束秒数
    """
    now = datetime.now()
    current_weekday = now.weekday()
    current_hour = now.hour
    current_minute = now.minute
    current_second = now.second

    if end_weekday is None:
        end_weekday = start_weekday
    if end_hour is None:
        end_hour = 23
        end_minute = 59
        end_second = 59

    # 同一天的时间段
    if start_weekday == end_weekday:
        if current_weekday != start_weekday:
            return False

        start_time = start_hour * 3600 + start_minute * 60 + start_second
        end_time = end_hour * 3600 + end_minute * 60 + end_second
        current_time = current_hour * 3600 + current_minute * 60 + current_second

        return start_time <= current_time <= end_time

    # 跨天的时间段
    current_time = current_hour * 3600 + current_minute * 60 + current_second
    start_time = start_hour * 3600 + start_minute * 60 + start_second
    end_time = end_hour * 3600 + end_minute * 60 + end_second

    if current_weekday == start_weekday:
        return current_time >= start_time
    elif current_weekday == end_weekday:
        return current_time <= end_time
    elif start_weekday < end_weekday:
        return start_weekday < current_weekday < end_weekday
    else:  # start_weekday > end_weekday (跨周)
        return current_weekday > start_weekday or current_weekday < end_weekday


def validate_time_window(
    start_weekday: int,
    start_hour: int,
    start_minute: int = 0,
    start_second: int = 0,
    end_weekday: Optional[int] = None,
    end_hour: Optional[int] = None,
    end_minute: int = 0,
    end_second: int = 0,
    error_code: int = 403,
    error_message: str = "该功能未在开放时间内",
) -> Optional[HTTPException]:
    """
    检查时间窗口，如果不在窗口内则返回 HTTPException（适合直接 raise）

    使用示例：
    >>> exc = validate_time_window(
    ...     start_weekday=3,
    ...     start_hour=12,
    ...     start_minute=0,
    ...     start_second=0,
    ...     end_hour=13,
    ...     end_minute=20,
    ...     end_second=0,
    ...     error_message="选社开放时间为4月9日（周四）12:00-13:20，敬请期待"
    ... )
    >>> if exc:
    ...     raise exc
    """
    if is_within_time_window(
        start_weekday,
        start_hour,
        start_minute,
        start_second,
        end_weekday,
        end_hour,
        end_minute,
        end_second,
    ):
        return None

    # 计算还要等多久
    time_until = calculate_time_until_window(
        start_weekday, start_hour, start_minute, start_second
    )
    full_message = f"{error_message}（距离开放还有 {time_until}）"

    return HTTPException(status_code=error_code, detail=full_message)


def validate_time_window_json(
    start_weekday: int,
    start_hour: int,
    start_minute: int = 0,
    start_second: int = 0,
    end_weekday: Optional[int] = None,
    end_hour: Optional[int] = None,
    end_minute: int = 0,
    end_second: int = 0,
    error_code: int = 403,
    error_message: str = "该功能未在开放时间内",
) -> Optional[JSONResponse]:
    """
    检查时间窗口，如果不在窗口内则返回 JSONResponse

    使用示例：
    >>> response = validate_time_window_json(
    ...     start_weekday=3,      # 周四
    ...     start_hour=12,
    ...     start_minute=0,
    ...     start_second=0,
    ...     end_hour=13,
    ...     end_minute=20,
    ...     end_second=0,
    ...     error_message="选社开放时间为4月9日（周四）12:00-13:20，敬请期待"
    ... )
    >>> if response:
    ...     return response
    """
    if is_within_time_window(
        start_weekday,
        start_hour,
        start_minute,
        start_second,
        end_weekday,
        end_hour,
        end_minute,
        end_second,
    ):
        return None

    # 计算还要等多久
    time_until = calculate_time_until_window(
        start_weekday, start_hour, start_minute, start_second
    )
    full_message = f"{error_message}（距离开放还有 {time_until}）"

    return JSONResponse(
        status_code=error_code,
        content={
            "code": error_code,
            "message": full_message,
        },
    )


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

    response = validate_time_window_json(
        start_weekday=3,  # 周四
        start_hour=12,
        end_hour=13,
        end_minute=20,
        error_message="选社开放时间为4月9日（周四）12:00-13:20，敬请期待",
    )
    if response:
        return response

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
