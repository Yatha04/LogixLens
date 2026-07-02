"""Shared fixtures for the Ask-the-PLC backend tests (run against the real
PressLine_3 demo file — fast, ~0.1s to parse)."""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.backend.plc_tools import (  # noqa: E402
    PLCToolbox, StaticSnapshotProvider, DEFAULT_L5X, SNAPSHOT_DIR,
)


@pytest.fixture(scope="session")
def guard_snapshot():
    return StaticSnapshotProvider(SNAPSHOT_DIR / "guard_door_open.json")


@pytest.fixture(scope="session")
def healthy_snapshot():
    return StaticSnapshotProvider(SNAPSHOT_DIR / "healthy.json")


@pytest.fixture(scope="session")
def toolbox(guard_snapshot):
    """PLCToolbox with the guard-door-open live snapshot attached."""
    return PLCToolbox(str(DEFAULT_L5X), live_provider=guard_snapshot)


@pytest.fixture(scope="session")
def healthy_toolbox(healthy_snapshot):
    return PLCToolbox(str(DEFAULT_L5X), live_provider=healthy_snapshot)
