"""Separate-machine load driver. Requires an explicitly identified TEST service.
Only the fixed synthetic fixture CLI resets test data; never a public test API.
"""

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import aiohttp
import psutil


def p(values, q):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(len(values) * q))], 4) if values else None


async def ssh(args, command):
    process = await asyncio.create_subprocess_exec(
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-S",
        args.control,
        args.ssh,
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await process.communicate()
    if process.returncode:
        raise RuntimeError("Test SSH command failed (credentials are not logged)")
    return out.decode()


async def fixture(args, action, scenario="uniform"):
    raw = await ssh(
        args,
        f"podman exec club-capacity-test_api_1 python -m club.load_fixture {action} --scenario {scenario}",
    )
    return json.loads(raw) if action == "check" else None


async def main(args):
    report = {
        "environment": args.url,
        "test_only": True,
        "users": args.users,
        "target_ws_hold_seconds": args.hold_seconds,
        "runs": [],
        "resources": [],
        "errors": [],
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)

    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    timeout = aiohttp.ClientTimeout(total=20)
    tokens = [None] * args.users
    sockets = []
    tasks = []
    stopped = asyncio.Event()
    workers = set()
    notification = []
    transport_lag = []
    received_events = 0
    ws_failures = 0
    lag = []
    generator = psutil.Process()
    generator.cpu_percent()
    async with aiohttp.ClientSession(
        base_url=args.url, connector=aiohttp.TCPConnector(limit=4000), timeout=timeout, trust_env=False
    ) as client:
        r = await client.get("/health/live")
        if r.status != 200 or (await r.json()).get("environment") != "test":
            raise RuntimeError("Refusing a service not explicitly marked TEST")
        await fixture(args, "check")

        async def monitor():
            while not stopped.is_set():
                started = time.perf_counter()
                await asyncio.sleep(1)
                lag.append(max(0, time.perf_counter() - started - 1))

        monitor_task = asyncio.create_task(monitor())

        async def resources():
            while not stopped.is_set():
                try:
                    value = json.loads(
                        await ssh(args, "python3 ~/club-system-test/backend/deploy/metrics-test.py")
                    )
                    report["resources"].append(
                        {
                            "at": datetime.now(timezone.utc).isoformat(),
                            "test_containers": value,
                            "generator_cpu_percent": psutil.cpu_percent(),
                            "generator_process_cpu_percent": generator.cpu_percent(),
                            "generator_process_rss_bytes": generator.memory_info().rss,
                            "generator_memory": psutil.virtual_memory().percent,
                        }
                    )
                    save()
                except Exception as exc:
                    report["errors"].append("resource monitor: " + type(exc).__name__)
                await asyncio.sleep(10)

        resource_task = asyncio.create_task(resources())
        login_results = []

        async def login(i):
            await asyncio.sleep(i * 60 / args.users)
            started = time.perf_counter()
            async with client.post(
                "/api/v1/auth/login", json={"username": f"load{i + 1:04d}", "password": "SyntheticLoad2026!"}
            ) as r:
                data = await r.json()
                login_results.append((r.status, time.perf_counter() - started))
                if r.status == 200:
                    tokens[i] = data["data"]["token"]

        print("login started", flush=True)
        await asyncio.gather(*(login(i) for i in range(args.users)))
        report["login"] = {
            "statuses": dict(Counter(str(x[0]) for x in login_results)),
            "p95_s": p([x[1] for x in login_results], 0.95),
            "duration_offered_s": 60,
        }
        save()
        print(json.dumps({"login": report["login"]}), flush=True)
        if not all(tokens):
            raise RuntimeError("Not all synthetic accounts logged in; capacity run aborted")
        # Measure server clock offset using midpoint of a short bootstrap round trip.
        start = time.time()
        r = await client.get("/api/v1/bootstrap", headers={"Authorization": "Bearer " + tokens[0]})
        server = datetime.fromisoformat(
            (await r.json())["data"]["server_time"].replace("Z", "+00:00")
        ).timestamp()
        clock_offset = server - (start + time.time()) / 2
        report["clock_offset_estimate_seconds"] = round(clock_offset, 4)
        ws_gate = asyncio.Semaphore(25)

        async def consume(ws):
            nonlocal received_events, ws_failures
            try:
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        event = json.loads(message.data)
                        if "worker_id" in event:
                            workers.add(event["worker_id"])
                        quota_events = (
                            [
                                {"club_id": r[0], "remaining": r[1], "version": r[2]}
                                for r in event.get("rows", [])
                            ]
                            if event.get("event") == "quota_delta"
                            else event.get("items", [])
                            if event.get("event") == "quotas"
                            else [event]
                            if event.get("event") == "quota"
                            else []
                        )
                        for item in quota_events:
                            received_events += 1
                            created = item.get("enqueued_at") or event.get("enqueued_at")
                            if created:
                                notification.append(
                                    max(
                                        0,
                                        time.time()
                                        + clock_offset
                                        - datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp(),
                                    )
                                )
                        if event.get("published_at"):
                            transport_lag.append(
                                max(
                                    0,
                                    time.time()
                                    + clock_offset
                                    - datetime.fromisoformat(
                                        event["published_at"].replace("Z", "+00:00")
                                    ).timestamp(),
                                )
                            )
                    elif message.type == aiohttp.WSMsgType.ERROR:
                        break
            except Exception as exc:
                if len(report["errors"]) < 10:
                    report["errors"].append("ws consumer: " + type(exc).__name__)
            finally:
                if not stopped.is_set():
                    ws_failures += 1
                    if ws_failures <= 5:
                        reason = {
                            "ws_close_code": ws.close_code,
                            "exception": type(ws.exception()).__name__ if ws.exception() else None,
                        }
                        report["errors"].append(reason)
                        print(json.dumps(reason), flush=True)

        async def connect(tok):
            async with ws_gate:
                r = await client.post("/api/v1/auth/ws-ticket", headers={"Authorization": "Bearer " + tok})
                ticket = (await r.json())["data"]["ticket"]
                ws = await client.ws_connect(
                    "/api/v1/ws?ticket=" + ticket, heartbeat=None, max_msg_size=65536
                )
                sockets.append(ws)
                tasks.append(asyncio.create_task(consume(ws)))

        await asyncio.gather(*(connect(t) for t in tokens))
        connected_at = time.monotonic()
        print(f"WebSockets connected: {len(sockets)}", flush=True)

        async def heartbeat():
            while not stopped.is_set():
                await asyncio.sleep(20)
                await asyncio.gather(
                    *(ws.send_json({"event": "ping"}) for ws in sockets if not ws.closed),
                    return_exceptions=True,
                )

        hb = asyncio.create_task(heartbeat())
        try:
            for scenario in ("last_seat", "uniform", "hot_club"):
                for round_no in range(args.rounds):
                    await fixture(args, "prepare", scenario)
                    await asyncio.sleep(0.5)
                    released = time.perf_counter()
                    results = []

                    async def enroll(i, tok):
                        await asyncio.sleep(i * 0.95 / args.users)
                        started = time.perf_counter()
                        server_seconds = 0
                        try:
                            async with client.post(
                                "/api/v1/enrollment",
                                json={"club_id": i % 42 + 1 if scenario == "uniform" else 1},
                                headers={
                                    "Authorization": "Bearer " + tok,
                                    "Idempotency-Key": f"{scenario}-{round_no}-{i:08d}",
                                },
                            ) as r:
                                body = await r.json()
                                status = r.status
                                code = body.get("error", {}).get("code", "OK")
                                server_seconds = (
                                    float(r.headers.get("Server-Timing", "app;dur=0").split("dur=")[1]) / 1000
                                )
                        except (aiohttp.ClientError, TimeoutError) as exc:
                            status = 0
                            code = type(exc).__name__
                        results.append(
                            (status, code, time.perf_counter() - started, started - released, server_seconds)
                        )

                    await asyncio.gather(*(enroll(i, t) for i, t in enumerate(tokens)))
                    db = await fixture(args, "check")
                    expected = (
                        1
                        if scenario == "last_seat"
                        else min(args.users, 100)
                        if scenario == "hot_club"
                        else args.users
                    )
                    item = {
                        "scenario": scenario,
                        "round": round_no + 1,
                        "statuses": dict(Counter(str(x[0]) + ":" + x[1] for x in results)),
                        "p95_s": p([x[2] for x in results], 0.95),
                        "p99_s": p([x[2] for x in results], 0.99),
                        "server_p95_s": p([x[4] for x in results], 0.95),
                        "dispatch_span_s": round(max(x[3] for x in results) - min(x[3] for x in results), 4),
                        "unexpected_error_rate": sum(x[0] == 0 or x[0] >= 500 for x in results) / args.users,
                        "db": db,
                        "expected_enrollments": expected,
                        "correctness_pass": db["enrollments"] == expected and not db["inconsistencies"],
                        "data_consistency_pass": not db["inconsistencies"]
                        and db["enrollments"] == sum(x[0] == 200 for x in results),
                    }
                    report["runs"].append(item)
                    save()
                    print(json.dumps(item), flush=True)
                    await asyncio.sleep(2)
            read = []
            for i in range(200):
                started = time.perf_counter()
                async with client.get(
                    "/api/v1/clubs/quotas", headers={"Authorization": "Bearer " + tokens[i % len(tokens)]}
                ) as r:
                    await r.read()
                    if r.status != 200:
                        raise RuntimeError("Status query unavailable")
                read.append(time.perf_counter() - started)
            report["steady_read_p95_s"] = p(read, 0.95)
            while time.monotonic() - connected_at < args.hold_seconds:
                report["ws_progress"] = {
                    "seconds": round(time.monotonic() - connected_at),
                    "open": sum(not ws.closed for ws in sockets),
                    "failures": ws_failures,
                    "notification_p95_s": p(notification, 0.95),
                    "publish_to_client_p95_s": p(transport_lag, 0.95),
                }
                save()
                print(json.dumps(report["ws_progress"]), flush=True)
                await asyncio.sleep(min(30, max(1, args.hold_seconds - (time.monotonic() - connected_at))))
            report["websocket"] = {
                "connected": len(sockets),
                "open_at_end": sum(not ws.closed for ws in sockets),
                "held_seconds": round(time.monotonic() - connected_at),
                "unexpected_closes": ws_failures,
                "api_workers_observed": len(workers),
                "quota_deliveries": received_events,
                "notification_p95_s": p(notification, 0.95),
                "publish_to_client_p95_s": p(transport_lag, 0.95),
            }
            report["generator_loop_lag_p95_s"] = p(lag, 0.95)
            save()
            print(json.dumps({"websocket": report["websocket"]}), flush=True)
        finally:
            stopped.set()
            hb.cancel()
            monitor_task.cancel()
            resource_task.cancel()
            await asyncio.gather(*(ws.close() for ws in sockets), return_exceptions=True)
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.gather(hb, monitor_task, resource_task, return_exceptions=True)
            save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--ssh", default="gg1214@192.168.100.130")
    parser.add_argument("--control", default="/private/tmp/club-test-ssh")
    parser.add_argument("--users", type=int, choices=[1500, 3000], default=1500)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--hold-seconds", type=int, default=600)
    parser.add_argument("--report", default="reports/linux-capacity.json")
    asyncio.run(main(parser.parse_args()))
