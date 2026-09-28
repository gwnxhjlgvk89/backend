"""Read only: named TEST container/process continuity and local health, no credentials."""

import json
from pathlib import Path
import subprocess
import time
import urllib.request

names = ["club-capacity-test_" + s + "_1" for s in ("mysql", "redis", "api", "worker", "nginx")]
items = json.loads(subprocess.check_output(["podman", "inspect", *names]))
result = {
    "at": time.time(),
    "containers": {},
    "health": {},
    "health_origin": "http://192.168.100.130:18081",
}
for item in items:
    name = item["Name"].lstrip("/")
    if name not in names:
        raise SystemExit("Unexpected container")
    processes = []
    if item["State"]["Running"]:
        rows = subprocess.check_output(["podman", "top", name, "hpid", "comm"], text=True)
        for row in rows.splitlines()[1:]:
            pid, comm = row.split(maxsplit=1)
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
                processes.append({"pid": int(pid), "start_ticks": int(fields[19]), "comm": comm})
            except FileNotFoundError:
                processes.append({"pid": int(pid), "gone_during_snapshot": True})
    result["containers"][name] = {
        "running": item["State"]["Running"],
        "started_at": item["State"]["StartedAt"],
        "restart_count": item.get("RestartCount"),
        "oom_killed": item["State"].get("OOMKilled"),
        "processes": processes,
    }
parents = {item["HostConfig"]["CgroupParent"] for item in items}
if len(parents) != 1:
    raise SystemExit("Expected one TEST pod")
unit = parents.pop().rsplit("/", 1)[-1]
group = subprocess.check_output(
    ["systemctl", "--user", "show", unit, "-p", "ControlGroup", "--value"], text=True
).strip()
folder = Path("/sys/fs/cgroup" + group)
result["budget"] = {
    key: (folder / key).read_text().strip()
    for key in (
        "cpu.stat",
        "cpu.max",
        "memory.current",
        "memory.events",
        "memory.max",
        "cpu.pressure",
        "io.pressure",
    )
}
for endpoint in ("live", "ready"):
    start = time.monotonic()
    try:
        with urllib.request.urlopen(f"http://192.168.100.130:18081/health/{endpoint}", timeout=5) as response:
            result["health"][endpoint] = {"status": response.status}
    except Exception as exc:
        result["health"][endpoint] = {"error": type(exc).__name__}
    result["health"][endpoint]["seconds"] = time.monotonic() - start
print(json.dumps(result))
