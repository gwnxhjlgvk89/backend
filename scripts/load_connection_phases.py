"""TEST-only cold TCP/TLS/HTTP probes; no response bodies or credentials recorded.

Each synthetic user gets a new verified TLS connection. TCP and TLS are timed
separately, including incomplete stages. Samples remain in memory during load.
The same stdlib driver runs on Mac and Linux; Linux-on-target is diagnostic only.
"""

import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import resource
import socket
import ssl
import time

TARGET = "192.168.100.130"
PORT = 18082
DIAL = (TARGET, PORT)


def percentile(values, q):
    values = sorted(values)
    return round(values[min(int(len(values) * q), len(values) - 1)], 6) if values else None


def summarize(rows):
    result = {"count": len(rows), "outcomes": dict(Counter(r["outcome"] for r in rows))}
    for k in ("total_s", "tcp_s", "tls_s", "headers_wait_s", "server_s"):
        values = [r[k] for r in rows if k in r]
        result[k] = {
            "count": len(values),
            "p50": percentile(values, 0.5),
            "p95": percentile(values, 0.95),
            "p99": percentile(values, 0.99),
        }
    result["failures_by_stage"] = dict(
        Counter(r["stage"] for r in rows if r["outcome"] not in ("200", "TLS_OK"))
    )
    result["start_span_s"] = max(r["start_epoch"] for r in rows) - min(r["start_epoch"] for r in rows)
    return result


async def probe(ctx, mode, index, timeout, epoch, guard=False):
    await asyncio.sleep(max(0, epoch - time.time()))
    start = time.monotonic()
    row = {"index": index, "start_epoch": time.time(), "stage": "tcp"}
    sock, writer = None, None
    payload = None
    try:
        async with asyncio.timeout(timeout):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setblocking(False)
            await asyncio.get_running_loop().sock_connect(sock, DIAL)
            row["tcp_s"] = time.monotonic() - start
            row["stage"] = "tls"
            begin = time.monotonic()
            reader, writer = await asyncio.open_connection(
                sock=sock, ssl=ctx, server_hostname=TARGET, ssl_handshake_timeout=timeout
            )
            sock = None  # Transport owns it now.
            row["tls_s"] = time.monotonic() - begin
            row["tls_version"] = writer.get_extra_info("ssl_object").version()
            if mode == "tls":
                row["outcome"] = "TLS_OK"
            else:
                body = (
                    json.dumps(
                        {"username": f"load{index + 1:04d}", "password": "SyntheticLoad2026!"}
                    ).encode()
                    if mode == "login"
                    else b""
                )
                method, path = ("POST", "/api/v1/auth/login") if mode == "login" else ("GET", "/health/live")
                headers = f"{method} {path} HTTP/1.1\r\nHost: {TARGET}:{PORT}\r\nConnection: close\r\nAccept-Encoding: identity\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode()
                row["stage"] = "send"
                writer.write(headers + body)
                await writer.drain()
                row["sent_s"] = time.monotonic() - start
                row["stage"] = "response_headers"
                begin = time.monotonic()
                raw = await reader.readuntil(b"\r\n\r\n")
                row["headers_wait_s"] = time.monotonic() - begin
                lines = raw.decode("latin1").split("\r\n")
                row["outcome"] = lines[0].split()[1]
                fields = {
                    k.lower(): v.strip() for k, v in (line.split(":", 1) for line in lines[1:] if ":" in line)
                }
                timing = fields.get("server-timing", "")
                if "dur=" in timing:
                    row["server_s"] = float(timing.split("dur=")[1]) / 1000
                row["stage"] = "response_body"
                if "content-length" in fields:
                    payload = await reader.readexactly(int(fields["content-length"]))
                elif fields.get("transfer-encoding") == "chunked":
                    chunks = []
                    while True:
                        size = int((await reader.readline()).split(b";", 1)[0], 16)
                        if not size:
                            await reader.readline()
                            break
                        chunks.append(await reader.readexactly(size))
                        await reader.readexactly(2)
                    payload = b"".join(chunks)
                else:
                    payload = await reader.read()
                row["response_bytes"] = len(payload)
            row["stage"] = "complete"
    except Exception as exc:
        row["outcome"] = type(exc).__name__
        row["incomplete_stage_elapsed_s"] = (
            time.monotonic() - start - row.get("tcp_s", 0) - row.get("tls_s", 0)
        )
    finally:
        row["total_s"] = time.monotonic() - start
        if writer:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except Exception:
                writer.transport.abort()
        if sock:
            sock.close()
    if guard:
        if row.get("outcome") != "200" or json.loads(payload or b"{} ").get("environment") != "test":
            raise RuntimeError("Refusing an endpoint without a verified TEST health response")
    return row


async def main(args):
    if Path(args.report).exists():
        raise RuntimeError("Refusing to overwrite diagnostic evidence")
    ctx = ssl.create_default_context(cafile=args.ca)
    await probe(ctx, "health", 0, 10, time.time(), guard=True)
    if args.epoch < time.time() + 0.2:
        raise RuntimeError("Missed coordinated start; do not silently reduce offered load")
    samples = []
    stopped = False

    async def monitor():
        while not stopped:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            samples.append({"epoch": time.time(), "cpu_s": usage.ru_utime + usage.ru_stime})
            await asyncio.sleep(0.05)

    task = asyncio.create_task(monitor())
    rows = await asyncio.gather(
        *(
            probe(ctx, args.mode, args.offset + i, args.timeout, args.epoch + i * args.burst / args.users)
            for i in range(args.users)
        )
    )
    stopped = True
    await task
    Path(args.report).write_text(
        json.dumps(
            {
                "target": TARGET,
                "port": PORT,
                "dial": DIAL,
                "mode": args.mode,
                "users": args.users,
                "timeout_s": args.timeout,
                "epoch": args.epoch,
                "burst_s": args.burst,
                "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "samples": samples,
                "summary": summarize(rows),
                "rows": rows,
                "production_capacity_verified": False,
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(summarize(rows)), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("tls", "health", "login"), required=True)
    p.add_argument("--users", type=int, required=True)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--timeout", type=float, default=10)
    p.add_argument("--burst", type=float, default=0.6)
    p.add_argument("--epoch", type=float, required=True)
    p.add_argument("--ca", required=True)
    p.add_argument("--report", required=True)
    p.add_argument(
        "--ssh-tunnel",
        action="store_true",
        help="Use the temporary fixed loopback forward; TLS identity still verifies TEST target",
    )
    a = p.parse_args()
    if not 1 <= a.users <= 1500 or not 0 <= a.offset <= 3000 - a.users or not 0 < a.timeout <= 30:
        p.error("Bounded synthetic TEST requests only")
    if a.ssh_tunnel:
        DIAL = ("127.0.0.1", 18083)
    asyncio.run(main(a))
