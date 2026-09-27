from club.logging import install
from club.admin import router as admin_router
from club.upload import router as upload_router
import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from prometheus_client import Counter, Histogram

from club.config import settings
from club.metrics import render, CONNECTIONS, LOOP_LAG
from club.db import make_engine, sessions
from club.errors import DomainError, fail
from club.models import Activity, Club, Favorite, User, utcnow
from club.realtime import Hub
from club.schemas import Contact, EnrollmentInput, Login, PasswordChange
from club.security import (
    current_user,
    enrollment_identity,
    hash_password,
    issue_ticket,
    public_user,
    rate_limit,
    student,
    token,
    verify_password,
)
from club.services import activity_data, club_data, enrollment_data, event, iso, mutate_enrollment

install()
logger = logging.getLogger("club")
REQUESTS = Counter("club_http_requests", "HTTP responses", ["route", "method", "status"])
LATENCY = Histogram(
    "club_http_seconds",
    "HTTP latency",
    ["route", "method"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.3, 0.5, 1, 2, 5, 10),
)


@asynccontextmanager
async def lifespan(app):
    s = settings()
    app.state.engine = make_engine()
    app.state.sessions = sessions(app.state.engine)
    app.state.redis = Redis.from_url(
        s.redis_url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2, max_connections=100
    )
    app.state.hub = Hub()
    # Pub/Sub is deliberately idle between events; command socket timeouts must
    # not force a subscription reconnect every two seconds.
    subscriber_redis = Redis.from_url(
        s.redis_url,
        decode_responses=True,
        socket_timeout=None,
        socket_connect_timeout=2,
        max_connections=2,
        health_check_interval=20,
    )
    task = asyncio.create_task(app.state.hub.subscriber(subscriber_redis))

    async def monitor_loop():
        while True:
            started = time.monotonic()
            await asyncio.sleep(1)
            LOOP_LAG.set(max(0, time.monotonic() - started - 1))
            CONNECTIONS.set(len(app.state.hub.connections))

    monitor = asyncio.create_task(monitor_loop())
    yield
    monitor.cancel()
    await asyncio.gather(monitor, return_exceptions=True)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await app.state.redis.aclose()
    await subscriber_redis.aclose()
    await app.state.engine.dispose()


app = FastAPI(
    title="社团填报系统 v2",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
)


@app.middleware("http")
async def observe(request, call_next):
    started = time.monotonic()
    request.state.request_id = uuid.uuid4().hex
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "unmatched")
    elapsed = time.monotonic() - started
    REQUESTS.labels(route, request.method, response.status_code).inc()
    LATENCY.labels(route, request.method).observe(elapsed)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Server-Timing"] = f"app;dur={elapsed * 1000:.2f}"
    response.headers["Cache-Control"] = "no-store"
    logger.info(
        json.dumps(
            {
                "request_id": request.state.request_id,
                "route": route,
                "method": request.method,
                "status": response.status_code,
                "ms": round(elapsed * 1000),
            }
        )
    )
    return response


def ok(data=None):
    return {"data": data}


def error_response(request, status, code, message):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", ""),
            }
        },
    )


@app.exception_handler(DomainError)
async def domain_error(request, exc):
    return error_response(request, exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def invalid(request, exc):
    # Pydantic errors can contain raw password input; never echo them.
    return error_response(request, 422, "INVALID_INPUT", "参数格式不正确，请检查必填项和时间格式")


@app.exception_handler(IntegrityError)
async def integrity(request, exc):
    return error_response(request, 409, "DATA_CONFLICT", "数据冲突，请刷新后重试")


@app.exception_handler(SQLAlchemyError)
@app.exception_handler(RedisError)
async def unavailable(request, exc):
    logger.error("dependency_failure type=%s", type(exc).__name__)
    return error_response(request, 503, "TEMPORARILY_UNAVAILABLE", "服务暂时繁忙，请稍后确认结果")


@app.get("/health/live")
async def live():
    return {"status": "ok", "environment": settings().club_env}


@app.get("/health/ready")
async def ready(request: Request):
    async with request.app.state.sessions() as db:
        await db.execute(text("SELECT 1"))
        if not await db.get(Activity, 1):
            fail(503, "NOT_INITIALIZED", "数据库未初始化")
    await request.app.state.redis.ping()
    return {"status": "ready"}


@app.get("/metrics")
async def metrics(request: Request):
    if request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        fail(403, "PRIVATE_ENDPOINT", "此接口仅供本机监控")
    return Response(render(), media_type="text/plain; version=0.0.4")


@app.post("/api/v1/auth/login")
async def login(body: Login, request: Request):
    await rate_limit(request, "login", body.username, 10, 60)
    async with request.app.state.sessions() as db:
        u = await db.scalar(select(User).where(User.username == body.username))
        if not u or not u.active or not await verify_password(body.password, u.password_hash):
            fail(401, "INVALID_CREDENTIALS", "账号或密码错误")
        verified_hash = u.password_hash
        # Serialize concurrent logins; returned token always has the committed version.
        await db.rollback()
        async with db.begin():
            u = await db.scalar(select(User).where(User.username == body.username).with_for_update())
            if not u or not u.active or u.password_hash != verified_hash:
                fail(401, "INVALID_CREDENTIALS", "账号或密码错误")
            u.token_version += 1
            event(db, {"event": "session_revoked", "user_id": u.id, "version": u.token_version})
        return ok({"token": token(u), "user": public_user(u)})


@app.post("/api/v1/auth/logout")
async def logout(request: Request, user=Depends(current_user)):
    async with request.app.state.sessions() as db, db.begin():
        u = await db.get(User, user.id, with_for_update=True)
        if not u or u.token_version != user.token_version:
            fail(401, "SESSION_EXPIRED", "登录已失效")
        u.token_version += 1
        event(db, {"event": "session_revoked", "user_id": u.id, "version": u.token_version})
    return ok()


@app.post("/api/v1/auth/password")
async def password(body: PasswordChange, request: Request, user=Depends(current_user)):
    await rate_limit(request, "password", user.id, 5, 60)
    if not await verify_password(body.old_password, user.password_hash):
        fail(400, "PASSWORD_INCORRECT", "原密码错误")
    hashed = await hash_password(body.new_password)
    async with request.app.state.sessions() as db, db.begin():
        u = await db.get(User, user.id, with_for_update=True)
        if u.token_version != user.token_version:
            fail(401, "SESSION_EXPIRED", "登录已失效")
        u.password_hash, u.must_change_password = hashed, False
        u.token_version += 1
        event(db, {"event": "session_revoked", "user_id": u.id, "version": u.token_version})
    return ok({"token": token(u), "user": public_user(u)})


@app.post("/api/v1/auth/ws-ticket")
async def ws_ticket(request: Request, user=Depends(current_user)):
    await rate_limit(request, "ticket", user.id, 30, 60)
    return ok({"ticket": await issue_ticket(request, user)})


async def clubs_cached(request):
    key = f"{settings().redis_prefix}:catalog"
    try:
        value = await request.app.state.redis.get(key)
        if value:
            return json.loads(value)
    except RedisError:
        pass
    async with request.app.state.sessions() as db:
        rows = list((await db.scalars(select(Club).where(Club.active.is_(True)).order_by(Club.id))).all())
        data = [{k: v for k, v in club_data(c).items() if k not in {"remaining", "version"}} for c in rows]
    try:
        await request.app.state.redis.set(key, json.dumps(data), ex=60)
    except RedisError:
        pass
    return data


async def quota_snapshot(request):
    async with request.app.state.sessions() as db:
        rows = (await db.execute(select(Club.id, Club.remaining, Club.version))).all()
        return [{"club_id": cid, "remaining": rem, "version": ver} for cid, rem, ver in rows]


@app.get("/api/v1/bootstrap")
async def bootstrap(request: Request, user=Depends(current_user)):
    async with request.app.state.sessions() as db:
        a = await db.get(Activity, 1)
        if not a:
            fail(503, "NOT_INITIALIZED", "活动尚未初始化")
        mine = await enrollment_data(db, user.id)
        favorites = list(
            (await db.scalars(select(Favorite.club_id).where(Favorite.student_id == user.id))).all()
        )
    return ok(
        {
            "user": public_user(user),
            "activity": activity_data(a),
            "server_time": iso(utcnow()),
            "enrollment": mine,
            "favorites": favorites,
            "clubs": await clubs_cached(request),
            "quotas": await quota_snapshot(request),
        }
    )


@app.get("/api/v1/clubs/quotas")
async def quotas(request: Request, user=Depends(current_user)):
    return ok(await quota_snapshot(request))


@app.get("/api/v1/clubs/{club_id}")
async def detail(club_id: int, request: Request, user=Depends(current_user)):
    async with request.app.state.sessions() as db:
        club = await db.get(Club, club_id)
        if not club or not club.active:
            fail(404, "CLUB_NOT_FOUND", "社团不存在")
        return ok(club_data(club, True))


@app.put("/api/v1/favorites/{club_id}")
async def favorite(club_id: int, request: Request, user=Depends(student)):
    async with request.app.state.sessions() as db, db.begin():
        await db.get(User, user.id, with_for_update=True)
        if not await db.get(Club, club_id):
            fail(404, "CLUB_NOT_FOUND", "社团不存在")
        if not await db.get(Favorite, (user.id, club_id)):
            db.add(Favorite(student_id=user.id, club_id=club_id))
    return ok()


@app.delete("/api/v1/favorites/{club_id}")
async def unfavorite(club_id: int, request: Request, user=Depends(student)):
    async with request.app.state.sessions() as db, db.begin():
        await db.execute(delete(Favorite).where(Favorite.student_id == user.id, Favorite.club_id == club_id))
    return ok()


@app.get("/api/v1/enrollment")
async def enrollment(request: Request, user=Depends(student)):
    async with request.app.state.sessions() as db:
        return ok(await enrollment_data(db, user.id))


@app.post("/api/v1/enrollment")
async def select_club(
    body: EnrollmentInput,
    request: Request,
    user=Depends(enrollment_identity),
    idempotency_key: str = Header(),
):
    await rate_limit(request, "enrollment", user.id, 6, 10)
    return ok(
        await mutate_enrollment(
            request.app.state.sessions, user.id, user.token_version, idempotency_key, body.club_id
        )
    )


@app.delete("/api/v1/enrollment")
async def cancel(request: Request, user=Depends(enrollment_identity), idempotency_key: str = Header()):
    await rate_limit(request, "enrollment", user.id, 6, 10)
    return ok(
        await mutate_enrollment(
            request.app.state.sessions, user.id, user.token_version, idempotency_key, cancel=True
        )
    )


@app.put("/api/v1/profile")
async def contact(body: Contact, request: Request, user=Depends(student)):
    async with request.app.state.sessions() as db, db.begin():
        await db.execute(update(User).where(User.id == user.id).values(**body.model_dump()))
    return ok(body.model_dump())


@app.websocket("/api/v1/ws")
async def ws(socket: WebSocket):
    await socket.app.state.hub.serve(socket)


app.include_router(admin_router, prefix="/api/v1/admin")
app.include_router(upload_router, prefix="/api/v1")


@app.api_route("/{legacy:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def legacy_route(legacy: str):
    if legacy.startswith("api/v1/"):
        fail(404, "NOT_FOUND", "接口不存在")
    fail(426, "UPGRADE_REQUIRED", "请关闭并重新进入小程序，更新到最新版本")
