"""Diagnostic accounting must retain failures without recording auth responses."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, Mock

import pytest

from scripts import load_connection_phases as driver


@pytest.mark.asyncio
async def test_http_probe_discards_token_and_keeps_server_timing(monkeypatch):
    payload = b'{"data":{"token":"must-not-appear-in-report"}}'
    reader = asyncio.StreamReader()
    reader.feed_data(
        b"HTTP/1.1 200 OK\r\nContent-Length: "
        + str(len(payload)).encode()
        + b"\r\nServer-Timing: app;dur=17.32\r\n\r\n"
        + payload
    )
    reader.feed_eof()
    writer = Mock()
    writer.get_extra_info.return_value.version.return_value = "TLSv1.3"
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "sock_connect", AsyncMock())
    monkeypatch.setattr(asyncio, "open_connection", AsyncMock(return_value=(reader, writer)))
    row = await driver.probe(None, "login", 0, 1, time.time())
    assert row["outcome"] == "200"
    assert row["server_s"] == pytest.approx(0.01732)
    assert "must-not-appear" not in json.dumps(row)
    assert "password" not in json.dumps(row)
    assert "sent_s" in row


@pytest.mark.asyncio
async def test_tls_timeout_retains_failed_stage(monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), "sock_connect", AsyncMock())

    async def delayed(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(asyncio, "open_connection", delayed)
    row = await driver.probe(None, "tls", 0, 0.01, time.time())
    assert row["outcome"] == "TimeoutError"
    assert row["stage"] == "tls"
    assert "tcp_s" in row and "tls_s" not in row and "sent_s" not in row
    result = driver.summarize([row])
    assert result["total_s"]["count"] == 1
    assert result["failures_by_stage"] == {"tls": 1}


@pytest.mark.asyncio
async def test_guard_rejects_non_test_service(monkeypatch):
    row = {"outcome": "200"}
    # Exercise real parser and guard, no server or production requests.
    payload = b'{"environment":"production"}'
    reader = asyncio.StreamReader()
    reader.feed_data(
        b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload
    )
    writer = Mock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    monkeypatch.setattr(asyncio.get_running_loop(), "sock_connect", AsyncMock())
    monkeypatch.setattr(asyncio, "open_connection", AsyncMock(return_value=(reader, writer)))
    with pytest.raises(RuntimeError, match="Refusing"):
        row = await driver.probe(None, "health", 0, 1, time.time(), guard=True)
    assert row == {"outcome": "200"}
