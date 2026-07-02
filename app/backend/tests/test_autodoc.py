"""Tests for the auto-documentation endpoints (mock mode — no API key needed).

Exercises the real pipeline: undocumented-tag selection, usage-context
gathering (reused from PLCToolbox.get_tag/get_rung), the deterministic name
heuristic, and CSV export.
"""

import csv
import io
import os

import pytest
from fastapi.testclient import TestClient

from app.backend.autodoc import split_words
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


def _new_session(client):
    r = client.post("/api/session", json={})
    assert r.status_code == 200
    return r.json()["session_id"]


def test_split_words():
    assert split_words("GuardDoor_Closed") == ["Guard", "Door", "Closed"]
    assert split_words("Press_Cycle_Start") == ["Press", "Cycle", "Start"]
    assert split_words("PLC_IO.Data") == ["PLC", "IO", "Data"]


def test_autodoc_generates_for_all_undocumented_tags(client):
    sid = _new_session(client)
    dossier = client.get(f"/api/dossier/{sid}").json()
    undocumented_count = dossier["documentation"]["undocumented_tags"]
    assert undocumented_count > 0  # PressLine_3 has undocumented tags to exercise

    r = client.post(f"/api/autodoc/{sid}", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "mock"
    assert body["total"] == undocumented_count
    assert len(body["proposals"]) == undocumented_count

    for row in body["proposals"]:
        assert row["current_description"] == ""
        assert row["proposed_description"]  # non-empty
        assert row["confidence"] == "low"  # mock mode always low-confidence
        assert set(row.keys()) == {
            "tag", "data_type", "scope", "current_description",
            "proposed_description", "confidence",
        }


def test_autodoc_is_deterministic(client):
    sid = _new_session(client)
    r1 = client.post(f"/api/autodoc/{sid}", json={}).json()
    r2 = client.post(f"/api/autodoc/{sid}", json={}).json()
    by_tag_1 = {p["tag"]: p["proposed_description"] for p in r1["proposals"]}
    by_tag_2 = {p["tag"]: p["proposed_description"] for p in r2["proposals"]}
    assert by_tag_1 == by_tag_2


def test_autodoc_scoped_to_tags(client):
    sid = _new_session(client)
    all_rows = client.post(f"/api/autodoc/{sid}", json={}).json()["proposals"]
    assert len(all_rows) > 1
    one_tag = all_rows[0]["tag"]

    r = client.post(f"/api/autodoc/{sid}", json={"tags": [one_tag]})
    body = r.json()
    assert body["total"] == 1
    assert body["proposals"][0]["tag"] == one_tag


def test_autodoc_scoped_ignores_documented_tags(client):
    sid = _new_session(client)
    # Press_Cycle_Start is a documented tag (used throughout the demo scenario)
    r = client.post(f"/api/autodoc/{sid}", json={"tags": ["Press_Cycle_Start"]})
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_autodoc_unknown_session(client):
    r = client.post("/api/autodoc/nope", json={})
    assert r.status_code == 404


def test_autodoc_export_csv_empty_before_generation(client):
    sid = _new_session(client)
    r = client.get(f"/api/autodoc/{sid}/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows == [["tag", "current_description", "proposed_description", "confidence"]]


def test_autodoc_export_csv_after_generation(client):
    sid = _new_session(client)
    generated = client.post(f"/api/autodoc/{sid}", json={}).json()["proposals"]

    r = client.get(f"/api/autodoc/{sid}/export.csv")
    assert r.status_code == 200
    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    assert len(rows) == len(generated)
    by_tag = {row["tag"]: row for row in rows}
    for p in generated:
        assert by_tag[p["tag"]]["proposed_description"] == p["proposed_description"]
        assert by_tag[p["tag"]]["confidence"] == "low"


def test_autodoc_export_csv_unknown_session(client):
    r = client.get("/api/autodoc/nope/export.csv")
    assert r.status_code == 404
