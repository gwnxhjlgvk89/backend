from datetime import datetime, timezone, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
import models
from app.core.config import settings

# ── JWT 配置 ─────────────────────────────
SECRET_KEY = settings.SERCRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

# ── 密码哈希配置 ─────────────────────────
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=6,  # 默认12，改成10，速度提升4倍，安全性仍然足够
)


def hash_password(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


# JWT Token工具


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """生成JWT Token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# jwt库内部会自动校验过期时间，如果过期会抛 JWTError 异常
def decode_access_token(token: str) -> dict:
    """解码JWT Token，返回payload"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─────────────────────────────────────────
# OAuth2 scheme：告诉 FastAPI 从请求头的
# Authorization: Bearer <token> 里提取 Token
# ─────────────────────────────────────────
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ─────────────────────────────────────────
# 依赖注入：获取当前登录的学生
# 在需要登录才能访问的接口里注入这个函数
# ─────────────────────────────────────────
def get_current_student(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.Students:
    """
    解析 Token → 拿到 student_id → 查数据库 → 返回学生对象
    任何一步失败都抛 401
    """
    payload = decode_access_token(token)

    # 验证 Token 类型，防止用管理员 Token 访问学生接口
    if payload.get("type") != "student":
        raise HTTPException(status_code=401, detail="Token类型错误")

    student_id = payload.get("sub")
    if not student_id:
        raise HTTPException(status_code=401, detail="Token无效")

    student = (
        db.query(models.Students)
        .filter(models.Students.student_id == student_id)
        .first()
    )

    if not student:
        raise HTTPException(status_code=401, detail="用户不存在")
    if student.account_status != 1:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    # ✅ 新增版本号校验
    if payload.get("ver") != student.token_ver:
        raise HTTPException(status_code=401, detail="账号已在其他设备登录")

    return student


# ─────────────────────────────────────────
# 依赖注入：获取当前登录的管理员
# ─────────────────────────────────────────
admin_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/admin/login")


def get_current_admin(
    token: str = Depends(admin_oauth2_scheme), db: Session = Depends(get_db)
) -> models.AdminUser:
    payload = decode_access_token(token)

    if payload.get("type") != "admin":
        raise HTTPException(status_code=401, detail="Token类型错误")

    admin_id = payload.get("sub")
    admin = (
        db.query(models.AdminUser).filter(models.AdminUser.admin_id == admin_id).first()
    )

    if not admin:
        raise HTTPException(status_code=401, detail="管理员不存在")
    if admin.is_active != 1:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    return admin


def require_super_admin(admin: models.AdminUser = Depends(get_current_admin)):
    """进一步限制：只有超级管理员才能访问"""
    if admin.role != 2:
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return admin
