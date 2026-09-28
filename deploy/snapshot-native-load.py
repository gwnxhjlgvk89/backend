import json
import subprocess
import time
import urllib.request
from pathlib import Path

NAMES = ["club-api", "club-worker", "mysql", "redis-server", "nginx"]


def sample():
    result = {"at": time.time(), "services": {}, "health": {}}
    for name in NAMES:
        text = subprocess.check_output(
            [
                "systemctl",
                "show",
                name,
                "-p",
                "ActiveState",
                "-p",
                "MainPID",
                "-p",
                "NRestarts",
                "-p",
                "ControlGroup",
            ],
            text=True,
        )
        d = dict(line.split("=", 1) for line in text.splitlines())
        path = Path("/sys/fs/cgroup" + d["ControlGroup"])
        d["resources"] = {
            key: (path / key).read_text().strip()
            for key in ["memory.current", "memory.events", "cpu.stat"]
            if (path / key).exists()
        }
        procs = []
        for raw in (path / "cgroup.procs").read_text().splitlines():
            try:
                p = Path("/proc") / raw
                fields = (p / "stat").read_text().rsplit(") ", 1)[1].split()
                procs.append(
                    {
                        "pid": int(raw),
                        "start_ticks": int(fields[19]),
                        "comm": (p / "comm").read_text().strip(),
                    }
                )
            except (FileNotFoundError, ProcessLookupError):
                pass
        d["processes"] = procs
        result["services"][name] = d
    for kind, url in [
        ("local", "http://127.0.0.1:8001/health/ready"),
        ("public", "https://wjy-1214.cloud/health/ready"),
    ]:
        start = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                result["health"][kind] = {"status": r.status, "seconds": time.monotonic() - start}
        except Exception as exc:
            result["health"][kind] = {"error": type(exc).__name__, "seconds": time.monotonic() - start}
    try:
        with urllib.request.urlopen("http://127.0.0.1:8001/metrics", timeout=5) as r:
            rows = r.read().decode().splitlines()
        result["dependencies"] = {
            k: float(v)
            for line in rows
            for k, v in [line.split(" ", 1)]
            if k in {"club_outbox_pending", "club_database_available", "club_redis_available"}
        }
    except Exception as exc:
        result["metrics_error"] = type(exc).__name__
    result["net_dev"] = Path("/proc/net/dev").read_text()
    result["netstat"] = Path("/proc/net/netstat").read_text()
    result["snmp"] = Path("/proc/net/snmp").read_text()
    result["sockstat"] = Path("/proc/net/sockstat").read_text()
    result["host_cpu_ticks"] = Path("/proc/stat").read_text().splitlines()[0]
    result["pressure"] = {k: Path("/proc/pressure/" + k).read_text() for k in ("cpu", "memory", "io")}
    result["host_memory"] = dict(
        line.split(":", 1)
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith(("MemTotal:", "MemAvailable:", "SwapTotal:", "SwapFree:"))
    )
    result["host_oom_kills"] = next(
        int(x.split()[1]) for x in Path("/proc/vmstat").read_text().splitlines() if x.startswith("oom_kill ")
    )
    return result


if __name__ == "__main__":
    print(json.dumps(sample()))
