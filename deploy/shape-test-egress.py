"""Shape only IPv4 HTTP/WS responses in the named TEST nginx network namespace.
Never enters the host namespace, replaces an existing qdisc, or changes host NICs.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["show", "limit", "clear"])
    parser.add_argument("--mbps", type=int, choices=[10, 20, 50], default=10)
    parser.add_argument("--port", type=int, choices=[8080, 8443], default=8080)
    args = parser.parse_args()
    target = "club-capacity-test_nginx_1"
    data = json.loads(subprocess.check_output(["podman", "inspect", target]))[0]
    labels = data["Config"]["Labels"]
    if (
        labels.get("com.docker.compose.project") != "club-capacity-test"
        or labels.get("com.docker.compose.service") != "nginx"
    ):
        raise SystemExit("Refusing a container outside the synthetic test project")
    namespace = data["NetworkSettings"]["SandboxKey"]
    if not namespace.startswith(f"/run/user/{os.getuid()}/netns/"):
        raise SystemExit("Expected a private rootless network namespace")
    pid = data["State"]["Pid"]
    if not pid or os.readlink(f"/proc/{pid}/ns/net") == os.readlink("/proc/self/ns/net"):
        raise SystemExit("Refusing the host namespace or stopped container")
    # Current rootless port forwarding delivers public connections through lo;
    # eth0 carries nginx-to-API traffic. Confirm packet headers before reuse.
    base = ["podman", "unshare", "nsenter", "--net=" + namespace, "tc"]

    def run(*parts):
        return subprocess.check_output(base + list(parts), text=True)

    qdiscs = json.loads(run("-s", "-j", "qdisc", "show", "dev", "lo"))
    root = next(q for q in qdiscs if q.get("root"))
    state = Path(".local/egress-shaping.json")
    identity = {"container_id": data["Id"], "namespace": namespace}
    if args.action == "limit":
        if root["kind"] != "noqueue" or state.exists():
            raise SystemExit("Refusing to overwrite traffic controls or an existing rehearsal")
        run(
            "qdisc",
            "add",
            "dev",
            "lo",
            "root",
            "handle",
            "c10:",
            "prio",
            "bands",
            "3",
            "priomap",
            *(["1"] * 16),
        )
        state.parent.mkdir(exist_ok=True)
        state.write_text(json.dumps(identity))
        state.chmod(0o600)
        try:
            run(
                "qdisc",
                "add",
                "dev",
                "lo",
                "parent",
                "c10:1",
                "handle",
                "c11:",
                "tbf",
                "rate",
                f"{args.mbps}mbit",
                "burst",
                "32kb",
                "latency",
                "2000ms",
            )
            # Upstream requests use an ephemeral source port and remain unshaped.
            run(
                "filter",
                "add",
                "dev",
                "lo",
                "parent",
                "c10:",
                "protocol",
                "ip",
                "prio",
                "1",
                "u32",
                "match",
                "ip",
                "protocol",
                "6",
                "0xff",
                "match",
                "ip",
                "sport",
                str(args.port),
                "0xffff",
                "flowid",
                "c10:1",
            )
        except Exception:
            run("qdisc", "del", "dev", "lo", "root", "handle", "c10:")
            state.unlink()
            raise
    elif args.action == "clear":
        if not state.exists() or json.loads(state.read_text()) != identity or root.get("handle") != "c10:":
            raise SystemExit("Refusing to remove a qdisc not owned by this rehearsal")
        run("qdisc", "del", "dev", "lo", "root", "handle", "c10:")
        state.unlink()
    print(
        json.dumps(
            {
                "target": target,
                "namespace": namespace,
                "qdiscs": json.loads(run("-s", "-j", "qdisc", "show", "dev", "lo")),
                "filters": json.loads(run("-s", "-j", "filter", "show", "dev", "lo", "parent", "c10:"))
                if args.action != "clear" and (args.action == "limit" or root.get("handle") == "c10:")
                else [],
            }
        )
    )


if __name__ == "__main__":
    main()
