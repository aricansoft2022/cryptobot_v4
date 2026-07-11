"""Tests for the HTTP status server (served over a real ephemeral port)."""

from __future__ import annotations

import http.client
import json

import pytest

from cryptobot.runtime.status_server import StatusServer


@pytest.fixture
def server():
    snapshots = {"value": {"realized_trades": 0, "open_positions": []}}
    srv = StatusServer(lambda: snapshots["value"], host="127.0.0.1", port=0).start()
    try:
        yield srv, snapshots
    finally:
        srv.stop()


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8")
    finally:
        conn.close()


def test_status_endpoint_returns_provider_json(server):
    srv, snapshots = server
    snapshots["value"] = {"realized_trades": 3, "realized_net_pnl": "12.5"}
    status, body = _get(srv.port, "/status")
    assert status == 200
    assert json.loads(body) == {"realized_trades": 3, "realized_net_pnl": "12.5"}


def test_status_reflects_live_updates(server):
    srv, snapshots = server
    snapshots["value"] = {"realized_trades": 1}
    assert json.loads(_get(srv.port, "/status")[1])["realized_trades"] == 1
    snapshots["value"] = {"realized_trades": 2}
    assert json.loads(_get(srv.port, "/status")[1])["realized_trades"] == 2


def test_health_endpoint(server):
    srv, _ = server
    status, body = _get(srv.port, "/health")
    assert status == 200
    assert json.loads(body) == {"ok": True}


def test_unknown_path_is_404(server):
    srv, _ = server
    status, _body = _get(srv.port, "/nope")
    assert status == 404


def test_url_and_port_exposed(server):
    srv, _ = server
    assert srv.port > 0
    assert srv.url.startswith(f"http://127.0.0.1:{srv.port}/status")
