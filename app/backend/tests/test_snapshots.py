"""Snapshot loading + live-value provider tests."""

import json

import pytest

from app.backend.plc_tools import (
    StaticSnapshotProvider, OpcUaProvider, SNAPSHOT_DIR,
)


def test_static_snapshot_loads_wrapped():
    p = StaticSnapshotProvider(SNAPSHOT_DIR / "guard_door_open.json")
    assert p.available() is True
    vals = p.get_values()
    assert vals["GuardDoor_Closed"] is False
    assert vals["Safety_OK"] is False
    assert p.description  # description carried through


def test_static_snapshot_consistency():
    # both money-shot snapshots must be internally consistent
    guard = StaticSnapshotProvider(SNAPSHOT_DIR / "guard_door_open.json").get_values()
    assert guard["GuardDoor_Closed"] is False and guard["Safety_OK"] is False
    healthy = StaticSnapshotProvider(SNAPSHOT_DIR / "healthy.json").get_values()
    assert healthy["GuardDoor_Closed"] is True and healthy["Safety_OK"] is True


def test_static_snapshot_bare_map(tmp_path):
    f = tmp_path / "bare.json"
    f.write_text(json.dumps({"A": True, "B": False}))
    p = StaticSnapshotProvider(f)
    assert p.get_values() == {"A": True, "B": False}
    assert p.name == "bare"


def test_static_snapshot_filter():
    p = StaticSnapshotProvider(SNAPSHOT_DIR / "healthy.json")
    v = p.get_values(["safety_ok"])  # case-insensitive
    assert set(v.keys()) == {"Safety_OK"}


def test_opcua_placeholder():
    p = OpcUaProvider("opc.tcp://x")
    assert p.available() is False
    with pytest.raises(NotImplementedError):
        p.get_values()
