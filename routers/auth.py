# 登录注册接口
from fastapi import APIRouter, Body, HTTPException, Depends
from sqlalchemy.orm import Session
from database import get_db
import models
from datetime import datetime
from schemas import (
    ResponseSchema,
    LoginRequestSchema,
    LoginResponseSchema,
    ChangePasswordRequestSchema,
    PersonalInfoRequestSchema,
    PersonalInfoResponseSchema,
    ClubsResponseSchema,
)

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

from crud import get_clubs_with_major_restrictions


# APIRouter 用于分组接口, prefix="/auth" 表示这个文件里的接口都以 /auth 开头, tags 用于文档分类
router = APIRouter(prefix="/auth", tags=["认证模块"])

# 对于数据是否为空，统一前端进行校验，前端必须保证传递的数据完整，后端只进行逻辑校验，避免重复校验和不必要的数据库查询


# ─────────────────────────────────────────
# 统一登录接口，管理员和学生共用
# POST /auth/login
# ─────────────────────────────────────────
@router.post("/login", summary="统一登录")
def login(body: LoginRequestSchema, db: Session = Depends(get_db)):
    username = body.username
    password = body.password

    # ── Step 1：先查管理员表 ──────────────────────────────────
    admin = (
        db.query(models.AdminUser).filter(models.AdminUser.username == username).first()
    )

    if admin:
        # 命中管理员 → 走管理员逻辑
        if admin.is_active != 1:
            raise HTTPException(status_code=403, detail="账号已被禁用")

        if not verify_password(password, admin.password_hash):
            raise HTTPException(status_code=401, detail="账号或密码错误")

        admin.last_login_at = datetime.now()
        db.commit()

        token = create_access_token(data={"sub": str(admin.admin_id), "type": "admin"})

        return ResponseSchema(
            code=200,
            message="登录成功",
            data=LoginResponseSchema(
                token=token,
                token_type="Bearer",
                identity="admin",
                admin={
                    "username": admin.username,
                    "real_name": admin.real_name,
                    "is_active": bool(admin.is_active),
                },
                student={},
                clubs=get_clubs_with_major_restrictions(db=db),
            ),
        )

    # ── Step 2：不是管理员 → 查学生表 ────────────────────────
    student = (
        db.query(models.Students).filter(models.Students.student_id == username).first()
    )

    if not student:
        raise HTTPException(status_code=404, detail="账号不存在")

    if student.account_status != 1:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    if not verify_password(password, student.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")

    student.token_ver += 1
    db.commit()
    db.refresh(student)

    token = create_access_token(
        data={"sub": student.student_id, "type": "student", "ver": student.token_ver}
    )

    # Step 3：登录成功，返回学生信息和社团列表(存于storage) ────────────────────────

    print(f"学生 {student.student_id} 登录成功, token: {token}")  # 打印日志，方便调试

    return ResponseSchema(
        code=200,
        message="登录成功",
        data=LoginResponseSchema(
            token=token,
            token_type="Bearer",
            identity="student",
            admin={},
            student={
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
            clubs=get_clubs_with_major_restrictions(db=db),
        ),
    )


# ─────────────────────────────────────────
# 修改密码（学生）
# PATCH /auth/student/password
# ─────────────────────────────────────────
@router.patch("/student/password", summary="学生修改密码")
def change_student_password(
    body: ChangePasswordRequestSchema,
    student: models.Students = Depends(get_current_student),  # 必须登录才能访问
    db: Session = Depends(get_db),
):
    """
    get_current_student 是一个依赖函数：
    它会自动从请求头解析 Token，验证身份，返回当前学生对象
    如果 Token 无效或未登录，FastAPI 会在进入这个函数之前就返回 401
    """
    print(f"学生 {student.student_id} 请求修改密码")  # 打印日志，方便调试
    print(
        f"旧密码: {body.old_password}, 新密码: {body.new_password}"
    )  # 打印日志，方便调试

    # 验证旧密码
    if not verify_password(body.old_password, student.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")

    # 新旧密码不能一样
    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")

    # 更新密码哈希和修改标记
    student.password_hash = hash_password(body.new_password)
    student.is_pwd_changed = 1
    db.commit()  # 提交事务

    return ResponseSchema(code=200, message="密码修改成功", data=None)


# ─────────────────────────────────────────
# 目前认为认证接口已完善
