"""Small HTTP/WS deployment acceptance; refuses the production database."""

import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import sys
import uuid

import httpx
from openpyxl import Workbook
from sqlalchemy.engine import make_url
from websockets.asyncio.client import connect
from club.config import settings
from club.db import make_engine, sessions
from club.services import consistency


async def main():
    s = settings()
    if (
        s.club_env != "test"
        or make_url(s.database_url).database != "club_v2_verify"
        or s.redis_prefix != "club:deploy:verify"
    ):
        raise SystemExit("Isolated deployment database and Redis namespace required")
    credentials = json.loads(Path(sys.argv[1]).read_text())
    checks = []
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8002", timeout=15, trust_env=False) as c:

        async def call(method, path, expected=200, token=None, **kw):
            headers = kw.pop("headers", {})
            if token:
                headers["Authorization"] = "Bearer " + token
            r = await c.request(method, "/api/v1" + path, headers=headers, **kw)
            if r.status_code != expected:
                code = r.json().get("error", {}).get("code", "UNKNOWN")
                raise RuntimeError(f"{method} {path}: {r.status_code}, {code}; expected {expected}")
            return r.json().get("data")

        async def login(username, password):
            return await call("POST", "/auth/login", json={"username": username, "password": password})

        first = await login("admin", credentials["password"])
        assert first["user"]["must_change_password"]
        admin = (
            await call(
                "POST",
                "/auth/password",
                token=first["token"],
                json={"old_password": credentials["password"], "new_password": "DeployVerifyChanged2026!"},
            )
        )["token"]
        await call("GET", "/admin/students", 401)
        checks.append("administrator login, first password change, anonymous denial")
        club = (
            await call(
                "POST",
                "/admin/clubs",
                token=admin,
                json={"name": "Deployment verification", "capacity": 1, "allowed_majors": ["CS"]},
            )
        )["id"]
        for number, major in ((1, "CS"), (2, "Arts")):
            await call(
                "POST",
                "/admin/students",
                token=admin,
                json={
                    "username": f"verify{number}",
                    "name": f"Verify {number}",
                    "major": major,
                    "password": "DeployVerifyInitial2026!",
                },
            )
        book = Workbook()
        sheet = book.active
        sheet.append(["username", "name", "major", "class_name", "password", "reserved_club_id"])
        sheet.append(["verify3", "Verify 3", "CS", "Synthetic", "DeployVerifyInitial2026!", None])
        content = BytesIO()
        book.save(content)

        async def wait_job(job, state):
            for _ in range(80):
                d = await call("GET", "/admin/jobs/" + job, token=admin)
                if d["state"] == state:
                    return d
                if d["state"] == "failed":
                    raise RuntimeError("Background job failed")
                await asyncio.sleep(0.25)
            raise RuntimeError("Background job stalled")

        job = (
            await call(
                "POST",
                "/admin/jobs/import",
                token=admin,
                files={
                    "file": (
                        "verify.xlsx",
                        content.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        )["id"]
        await wait_job(job, "preview")
        await call("POST", f"/admin/jobs/{job}/confirm", token=admin)
        await wait_job(job, "done")
        export = (await call("POST", "/admin/jobs/export", token=admin))["id"]
        await wait_job(export, "done")
        r = await c.get(
            "/api/v1/admin/jobs/" + export + "/download", headers={"Authorization": "Bearer " + admin}
        )
        assert r.status_code == 200 and r.content[:2] == b"PK"
        checks.append("student and club management, import preview/confirm, worker export/download")
        tokens = {}
        for n in (1, 2, 3):
            u = await login("verify" + str(n), "DeployVerifyInitial2026!")
            tokens[n] = (
                await call(
                    "POST",
                    "/auth/password",
                    token=u["token"],
                    json={
                        "old_password": "DeployVerifyInitial2026!",
                        "new_password": "DeployVerifyChanged2026!",
                    },
                )
            )["token"]

        async def enroll(n, status=200):
            return await call(
                "POST",
                "/enrollment",
                status,
                token=tokens[n],
                headers={"Idempotency-Key": uuid.uuid4().hex},
                json={"club_id": club},
            )

        await enroll(1, 409)
        now = datetime.now(timezone.utc)
        await call(
            "PUT",
            "/admin/activity",
            token=admin,
            json={
                "name": "Isolated deployment check",
                "starts_at": (now - timedelta(minutes=1)).isoformat(),
                "ends_at": (now + timedelta(hours=1)).isoformat(),
                "allow_cancel": True,
                "cancel_until": (now + timedelta(hours=1)).isoformat(),
            },
        )
        await call("POST", "/admin/activity/state", token=admin, json={"state": "published"})
        ticket = (await call("POST", "/auth/ws-ticket", token=tokens[1]))["ticket"]
        async with connect("ws://127.0.0.1:8002/api/v1/ws?ticket=" + ticket) as ws:
            initial = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert initial["event"] == "resync"
            await enroll(2, 403)
            await enroll(1)
            await enroll(3, 409)
            saw_quota = False
            for _ in range(12):
                event = json.loads(await asyncio.wait_for(ws.recv(), 5))
                if event["event"] == "quota_delta":
                    saw_quota = True
                    break
            assert saw_quota
            await call(
                "DELETE", "/enrollment", token=tokens[1], headers={"Idempotency-Key": uuid.uuid4().hex}
            )
            await enroll(3)
        checks.append("draft rejection, qualification, enrollment, full club, cancellation, quota WebSocket")
        await call("POST", "/admin/activity/state", token=admin, json={"state": "paused"})
        engine = make_engine()
        async with sessions(engine)() as db:
            assert not await consistency(db)
        await engine.dispose()
        checks.append("database enrollment/quota consistency")
    Path(sys.argv[2]).write_text(
        json.dumps(
            {"passed": True, "checks": checks, "scope": "isolated loopback HTTP and WS, synthetic data only"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(json.dumps({"passed": True, "checks": checks}))


asyncio.run(main())
