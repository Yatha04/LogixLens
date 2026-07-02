"""End-to-end tests for the FastAPI backend: session lifecycle, REST endpoints,
and the WebSocket chat flow in mock mode (exercises the real tool loop)."""

import os

import pytest
from fastapi.testclient import TestClient

from app.backend.server import app


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


def _new_session(client, snapshot=None):
    body = {}
    if snapshot:
        body["snapshot"] = snapshot
    r = client.post("/api/session", json=body)
    assert r.status_code == 200
    return r.json()


def test_create_session(client):
    data = _new_session(client, snapshot="guard_door_open")
    assert "session_id" in data
    assert data["mock"] is True
    assert data["summary"]["controller"]["name"] == "PressLine_3"
    assert "FB_VALVE" in data["summary"]["aoi_instances"]


def test_session_missing(client):
    assert client.get("/api/dossier/nope").status_code == 404


def test_dossier(client):
    sid = _new_session(client)["session_id"]
    r = client.get(f"/api/dossier/{sid}")
    assert r.status_code == 200
    d = r.json()
    assert d["counts"]["tags"] == 169
    assert d["documentation"]["coverage_pct"] > 0
    assert "FB_VALVE" in d["aoi_instances"]


def test_routine_endpoint(client):
    sid = _new_session(client)["session_id"]
    r = client.get(f"/api/routine/{sid}/P900_Safety/R92_SafetyOK")
    assert r.status_code == 200
    assert r.json()["total_rungs"] == 2
    assert client.get(f"/api/routine/{sid}/Nope/Nope").status_code == 404


def test_trace_endpoint(client):
    sid = _new_session(client, snapshot="guard_door_open")["session_id"]
    r = client.get(f"/api/trace/{sid}/Press_Cycle_Start")
    assert r.status_code == 200
    body = r.json()
    assert body["root_satisfied"] is False
    assert body["failing_paths"][0]["chain"] == ["Safety_OK", "GuardDoor_Closed"]


def test_trace_endpoint_snapshot_override(client):
    # session has no snapshot; override via query param -> healthy = satisfied
    sid = _new_session(client)["session_id"]
    r = client.get(f"/api/trace/{sid}/Press_Cycle_Start", params={"snapshot": "healthy"})
    assert r.json()["root_satisfied"] is True


def _drain_ws(ws):
    frames = []
    while True:
        f = ws.receive_json()
        frames.append(f)
        if f["type"] in ("done", "error"):
            break
    return frames


def test_ws_why_question(client):
    sid = _new_session(client, snapshot="guard_door_open")["session_id"]
    with client.websocket_connect(f"/api/chat/{sid}") as ws:
        ws.send_json({"message": "why is the press not cycling?", "audience": "maintenance"})
        frames = _drain_ws(ws)
    types = [f["type"] for f in frames]
    assert "tool_call" in types
    assert "tool_result_summary" in types
    assert "text_delta" in types
    assert types[-1] == "done"
    # the trace tool was called and the answer names the failing contact
    tools = [f["tool"] for f in frames if f["type"] == "tool_call"]
    assert "trace_blockers" in tools
    text = "".join(f["text"] for f in frames if f["type"] == "text_delta")
    assert "GuardDoor_Closed" in text
    cites = [f for f in frames if f["type"] == "citations"]
    assert cites and any(c["routine"] == "R92_SafetyOK" for c in cites[0]["citations"])


def test_ws_why_question_citations_prefer_failing_path(client):
    # The full condition tree for Press_Cycle_Start touches ~20 rungs across
    # several routines (R31_Hydraulics, R21_Sequence, R90_EstopChain...), but
    # only Safety_OK / GuardDoor_Closed are actually broken. The citations
    # frame should carry just the failing-path rungs, not every rung the
    # tree happened to visit while confirming everything else was fine.
    sid = _new_session(client, snapshot="guard_door_open")["session_id"]
    with client.websocket_connect(f"/api/chat/{sid}") as ws:
        ws.send_json({"message": "why is the press not cycling?", "audience": "maintenance"})
        frames = _drain_ws(ws)
    cite_frames = [f for f in frames if f["type"] == "citations"]
    assert cite_frames
    routines = {c["routine"] for c in cite_frames[0]["citations"]}
    assert routines == {"R30_PressCycle", "R92_SafetyOK"}
    assert "R31_Hydraulics" not in routines
    assert "R90_EstopChain" not in routines


def test_ws_overview_question(client):
    sid = _new_session(client)["session_id"]
    with client.websocket_connect(f"/api/chat/{sid}") as ws:
        ws.send_json({"message": "what does this machine do?", "audience": "operator"})
        frames = _drain_ws(ws)
    tools = [f["tool"] for f in frames if f["type"] == "tool_call"]
    assert "get_project_summary" in tools
    text = "".join(f["text"] for f in frames if f["type"] == "text_delta")
    assert "press" in text.lower()


def test_ws_result_summary_suppresses_payload(client):
    sid = _new_session(client, snapshot="guard_door_open")["session_id"]
    with client.websocket_connect(f"/api/chat/{sid}") as ws:
        ws.send_json({"message": "why is the press not cycling?", "audience": "controls_engineer"})
        frames = _drain_ws(ws)
    summaries = [f for f in frames if f["type"] == "tool_result_summary"]
    assert summaries
    for s in summaries:
        # compact summary only — no raw tool result payload leaked
        assert "result" not in s
        assert "result_bytes" in s and "breadcrumb" in s


def test_ws_empty_message(client):
    sid = _new_session(client)["session_id"]
    with client.websocket_connect(f"/api/chat/{sid}") as ws:
        ws.send_json({"message": "", "audience": "maintenance"})
        f = ws.receive_json()
    assert f["type"] == "error"
