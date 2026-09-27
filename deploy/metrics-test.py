"""Non-sensitive metrics for this project's containers only."""

import json
import os
from pathlib import Path
import subprocess

stats = json.loads(subprocess.check_output(["podman", "stats", "--no-stream", "--format", "json"]))
result = {
    "containers": [s for s in stats if s.get("name", "").startswith("club-capacity-test")],
    "cgroups": {},
    "host_load_average": os.getloadavg(),
    "host_cpu_ticks": Path("/proc/stat").read_text().splitlines()[0],
    "host_pressure": {
        name: Path("/proc/pressure/" + name).read_text().strip() for name in ("cpu", "memory", "io")
    },
}
for short in ("mysql", "redis", "api", "worker", "nginx"):
    name = "club-capacity-test_" + short + "_1"
    d = json.loads(subprocess.check_output(["podman", "inspect", name]))[0]
    pid = d["State"]["Pid"]
    if not pid:
        continue
    group = Path("/proc/" + str(pid) + "/cgroup").read_text().strip().split(":")[-1]
    folder = Path("/sys/fs/cgroup" + group)
    result["cgroups"][short] = {
        key: (folder / key).read_text().strip()
        for key in ("memory.current", "memory.peak", "memory.events", "cpu.stat")
        if (folder / key).exists()
    }
result["budget"] = subprocess.check_output(
    [
        "systemctl",
        "--user",
        "show",
        d["HostConfig"]["CgroupParent"].rsplit("/", 1)[-1],
        "-p",
        "CPUQuotaPerSecUSec",
        "-p",
        "MemoryMax",
        "-p",
        "MemorySwapMax",
    ],
    text=True,
)
parent = subprocess.check_output(
    [
        "systemctl",
        "--user",
        "show",
        d["HostConfig"]["CgroupParent"].rsplit("/", 1)[-1],
        "-p",
        "ControlGroup",
        "--value",
    ],
    text=True,
).strip()
folder = Path("/sys/fs/cgroup" + parent)
result["cgroups"]["budget_total"] = {
    key: (folder / key).read_text().strip()
    for key in ("memory.current", "memory.peak", "memory.events", "cpu.stat", "cpu.max", "memory.max")
    if (folder / key).exists()
}
# Rootless networking can live outside the pod quota. Observe same-user helpers
# without exposing command lines; shared helpers are not attributed to this app.
result["network_helpers_observed"] = []
for process in Path("/proc").iterdir():
    if not process.name.isdigit():
        continue
    try:
        if process.stat().st_uid != os.getuid():
            continue
        name = (process / "comm").read_text().strip()
        if name not in {"rootlessport", "slirp4netns", "pasta"}:
            continue
        fields = (process / "stat").read_text().rsplit(") ", 1)[1].split()
        group = (process / "cgroup").read_text().strip().split(":")[-1]
        result["network_helpers_observed"].append(
            {
                "pid": int(process.name),
                "name": name,
                "cpu_seconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
                "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
                "inside_test_budget": group == parent or group.startswith(parent + "/"),
                "attribution": "same-user helper; may serve other rootless containers",
            }
        )
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        continue
print(json.dumps(result))
