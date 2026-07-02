"""Tests for GET /api/rung/{sid}/{program}/{routine}/{number} — the nested
rung parse structure consumed by the frontend ladder renderer — and for the
rung_json serializer module it delegates to."""

import pytest
from fastapi.testclient import TestClient

from app.backend.server import app
from app.backend.rung_json import (
    serialize_element,
    collect_tag_operands,
    rung_payload,
)


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


# ──────────────────────────────────────────────────────────────────────
# Serializer unit tests (against the cached ParsedRung objects)
# ──────────────────────────────────────────────────────────────────────

def test_serialize_simple_instruction(toolbox):
    prung = toolbox.project.parsed_rungs[("P900_Safety", "R92_SafetyOK", 0)]
    el = serialize_element(prung.elements[0])
    assert el["type"] == "instruction"
    assert el["mnemonic"] == "XIC"
    assert el["category"] == "bit_io"
    assert el["is_condition"] is True
    assert el["operands"] == [{"value": "Safety_OK", "is_literal": False}]


def test_serialize_branch_seal_in(toolbox):
    # MainProgram/R02_CycleControl rung 0 is the master 3-wire seal-in:
    # [XIC(Master_Start_PB),XIC(System_Running)]XIC(Master_Stop_PB)XIC(Safety_OK)OTE(System_Running)
    prung = toolbox.project.parsed_rungs[("MainProgram", "R02_CycleControl", 0)]
    branch = serialize_element(prung.elements[0])
    assert branch["type"] == "branch"
    assert len(branch["legs"]) == 2
    leg_tags = [leg[0]["operands"][0]["value"] for leg in branch["legs"]]
    assert leg_tags == ["Master_Start_PB", "System_Running"]
    # legs recursively serialize to instruction dicts
    assert all(leg[0]["type"] == "instruction" for leg in branch["legs"])


def test_collect_tag_operands_skips_literals(toolbox):
    # FB_DEBOUNCE(Debounce_PartEye,PartPresent_Eye1,50,Part_Present) — the 50 is a literal
    prung = toolbox.project.parsed_rungs[("P100_Infeed", "R11_PartDetect", 0)]
    ops = collect_tag_operands(prung.elements)
    assert "Debounce_PartEye" in ops
    assert "PartPresent_Eye1" in ops
    assert "50" not in ops


def test_rung_payload_error_paths(toolbox):
    assert "error" in rung_payload(toolbox, "Nope", "Nope", 0)
    assert "error" in rung_payload(toolbox, "P300_Press", "R32_Recipe", 0)  # ST routine
    assert "error" in rung_payload(toolbox, "P900_Safety", "R92_SafetyOK", 99)


# ──────────────────────────────────────────────────────────────────────
# Endpoint tests
# ──────────────────────────────────────────────────────────────────────

def test_rung_endpoint_nested_structure(client):
    sid = _new_session(client)["session_id"]
    r = client.get(f"/api/rung/{sid}/MainProgram/R02_CycleControl/0")
    assert r.status_code == 200
    body = r.json()
    assert body["program"] == "MainProgram"
    assert body["routine"] == "R02_CycleControl"
    assert body["number"] == 0
    assert body["comment"].startswith("Master seal-in")
    types = [el["type"] for el in body["elements"]]
    assert types == ["branch", "instruction", "instruction", "instruction"]
    assert body["elements"][-1]["mnemonic"] == "OTE"
    # no snapshot on the session and none requested -> no values map
    assert "values" not in body
    # tag descriptions present for the sub-labels
    assert "System_Running" in body["tags"]


def test_rung_endpoint_values_from_query_snapshot(client):
    sid = _new_session(client)["session_id"]
    r = client.get(
        f"/api/rung/{sid}/P900_Safety/R92_SafetyOK/1",
        params={"snapshot": "guard_door_open"},
    )
    assert r.status_code == 200
    body = r.json()
    vals = body["values"]
    assert vals["GuardDoor_Closed"] is False
    assert vals["Estop_Chain_OK"] is True
    assert vals["SafetyRelay_CH1"] is True


def test_rung_endpoint_values_from_session_snapshot(client):
    sid = _new_session(client, snapshot="healthy")["session_id"]
    r = client.get(f"/api/rung/{sid}/P900_Safety/R92_SafetyOK/1")
    assert r.status_code == 200
    assert r.json()["values"]["GuardDoor_Closed"] is True


def test_tag_search_endpoint(client):
    sid = _new_session(client)["session_id"]
    r = client.get(f"/api/tags/{sid}", params={"q": "guarddoor"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(t["name"] == "GuardDoor_Closed" for t in body["tags"])


def test_rung_endpoint_404s(client):
    sid = _new_session(client)["session_id"]
    assert client.get(f"/api/rung/{sid}/Nope/Nope/0").status_code == 404
    assert client.get(f"/api/rung/{sid}/P900_Safety/R92_SafetyOK/99").status_code == 404
    assert client.get("/api/rung/nosession/P900_Safety/R92_SafetyOK/0").status_code == 404
    r = client.get(
        f"/api/rung/{sid}/P900_Safety/R92_SafetyOK/1",
        params={"snapshot": "no_such_snapshot"},
    )
    assert r.status_code == 404
