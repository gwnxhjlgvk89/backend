"""Verify and limit the actual pod's systemd cgroup, not an unused compose hint."""

import argparse
import json
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--cpus", type=int, choices=[4, 6, 8, 12, 16], default=4)
args = parser.parse_args()

names = ["club-capacity-test_" + s + "_1" for s in ("mysql", "redis", "api", "worker", "nginx")]
items = json.loads(subprocess.check_output(["podman", "inspect", *names]))
parents = {c["HostConfig"]["CgroupParent"] for c in items}
if len(parents) != 1:
    raise SystemExit("Test containers do not share a single pod cgroup")
unit = parents.pop().rsplit("/", 1)[-1]
if not unit.startswith("user-libpod_pod_") or not unit.endswith(".slice"):
    raise SystemExit("Unexpected test pod cgroup name")
subprocess.run(
    [
        "systemctl",
        "--user",
        "set-property",
        "--runtime",
        unit,
        f"CPUQuota={args.cpus * 100}%",
        "MemoryMax=3000M",
        "MemorySwapMax=0",
    ],
    check=True,
)
result = subprocess.check_output(
    [
        "systemctl",
        "--user",
        "show",
        unit,
        "-p",
        "ControlGroup",
        "-p",
        "CPUQuotaPerSecUSec",
        "-p",
        "MemoryMax",
        "-p",
        "MemorySwapMax",
    ],
    text=True,
)
print(result)
if f"CPUQuotaPerSecUSec={args.cpus}s" not in result or "MemoryMax=3145728000" not in result:
    raise SystemExit("Resource limits were not applied")
