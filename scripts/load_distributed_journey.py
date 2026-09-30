"""Coordinate independent process shards; retain exact per-request observations.

Only the coordinator resets synthetic data and publishes the opening time.
Children retain all TEST checks and each owns disjoint accounts/connections.
"""

import argparse
import asyncio
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import time

try:
    from scripts.load_remote import fixture, p, ssh
    from scripts.load_journey import journey_gates, summary
except ModuleNotFoundError:
    from load_remote import fixture, p, ssh
    from load_journey import journey_gates, summary


async def counters(args):
    code = "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').read().decode())"
    raw = await ssh(args, "podman exec club-capacity-test_api_1 python -c " + shlex.quote(code))
    return {
        line.split()[0]: float(line.split()[1])
        for line in raw.splitlines()
        if line.startswith(
            (
                "club_password_",
                "club_http_seconds_",
                "club_db_query_seconds_",
                "club_read_pool_wait_seconds_",
                "club_pool_wait_seconds_",
            )
        )
        and ("_sum" in line.split()[0] or "_count" in line.split()[0])
    }


def combine(parts, db, mode, scenario, users):
    rows = defaultdict(list)
    outcomes = Counter()
    ws = Counter()
    delays = []
    for part in parts:
        run = part["runs"][0]
        for key, values in run["raw_stages"].items():
            rows[key].extend(values)
        outcomes.update(run["outcomes"])
        for key in ("open_at_end", "unexpected_close", "timed_deliveries", "missing_final_quota_snapshots"):
            ws[key] += run["websocket"].get(key, 0)
        delays.extend(run["raw_notification_delays"])
    confirmed = sum(part["runs"][0]["confirmed_enrollments"] for part in parts)
    expected = users if scenario == "uniform" else 1 if scenario == "last_seat" else min(100, users)
    item = {
        "round": 1,
        "stages": {k: summary(v) for k, v in rows.items()},
        "steady_reads_after_20s": summary(
            [
                r
                for k, values in rows.items()
                if k in {"active_detail", "periodic_quotas"}
                for r in values
                if r[3] >= 20
            ]
        ),
        "completed_students": sum(part["runs"][0]["completed_students"] for part in parts),
        "confirmed_enrollments": confirmed,
        "db": db,
        "expected_enrollments": expected,
        "data_consistency_pass": not db["inconsistencies"] and db["enrollments"] == confirmed,
        "all_expected_enrolled": db["enrollments"] == expected,
        "outcomes": dict(outcomes),
        "active_duration_s": min(part["runs"][0]["active_duration_s"] for part in parts),
        "websocket": {**ws, "notification_p95_s": p(delays, 0.95)},
    }
    item["unfinished_students"] = users - item["completed_students"]
    item["scope_gates"] = journey_gates(item, mode, users)
    return item


async def main(args):
    path = Path(args.report)
    if path.exists():
        raise SystemExit("Refusing existing report")
    parts_folder = path.with_suffix(".parts")
    parts_folder.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "student-journey-distributed-v1",
        "completed": False,
        "parameters": vars(args),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "child_driver_sha256": hashlib.sha256(
            Path(__file__).with_name("load_journey.py").read_bytes()
        ).hexdigest(),
        "runs": [],
        "resources": [],
        "errors": [],
        "parts": [],
        "production_capacity_verified": False,
        "network_scope": "LAN, TLS per student, external shaping; no WAN RTT/loss",
        "cpu_scope": "Pod quota excludes some rootless networking helpers; not physical-core equivalence",
        "generator_scope": f"{args.processes} independent Python processes, disjoint student accounts",
    }
    children = []
    control = None
    handles = []

    try:
        from scripts.load_native import enabled, scope
    except ModuleNotFoundError:
        from load_native import enabled, scope
    if enabled():
        report.update(scope(args))

    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    try:
        for round_no in range(args.rounds):
            await fixture(args, "check")
            await fixture(args, "prepare", args.scenario)
            Path(".local").mkdir(exist_ok=True)
            control = Path(tempfile.mkdtemp(prefix="journey-control-", dir=".local")).resolve()
            children, offsets, files = [], [], []
            offset = 0
            for shard in range(args.processes):
                count = args.users // args.processes + (shard < args.users % args.processes)
                offsets.append(offset)
                output = parts_folder / f"round-{round_no + 1}-part-{shard + 1}.json"
                files.append(output)
                log = open(output.with_suffix(".log"), "w")
                handles.append(log)
                command = [
                    sys.executable,
                    str(Path(__file__).with_name("load_journey.py")),
                    "--url",
                    args.url,
                    "--ssh",
                    args.ssh,
                    "--control",
                    args.control,
                    "--users",
                    str(count),
                    "--user-offset",
                    str(offset),
                    "--control-dir",
                    str(control),
                    "--client-profile",
                    args.client_profile,
                    "--mode",
                    args.mode,
                    "--scenario",
                    args.scenario,
                    "--cache",
                    args.cache,
                    "--rounds",
                    "1",
                    "--hold-seconds",
                    str(args.hold_seconds),
                    "--report",
                    str(output),
                ]
                if args.ca_cert:
                    command += ["--ca-cert", args.ca_cert]
                if args.first_password_change:
                    command += ["--first-password-change"]
                children.append(await asyncio.create_subprocess_exec(*command, stdout=log, stderr=log))
                offset += count
            async with asyncio.timeout(180):
                while not all((control / f"{o}.ready").exists() for o in offsets):
                    if any(child.returncode is not None for child in children):
                        raise RuntimeError("Shard stopped before ready; inspect retained TEST-only part log")
                    await asyncio.sleep(0.2)
            initial = [json.loads(file.read_text()) for file in files]
            if len({d["application_sha256"] for d in initial}) != 1:
                raise RuntimeError("Application changed during preparation")
            for key in (
                "application_sha256",
                "api_image_id",
                "api_command",
                "runtime_settings",
                "test_ca_sha256",
                "deployment_config_sha256",
                "opening_guard_s",
            ):
                report[key] = initial[0][key]
            before_counters = await counters(args)
            epoch = time.time() + 5
            opening = epoch + 5 + initial[0]["clock_offset_s"]
            code = """import asyncio
from datetime import datetime,timezone,timedelta
from redis.asyncio import Redis
from club.config import settings
from club.db import make_engine,sessions
from club.models import Activity
async def f():
 e=make_engine()
 async with sessions(e)() as d,d.begin():
  a=await d.get(Activity,1,with_for_update=True)
  a.state='published'
  a.starts_at=datetime.fromtimestamp(OPENING,timezone.utc).replace(tzinfo=None)
  a.ends_at=a.starts_at+timedelta(hours=1)
 await e.dispose()
 if COLD:
  r=Redis.from_url(settings().redis_url)
  keys=[k async for k in r.scan_iter(settings().redis_prefix+':catalog*')]
  if keys: await r.delete(*keys)
  await r.aclose()
asyncio.run(f())""".replace("OPENING", repr(opening)).replace("COLD", repr(args.cache == "cold"))
            await ssh(args, "podman exec club-capacity-test_api_1 python -c " + shlex.quote(code))
            if time.time() >= epoch - 1:
                raise RuntimeError("Coordinator missed barrier deadline")
            temporary = control / "start.tmp"
            temporary.write_text(json.dumps({"epoch": epoch}))
            temporary.replace(control / "start.json")
            print(
                f"round {round_no + 1}: {args.users} students, {args.processes} processes, {args.mode}/{args.scenario}",
                flush=True,
            )
            save()
            codes = await asyncio.gather(*(child.wait() for child in children))
            if any(codes):
                raise RuntimeError("Shard failed; partial results retained")
            parts = [json.loads(file.read_text()) for file in files]
            if not all(d.get("completed") and len(d["runs"]) == 1 and not d["errors"] for d in parts):
                raise RuntimeError("Incomplete shard evidence")
            item = combine(parts, await fixture(args, "check"), args.mode, args.scenario, args.users)
            after_counters = await counters(args)
            item["server_counter_deltas"] = {
                key: value - before_counters.get(key, 0) for key, value in after_counters.items()
            }
            item["round"] = round_no + 1
            item["measured_epoch"] = epoch
            report["runs"].append(item)
            report["resources"].extend(parts[0]["resources"])
            report["parts"].extend(
                {
                    "file": str(file.relative_to(path.parent)),
                    "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                }
                for file in files
            )
            print(
                json.dumps(
                    {
                        "round": round_no + 1,
                        "login_p95_s": item["stages"].get("login", {}).get("p95_s"),
                        "enrollment_p95_s": item["stages"]["enroll"]["p95_s"],
                        "gates": item["scope_gates"],
                    }
                ),
                flush=True,
            )
            save()
            shutil.rmtree(control)
            control = None
            await asyncio.sleep(2)
        report["completed"] = True
    except Exception as exc:
        report["errors"].append(type(exc).__name__)
        raise
    finally:
        for child in children:
            if child.returncode is None:
                child.terminate()
        await asyncio.gather(*(child.wait() for child in children))
        for handle in handles:
            handle.close()
        if control:
            shutil.rmtree(control)
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--ca-cert")
    parser.add_argument("--ssh", default="gg1214@192.168.100.130")
    parser.add_argument("--control", default="/private/tmp/club-test-ssh")
    parser.add_argument("--users", type=int, choices=[30, 1500, 3000], default=1500)
    parser.add_argument("--processes", type=int, choices=[2, 3, 4], default=3)
    parser.add_argument(
        "--mode", choices=["login", "login_warm", "ready", "mixed", "reconnect"], default="login"
    )
    parser.add_argument(
        "--client-profile", choices=["legacy", "lean", "connected_first"], default="connected_first"
    )
    parser.add_argument("--scenario", choices=["uniform", "hot_club", "last_seat"], default="uniform")
    parser.add_argument("--cache", choices=["cold", "warm"], default="cold")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--hold-seconds", type=int, default=30)
    parser.add_argument("--report", required=True)
    parser.add_argument("--first-password-change", action="store_true")
    args = parser.parse_args()
    if args.rounds < 1 or args.hold_seconds < 10:
        parser.error("rounds>=1 and hold-seconds>=10 required")
    if args.first_password_change and (args.mode != "login" or args.rounds != 1 or args.users > 1500):
        parser.error("first-password-change requires one login round and at most 1500 students")
    asyncio.run(main(args))
