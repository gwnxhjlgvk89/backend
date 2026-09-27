from scripts.load_journey import summary


def test_failed_and_timed_out_requests_are_in_latency_and_error_denominator():
    rows = [
        (200, "OK", 0.1, 0, 0.05, 100),
        (503, "BUSY", 4, 0.4, 3.9, 50),
        (0, "TimeoutError", 10, 0.85, None, 0),
    ]
    result = summary(rows)
    assert result["count"] == 3
    assert result["p95_s"] == result["max_s"] == 10
    assert result["unexpected_errors"] == 2
    assert result["capacity_rejections"] == 1
    assert result["dispatch_span_s"] == 0.85
    assert result["arrivals_per_second"] == {0: 3}


def test_empty_metrics_never_invent_zero_latency():
    assert summary([])["p95_s"] is None
    assert summary([])["count"] == 0


def test_tls_delays_cannot_be_hidden_by_a_fast_request_start_burst():
    rows = [
        (200, "OK", 2, 0, 0.1, 100, 1.8, 1.8, 0.2),
        (200, "OK", 4, 0.6, 0.1, 100, 3.8, 3.8, 0.2),
    ]
    result = summary(rows)
    assert result["dispatch_span_s"] == 0.6
    assert result["headers_dispatch_span_s"] == 2.6
    assert result["connect_tls_p95_s"] == 3.8
    assert result["p95_s"] == 4


def test_short_or_incomplete_report_cannot_approve_hardware(tmp_path):
    import json
    from scripts.check_journey import evaluate

    path = tmp_path / "sample.json"
    path.write_text(
        json.dumps(
            {
                "completed": False,
                "parameters": {
                    "rounds": 3,
                    "users": 1500,
                    "url": "http://test",
                    "mode": "ready",
                    "scenario": "uniform",
                    "hold_seconds": 30,
                },
                "runs": [],
                "errors": [],
                "application_sha256": "app",
                "driver_sha256": "driver",
            }
        )
    )
    result = evaluate(path)
    assert not result["evidence_gates"]["explicitly_completed"]
    assert not result["evidence_gates"]["requested_rounds_present"]
    assert not result["evidence_gates"]["egress_was_used"]
    assert not result["hardware_equivalence_verified"]
    assert not result["production_capacity_verified"]


def test_process_merge_uses_raw_latencies_and_global_burst_not_average_percentiles():
    from scripts.load_distributed_journey import combine

    def part(latencies, offset):
        rows = [(200, "OK", t, offset, t, 100) for t in latencies]
        return {
            "runs": [
                {
                    "raw_stages": {"enroll": rows, "login": []},
                    "raw_notification_delays": [0.1],
                    "outcomes": {},
                    "websocket": {
                        "open_at_end": len(rows),
                        "timed_deliveries": 1,
                        "missing_final_quota_snapshots": 0,
                    },
                    "completed_students": len(rows),
                    "confirmed_enrollments": len(rows),
                    "active_duration_s": 30,
                }
            ]
        }

    # A percentile-of-percentiles would falsely weight the small shard equally.
    result = combine(
        [part([0.1] * 99, 0), part([10], 2)],
        {"enrollments": 100, "inconsistencies": []},
        "ready",
        "uniform",
        100,
    )
    assert result["stages"]["enroll"]["p95_s"] == 0.1
    assert result["stages"]["enroll"]["p99_s"] == 10
    assert not result["scope_gates"]["ready_enrollment_burst_within_1s"]
    assert not result["scope_gates"]["enrollment_p95_3s_p99_5s"]
    assert result["data_consistency_pass"]


def test_login_four_second_gate_does_not_relax_enrollment():
    from scripts.load_journey import journey_gates

    row = summary([(200, "OK", 3.8, 0, 3.7, 100)])
    item = {
        "stages": {"login": row, "enroll": row},
        "completed_students": 1,
        "data_consistency_pass": True,
        "all_expected_enrolled": True,
        "websocket": {
            "missing_final_quota_snapshots": 0,
            "timed_deliveries": 1,
            "open_at_end": 1,
            "notification_p95_s": 1,
        },
    }
    gates = journey_gates(item, "login", 1)
    assert gates["login_p95_4s"]
    assert not gates["enrollment_p95_3s_p99_5s"]
