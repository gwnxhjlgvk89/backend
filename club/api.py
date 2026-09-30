from club.logging import install
from club.admin import router as admin_router
import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import MutableHeaders
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from prometheus_client import Counter, Histogram

from club.config import settings
from club.metrics import render, CONNECTIONS, LOOP_LAG
from club.db import make_engine, sessions
from club.identity import IdentityReader
from club.bootstrap import BootstrapReader
from club.errors import DomainError, fail
from club.models import Activity, Club, Favorite, Job, Outbox, User, utcnow
from club.realtime import Hub
from club.schemas import (
    Contact,
    EnrollmentInput,
    Login,
    PasswordChange,
    Envelope,
    LoginOutput,
    BootstrapOutput,
    ClubDetailOutput,
    QuotaOutput,
    EnrollmentOutput,
    EnrollmentResult,
)
from club.security import (
    current_user,
    enrollment_identity,
    issue_ticket,
    public_user,
    set_password,
    rate_limit,
    student,
    token,
    verify_password,
)
from club.services import CLUB_KEYS, enrollment_data, event, iso, mutate_enrollment

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
    app.state.catalog_lock = asyncio.Lock()
    app.state.catalog_local = None
    # Enrollment transactions queue here, bounded below the write pool so login
    # and other writes keep the overflow connections.
    app.state.enrollment_slots = asyncio.Semaphore(s.pool_size)
    # Reserve connections per API process for identity, bootstrap, detail and
    # result reads; enrollment writes cannot exhaust this pool.
    app.state.read_engine = make_engine(pool_size=s.read_pool_size, max_overflow=0, read_only=True)
    app.state.read_sessions = sessions(app.state.read_engine)
    app.state.bootstrap_reads = BootstrapReader(app.state.read_sessions)
    app.state.identities = IdentityReader(app.state.read_sessions)
    app.state.login_accounts = IdentityReader(app.state.read_sessions, User.username)
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
    validator = asyncio.create_task(app.state.hub.validation_loop(app.state.read_sessions))

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
    validator.cancel()
    await asyncio.gather(task, validator, return_exceptions=True)
    await app.state.bootstrap_reads.close()
    await app.state.identities.close()
    await app.state.login_accounts.close()
    await app.state.redis.aclose()
    await subscriber_redis.aclose()
    await app.state.engine.dispose()
    await app.state.read_engine.dispose()


app = FastAPI(
    title="社团填报系统 v2",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
)


class Observe:
    """Observe response headers directly without a task/stream bridge per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.monotonic()
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def observed_send(message):
            if message["type"] == "http.response.start":
                route = getattr(scope.get("route"), "path", "unmatched")
                elapsed = time.monotonic() - started
                status = message["status"]
                REQUESTS.labels(route, scope["method"], status).inc()
                LATENCY.labels(route, scope["method"]).observe(elapsed)
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["Server-Timing"] = f"app;dur={elapsed * 1000:.2f}"
                headers["Cache-Control"] = "no-store"
                # nginx keeps the full access log; per-request journal writes cost
                # measurable CPU during the opening burst, so keep only outliers.
                if status >= 500 or elapsed >= 1:
                    logger.warning(
                        json.dumps(
                            {
                                "request_id": request_id,
                                "route": route,
                                "method": scope["method"],
                                "status": status,
                                "ms": round(elapsed * 1000),
                            }
                        )
                    )
            await send(message)

        await self.app(scope, receive, observed_send)


app.add_middleware(Observe)


def ok(data=None):
    return {"data": data}


def error_response(request, status, code, message, extra=None):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", ""),
                **(extra or {}),
            }
        },
    )


@app.exception_handler(DomainError)
async def domain_error(request, exc):
    return error_response(request, exc.status, exc.code, exc.message, exc.extra)


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
    async with request.app.state.read_sessions() as db:
        await db.execute(text("SELECT 1"))
        if not await db.get(Activity, 1):
            fail(503, "NOT_INITIALIZED", "数据库未初始化")
    await request.app.state.redis.ping()
    return {"status": "ready"}


@app.get("/metrics")
async def metrics(request: Request):
    if request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        fail(403, "PRIVATE_ENDPOINT", "此接口仅供本机监控")
    # Query shared durable state only at scrape time, never on enrollment writes.
    values = []
    try:
        async with asyncio.timeout(2), request.app.state.sessions() as db:
            pending = await db.scalar(
                select(func.count()).select_from(Outbox).where(Outbox.delivered.is_(False))
            )
            states = dict((await db.execute(select(Job.state, func.count()).group_by(Job.state))).all())
        values += ["club_database_available 1", f"club_outbox_pending {pending}"]
        values += [
            f'club_jobs{{state="{state}"}} {states.get(state, 0)}'
            for state in ("queued", "running", "failed", "preview")
        ]
    except (SQLAlchemyError, TimeoutError):
        values.append("club_database_available 0")
    try:
        await request.app.state.redis.ping()
        values.append("club_redis_available 1")
    except RedisError:
        values.append("club_redis_available 0")
    return Response(render() + ("\n".join(values) + "\n").encode(), media_type="text/plain; version=0.0.4")


@app.post("/api/v1/auth/login", response_model=Envelope[LoginOutput])
async def login(body: Login, request: Request):
    await rate_limit(request, "login", body.username, 10, 60)
    u = await request.app.state.login_accounts.get(body.username)
    if not u or not u.active:
        fail(401, "INVALID_CREDENTIALS", "账号或密码错误")
    verified_plaintext = u.password_plaintext
    uid = u.id
    if not await verify_password(body.password, verified_plaintext):
        fail(401, "INVALID_CREDENTIALS", "账号或密码错误")
    async with request.app.state.sessions() as db, db.begin():
        # Re-read after verification: an admin may have disabled/reset this user.
        u = await db.get(User, uid, with_for_update=True)
        if not u or not u.active or u.password_plaintext != verified_plaintext:
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


@app.post("/api/v1/auth/password", response_model=Envelope[LoginOutput])
async def password(body: PasswordChange, request: Request, user=Depends(current_user)):
    await rate_limit(request, "password", user.id, 5, 60)
    if not await verify_password(body.old_password, user.password_plaintext):
        fail(400, "PASSWORD_INCORRECT", "原密码错误")
    async with request.app.state.sessions() as db, db.begin():
        u = await db.get(User, user.id, with_for_update=True)
        if u.token_version != user.token_version:
            fail(401, "SESSION_EXPIRED", "登录已失效")
        set_password(u, body.new_password)
        u.must_change_password = False
        u.token_version += 1
        event(db, {"event": "session_revoked", "user_id": u.id, "version": u.token_version})
    return ok({"token": token(u), "user": public_user(u)})


@app.post("/api/v1/auth/ws-ticket")
async def ws_ticket(request: Request, user=Depends(current_user)):
    await rate_limit(request, "ticket", user.id, 30, 60)
    return ok({"ticket": await issue_ticket(request, user)})


CATALOG_COLUMNS = [getattr(Club, k) for k in CLUB_KEYS if k not in {"remaining", "version"}]
# Club fields change only while registration is closed (admin edits require it),
# so a few seconds of per-process reuse cannot serve a stale catalog mid-burst.
CATALOG_LOCAL_SECONDS = 5


def raw_json(body: str):
    # Hot read endpoints are assembled as JSON text: the response_model stays
    # for documentation, but returning a Response skips re-validating it.
    return Response(body, media_type="application/json")


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def catalog_json(request):
    """The active catalog as a JSON array string, reused without re-parsing."""
    state = request.app.state
    cached = getattr(state, "catalog_local", None)
    if cached and time.monotonic() - cached[0] < CATALOG_LOCAL_SECONDS:
        return cached[1]
    key = f"{settings().redis_prefix}:catalog"
    try:
        value = await state.redis.get(key)
    except RedisError:
        value = None
    if not value:
        # Coalesce a cold catalog miss within each process; quota reads stay separate.
        async with state.catalog_lock:
            try:
                value = await state.redis.get(key)
            except RedisError:
                value = None
            if not value:
                async with state.read_sessions() as db:
                    rows = (
                        await db.execute(
                            select(*CATALOG_COLUMNS).where(Club.active.is_(True)).order_by(Club.id)
                        )
                    ).all()
                value = dumps([row._asdict() for row in rows])
                try:
                    await state.redis.set(key, value, ex=60)
                except RedisError:
                    pass
    state.catalog_local = (time.monotonic(), value)
    return value


async def quota_snapshot(request):
    async with request.app.state.read_sessions() as db:
        rows = (await db.execute(select(Club.id, Club.remaining, Club.version))).all()
        return [{"club_id": cid, "remaining": rem, "version": ver} for cid, rem, ver in rows]


@app.get("/api/v1/bootstrap", response_model=Envelope[BootstrapOutput])
async def bootstrap(request: Request, user=Depends(current_user)):
    snapshot = await request.app.state.bootstrap_reads.get(user.id)
    catalog = await catalog_json(request)
    personal = dumps({"user": public_user(user), "server_time": iso(utcnow()), **snapshot})
    return raw_json('{"data":' + personal[:-1] + ',"clubs":' + catalog + "}}")


@app.get("/api/v1/clubs/quotas", response_model=Envelope[list[QuotaOutput]])
async def quotas(request: Request, user=Depends(current_user)):
    return raw_json(dumps(ok(await quota_snapshot(request))))


DETAIL_COLUMNS = [getattr(Club, k) for k in CLUB_KEYS + ("description",)]


@app.get("/api/v1/clubs/{club_id}", response_model=Envelope[ClubDetailOutput])
async def detail(club_id: int, request: Request, user=Depends(current_user)):
    async with request.app.state.read_sessions() as db:
        club = (await db.execute(select(*DETAIL_COLUMNS).where(Club.id == club_id))).first()
    if not club or not club.active:
        fail(404, "CLUB_NOT_FOUND", "社团不存在")
    return raw_json(dumps(ok(club._asdict())))


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


@app.get("/api/v1/enrollment", response_model=Envelope[EnrollmentOutput | None])
async def enrollment(request: Request, user=Depends(student)):
    async with request.app.state.read_sessions() as db:
        return ok(await enrollment_data(db, user.id))


@app.post("/api/v1/enrollment", response_model=Envelope[EnrollmentResult])
async def select_club(
    body: EnrollmentInput,
    request: Request,
    user=Depends(enrollment_identity),
    idempotency_key: str = Header(),
):
    await rate_limit(request, "enrollment", user.id, 6, 10)
    return ok(
        await mutate_enrollment(
            request.app.state.sessions,
            user.id,
            user.token_version,
            idempotency_key,
            body.club_id,
            slots=request.app.state.enrollment_slots,
        )
    )


@app.delete("/api/v1/enrollment", response_model=Envelope[EnrollmentResult])
async def cancel(request: Request, user=Depends(enrollment_identity), idempotency_key: str = Header()):
    await rate_limit(request, "enrollment", user.id, 6, 10)
    return ok(
        await mutate_enrollment(
            request.app.state.sessions,
            user.id,
            user.token_version,
            idempotency_key,
            cancel=True,
            slots=request.app.state.enrollment_slots,
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


@app.api_route("/{legacy:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def legacy_route(legacy: str):
    if legacy.startswith("api/v1/"):
        fail(404, "NOT_FOUND", "接口不存在")
    fail(426, "UPGRADE_REQUIRED", "请关闭并重新进入小程序，更新到最新版本")
