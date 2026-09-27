"""Fault rehearsal for the named synthetic TEST stack only; never production."""

import argparse
import asyncio
import json
from pathlib import Path
import time

import aiohttp

from load_remote import fixture, ssh


async def main(args):
    results = []
    stopped = set()
    async with aiohttp.ClientSession(
        base_url=args.url, trust_env=False, timeout=aiohttp.ClientTimeout(total=15)
    ) as client:
        async with client.get("/health/live") as r:
            assert r.status == 200 and (await r.json()).get("environment") == "test"
        await fixture(args, "check")
        await fixture(args, "prepare", "uniform")

        async def control(action, component):
            assert action in ("stop", "start", "restart") and component in ("redis", "worker", "api")
            await ssh(args, f"podman {action} club-capacity-test_{component}_1")
            if action == "stop":
                stopped.add(component)
            else:
                stopped.discard(component)

        async def ready():
            for _ in range(50):
                try:
                    async with client.get("/health/ready", timeout=aiohttp.ClientTimeout(total=3)) as r:
                        if r.status == 200:
                            return
                except (aiohttp.ClientError, TimeoutError):
                    pass
                await asyncio.sleep(0.5)
            raise AssertionError("TEST stack did not recover readiness")

        async def login(i):
            async with client.post(
                "/api/v1/auth/login", json={"username": f"load{i:04d}", "password": "SyntheticLoad2026!"}
            ) as r:
                assert r.status == 200
                return {"Authorization": "Bearer " + (await r.json())["data"]["token"]}

        async def connect(headers):
            async with client.post("/api/v1/auth/ws-ticket", headers=headers) as r:
                assert r.status == 200
                ticket = (await r.json())["data"]["ticket"]
            ws = await client.ws_connect("/api/v1/ws?ticket=" + ticket)
            assert (await ws.receive_json())["event"] == "resync"
            return ws

        async def enroll(headers, key):
            async with client.post(
                "/api/v1/enrollment", json={"club_id": 1}, headers={**headers, "Idempotency-Key": key}
            ) as r:
                return r.status, await r.json()

        try:
            h1, h2 = await login(1), await login(2)
            ws = await connect(h1)
            await control("stop", "worker")
            status, body = await enroll(h1, "fault-lost-response-0001")
            assert status == 200
            # Treat the initial success response as lost; query and retry the SAME key.
            async with client.get("/api/v1/enrollment", headers=h1) as r:
                assert r.status == 200 and (await r.json())["data"]["club_id"] == 1
            repeated_status, repeated_body = await enroll(h1, "fault-lost-response-0001")
            assert repeated_status == 200 and repeated_body == body
            assert (await fixture(args, "check"))["enrollments"] == 1
            results.append({"case": "response_loss_query_idempotent_retry", "pass": True})
            await control("start", "worker")
            started = time.monotonic()
            while True:
                event = await asyncio.wait_for(ws.receive_json(), timeout=15)
                items = event.get("items", []) if event.get("event") == "quotas" else [event]
                if any(p.get("club_id") == 1 and p.get("remaining") == 99 for p in items):
                    break
                assert time.monotonic() - started < 15
            results.append({"case": "worker_restart_replays_committed_outbox", "pass": True})

            await control("stop", "redis")
            async with client.get("/api/v1/enrollment", headers=h1) as r:
                assert r.status == 200 and (await r.json())["data"]["club_id"] == 1
            status, _ = await enroll(h2, "fault-redis-down-0002")
            assert status == 503
            assert (await fixture(args, "check"))["enrollments"] == 1
            results.append({"case": "redis_outage_blocks_new_writes_preserves_result_queries", "pass": True})
            await control("start", "redis")
            await ready()
            assert (await enroll(h2, "fault-redis-recovered-0002"))[0] == 200
            results.append({"case": "redis_recovery_resumes_writes", "pass": True})

            await ws.close()
            await control("restart", "api")
            await ready()
            async with client.get("/api/v1/enrollment", headers=h1) as r:
                assert r.status == 200 and (await r.json())["data"]["club_id"] == 1
            async with await connect(h1) as fresh:
                await fresh.send_json({"event": "ping"})
                while (await asyncio.wait_for(fresh.receive_json(), timeout=10))["event"] != "pong":
                    pass
            db = await fixture(args, "check")
            assert db["enrollments"] == 2 and not db["inconsistencies"]
            results.append({"case": "api_restart_reconnect_snapshot_and_data_consistency", "pass": True})
        finally:
            for component in list(stopped):
                await control("start", component)
            Path(args.report).write_text(json.dumps({"test_only": True, "cases": results}, indent=2) + "\n")
            await ready()
        print(json.dumps(results))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--ssh", default="gg1214@192.168.100.130")
    p.add_argument("--control", default="/private/tmp/club-test-ssh")
    p.add_argument("--report", default="reports/linux-fault-recovery.json")
    asyncio.run(main(p.parse_args()))
