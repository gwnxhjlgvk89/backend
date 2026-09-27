"""One isolated experiment with resource/traffic evidence and guaranteed tc cleanup."""

import argparse
import asyncio
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from load_remote import ssh


async def main(args):
    prefix = Path(args.report).with_suffix("")
    if Path(args.report).exists():
        raise SystemExit("Report already exists")

    async def remote(command):
        return await ssh(args, "cd ~/club-system-test/backend && " + command)

    async def proof(suffix, action):
        raw = await remote("python3 deploy/shape-test-egress.py " + action)
        Path(str(prefix) + suffix + ".json").write_text(raw)
        return json.loads(raw)

    shaped = False
    child = None
    try:
        limits = await remote(f"python3 deploy/limit-test-pod.py --cpus {args.cpus}")
        Path(str(prefix) + "-limits.txt").write_text(limits.rstrip() + "\n")
        await proof(
            "-egress-before",
            f"limit --mbps {args.mbps} --port {8443 if urlsplit(args.url).scheme == 'https' else 8080}",
        )
        shaped = True
        command = [
            sys.executable,
            str(
                Path(__file__).with_name(
                    "load_distributed_journey.py" if args.processes > 1 else "load_journey.py"
                )
            ),
            "--url",
            args.url,
            "--ssh",
            args.ssh,
            "--control",
            args.control,
            "--users",
            str(args.users),
            "--mode",
            args.mode,
            "--scenario",
            args.scenario,
            "--rounds",
            str(args.rounds),
            "--hold-seconds",
            str(args.hold_seconds),
            "--cache",
            args.cache,
            "--report",
            args.report,
        ]
        if args.processes > 1:
            command += ["--processes", str(args.processes)]
        if args.ca_cert:
            command += ["--ca-cert", args.ca_cert]
        child = await asyncio.create_subprocess_exec(*command)
        code = await child.wait()
        if code:
            raise RuntimeError(f"Journey process failed: {code}")
    finally:
        if child and child.returncode is None:
            child.terminate()
            await child.wait()
        if shaped:
            try:
                await proof("-egress-after", "show")
            finally:
                await proof("-egress-restored", "clear")
        await remote("python3 deploy/limit-test-pod.py --cpus 4")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--ca-cert")
    p.add_argument("--report", required=True)
    p.add_argument("--ssh", default="gg1214@192.168.100.130")
    p.add_argument("--control", default="/private/tmp/club-test-ssh")
    p.add_argument("--cpus", type=int, choices=[4, 6, 8, 12, 16], default=4)
    p.add_argument("--mbps", type=int, choices=[10, 20, 50], default=10)
    p.add_argument("--processes", type=int, choices=[1, 2, 3, 4], default=1)
    p.add_argument("--users", type=int, choices=[30, 1500, 3000], default=1500)
    p.add_argument("--mode", choices=["login", "login_warm", "ready", "mixed", "reconnect"], default="login")
    p.add_argument("--scenario", choices=["uniform", "hot_club", "last_seat"], default="uniform")
    p.add_argument("--cache", choices=["cold", "warm"], default="cold")
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--hold-seconds", type=int, default=30)
    asyncio.run(main(p.parse_args()))
