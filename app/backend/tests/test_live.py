"""Live-session tests for the REST backend.

Two layers:
  * ``test_live_session_503_when_sim_down`` needs no simulator — it asserts that
    a live-session request against an unreachable OPC UA endpoint fails fast with
    a clear 503.
  * The ``sim`` fixture spawns the real PressLine_3 simulator as a subprocess
    (reusing gate4's pattern) on private ports; the integration tests then create
    a live session, trace the healthy machine, inject ``guard_door_open`` through
    the chaos proxy, assert the Safety_OK -> GuardDoor_Closed failing chain, and
    clear it. Everything is skipped cleanly if the sim never comes up.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.backend.server import app

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Private ports, distinct from the default sim (4840/8090) and gate4 (4841/8091).
OPC_PORT = 4842
HTTP_PORT = 8092
OPC_ENDPOINT = f"opc.tcp://127.0.0.1:{OPC_PORT}/pressline3/"
SIM_HTTP = f"http://127.0.0.1:{HTTP_PORT}"


@pytest.fixture(autouse=True)
def _force_mock():
    prev = os.environ.get("ASKPLC_MOCK")
    os.environ["ASKPLC_MOCK"] = "1"
    yield
    if prev is None:
        os.environ.pop("ASKPLC_MOCK", None)
    else:
        os.environ["ASKPLC_MOCK"] = prev


@pytest.fixture
def client():
    return TestClient(app)


def _http_get(path: str, timeout: float = 3.0):
    with urllib.request.urlopen(SIM_HTTP + path, timeout=timeout) as r:
        return json.load(r)


def _wait(predicate, deadline_s: float, poll_s: float = 0.15) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            if predicate():
                return True
        except (urllib.error.URLError, ConnectionError, OSError, ValueError):
            pass
        time.sleep(poll_s)
    return False


@pytest.fixture(scope="module")
def sim():
    """Spawn the PressLine_3 simulator; skip the test module if it won't start."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.simulator",
         "--port", str(OPC_PORT), "--http-port", str(HTTP_PORT)],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        up = _wait(lambda: _http_get("/health").get("ok"), 15.0)
        if not up:
            proc.terminate()
            pytest.skip("PressLine_3 simulator did not start")
        # wait for a healthy, cycling machine before yielding
        _wait(lambda: _http_get("/state").get("cycling"), 15.0)
        yield SIM_HTTP
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def test_live_session_503_when_sim_down(client):
    # nothing is listening on this port -> connection refused -> fast 503
    r = client.post("/api/session", json={
        "live": True,
        "opcua_url": "opc.tcp://127.0.0.1:4999/pressline3/",
    })
    assert r.status_code == 503
    assert "unreachable" in r.json()["detail"].lower()


def _new_live_session(client) -> str:
    r = client.post("/api/session", json={
        "live": True,
        "opcua_url": OPC_ENDPOINT,
        "sim_http_url": SIM_HTTP,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["live"] is True
    assert body["opcua_url"] == OPC_ENDPOINT
    return body["session_id"]


def test_live_session_create_and_status(client, sim):
    sid = _new_live_session(client)
    r = client.get(f"/api/live/{sid}/status")
    assert r.status_code == 200
    st = r.json()
    assert st["state"] in ("RUNNING", "STARTING")
    assert "key_values" in st and "Safety_OK" in st["key_values"]


def test_live_trace_healthy_then_guard_then_clear(client, sim):
    sid = _new_live_session(client)

    # healthy: Press_Cycle_Start satisfied, live source is OPC UA
    def _healthy():
        t = client.get(f"/api/trace/{sid}/Press_Cycle_Start").json()
        return t.get("root_satisfied") is True
    assert _wait_client(_healthy, 10.0)
    healthy = client.get(f"/api/trace/{sid}/Press_Cycle_Start").json()
    assert healthy["live_source"] == "opcua"
    assert healthy["failing_count"] == 0

    # inject guard_door_open through the chaos proxy
    r = client.post(f"/api/live/{sid}/chaos", json={"fault": "guard_door_open"})
    assert r.status_code == 200
    assert r.json()["active_fault"] == "guard_door_open"

    # trace now isolates to exactly Safety_OK -> GuardDoor_Closed
    def _cascaded():
        t = client.get(f"/api/trace/{sid}/Press_Cycle_Start").json()
        paths = t.get("failing_paths") or []
        return (t.get("root_satisfied") is False and len(paths) == 1
                and paths[0]["chain"] == ["Safety_OK", "GuardDoor_Closed"])
    assert _wait_client(_cascaded, 10.0)

    # the rung endpoint reflects the live guard trip: Safety_OK is False on R30
    rung = client.get(f"/api/rung/{sid}/P300_Press/R30_PressCycle/9").json()
    assert "values" in rung
    # find Safety_OK operand value (case-insensitive)
    vals = {k.lower(): v for k, v in rung["values"].items()}
    assert vals.get("safety_ok") is False

    # clear + reset handshake -> recovers
    r = client.post(f"/api/live/{sid}/chaos/clear")
    assert r.status_code == 200

    def _recovered():
        t = client.get(f"/api/trace/{sid}/Press_Cycle_Start").json()
        return t.get("root_satisfied") is True
    assert _wait_client(_recovered, 15.0)


def test_live_chaos_unknown_fault_rejected(client, sim):
    sid = _new_live_session(client)
    r = client.post(f"/api/live/{sid}/chaos", json={"fault": "not_a_fault"})
    assert r.status_code == 400


def test_status_on_non_live_session_400(client):
    # a plain snapshot session is not live
    sid = client.post("/api/session", json={"snapshot": "healthy"}).json()["session_id"]
    assert client.get(f"/api/live/{sid}/status").status_code == 400


def _wait_client(predicate, deadline_s: float, poll_s: float = 0.2) -> bool:
    """Poll a predicate that itself issues TestClient requests."""
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(poll_s)
    return False
