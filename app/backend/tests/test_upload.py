"""Tests for POST /api/upload — the bring-your-own-L5X front door."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.backend.server as server
from app.backend.plc_tools import DEFAULT_L5X
from app.backend.server import app


@pytest.fixture(autouse=True)
def isolated_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "UPLOAD_DIR", tmp_path / "uploads")
    yield
    server._SESSIONS.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _upload(client, filename, content):
    return client.post(
        "/api/upload",
        files={"file": (filename, content, "application/xml")},
    )


def test_upload_valid_l5x_creates_working_session(client):
    r = _upload(client, "PressLine_3.L5X", Path(DEFAULT_L5X).read_bytes())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["uploaded"] is True
    assert body["filename"] == "PressLine_3.L5X"
    assert body["summary"]["controller"]["name"] == "PressLine_3"

    # The session is immediately usable.
    d = client.get(f"/api/dossier/{body['session_id']}")
    assert d.status_code == 200
    assert d.json()["controller"]["name"] == "PressLine_3"


def test_upload_is_content_addressed(client):
    data = Path(DEFAULT_L5X).read_bytes()
    r1 = _upload(client, "a.L5X", data)
    r2 = _upload(client, "a.L5X", data)  # same name + content -> same path
    assert r1.json()["l5x"] == r2.json()["l5x"]
    assert r1.json()["session_id"] != r2.json()["session_id"]
    # Same content under a different name shares the digest prefix.
    r3 = _upload(client, "b.L5X", data)
    digest = Path(r1.json()["l5x"]).name.split("_")[0]
    assert Path(r3.json()["l5x"]).name.startswith(digest)


def test_upload_rejects_wrong_extension(client):
    r = _upload(client, "notes.txt", b"hello")
    assert r.status_code == 400
    assert ".L5X" in r.json()["detail"]


def test_upload_rejects_unparseable_xml(client):
    r = _upload(client, "broken.L5X", b"<not-an-l5x/>")
    assert r.status_code == 400
    assert "Could not parse" in r.json()["detail"]
    # The rejected file must not be kept on disk.
    assert not any(server.UPLOAD_DIR.glob("*")) or not list(server.UPLOAD_DIR.iterdir())


def test_upload_rejects_empty_file(client):
    r = _upload(client, "empty.L5X", b"   ")
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


def test_upload_sanitizes_hostile_filename(client):
    r = _upload(client, "../../evil name.L5X", Path(DEFAULT_L5X).read_bytes())
    assert r.status_code == 200
    stored = Path(r.json()["l5x"])
    assert stored.parent == server.UPLOAD_DIR  # no path traversal
    assert stored.name.endswith("evil_name.L5X")
