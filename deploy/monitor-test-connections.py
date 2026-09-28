import json
import os
import time
import subprocess
from pathlib import Path
import argparse

p = argparse.ArgumentParser()
p.add_argument("--seconds", type=int, default=23)
a = p.parse_args()
ins = json.loads(
    subprocess.check_output(
        [
            "podman",
            "inspect",
            "club-capacity-test_nginx_1",
            "club-capacity-test_api_1",
            "club-capacity-test_mysql_1",
            "club-capacity-test_worker_1",
            "club-capacity-test_redis_1",
        ]
    )
)
nginx = ins[0]["State"]["Pid"]
groups = {}
pids = {}
for d in ins:
    pid = d["State"]["Pid"]
    group = Path("/proc/" + str(pid) + "/cgroup").read_text().strip().split(":")[-1]
    groups[d["Name"]] = Path("/sys/fs/cgroup" + group)
    pids[pid] = d["Name"]
    for child in Path(f"/proc/{pid}/task/{pid}/children").read_text().split():
        pids[int(child)] = d["Name"] + "-child"
parent = Path(
    "/sys/fs/cgroup"
    + subprocess.check_output(
        [
            "systemctl",
            "--user",
            "show",
            ins[0]["HostConfig"]["CgroupParent"].rsplit("/", 1)[-1],
            "-p",
            "ControlGroup",
            "--value",
        ],
        text=True,
    ).strip()
)
groups["budget_total"] = parent
for f in Path("/proc").iterdir():
    try:
        if (
            f.name.isdigit()
            and f.stat().st_uid == os.getuid()
            and (f / "comm").read_text().strip() in ("rootlessport", "slirp4netns", "pasta")
        ):
            pids[int(f.name)] = (f / "comm").read_text().strip()
    except (OSError, ValueError):
        pass
rows = []
end = time.monotonic() + a.seconds
while time.monotonic() < end:
    row = {"epoch": time.time(), "cgroups": {}, "processes": {}}
    for name, folder in groups.items():
        row["cgroups"][name] = {
            k: (folder / k).read_text().strip()
            for k in ("cpu.stat", "memory.current", "memory.events", "cpu.max", "memory.max")
            if (folder / k).exists()
        }
    for pid, name in pids.items():
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
            row["processes"][str(pid)] = {
                "name": name,
                "cpu_s": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
            }
        except OSError:
            pass
    try:
        lines = Path(f"/proc/{nginx}/net/netstat").read_text().splitlines()
        vals = {}
        for h, v in zip(lines[::2], lines[1::2]):
            vals.update(dict(zip(h.split()[1:], map(int, v.split()[1:]))))
        row["tcp"] = {
            k: vals[k]
            for k in (
                "ListenOverflows",
                "ListenDrops",
                "TCPTimeouts",
                "TCPSynRetrans",
                "TCPBacklogDrop",
                "TCPReqQFullDrop",
            )
        }
        row["dev"] = Path(f"/proc/{nginx}/net/dev").read_text()
    except OSError as e:
        row["net_error"] = type(e).__name__
    rows.append(row)
    time.sleep(0.2)
print(
    json.dumps(
        {
            "samples": rows,
            "scope": "TEST containers; helper attribution may be shared; target-local load generator excluded from pod quota",
        }
    )
)
