"""Read-only evidence summary; a passing short run is never production approval."""

import argparse
import hashlib
import json
from pathlib import Path
import re

try:
    from scripts.load_journey import journey_gates
except ModuleNotFoundError:
    from load_journey import journey_gates


def evaluate(path):
    path = Path(path)
    data = json.loads(path.read_text())
    prefix = path.with_suffix("")
    proofs = {}
    for suffix in ("egress-after", "egress-restored"):
        target = Path(f"{prefix}-{suffix}.json")
        proofs[suffix] = json.loads(target.read_text()) if target.exists() else {}
    limits = Path(f"{prefix}-limits.txt")
    limit_text = limits.read_text() if limits.exists() else ""
    cpu = re.search(r"CPUQuotaPerSecUSec=(\d+)s", limit_text)
    shaped = [q for q in proofs["egress-after"].get("qdiscs", []) if q["kind"] == "tbf"]
    restored = proofs["egress-restored"].get("qdiscs", [])
    params = data["parameters"]
    resources = [r["server"]["cgroups"]["budget_total"] for r in data.get("resources", [])]
    all_groups = [
        group
        for sample in data.get("resources", [])
        for group in sample["server"]["cgroups"].values()
        if "memory.events" in group
    ]
    no_oom = bool(all_groups) and all(
        all(
            int(line.split()[1]) == 0
            for line in r["memory.events"].splitlines()
            if line.split()[0] in {"oom", "oom_kill"}
        )
        for r in all_groups
    )
    evidence = {
        "explicitly_completed": data.get("completed") is True,
        "requested_rounds_present": len(data["runs"]) == params["rounds"],
        "no_driver_errors": not data["errors"],
        "tls_verified": params["url"].startswith("https://") and bool(data.get("test_ca_sha256")),
        "egress_was_used": len(shaped) == 1 and shaped[0].get("bytes", 0) > 0,
        "egress_restored": bool(restored) and all(q["kind"] == "noqueue" for q in restored),
        "no_oom": no_oom,
    }
    return {
        "file": path.name,
        "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "application_sha256": data.get("application_sha256"),
        "driver_sha256": data["driver_sha256"],
        "cpu_quota": int(cpu[1]) if cpu else None,
        "egress_mbps": shaped[0]["options"]["rate"] * 8 / 1e6 if len(shaped) == 1 else None,
        "runtime": data.get("runtime_settings"),
        "api_command": data.get("api_command"),
        "users": params["users"],
        "mode": params["mode"],
        "scenario": params["scenario"],
        "hold_seconds": params["hold_seconds"],
        "evidence_gates": evidence,
        "peak_pod_memory_mib": round(max((int(r["memory.peak"]) for r in resources), default=0) / 2**20, 1),
        "rounds": [
            {
                "round": r["round"],
                "completed": r["completed_students"],
                "login_p95_s": r["stages"].get("login", {}).get("p95_s"),
                "enrollment_p95_s": r["stages"]["enroll"]["p95_s"],
                "enrollment_p99_s": r["stages"]["enroll"]["p99_s"],
                "notification_p95_s": r["websocket"]["notification_p95_s"],
                "steady_p95_s": r.get("steady_reads_after_20s", {}).get("p95_s"),
                "failed_original_scope_gates": [k for k, v in r["scope_gates"].items() if not v],
                "failed_current_scope_gates": [
                    k for k, v in journey_gates(r, params["mode"], params["users"]).items() if not v
                ],
                "measured_scope_pass": all(evidence.values())
                and all(journey_gates(r, params["mode"], params["users"]).values()),
            }
            for r in data["runs"]
        ],
        "production_capacity_verified": False,
        "hardware_equivalence_verified": False,
        "note": "Each scope is partial; cold login, ready uniform/hot/last-seat, mixed, reconnect require three consecutive rounds at one configuration plus 600s active stability. No cloud-core equivalence inferred.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+")
    args = parser.parse_args()
    print(json.dumps([evaluate(p) for p in args.reports], ensure_ascii=False, indent=2))
