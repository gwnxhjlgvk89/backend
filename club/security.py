import asyncio
import hashlib
import secrets
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError

from club.config import settings
from club.errors import fail
from club.models import User

bearer = HTTPBearer(auto_error=False)
password_slots = asyncio.Semaphore(4)


async def hash_password(value: str):
    async with password_slots:
        return (await asyncio.to_thread(bcrypt.hashpw, value.encode(), bcrypt.gensalt(rounds=10))).decode()


async def verify_password(value: str, hashed: str):
    async with password_slots:
        try:
            return await asyncio.to_thread(bcrypt.checkpw, value.encode(), hashed.encode())
        except ValueError:
            return False


def token(user: User):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user.id),
            "ver": user.token_version,
            "iat": now,
            "exp": now + timedelta(minutes=settings().token_minutes),
            "aud": "club-v2",
        },
        settings().jwt_secret,
        algorithm="HS256",
    )


def claims(value):
    try:
        return jwt.decode(
            value,
            settings().jwt_secret,
            algorithms=["HS256"],
            audience="club-v2",
            options={"require": ["sub", "ver", "iat", "exp"]},
        )
    except jwt.InvalidTokenError:
        fail(401, "SESSION_EXPIRED", "登录已失效，请重新登录")


async def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        fail(401, "LOGIN_REQUIRED", "请先登录")
    data = claims(credentials.credentials)
    async with request.app.state.read_sessions() as db:
        user = await db.get(User, int(data["sub"]))
        if not user or not user.active or user.token_version != data["ver"]:
            fail(401, "SESSION_EXPIRED", "登录已失效，请重新登录")
        return user


async def enrollment_identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    # Enrollment validates the account under its transaction lock. Avoid a
    # redundant checkout/read/rollback immediately before that authoritative read.
    if not credentials:
        fail(401, "LOGIN_REQUIRED", "请先登录")
    data = claims(credentials.credentials)
    return SimpleNamespace(id=int(data["sub"]), token_version=data["ver"])


async def student(user=Depends(current_user)):
    if user.role != "student":
        fail(403, "STUDENT_REQUIRED", "此功能仅供学生使用")
    return user


async def admin(user=Depends(current_user)):
    if user.role not in {"admin", "super_admin"}:
        fail(403, "ADMIN_REQUIRED", "需要管理员权限")
    if user.must_change_password:
        fail(403, "PASSWORD_CHANGE_REQUIRED", "请先修改初始密码")
    return user


async def super_admin(user=Depends(admin)):
    if user.role != "super_admin":
        fail(403, "SUPER_ADMIN_REQUIRED", "需要超级管理员权限")
    return user


LIMIT_SCRIPT = """
local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end
return n
"""


async def rate_limit(request, scope, identity, limit, seconds):
    key = hashlib.sha256(str(identity).encode()).hexdigest()
    try:
        n = await request.app.state.redis.eval(
            LIMIT_SCRIPT, 1, f"{settings().redis_prefix}:limit:{scope}:{key}", seconds
        )
    except RedisError:
        fail(503, "TEMPORARILY_UNAVAILABLE", "服务暂时繁忙，请稍后确认结果")
    if n > limit:
        fail(429, "RATE_LIMITED", "操作太频繁，请稍后再试")


async def issue_ticket(request, user):
    ticket = secrets.token_urlsafe(32)
    await request.app.state.redis.set(f"{settings().redis_prefix}:ticket:{ticket}", token(user), ex=30)
    return ticket


def public_user(u):
    return {
        k: getattr(u, k)
        for k in (
            "id",
            "username",
            "name",
            "role",
            "major",
            "class_name",
            "active",
            "must_change_password",
            "avatar",
            "phone",
            "email",
        )
    }
