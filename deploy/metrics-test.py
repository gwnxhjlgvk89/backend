"""Non-sensitive metrics for this project's containers only."""

import json
from pathlib import Path
import subprocess

stats = json.loads(subprocess.check_output(["podman", "stats", "--no-stream", "--format", "json"]))
result = {
    "containers": [s for s in stats if s.get("name", "").startswith("club-capacity-test")],
    "cgroups": {},
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
print(json.dumps(result))
