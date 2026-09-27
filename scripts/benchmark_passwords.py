"""TEST-only hash service-demand calibration; no production users or writes."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import time
import bcrypt
from argon2 import PasswordHasher, Type
from club.config import settings


def main():
    if settings().club_env != "test":
        raise SystemExit("Only TEST environments may run this benchmark")
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=128)
    args = parser.parse_args()
    value = "SyntheticBenchmark2026!"
    argon = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
    encoded = {
        "bcrypt10": bcrypt.hashpw(value.encode(), bcrypt.gensalt(rounds=10)),
        "argon2id_19MiB_t2_p1": argon.hash(value),
    }
    rows = []
    for name, hashed in encoded.items():

        def verify(_):
            start = time.perf_counter()
            ok = bcrypt.checkpw(value.encode(), hashed) if name == "bcrypt10" else argon.verify(hashed, value)
            assert ok
            return time.perf_counter() - start

        for concurrency in (1, 4, 8, 16):
            wall, cpu = time.perf_counter(), time.process_time()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                durations = list(pool.map(verify, range(args.count)))
            seconds, cpu_seconds = time.perf_counter() - wall, time.process_time() - cpu
            rows.append(
                {
                    "algorithm": name,
                    "concurrency": concurrency,
                    "count": args.count,
                    "wall_s": seconds,
                    "cpu_seconds": cpu_seconds,
                    "verifications_per_second": args.count / seconds,
                    "cpu_ms_per_verification": cpu_seconds * 1000 / args.count,
                    "mean_native_elapsed_ms": sum(durations) * 1000 / args.count,
                }
            )
    print(
        json.dumps(
            {"scope": "Synthetic password verification only; not an HTTP capacity verdict", "rows": rows},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
