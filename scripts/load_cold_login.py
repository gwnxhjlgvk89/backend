"""One bounded synthetic cold-login burst; no WS, enrollment, or saved tokens."""
import argparse
import asyncio
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import ssl
import time

import aiohttp

URL = 'https://wjy-1214.cloud'


def percentile(values, q):
    values = sorted(values)
    return round(values[min(int(len(values) * q), len(values) - 1)], 6) if values else None


async def worker_async(offset, epoch):
    ctx = ssl.create_default_context()
    trace = aiohttp.TraceConfig()
    for signal, key in [(trace.on_connection_create_start, 'connect_start'),
                        (trace.on_connection_create_end, 'connect_end'),
                        (trace.on_request_headers_sent, 'headers_sent'),
                        (trace.on_dns_resolvehost_start, 'dns_start'),
                        (trace.on_dns_resolvehost_end, 'dns_end')]:
        async def record(session, context, params, name=key):
            context.trace_request_ctx[name] = time.monotonic()
        signal.append(record)
    lag = []

    async def monitor():
        while True:
            started = time.monotonic()
            await asyncio.sleep(.05)
            lag.append(max(0, time.monotonic() - started - .05))

    async def login(index):
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=6, ssl=ctx, keepalive_timeout=60),
            timeout=aiohttp.ClientTimeout(total=10, ceil_threshold=30),
            trust_env=False, headers={'Accept-Encoding': 'gzip'}, trace_configs=[trace],
        ) as session:
            await asyncio.sleep(max(0, epoch + (index - offset) * .6 / 500 - time.time()))
            start = time.monotonic()
            row = {'index': index, 'start_epoch': time.time()}
            phases = {}
            try:
                async with session.post(URL + '/api/v1/auth/login', json={
                    'username': f'load{index + 1:04d}', 'password': 'SyntheticLoad2026!',
                }, trace_request_ctx=phases) as response:
                    row['status'] = response.status
                    row['headers_received_s'] = time.monotonic() - start
                    raw = await response.read()
                    row['bytes'] = len(raw)
                    body = json.loads(raw)
                    row['outcome'] = 'OK' if response.status == 200 and body.get('data', {}).get('token') else str(response.status)
                    timing = response.headers.get('Server-Timing', '')
                    if 'dur=' in timing:
                        row['server_s'] = float(timing.split('dur=')[1].split(';')[0]) / 1000
            except Exception as exc:
                row['status'] = 0
                row['outcome'] = type(exc).__name__
                row['errno'] = getattr(getattr(exc, 'os_error', exc), 'errno', None)
            row['total_s'] = time.monotonic() - start
            row['phases'] = {k: v - start for k, v in phases.items()}
            return row

    monitor_task = asyncio.create_task(monitor())
    try:
        rows = await asyncio.gather(*(login(i) for i in range(offset, offset + 500)))
    finally:
        monitor_task.cancel()
        await asyncio.gather(monitor_task, return_exceptions=True)
    return {'rows': rows, 'loop_lag_p95_s': percentile(lag, .95), 'loop_lag_max_s': max(lag, default=0)}


def worker(offset, epoch):
    return asyncio.run(worker_async(offset, epoch))


async def guard():
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10), trust_env=False) as session:
        async with session.get(URL + '/health/live') as response:
            assert response.status == 200 and (await response.json()).get('environment') == 'test'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise SystemExit('Refusing to overwrite evidence')
    asyncio.run(guard())
    with ProcessPoolExecutor(max_workers=3) as executor:
        epoch = time.time() + 8
        futures = [executor.submit(worker, offset, epoch) for offset in (0, 500, 1000)]
        parts = [f.result(timeout=60) for f in futures]
    rows = [r for p in parts for r in p['rows']]
    assert len(rows) == 1500 and len({r['index'] for r in rows}) == 1500
    summary = {'attempts': len(rows), 'outcomes': dict(Counter(r['outcome'] for r in rows)),
               'dispatch_span_s': max(r['start_epoch'] for r in rows) - min(r['start_epoch'] for r in rows),
               'total_p95_s': percentile([r['total_s'] for r in rows], .95),
               'total_p99_s': percentile([r['total_s'] for r in rows], .99),
               'successful_server_p95_s': percentile([r['server_s'] for r in rows if r['outcome'] == 'OK' and 'server_s' in r], .95),
               'failures_before_headers': sum(r['outcome'] != 'OK' and 'headers_sent' not in r['phases'] for r in rows)}
    report = {'url': URL, 'users': 1500, 'processes': 3, 'timeout_s': 10, 'burst_s': .6,
              'scope': 'login only, independent cold HTTPS sessions, test accounts, no retries or WS',
              'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'epoch': epoch, 'summary': summary, 'parts': parts,
              'full_journey_capacity_verified': False}
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
