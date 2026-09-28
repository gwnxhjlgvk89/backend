"""TEST-only HTTP CONNECT diagnostic through the existing loopback Surge proxy.

Does not change Surge settings; keeps policy-selected WireGuard routing.
Reports no response body, password, token, or proxy configuration.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import resource
import ssl
import time

import aiohttp

try:
    from scripts.load_connection_phases import TARGET, PORT, summarize
except ModuleNotFoundError:
    from load_connection_phases import TARGET, PORT, summarize

PROXY = "http://127.0.0.1:6152"


async def main(a):
    if Path(a.report).exists():
        raise RuntimeError("Refusing to overwrite evidence")
    ctx = ssl.create_default_context(cafile=a.ca)
    tls = aiohttp.TCPConnector(ssl=ctx, limit=0, force_close=True)
    base = f"https://{TARGET}:{PORT}"
    async with aiohttp.ClientSession(
        connector=tls,
        trust_env=False,
        cookie_jar=aiohttp.DummyCookieJar(),
        timeout=aiohttp.ClientTimeout(total=10, ceil_threshold=30),
    ) as session:
        async with session.get(base + "/health/live", proxy=PROXY) as r:
            if r.status != 200 or (await r.json()).get("environment") != "test":
                raise RuntimeError("Refusing a non-TEST service")
        if a.epoch < time.time() + 0.2:
            raise RuntimeError("Missed coordinated start")
        samples = []
        stopped = False

        async def monitor():
            while not stopped:
                u = resource.getrusage(resource.RUSAGE_SELF)
                samples.append({"epoch": time.time(), "cpu_s": u.ru_utime + u.ru_stime})
                await asyncio.sleep(0.05)

        async def run(i):
            await asyncio.sleep(max(0, a.epoch + i * 0.6 / a.users - time.time()))
            start = time.monotonic()
            row = {"index": i + a.offset, "start_epoch": time.time(), "stage": "connect_or_response"}
            try:
                method, path, body = (
                    (
                        "POST",
                        "/api/v1/auth/login",
                        {"username": f"load{i + a.offset + 1:04d}", "password": "SyntheticLoad2026!"},
                    )
                    if a.mode == "login"
                    else ("GET", "/health/live", None)
                )
                async with session.request(method, base + path, json=body, proxy=PROXY) as r:
                    await r.read()
                    row["outcome"] = str(r.status)
                    row["stage"] = "complete"
                    if "dur=" in r.headers.get("Server-Timing", ""):
                        row["server_s"] = float(r.headers["Server-Timing"].split("dur=")[1]) / 1000
            except Exception as e:
                row["outcome"] = type(e).__name__
            row["total_s"] = time.monotonic() - start
            return row

        monitor_task = asyncio.create_task(monitor())
        rows = await asyncio.gather(*(run(i) for i in range(a.users)))
        stopped = True
        await monitor_task
    result = {
        "mode": a.mode,
        "route": "loopback HTTP CONNECT -> Surge rule-selected WireGuard",
        "rows": rows,
        "samples": samples,
        "summary": summarize(rows),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "caveat": "aiohttp proxy transport variant; stage timing not split; separate from raw TCP/TLS driver",
        "production_capacity_verified": False,
    }
    Path(a.report).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("health", "login"), required=True)
    p.add_argument("--users", type=int, required=True)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--epoch", type=float, required=True)
    p.add_argument("--ca", required=True)
    p.add_argument("--report", required=True)
    a = p.parse_args()
    if not 1 <= a.users <= 1500 or not 0 <= a.offset <= 3000 - a.users:
        p.error("Synthetic TEST accounts only")
    asyncio.run(main(a))
