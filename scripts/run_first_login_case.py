"""Explicit first-password-change rehearsal; only the fixed synthetic TEST fixture.

No work occurs on import. Restores the synthetic password and flags after closing
the child driver, including failed runs. Never records passwords, hashes or tokens.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import shlex
import signal
import ssl
import sys

import aiohttp

try:
    from scripts.load_remote import fixture, ssh
except ModuleNotFoundError:
    from load_remote import fixture, ssh


async def main(args):
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    proof = report.with_name(report.stem + "-first-login-fixture.json")
    if report.exists() or proof.exists():
        raise SystemExit("Refusing existing first-login evidence")
    status = {"test_only": True, "users": 1500, "prepared": False, "restored": False}
    child = None
    prepared = False

    async def set_required(required):
        # The calibration accounts used by three 500-student shards are >1500.
        code = """import asyncio
from sqlalchemy import select, update
from sqlalchemy.engine import make_url
from club.config import settings
from club.db import make_engine, sessions
from club.models import User
async def f():
 s=settings()
 assert s.club_env=='test' and make_url(s.database_url).database=='club_test' and s.redis_prefix=='club:test'
 e=make_engine()
 try:
  async with sessions(e)() as db, db.begin():
   rows=(await db.execute(select(User.id,User.username).order_by(User.id))).all()
   assert rows==[(i,f'load{i:04d}') for i in range(1,3001)], 'Only the exact synthetic fixture is allowed'
   await db.execute(update(User).where(User.id<=1500).values(must_change_password=REQUIRED))
 finally: await e.dispose()
asyncio.run(f())""".replace("REQUIRED", repr(required))
        await ssh(args, "podman exec club-capacity-test_api_1 python -c " + shlex.quote(code))

    try:
        await fixture(args, "check")
        # Verify exact names/IDs before any password reset.
        await set_required(False)
        prepared = True
        await fixture(args, "passwords")
        await set_required(True)
        status["prepared"] = True
        proof.write_text(json.dumps(status, indent=2) + "\n")
        command = [
            sys.executable,
            str(Path(__file__).with_name("run_journey_case.py")),
            "--url",
            args.url,
            "--ca-cert",
            args.ca_cert,
            "--ssh",
            args.ssh,
            "--control",
            args.control,
            "--cpus",
            "16",
            "--mbps",
            "50",
            "--users",
            "1500",
            "--processes",
            "3",
            "--mode",
            "login",
            "--rounds",
            "1",
            "--hold-seconds",
            "45",
            "--first-password-change",
            "--report",
            args.report,
        ]
        child = await asyncio.create_subprocess_exec(*command, start_new_session=True)
        if await child.wait():
            raise RuntimeError("First-login driver failed; evidence retained")
    finally:
        if child and child.returncode is None:
            os.killpg(child.pid, signal.SIGTERM)
            await child.wait()
        if prepared:
            await fixture(args, "passwords")
            await set_required(False)
            tls = ssl.create_default_context(cafile=args.ca_cert)
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=tls),
                trust_env=False,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as client:
                async with client.post(
                    args.url + "/api/v1/auth/login",
                    json={
                        "username": "load0001",
                        "password": "SyntheticLoad2026!",
                    },
                ) as response:
                    assert response.status == 200
                    assert not (await response.json())["data"]["user"]["must_change_password"]
            status["restored"] = True
        proof.write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--ca-cert", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--ssh", default="gg1214@192.168.100.130")
    parser.add_argument("--control", default="/private/tmp/club-test-ssh")
    asyncio.run(main(parser.parse_args()))
