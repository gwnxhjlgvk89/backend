"""Explicit short host probe; no application imports, credentials or business IO."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time
from datetime import datetime, timezone


def snapshot():
    return {
        "load": list(os.getloadavg()),
        "cpu_stat": [s for s in Path("/proc/stat").read_text().splitlines() if s.startswith("cpu")],
        "memory": {
            key: int(value.split()[0])
            for key, value in (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
            if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}
        },
        "cpu_pressure": Path("/proc/pressure/cpu").read_text().strip(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("--argon-library", type=Path, default=Path("/lib/x86_64-linux-gnu/libargon2.so.1"))
    args = parser.parse_args()
    allowed = sorted(os.sched_getaffinity(0))
    before = snapshot()
    if before["load"][0] > len(allowed) * 0.5 or before["memory"]["MemAvailable"] < 512 * 1024:
        raise SystemExit("Host busy or memory low; probe refused")
    time.sleep(1)
    baseline = snapshot()

    def ticks(s):
        return {line.split()[0]: list(map(int, line.split()[1:])) for line in s["cpu_stat"]}

    first, second = ticks(before), ticks(baseline)

    def busy(cpu):
        delta = [b - a for a, b in zip(first[f"cpu{cpu}"], second[f"cpu{cpu}"])]
        return 1 - (delta[3] + delta[4]) / max(1, sum(delta[:8]))

    cpu = min(allowed, key=busy)
    if busy(cpu) > 0.25:
        raise SystemExit("No sufficiently idle CPU; probe refused")
    version = subprocess.run(
        ["dpkg-query", "-W", "-f=${Package} ${Version}\\n", "libc6"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    lib = args.argon_library.resolve()
    os.sched_setaffinity(0, {cpu})
    os.nice(19)
    result = subprocess.run(
        [str(args.binary.resolve())],
        capture_output=True,
        text=True,
        timeout=25,
        check=True,
        env={**os.environ, "LD_LIBRARY_PATH": str(lib.parent)},
    )
    after = snapshot()
    print(
        json.dumps(
            {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "scope": "Native single-thread synthetic CPU probe; no HTTP or database workload",
                "cpu_model": next(
                    s.split(":", 1)[1].strip()
                    for s in Path("/proc/cpuinfo").read_text().splitlines()
                    if s.startswith("model name")
                ),
                "kernel": platform.release(),
                "allowed_cpus_before": allowed,
                "pinned_cpu": cpu,
                "nice": os.getpriority(os.PRIO_PROCESS, 0),
                "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                "native_packages": version,
                "argon_library_sha256": hashlib.sha256(lib.read_bytes()).hexdigest(),
                "before": before,
                "baseline": baseline,
                "after": after,
                "benchmark": json.loads(result.stdout),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
