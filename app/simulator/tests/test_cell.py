"""
Pure state-machine tests for the PressLine_3 Cell -- NO OPC UA server required.

These exercise the tick transitions, every chaos fault's cascade, recovery, and
the prime-directive consistency invariants (Safety_OK / Press_Cycle_Start always
equal the AND/OR/NOT of their YAML interlock condition tags, across random ticks
with random fault injection).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from app.simulator.cell import (
    CHAOS_FAULTS, FAULTED, RUNNING, STOPPED, Cell,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SNAP = _REPO_ROOT / "app" / "backend" / "snapshots"


def _run_to_running(cell: Cell, ticks: int = 20) -> None:
    for _ in range(ticks):
        cell.tick(0.1)


# --------------------------------------------------------------- interlocks
def _expected_interlock(cell: Cell, name: str) -> bool:
    il = cell.interlocks[name]
    ok = all(bool(cell.get(t)) for t in (il.get("all_of") or []))
    if il.get("any_of"):
        ok = ok and any(bool(cell.get(t)) for t in il["any_of"])
    for t in (il.get("none_of") or []):
        ok = ok and not bool(cell.get(t))
    return ok


def test_powers_on_and_cycles():
    c = Cell(seed=1)
    assert c.state() == STOPPED
    _run_to_running(c)
    assert c.state() == RUNNING
    assert c.is_cycling() is True
    assert c.get("Safety_OK") is True
    assert c.get("Press_Cycle_Start") is True


def test_matches_healthy_snapshot():
    c = Cell(seed=2)
    _run_to_running(c)
    healthy = json.loads((_SNAP / "healthy.json").read_text())["values"]
    mismatches = {k: (want, c.get(k)) for k, want in healthy.items()
                  if bool(c.get(k)) != bool(want)}
    assert mismatches == {}


def test_guard_open_matches_snapshot_and_isolates():
    c = Cell(seed=3)
    _run_to_running(c)
    c.inject("guard_door_open")
    c.tick(0.1)
    guard = json.loads((_SNAP / "guard_door_open.json").read_text())["values"]
    mismatches = {k: (want, c.get(k)) for k, want in guard.items()
                  if bool(c.get(k)) != bool(want)}
    assert mismatches == {}
    assert c.get("Safety_OK") is False
    assert c.get("Press_Cycle_Start") is False
    assert c.get("Fault_GuardOpen") is True
    assert c.state() == FAULTED
    # everything OTHER than the safety chain stays healthy (money-shot isolation)
    assert c.get("Hydraulics_OK") is True
    assert c.get("System_Running") is True
    assert c.get("Cycle_Active") is True


@pytest.mark.parametrize("fault", CHAOS_FAULTS)
def test_every_fault_halts_and_recovers(fault):
    c = Cell(seed=4)
    _run_to_running(c)
    assert c.is_cycling() is True

    c.inject(fault)
    for _ in range(5):
        c.tick(0.1)
    assert c.is_cycling() is False, f"{fault} should stop cycling"
    assert c.state() == FAULTED

    c.clear_chaos()
    recovered = any((c.tick(0.1) or c.is_cycling()) for _ in range(40))
    assert recovered is True, f"{fault} should recover after clear+reset"


@pytest.mark.parametrize("fault,latched", [
    ("guard_door_open", "Fault_GuardOpen"),
    ("light_curtain_break", "Fault_LightCurtain"),
    ("press_overtemp", "Fault_PressOvertemp"),
    ("hydraulic_low", "Fault_HydLowPressure"),
    ("infeed_jam", "Fault_InfeedJam"),
    ("drive_fault", "Fault_DriveFault"),
])
def test_fault_latches_expected_tag(fault, latched):
    c = Cell(seed=5)
    _run_to_running(c)
    c.inject(fault)
    c.tick(0.1)
    assert c.get(latched) is True


def test_estop_drops_mode_and_master():
    c = Cell(seed=6)
    _run_to_running(c)
    c.inject("estop")
    c.tick(0.1)
    assert c.get("Estop_Active") is True
    assert c.get("Estop_Chain_OK") is False
    assert c.get("Mode_Auto") is False
    assert c.get("System_Running") is False
    assert c.get("Safety_OK") is False
    assert c.get("Press_Cycle_Start") is False


def test_overtemp_breaks_hydraulics_permissive():
    c = Cell(seed=7)
    _run_to_running(c)
    c.inject("press_overtemp")
    c.tick(0.1)
    assert c.get("Hydraulics_OK") is False
    assert c.get("Hyd_Pump_Running") is False
    assert c.get("Press_Cycle_Fault") is True
    assert c.get("Press_Cycle_Start") is False


def test_hydraulic_low_breaks_hydraulics():
    c = Cell(seed=8)
    _run_to_running(c)
    c.inject("hydraulic_low")
    c.tick(0.1)
    assert c.get("Hyd_LowPressure") is True
    assert c.get("Hydraulics_OK") is False
    assert c.get("Press_Cycle_Start") is False


def test_unknown_fault_rejected():
    c = Cell()
    with pytest.raises(ValueError):
        c.inject("not_a_real_fault")


def test_consistency_invariant_over_random_ticks():
    """PRIME DIRECTIVE: Safety_OK and Press_Cycle_Start must ALWAYS equal the
    AND/OR/NOT of their interlock condition tags -- for 200 random ticks with
    random fault injection / clearing."""
    c = Cell(seed=42)
    rng = random.Random(123)
    for i in range(200):
        c.tick(0.1)
        if rng.random() < 0.05:
            c.inject(rng.choice(CHAOS_FAULTS))
        if rng.random() < 0.05:
            c.clear_chaos()
        assert c.get("Safety_OK") == _expected_interlock(c, "Safety_OK"), \
            f"Safety_OK inconsistent at tick {i}"
        assert c.get("Press_Cycle_Start") == _expected_interlock(c, "Press_Cycle_Start"), \
            f"Press_Cycle_Start inconsistent at tick {i}"


def test_safety_ok_is_and_of_six_conditions():
    c = Cell(seed=9)
    _run_to_running(c)
    conds = ["Estop_Chain_OK", "GuardDoor_Closed", "LightCurtain_Clear",
             "SafetyRelay_CH1", "SafetyRelay_CH2", "Safety_Reset_Done"]
    assert c.get("Safety_OK") == all(c.get(x) for x in conds)
    # break one condition, invariant still holds
    c.inject("light_curtain_break")
    c.tick(0.1)
    assert c.get("Safety_OK") == all(c.get(x) for x in conds)
    assert c.get("Safety_OK") is False


def test_values_and_summary_shape():
    c = Cell(seed=10)
    _run_to_running(c)
    vals = c.values()
    from app.simulator.cell import ALL_TAGS
    assert set(vals) == set(ALL_TAGS)
    subset = c.values(["Safety_OK", "Press_Cycle_Start"])
    assert set(subset) == {"Safety_OK", "Press_Cycle_Start"}
    s = c.state_summary()
    assert s["state"] == RUNNING
    assert "key_values" in s and "Safety_OK" in s["key_values"]
    assert s["faults"] == CHAOS_FAULTS
