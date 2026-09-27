"""Read-only acceptance summary. Failed gates remain failed; no report rewriting."""

import argparse
from collections import Counter
import json
from pathlib import Path


def assess(data, stability):
    runs = data.get("runs", [])
    ws = stability.get("websocket", {})
    notification = data.get("websocket", {})
    login = data.get("login", {})
    checks = {
        "same_application_build": bool(data.get("application_sha256"))
        and data.get("application_sha256") == stability.get("application_sha256"),
        "1500_users": data.get("users") == stability.get("users") == 1500,
        "three_rounds_per_scenario": Counter(r["scenario"] for r in runs)
        == Counter({"last_seat": 3, "uniform": 3, "hot_club": 3}),
        "login_60s_p95_2s": login.get("statuses") == {"200": 1500}
        and login.get("duration_offered_s", float("inf")) <= 60
        and login.get("p95_s", float("inf")) <= 2,
        "actual_burst_1s": bool(runs) and all(r["dispatch_span_s"] <= 1 for r in runs),
        "enrollment_p95_2s_p99_5s": bool(runs) and all(r["p95_s"] <= 2 and r["p99_s"] <= 5 for r in runs),
        "consistent_correct_results": bool(runs)
        and all(r["correctness_pass"] and r["data_consistency_pass"] for r in runs),
        "no_capacity_rejection": bool(runs)
        and all(not any(k.startswith(("429:", "503:")) for k in r["statuses"]) for r in runs),
        "unexpected_errors_below_0_1_percent": bool(runs)
        and all(r["unexpected_error_rate"] < 0.001 for r in runs),
        "steady_queries_p95_300ms": data.get("steady_read_p95_s", float("inf")) <= 0.3,
        "1500_websockets_10min": ws.get("connected") == ws.get("open_at_end") == 1500
        and ws.get("held_seconds", 0) >= 600
        and ws.get("unexpected_closes") == 0,
        "notifications_p95_2s": notification.get("notification_p95_s") is not None
        and notification["notification_p95_s"] <= 2,
        "observed_notifications_complete": notification.get("notification_timing_matched", 0) > 0
        and notification.get("notification_timing_missing") == 0
        and notification.get("missing_deliveries_for_observed_versions") == 0,
        "measurement_errors_absent": not data.get("errors") and not stability.get("errors"),
    }
    return {"checks": checks, "measured_gates_pass": all(checks.values())}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("report", type=Path)
    p.add_argument("--stability", type=Path, help="Same application build, separate 10-minute record")
    p.add_argument("--shaping-proof", type=Path, help="Post-run tc counters for the 10 Mbps experiment")
    p.add_argument("--egress-mbps", type=int, choices=[10, 20, 50], default=10)
    args = p.parse_args()
    data = json.loads(args.report.read_text())
    stability = json.loads((args.stability or args.report).read_text())
    result = assess(data, stability)
    if args.shaping_proof:
        proof = json.loads(args.shaping_proof.read_text())
        result["checks"][f"{args.egress_mbps}mbps_shaper_matched_traffic"] = any(
            q.get("kind") == "tbf"
            and q.get("options", {}).get("rate") == args.egress_mbps * 125000
            and q.get("bytes", 0) > 0
            and q.get("packets", 0) > 0
            for q in proof.get("qdiscs", [])
        )
        result["shaping_proof"] = str(args.shaping_proof)
        result["measured_gates_pass"] = all(result["checks"].values())
    result["report"] = str(args.report)
    result["stability_report"] = str(args.stability or args.report)
    result["scope"] = (
        "Measured LAN gates only; manually review resource, build identity and production differences"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["measured_gates_pass"] else 1)


if __name__ == "__main__":
    main()
