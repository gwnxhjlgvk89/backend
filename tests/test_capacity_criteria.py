"""Offline acceptance checks: changed latency targets must not hide missing coverage."""

import json
from pathlib import Path

import pytest

from scripts.check_capacity import assess


REPORTS = Path(__file__).resolve().parents[1] / "reports"


def reports():
    return (
        json.loads((REPORTS / "linux-capacity-egress10.json").read_text()),
        json.loads((REPORTS / "linux-capacity-confirmation.json").read_text()),
    )


def test_existing_evidence_under_old_and_new_criteria():
    data, stability = reports()
    assert not assess(data, stability, enrollment_p95_seconds=2)["measured_gates_pass"]
    result = assess(data, stability)
    assert result["measured_gates_pass"]
    assert not result["full_journey_verified"]
    assert not result["production_capacity_verified"]
    assert result["coverage_gaps"]


@pytest.mark.parametrize("p95,p99,passed", [(3, 5, True), (3.0001, 5, False), (3, 5.0001, False)])
def test_latency_boundaries(p95, p99, passed):
    data, stability = reports()
    data["runs"][0].update(p95_s=p95, p99_s=p99)
    assert assess(data, stability)["measured_gates_pass"] is passed


@pytest.mark.parametrize("fault", ["build", "consistency", "dispatch", "errors", "capacity", "duration"])
def test_relaxed_latency_does_not_relax_other_gates(fault):
    data, stability = reports()
    if fault == "build":
        data["application_sha256"] = "different"
    elif fault == "consistency":
        data["runs"][0]["data_consistency_pass"] = False
    elif fault == "dispatch":
        data["runs"][0]["dispatch_span_s"] = 1.0001
    elif fault == "errors":
        data["runs"][0]["unexpected_error_rate"] = 0.001
    elif fault == "capacity":
        data["runs"][0]["statuses"]["429:CAPACITY_LIMIT"] = 1
    else:
        stability["websocket"]["held_seconds"] = 599
    assert not assess(data, stability)["measured_gates_pass"]
