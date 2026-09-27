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
