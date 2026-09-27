import asyncio
import hashlib
import secrets
import time
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import bcrypt
from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError

from club.config import settings
from club.errors import fail
from club.models import User
from club.metrics import PASSWORD_EXECUTION, PASSWORD_WAIT, PASSWORD_NATIVE

bearer = HTTPBearer(auto_error=False)
password_slots = asyncio.Semaphore(settings().password_concurrency)
# OWASP-listed tradeoff: 7 MiB, five passes, one lane. Bcrypt remains readable.
password_hasher = PasswordHasher(time_cost=5, memory_cost=7168, parallelism=1, type=Type.ID)


async def password_work(operation, function, *args):
    waiting = time.monotonic()
    await password_slots.acquire()
    PASSWORD_WAIT.observe(time.monotonic() - waiting)
    started = time.monotonic()

    def native():
        native_started = time.monotonic()
        try:
            return function(*args)
        finally:
            PASSWORD_NATIVE.labels(operation).observe(time.monotonic() - native_started)

    task = asyncio.create_task(asyncio.to_thread(native))

    def completed(done):
        if not done.cancelled():
            done.exception()  # Retrieve errors even if the HTTP task was cancelled.
        PASSWORD_EXECUTION.labels(operation).observe(time.monotonic() - started)
        password_slots.release()

    task.add_done_callback(completed)
    # Cancellation cannot release the slot while its native thread is still working.
    return await asyncio.shield(task)


async def hash_password(value: str):
    return await password_work("argon2_hash", password_hasher.hash, value)


async def verify_password(value: str, hashed: str):
    try:
        if hashed.startswith("$argon2id$"):
            return await password_work("argon2_verify", password_hasher.verify, hashed, value)
        if hashed.startswith(("$2a$", "$2b$", "$2y$")):
            return await password_work("bcrypt_verify", bcrypt.checkpw, value.encode(), hashed.encode())
        return False
    except (ValueError, InvalidHashError, VerificationError):
        return False


def password_needs_upgrade(hashed):
    if not hashed.startswith("$argon2id$"):
        return True
    parameters = extract_parameters(hashed)
    # Keep existing OWASP-listed or stronger profiles; never demote a stronger hash.
    profiles = ((47104, 1), (19456, 2), (12288, 3), (9216, 4), (7168, 5))
    return (
        parameters.hash_len < 32
        or parameters.salt_len < 16
        or not any(
            parameters.memory_cost >= memory and parameters.time_cost >= passes for memory, passes in profiles
        )
    )


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
    user = await request.app.state.identities.get(int(data["sub"]))
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
            "phone",
            "email",
        )
    }
