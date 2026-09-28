import json
from pathlib import Path
import runpy
import sys

import pytest


def module():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / "deploy/trace-test-requests.py"))


def test_trace_refuses_non_test_container_before_changing_files(monkeypatch):
    namespace = module()
    monkeypatch.setattr(sys, "argv", ["trace-test-requests.py", "enable"])
    monkeypatch.setattr(
        namespace["subprocess"],
        "check_output",
        lambda _: json.dumps([{"Config": {"Labels": {"com.docker.compose.project": "production"}}}]).encode(),
    )
    with pytest.raises(SystemExit, match="Only isolated TEST"):
        namespace["main"]()


def test_trace_excludes_credentials_and_websocket_ticket_query():
    config = module()["PREFIX"]
    for unsafe in ("$request_body", "$http_authorization", "$request_uri", "$args", "$query_string"):
        assert unsafe not in config
    assert '"~^[a-f0-9]{32}$"' in config
    assert "$upstream_http_x_request_id" in config
