"""Local-only destructive synthetic capacity rehearsal; never targets production.
Runs two API workers on port 8002 and uses club_test / Redis DB15 exclusively.
"""

import argparse
import asyncio
from collections import Counter
from datetime import timedelta
import json
import os
from pathlib import Path
import signal
import subprocess
import time

os.environ.update(
    CLUB_ENV="test",
    DATABASE_URL="mysql+asyncmy://club:club-local-only@127.0.0.1:13306/club_test?charset=utf8mb4",
    REDIS_URL="redis://127.0.0.1:16379/15",
    REDIS_PREFIX="club:load",
    JWT_SECRET="synthetic-load-secret-not-a-production-credential",
)
# Keep source root importable when run as a script.
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aiohttp
from redis.asyncio import Redis
from sqlalchemy import delete, select, text
from club.db import make_engine, sessions
from club.models import Activity, Base, Club, Enrollment, Favorite, Idempotency, Outbox, User, utcnow
from club.security import hash_password, token
from club.services import consistency


def percentile(values, q):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(len(values) * q))], 3) if values else None


async def main(args):
    root = Path(__file__).resolve().parents[1]
    engine = make_engine()
    factory = sessions(engine)
    redis = Redis.from_url(os.environ["REDIS_URL"])
    # Refuse to touch a database while another local test service owns port 8002.
    import socket

    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 8002))
    except OSError:
        raise SystemExit("Port 8002 is busy; stop the owning test process before running")
    finally:
        sock.close()
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    await redis.flushdb()
    hashed = await hash_password("SyntheticLoad2026!")
    async with factory() as db, db.begin():
        db.add(
            Activity(
                id=1,
                starts_at=utcnow() - timedelta(hours=1),
                ends_at=utcnow() + timedelta(hours=2),
                state="published",
            )
        )
        users = [
            User(
                id=i,
                username=f"load{i:04d}",
                name=f"Synthetic {i}",
                password_hash=hashed,
                must_change_password=False,
            )
            for i in range(1, args.users + 1)
        ]
        db.add_all(users)
        db.add_all(
            [
                Club(id=i, name=f"Synthetic club {i}", capacity=args.users, remaining=args.users)
                for i in range(1, 43)
            ]
        )
    tokens = [token(u) for u in users]
    root.joinpath(".local").mkdir(exist_ok=True)
    report = {
        "environment": "macOS local loopback; load generator and service share hardware; NOT production capacity acceptance",
        "users": args.users,
        "api_workers": 2,
        "runs": [],
    }
    logs = root.joinpath(".local/load-api.log").open("w")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "club.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8002",
            "--workers",
            "2",
            "--no-access-log",
        ],
        cwd=root,
        env=os.environ,
        stdout=logs,
        stderr=logs,
        start_new_session=True,
    )
    try:
        async with aiohttp.ClientSession(
            base_url="http://127.0.0.1:8002",
            connector=aiohttp.TCPConnector(limit=args.users),
            timeout=aiohttp.ClientTimeout(total=20),
            trust_env=False,
        ) as client:
            for _ in range(50):
                try:
                    if (await client.get("/health/ready")).status == 200:
                        break
                except (aiohttp.ClientError, TimeoutError):
                    pass
                await asyncio.sleep(0.2)
            else:
                raise RuntimeError("API did not start")
            # Warm connections before the synchronized burst. Transport and client
            # scheduling are measured separately from server work.
            gate = asyncio.Semaphore(100)

            async def warm(t):
                async with gate:
                    r = await client.get("/health/live")
                    await r.read()

            await asyncio.gather(*(warm(t) for t in tokens))
            for scenario in ("last_seat", "uniform", "hot_club"):
                for run in range(args.rounds):
                    async with factory() as db, db.begin():
                        for model in (Favorite, Idempotency, Enrollment, Outbox):
                            await db.execute(delete(model))
                        await db.execute(
                            text("UPDATE v2_clubs SET capacity=:n,remaining=:n,version=version+1"),
                            {"n": 1 if scenario == "last_seat" else args.users},
                        )
                    async for key in redis.scan_iter("club:load:limit:*"):
                        await redis.delete(key)
                    released = time.perf_counter()
                    results = []

                    async def enroll(i, tok):
                        cid = i % 42 + 1 if scenario == "uniform" else 1
                        await asyncio.sleep(i / args.users)  # 1500/3000 offered in one second
                        start = time.perf_counter()
                        try:
                            r = await client.post(
                                "/api/v1/enrollment",
                                json={"club_id": cid},
                                headers={
                                    "Authorization": f"Bearer {tok}",
                                    "Idempotency-Key": f"{scenario}-{run}-{i:08d}",
                                },
                            )
                            code = (await r.json()).get("error", {}).get("code", "OK")
                            server_ms = float(r.headers.get("Server-Timing", "app;dur=0").split("dur=")[1])
                            results.append(
                                (r.status, code, time.perf_counter() - start, start - released, server_ms)
                            )
                        except (aiohttp.ClientError, TimeoutError) as exc:
                            results.append(
                                (0, type(exc).__name__, time.perf_counter() - start, start - released, 0)
                            )

                    await asyncio.gather(*(enroll(i, t) for i, t in enumerate(tokens)))
                    async with factory() as db:
                        mismatch = await consistency(db)
                        selected = len(list(await db.scalars(select(Enrollment.student_id))))
                    statuses = Counter(str(r[0]) + ":" + r[1] for r in results)
                    latency = [r[2] for r in results]
                    accepted = [r[2] for r in results if r[0] == 200]
                    expected = 1 if scenario == "last_seat" else args.users
                    item = {
                        "scenario": scenario,
                        "round": run + 1,
                        "status": dict(statuses),
                        "p50_s": percentile(latency, 0.5),
                        "p95_s": percentile(latency, 0.95),
                        "p99_s": percentile(latency, 0.99),
                        "success_p95_s": percentile(accepted, 0.95),
                        "server_p95_s": percentile([r[4] / 1000 for r in results], 0.95),
                        "dispatch_span_s": round(max(r[3] for r in results) - min(r[3] for r in results), 3),
                        "enrollments": selected,
                        "expected": expected,
                        "quota_consistent": not mismatch,
                        "correctness_pass": selected == expected and not mismatch,
                        "latency_pass": percentile(latency, 0.95) <= 2 and percentile(latency, 0.99) <= 5,
                        "unexpected_error_rate": sum(r[0] == 0 or r[0] >= 500 for r in results) / args.users,
                        "wall_s": round(time.perf_counter() - released, 3),
                    }
                    report["runs"].append(item)
                    print(json.dumps(item), flush=True)
                    root.joinpath(args.report).write_text(
                        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
                    )
                    await asyncio.sleep(1)
            read = []
            for i in range(100):
                start = time.perf_counter()
                r = await client.get(
                    "/api/v1/clubs/quotas", headers={"Authorization": f"Bearer {tokens[i % len(tokens)]}"}
                )
                if r.status != 200:
                    raise RuntimeError("Read failed after load")
                read.append(time.perf_counter() - start)
            report["steady_read_p95_s"] = percentile(read, 0.95)
            root.joinpath(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)
        logs.close()
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--users", type=int, choices=[1500, 3000], default=1500)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--report", default="reports/local-capacity.json")
    asyncio.run(main(p.parse_args()))
