"""Model one explicit user retry after a completed synthetic cold-flow test.

No fixture reset. Only unselected load0001..load1500 accounts may be touched.
This does not claim the current mini-program automatically retries login.
"""

import argparse
import asyncio
import json
from pathlib import Path
import shlex
import ssl
import time
import uuid
from types import SimpleNamespace

import aiohttp

try:
    from scripts.load_remote import fixture, ssh
except ModuleNotFoundError:
    from load_remote import fixture, ssh


async def main(args):
    source = json.loads(Path(args.journey_report).read_text())
    params = source["parameters"]
    if not (
        source.get("completed")
        and not source["errors"]
        and params["url"] == "https://192.168.100.130:18082"
        and params["mode"] == "login"
        and params["scenario"] == "uniform"
        and params["users"] == 1500
        and params["rounds"] == 1
    ):
        raise SystemExit("Requires one completed original TEST cold/uniform round")
    output = Path(args.report)
    if output.exists():
        raise SystemExit("Refusing existing report")
    remote = SimpleNamespace(ssh="gg1214@192.168.100.130", control="/tmp/club-target-test-ssh")
    before = await fixture(remote, "check")
    if before["inconsistencies"] or before["enrollments"] != source["runs"][0]["db"]["enrollments"]:
        raise SystemExit("Fixture changed or inconsistent; refusing recovery")
    code = """import asyncio,json
from sqlalchemy import select,func
from sqlalchemy.engine import make_url
from club.config import settings
from club.db import make_engine,sessions
from club.models import User,Enrollment,Club
async def f():
 s=settings()
 assert s.club_env=='test' and make_url(s.database_url).database=='club_test' and s.redis_prefix=='club:test'
 e=make_engine()
 async with sessions(e)() as d:
  assert not await d.scalar(select(func.count()).select_from(User).where(~User.username.like('load%')))
  clubs=(await d.execute(select(Club.id,Club.capacity))).all()
  assert len(clubs)==42 and all(c==100 for _,c in clubs)
  rows=(await d.execute(select(User.id,User.username).outerjoin(Enrollment,Enrollment.student_id==User.id).where(User.id<=1500,Enrollment.student_id.is_(None)).order_by(User.id))).all()
  assert all(n==f'load{i:04d}' for i,n in rows)
  print(json.dumps([dict(id=i,username=n) for i,n in rows]))
 await e.dispose()
asyncio.run(f())"""
    missing = json.loads(
        await ssh(remote, "podman exec club-capacity-test_api_1 python -c " + shlex.quote(code))
    )
    if len(missing) != 1500 - before["enrollments"]:
        raise SystemExit("Unexpected missing-account population")
    result = {
        "policy": "one explicit user retry after pressure; no automatic login retry claim",
        "started_at": time.time(),
        "seconds_since_burst": time.time() - source["runs"][0]["measured_epoch"],
        "before": before,
        "missing_synthetic_accounts": missing,
        "attempts": [],
    }
    tls = ssl.create_default_context(cafile=args.ca_cert)
    async with aiohttp.ClientSession(
        base_url=params["url"],
        connector=aiohttp.TCPConnector(ssl=tls),
        timeout=aiohttp.ClientTimeout(total=10, ceil_threshold=30),
        trust_env=False,
    ) as session:
        async with session.get("/health/live") as response:
            if response.status != 200 or (await response.json()).get("environment") != "test":
                raise SystemExit("Refusing non-TEST endpoint")
        for user in missing:
            item = {"synthetic_id": user["id"], "stages": [], "confirmed": False}
            started = time.monotonic()

            async def request(stage, method, path, **kwargs):
                begin = time.monotonic()
                try:
                    async with session.request(method, "/api/v1" + path, **kwargs) as response:
                        data = await response.json()
                        item["stages"].append(
                            {"stage": stage, "status": response.status, "seconds": time.monotonic() - begin}
                        )
                        return response.status, data.get("data", data)
                except (aiohttp.ClientError, TimeoutError) as exc:
                    item["stages"].append(
                        {
                            "stage": stage,
                            "status": 0,
                            "error": type(exc).__name__,
                            "seconds": time.monotonic() - begin,
                        }
                    )
                    return 0, {}

            status, data = await request(
                "login_retry",
                "POST",
                "/auth/login",
                json={"username": user["username"], "password": "SyntheticLoad2026!"},
            )
            if status == 200:
                headers = {"Authorization": "Bearer " + data["token"]}
                status, _ = await request("bootstrap", "GET", "/bootstrap", headers=headers)
                if status == 200:
                    cid = (user["id"] - 1) % 42 + 1
                    status, _ = await request("detail", "GET", f"/clubs/{cid}", headers=headers)
                    if status == 200:
                        status, _ = await request(
                            "enroll",
                            "POST",
                            "/enrollment",
                            headers={**headers, "Idempotency-Key": "recovery-" + uuid.uuid4().hex},
                            json={"club_id": cid},
                        )
                        query, mine = await request("confirm", "GET", "/enrollment", headers=headers)
                        item["confirmed"] = query == 200 and bool(mine) and mine.get("club_id") == cid
            item["seconds"] = time.monotonic() - started
            result["attempts"].append(item)
    result["after"] = await fixture(remote, "check")
    result["finished_at"] = time.time()
    result["all_1500_enrolled"] = (
        result["after"]["enrollments"] == 1500 and not result["after"]["inconsistencies"]
    )
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "missing": len(missing),
                "recovered": sum(a["confirmed"] for a in result["attempts"]),
                "all_1500_enrolled": result["all_1500_enrolled"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--journey-report", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--ca-cert", required=True)
    asyncio.run(main(parser.parse_args()))
