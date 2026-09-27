"""Compare only OWASP-listed Argon2id profiles, inside an idle TEST container."""

from concurrent.futures import ThreadPoolExecutor
import json
import time
from argon2 import PasswordHasher, Type
from club.config import settings

if settings().club_env != "test":
    raise SystemExit("TEST only")
rows = []
for memory, passes in ((19456, 2), (12288, 3), (9216, 4), (7168, 5)):
    hasher = PasswordHasher(memory_cost=memory, time_cost=passes, parallelism=1, type=Type.ID)
    hashed = hasher.hash("SyntheticBenchmark2026!")
    for workers in (4, 8, 12):
        cpu, wall = time.process_time(), time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            assert all(pool.map(lambda _: hasher.verify(hashed, "SyntheticBenchmark2026!"), range(192)))
        wall, cpu = time.perf_counter() - wall, time.process_time() - cpu
        rows.append(
            {
                "memory_kib": memory,
                "passes": passes,
                "concurrency": workers,
                "count": 192,
                "cpu_ms_each": cpu * 1000 / 192,
                "per_second": 192 / wall,
                "wall_s": wall,
            }
        )
print(
    json.dumps(
        {"scope": "Idle synthetic hash benchmark only; OWASP-listed profiles; no HTTP traffic", "rows": rows},
        indent=2,
    )
)
