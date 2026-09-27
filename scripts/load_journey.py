"""TEST-only student journeys from a separate machine; never a production verdict.

Each student progresses independently. Only opening time is a business barrier.
Failures, unfinished users and generator scheduling lag remain in the report.
"""

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import shlex
import ssl
import hashlib
import time

import aiohttp
import psutil

try:
    from scripts.load_remote import fixture, p, ssh
except ModuleNotFoundError:
    from load_remote import fixture, p, ssh


def summary(rows):
    times = [r[2] for r in rows]
    return {
        "count": len(rows),
        "statuses": dict(Counter(f"{r[0]}:{r[1]}" for r in rows)),
        "p50_s": p(times, 0.5),
        "p95_s": p(times, 0.95),
        "p99_s": p(times, 0.99),
        "max_s": round(max(times), 4) if times else None,
        "server_p95_s": p([r[4] for r in rows if r[4] is not None], 0.95),
        "dispatch_span_s": round(max(r[3] for r in rows) - min(r[3] for r in rows), 4) if rows else None,
        "unexpected_errors": sum(r[0] == 0 or r[0] >= 500 for r in rows),
        "capacity_rejections": sum(r[0] in (429, 503) for r in rows),
        "response_bytes": sum(r[5] for r in rows),
        "arrivals_per_second": dict(sorted(Counter(int(r[3]) for r in rows).items())),
    }


async def run(args):
    path = Path(args.report)
    if path.exists():
        raise SystemExit("Refusing to overwrite an existing report")
    report = {
        "schema": "student-journey-v1",
        "environment": args.url,
        "test_only": True,
        "parameters": vars(args),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "http_sessions": "One independent connection pool per student (limit=6 including WS)",
        "runs": [],
        "errors": [],
        "resources": [],
        "production_capacity_verified": False,
        "network_scope": "LAN with externally recorded egress shaping; no simulated public RTT/loss",
    }
    path.parent.mkdir(parents=True, exist_ok=True)

    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    tls = ssl.create_default_context(cafile=args.ca_cert) if args.ca_cert else True
    connector = aiohttp.TCPConnector(limit=6, ttl_dns_cache=300, ssl=tls)
    async with aiohttp.ClientSession(
        base_url=args.url,
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=10),
        trust_env=False,
        headers={"Accept-Encoding": "gzip"},
    ) as client:
        for attempt in range(20):
            try:
                async with client.get("/health/live") as r:
                    if r.status == 200:
                        if (await r.json()).get("environment") != "test":
                            raise RuntimeError("Refusing non-TEST target")
                        break
            except aiohttp.ClientConnectionError:
                pass
            await asyncio.sleep(1)
        else:
            raise RuntimeError("Test service did not become ready")
        await fixture(args, "check")
        code = "from pathlib import Path; import hashlib; f=sorted(Path('club').glob('*.py')); print(hashlib.sha256(b''.join(p.name.encode()+bytes([0])+p.read_bytes() for p in f)).hexdigest())"
        selected = "import json; from club.config import settings; s=settings(); print(json.dumps({k:getattr(s,k) for k in ('password_concurrency','pool_size','pool_overflow')}))"
        report["runtime_settings"] = json.loads(
            await ssh(args, "podman exec club-capacity-test_api_1 python -c " + shlex.quote(selected))
        )
        report["application_sha256"] = (
            await ssh(args, "podman exec club-capacity-test_api_1 python -c " + shlex.quote(code))
        ).strip()
        async with client.post(
            "/api/v1/auth/login", json={"username": "load3000", "password": "SyntheticLoad2026!"}
        ) as r:
            calibration_token = (await r.json())["data"]["token"]
        clock_start = time.time()
        async with client.get(
            "/api/v1/bootstrap", headers={"Authorization": "Bearer " + calibration_token}
        ) as r:
            clock_data = (await r.json())["data"]
        clock_end = time.time()
        offset = (
            datetime.fromisoformat(clock_data["server_time"].replace("Z", "+00:00")).timestamp()
            - (clock_start + clock_end) / 2
        )
        report["clock_offset_s"] = offset
        report["clock_calibration_rtt_s"] = clock_end - clock_start
        report["started_at"] = datetime.now(timezone.utc).isoformat()
        stop_monitor = asyncio.Event()
        lag = []
        proc = psutil.Process()
        proc.cpu_percent()

        async def monitor():
            while not stop_monitor.is_set():
                tick = time.monotonic()
                await asyncio.sleep(0.1)
                lag.append(max(0, time.monotonic() - tick - 0.1))

        async def resources():
            while not stop_monitor.is_set():
                try:
                    data = json.loads(
                        await ssh(args, "python3 ~/club-system-test/backend/deploy/metrics-test.py")
                    )
                    report["resources"].append(
                        {
                            "at": time.time(),
                            "server": data,
                            "generator_cpu_percent": proc.cpu_percent(),
                            "generator_rss": proc.memory_info().rss,
                        }
                    )
                    save()
                except Exception as exc:
                    report["errors"].append("monitor: " + type(exc).__name__)
                await asyncio.sleep(10)

        students = [
            aiohttp.ClientSession(
                base_url=args.url,
                connector=aiohttp.TCPConnector(limit=6, ssl=tls),
                timeout=aiohttp.ClientTimeout(total=10, ceil_threshold=30),
                trust_env=False,
                headers={"Accept-Encoding": "gzip"},
            )
            for _ in range(args.users)
        ]
        monitors = [asyncio.create_task(monitor()), asyncio.create_task(resources())]
        reusable_tokens = [None] * args.users
        try:
            for round_no in range(args.rounds):
                await fixture(args, "prepare", args.scenario)

                async def cold_cache():
                    code = "import asyncio; from redis.asyncio import Redis; from club.config import settings\nasync def f():\n r=Redis.from_url(settings().redis_url)\n keys=[k async for k in r.scan_iter(settings().redis_prefix+':catalog*')]\n if keys: await r.delete(*keys)\n await r.aclose()\nasyncio.run(f())"
                    await ssh(args, "podman exec club-capacity-test_api_1 python -c " + shlex.quote(code))

                if args.cache == "cold":
                    await cold_cache()
                stages = defaultdict(list)
                setup = defaultdict(list)
                tokens = [None] * args.users
                sockets = {}
                pending_boot = {}
                auxiliaries = set()
                outcomes = Counter()
                last_codes = {}
                seen_enrolled = set()
                completed = set()
                ws_counts = Counter()
                ws_workers = set()
                payload = Counter()
                received_quotas = {}
                latest_seen = defaultdict(dict)
                stop_users = asyncio.Event()
                measuring = False
                zero = time.monotonic()
                deadline = float("inf")
                rng = random.Random(args.seed + round_no)
                measured_epoch = None

                def spawn(coro):
                    task = asyncio.create_task(coro)
                    auxiliaries.add(task)
                    task.add_done_callback(auxiliaries.discard)
                    return task

                async def request(i, stage, method, endpoint, body=None, key=None):
                    records = stages if measuring else setup
                    begin = time.monotonic()
                    status, code, data, server, size = 0, "UNKNOWN", None, None, 0
                    headers = {"Authorization": "Bearer " + tokens[i]} if tokens[i] else {}
                    if key:
                        headers["Idempotency-Key"] = key
                    try:
                        async with students[i].request(
                            method, "/api/v1" + endpoint, json=body, headers=headers
                        ) as r:
                            raw = await r.read()
                            size = len(raw)
                            status = r.status
                            result = json.loads(raw)
                            code = result.get("error", {}).get("code", "OK")
                            data = result.get("data")
                            if status == 200:
                                snapshots = (
                                    data.get("quotas", [])
                                    if isinstance(data, dict)
                                    else data
                                    if endpoint == "/clubs/quotas"
                                    else []
                                )
                                for q in snapshots:
                                    cid, version = q["club_id"], q["version"]
                                    latest_seen[i][cid] = max(latest_seen[i].get(cid, 0), version)
                            header = r.headers.get("Server-Timing", "")
                            if "dur=" in header:
                                server = float(header.split("dur=")[1]) / 1000
                    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                        code = type(exc).__name__
                    records[stage].append(
                        (status, code, time.monotonic() - begin, begin - zero, server, size)
                    )
                    last_codes[(i, stage)] = code
                    return status, data

                async def bootstrap(i, stage="bootstrap"):
                    if i in pending_boot:
                        return await pending_boot[i]
                    task = asyncio.create_task(request(i, stage, "GET", "/bootstrap"))
                    pending_boot[i] = task
                    try:
                        return await task
                    finally:
                        pending_boot.pop(i, None)

                async def consume(i, ws):
                    try:
                        async for message in ws:
                            if message.type != aiohttp.WSMsgType.TEXT:
                                continue
                            value = json.loads(message.data)
                            if measuring:
                                payload[int(time.monotonic() - zero)] += len(message.data.encode())
                            if "worker_id" in value:
                                ws_workers.add(value["worker_id"])
                            event = value.get("event")
                            if event == "quota_delta":
                                now = time.time() + offset
                                for cid, remaining, version in value.get("rows", []):
                                    received_quotas.setdefault((cid, version), {})[i] = now
                                    latest_seen[i][cid] = max(latest_seen[i].get(cid, 0), version)
                            elif event == "enrollment" and args.client_profile == "lean":
                                spawn(request(i, "event_enrollment", "GET", "/enrollment"))
                            elif event in {"resync", "catalog", "activity", "enrollment"}:
                                spawn(bootstrap(i, "event_bootstrap"))
                    except (aiohttp.ClientError, ValueError):
                        ws_counts["consumer_error"] += 1
                    finally:
                        if not stop_users.is_set() and sockets.get(i) is ws:
                            ws_counts["unexpected_close"] += 1

                async def connect(i):
                    status, data = await request(i, "ws_ticket", "POST", "/auth/ws-ticket")
                    if status != 200:
                        return False
                    started = time.monotonic()
                    records = stages if measuring else setup
                    try:
                        ws = await students[i].ws_connect(
                            "/api/v1/ws?ticket=" + data["ticket"], heartbeat=None
                        )
                        sockets[i] = ws
                        records["ws_connect"].append(
                            (101, "OK", time.monotonic() - started, started - zero, None, 0)
                        )
                        ws_counts["connected"] += 1
                        spawn(consume(i, ws))
                        return True
                    except (aiohttp.ClientError, TimeoutError):
                        records["ws_connect"].append(
                            (0, "CONNECT_FAILED", time.monotonic() - started, started - zero, None, 0)
                        )
                        return False

                async def background(i):
                    next_ping = time.monotonic() + 20
                    next_sync = time.monotonic() + 60
                    next_browse = time.monotonic() + 20 + rng.random() * 20
                    while not stop_users.is_set():
                        await asyncio.sleep(1)
                        now = time.monotonic()
                        ws = sockets.get(i)
                        online = ws is not None and not ws.closed
                        if now >= next_ping:
                            if online:
                                try:
                                    await ws.send_json({"event": "ping"})
                                except (aiohttp.ClientError, ConnectionError):
                                    ws_counts["ping_error"] += 1
                            next_ping = now + 20
                        if now >= next_sync:
                            await request(i, "periodic_quotas", "GET", "/clubs/quotas")
                            if not online:
                                await connect(i)
                            next_sync = time.monotonic() + (60 if online else 10 + rng.random() * 5)
                        if measuring and now >= next_browse:
                            await request(i, "active_detail", "GET", f"/clubs/{i % 42 + 1}")
                            next_browse = time.monotonic() + 20 + rng.random() * 20

                async def login(i):
                    status, data = await request(
                        i,
                        "login",
                        "POST",
                        "/auth/login",
                        {"username": f"load{i + 1:04d}", "password": "SyntheticLoad2026!"},
                    )
                    if status != 200:
                        return False
                    tokens[i] = data["token"]
                    return True

                async def enter(i):
                    status, _ = await bootstrap(i)
                    if status != 200:
                        return False
                    await connect(i)
                    spawn(background(i))
                    return True

                prepared = (
                    args.users
                    if args.mode in {"ready", "reconnect"}
                    else args.users * 4 // 5
                    if args.mode == "mixed"
                    else 0
                )
                if prepared:
                    before = time.monotonic()
                    reused_sessions = sum(bool(t) for t in reusable_tokens[:prepared])
                    preparation_window = 3 if reused_sessions == prepared else 60

                    async def prepare(i):
                        await asyncio.sleep(
                            max(0, before + i * preparation_window / args.users - time.monotonic())
                        )
                        if reusable_tokens[i]:
                            tokens[i] = reusable_tokens[i]
                            await enter(i)
                        elif await login(i):
                            reusable_tokens[i] = tokens[i]
                            await enter(i)

                    print(f"preparing {prepared} existing sessions", flush=True)
                    await asyncio.gather(*(prepare(i) for i in range(prepared)))
                    await asyncio.sleep(1)
                if args.cache == "cold":
                    await cold_cache()
                zero = time.monotonic() + 2
                measured_epoch = time.time() + 2
                deadline = zero + args.hold_seconds
                opening = zero + args.open_after
                # The actual server enforces the same opening boundary, not only the driver.
                code = (
                    "import asyncio; from datetime import datetime,timezone,timedelta; from club.db import make_engine,sessions; from club.models import Activity\nasync def f():\n e=make_engine()\n async with sessions(e)() as d,d.begin():\n  a=await d.get(Activity,1,with_for_update=True)\n  a.state='published'; a.starts_at=datetime.fromtimestamp("
                    + str(measured_epoch + args.open_after + offset)
                    + ",timezone.utc).replace(tzinfo=None); a.ends_at=a.starts_at+timedelta(hours=1)\n await e.dispose()\nasyncio.run(f())"
                )
                await ssh(args, "podman exec club-capacity-test_api_1 python -c " + shlex.quote(code))
                # Clock skew is bounded by LAN clock calibration recorded before the burst.
                measuring = True

                async def journey(i):
                    await asyncio.sleep(
                        max(
                            0,
                            zero
                            + (i - prepared if i >= prepared else i)
                            * args.burst_seconds
                            / max(1, args.users - prepared if i >= prepared else prepared)
                            - time.monotonic(),
                        )
                    )
                    begin = time.monotonic()
                    if i >= prepared:
                        if not await login(i):
                            outcomes["login_failed"] += 1
                            return
                        if not await enter(i):
                            outcomes["bootstrap_failed"] += 1
                            return
                    elif not tokens[i]:
                        outcomes["setup_failed"] += 1
                        return
                    else:
                        status, _ = await bootstrap(i, "burst_bootstrap")
                        if status != 200:
                            outcomes["bootstrap_failed"] += 1
                            return
                    if args.mode == "reconnect":
                        old = sockets.pop(i, None)
                        if old:
                            await old.close()
                        ws_counts["intentional_disconnect"] += 1
                        await connect(i)
                    cid = i % 42 + 1 if args.scenario == "uniform" else 1
                    status, _ = await request(i, "detail", "GET", f"/clubs/{cid}")
                    if status != 200:
                        outcomes["detail_failed"] += 1
                        return
                    await asyncio.sleep(
                        max(0, opening + i * args.burst_seconds / args.users - time.monotonic())
                    )
                    key = f"journey-{args.mode}-{time.time_ns()}-{i}"
                    status, data = await request(i, "enroll", "POST", "/enrollment", {"club_id": cid}, key)
                    if status == 200:
                        seen_enrolled.add(i)
                        if args.client_profile == "legacy":
                            await bootstrap(i, "after_enrollment_bootstrap")
                    elif status == 0 or status >= 500:
                        q, mine = await request(i, "uncertain_result", "GET", "/enrollment")
                        if q == 200 and mine:
                            seen_enrolled.add(i)
                        elif q == 200:
                            # One explicit same-key retry, after result lookup. Report separately.
                            await asyncio.sleep(0.5 + rng.random())
                            retry, data = await request(
                                i, "enroll_retry", "POST", "/enrollment", {"club_id": cid}, key
                            )
                            if retry == 200:
                                seen_enrolled.add(i)
                    if (
                        status == 200
                        or (status == 409 and last_codes.get((i, "enroll")) == "CLUB_FULL")
                        or i in seen_enrolled
                    ):
                        completed.add(i)
                    outcomes[f"enroll_http_{status}"] += 1
                    stages["journey"].append(
                        (
                            200 if i in completed else 0,
                            "COMPLETE" if i in completed else "INCOMPLETE",
                            time.monotonic() - begin,
                            begin - zero,
                            None,
                            0,
                        )
                    )

                print(f"round {round_no + 1} {args.mode}/{args.scenario} burst started", flush=True)
                await asyncio.gather(*(journey(i) for i in range(args.users)))
                print(
                    json.dumps(
                        {
                            "login": summary(stages["login"]),
                            "enroll": summary(stages["enroll"]),
                            "completed": len(completed),
                        }
                    ),
                    flush=True,
                )
                while time.monotonic() < deadline:
                    await asyncio.sleep(min(10, max(0, deadline - time.monotonic())))
                    print(
                        json.dumps(
                            {
                                "active_seconds": round(time.monotonic() - zero),
                                "ws_open": sum(not s.closed for s in sockets.values()),
                            }
                        ),
                        flush=True,
                    )
                db = await fixture(args, "check", timings=True)
                quota_times = {(c, v): t for c, v, t in db.pop("quota_timings")}
                delays = [
                    max(0, t - quota_times[key])
                    for key, values in received_quotas.items()
                    if key in quota_times
                    for t in values.values()
                ]
                final_versions = {}
                for cid, version in quota_times:
                    final_versions[cid] = max(final_versions.get(cid, 0), version)
                missing_final = sum(
                    latest_seen[i].get(cid, 0) < version
                    for i in range(args.users)
                    for cid, version in final_versions.items()
                )
                expected = (
                    args.users
                    if args.scenario == "uniform"
                    else 1
                    if args.scenario == "last_seat"
                    else min(100, args.users)
                )
                item = {
                    "round": round_no + 1,
                    "measured_epoch": measured_epoch,
                    "stages": {k: summary(v) for k, v in stages.items()},
                    "setup": {k: summary(v) for k, v in setup.items()},
                    "outcomes": dict(outcomes),
                    "completed_students": len(completed),
                    "unfinished_students": args.users - len(completed),
                    "confirmed_enrollments": len(seen_enrolled),
                    "db": db,
                    "data_consistency_pass": not db["inconsistencies"]
                    and db["enrollments"] == len(seen_enrolled),
                    "expected_enrollments": expected,
                    "all_expected_enrolled": db["enrollments"] == expected,
                    "active_duration_s": round(time.monotonic() - zero, 2),
                    "websocket": {
                        **ws_counts,
                        "open_at_end": sum(not s.closed for s in sockets.values()),
                        "workers_observed": len(ws_workers),
                        "notification_p95_s": p(delays, 0.95),
                        "timed_deliveries": len(delays),
                        "missing_final_quota_snapshots": missing_final,
                        "payload_peak_mbps": max(payload.values(), default=0) * 8 / 1e6,
                    },
                }
                item["scope_gates"] = {
                    "all_students_completed": len(completed) == args.users,
                    "data_correct": item["data_consistency_pass"] and item["all_expected_enrolled"],
                    "all_final_quota_snapshots_current": missing_final == 0 and bool(final_versions),
                    "all_websockets_online": item["websocket"]["open_at_end"] == args.users,
                    "no_unexpected_ws_close": ws_counts["unexpected_close"] == 0,
                    "ready_enrollment_burst_within_1s": args.mode != "ready"
                    or (bool(stages["enroll"]) and item["stages"]["enroll"]["dispatch_span_s"] <= 1),
                    "login_p95_3s": not stages["login"] or item["stages"]["login"]["p95_s"] <= 3,
                    "login_burst_within_1s": not stages["login"]
                    or item["stages"]["login"]["dispatch_span_s"] <= 1,
                    "interactive_reads_p95_3s": all(
                        v["p95_s"] <= 3
                        for k, v in item["stages"].items()
                        if k
                        in {
                            "bootstrap",
                            "burst_bootstrap",
                            "detail",
                            "after_enrollment_bootstrap",
                            "event_bootstrap",
                        }
                        and v["count"]
                    ),
                    "notifications_p95_3s": bool(delays) and p(delays, 0.95) <= 3,
                    "enrollment_p95_3s_p99_5s": bool(stages["enroll"])
                    and item["stages"]["enroll"]["p95_s"] <= 3
                    and item["stages"]["enroll"]["p99_s"] <= 5,
                    "no_capacity_rejections": all(
                        v["capacity_rejections"] == 0 for k, v in item["stages"].items() if k != "journey"
                    ),
                    "unexpected_errors_under_0_1_percent": sum(
                        v["unexpected_errors"] for k, v in item["stages"].items() if k != "journey"
                    )
                    / max(1, sum(v["count"] for k, v in item["stages"].items() if k != "journey"))
                    < 0.001,
                }
                report["runs"].append(item)
                stop_users.set()
                await asyncio.gather(*(s.close() for s in sockets.values()), return_exceptions=True)
                for task in list(auxiliaries):
                    task.cancel()
                await asyncio.gather(*list(auxiliaries), return_exceptions=True)
                save()
                print(json.dumps({"round": round_no + 1, "gates": item["scope_gates"]}), flush=True)
                await asyncio.sleep(2)
        finally:
            await asyncio.gather(*(student.close() for student in students), return_exceptions=True)
            stop_monitor.set()
            for task in monitors:
                task.cancel()
            await asyncio.gather(*monitors, return_exceptions=True)
            report["generator_loop_lag_p95_s"] = p(lag, 0.95)
            report["generator_loop_lag_max_s"] = max(lag, default=0)
            save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--ca-cert", help="Explicit test CA for HTTPS; certificate verification remains enabled"
    )
    parser.add_argument("--ssh", default="gg1214@192.168.100.130")
    parser.add_argument("--control", default="/private/tmp/club-test-ssh")
    parser.add_argument("--users", type=int, choices=[30, 1500, 3000], default=1500)
    parser.add_argument("--mode", choices=["login", "ready", "mixed", "reconnect"], default="login")
    parser.add_argument("--scenario", choices=["uniform", "hot_club", "last_seat"], default="uniform")
    parser.add_argument("--client-profile", choices=["legacy", "lean"], default="lean")
    parser.add_argument("--cache", choices=["cold", "warm"], default="cold")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--hold-seconds", type=int, default=30)
    parser.add_argument("--burst-seconds", type=float, default=0.85)
    parser.add_argument("--open-after", type=float, default=5)
    parser.add_argument("--seed", type=int, default=1214)
    parser.add_argument("--report", required=True)
    arguments = parser.parse_args()
    if (
        arguments.rounds < 1
        or arguments.hold_seconds < 10
        or not 0 < arguments.burst_seconds <= 1
        or arguments.open_after < 2
    ):
        parser.error("positive rounds, hold>=10, burst in (0,1], open-after>=2 required")
    asyncio.run(run(arguments))
