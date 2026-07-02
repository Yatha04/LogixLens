"""
cell.py -- the pure, synchronous PressLine_3 cell state machine.

This is the beating heart of the Stage-4 live simulator. It owns the full tag
state of the cell and advances it on a fixed tick (~10 Hz). It has **no** OPC UA
or HTTP dependency, so the state-machine logic (transitions, fault cascades,
consistency invariants) is unit-testable on its own.

CONSISTENCY IS THE PRIME DIRECTIVE
----------------------------------
The two permissive coils that the diagnosis engine traces -- ``Safety_OK`` and
``Press_Cycle_Start`` -- are **not** hand-written here. They are evaluated from
the *same* ``interlocks:`` block of ``demo_cell/pressline3.yaml`` that
``generate_l5x.py`` compiles into ladder (all_of -> series XIC, any_of ->
parallel branch, none_of -> series XIO). Because both the L5X and the simulator
derive these coils from one source of truth, the live values published over OPC
UA can never disagree with the ladder the diagnosis engine reads. See
:meth:`Cell._eval_interlock`.

Everything the healthy snapshot (``app/backend/snapshots/healthy.json``) asserts
holds on a healthy running machine, and each chaos fault reproduces the PLC
cascade the ladder would compute (e.g. guard door open -> ``Safety_OK`` false ->
``Press_Cycle_Start`` false, with ``Fault_GuardOpen`` latched).
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List, Optional

import yaml

# Repo layout: app/simulator/cell.py -> parents[2] == repo root (LogixLens/)
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = _REPO_ROOT / "demo_cell" / "pressline3.yaml"

# Shared with the OPC UA server AND the OpcUaProvider client (kept in sync by
# documentation -- the provider hard-codes the same URI to avoid importing the
# simulator into the backend package).
NAMESPACE_URI = "urn:logixlens:pressline3"
ROOT_FOLDER = "PressLine_3"

# Hydraulic pressure band (the YAML marks the limit tags `constant` but leaves
# the values to the runtime; these are the demo-cell design values).
HYD_LOW_LIMIT = 1200.0
HYD_HIGH_LIMIT = 2600.0
HYD_SETPOINT = 1800.0          # recipe 1
HYD_LOW_FAULT_PRESSURE = 750.0  # what "hydraulic_low" drives the pressure to

# The chaos fault vocabulary the HTTP API accepts (Stage-4 spec).
CHAOS_FAULTS = [
    "guard_door_open",
    "light_curtain_break",
    "estop",
    "infeed_jam",
    "press_overtemp",
    "drive_fault",
    "hydraulic_low",
]

# ---------------------------------------------------------------------------
# Published tag catalogue: name -> OPC UA scalar type.
# NodeId string identifier == tag name (documented, simple, 1:1 with the L5X).
# ---------------------------------------------------------------------------
BOOL_TAGS = [
    # --- Press permissive chain (Press_Cycle_Start) --------------------------
    "Mode_Auto", "Cycle_Active", "Part_Present", "Transfer_Clear",
    "Press_At_Top", "Hydraulics_OK", "Clamp_Closed", "Lube_OK", "Safety_OK",
    "Cycle_Start_PB", "Auto_Sequence_Run", "Press_Cycle_Fault",
    # --- Master safety chain (Safety_OK) -------------------------------------
    "Estop_Chain_OK", "GuardDoor_Closed", "LightCurtain_Clear",
    "SafetyRelay_CH1", "SafetyRelay_CH2", "Safety_Reset_Done",
    # --- Master / mode -------------------------------------------------------
    "Estop_Active", "System_Running", "Press_Cycle_Start", "Press_Cycle_Active",
    # --- Latched faults ------------------------------------------------------
    "Fault_InfeedJam", "Fault_PressOvertemp", "Fault_HydLowPressure",
    "Fault_DriveFault", "Fault_GuardOpen", "Fault_LightCurtain",
    "Fault_TransferTimeout",
    # --- Physical / field inputs (chaos actuates these) ----------------------
    "Estop_PB1", "Estop_PB2", "Master_Stop_PB", "Safety_Reset_PB", "Reset_PB",
    "Press_Overtemp", "Drive_Fault_In", "Drive_Ready",
    "Hyd_Pump_Running", "PartPresent_Eye1",
    "TransferArm_Extended", "TransferArm_Retracted", "Part_At_Outfeed",
    # --- Derived detections / station readies --------------------------------
    "Guard_Open_Detected", "LightCurtain_Broken", "Infeed_Jam_Detected",
    "Hyd_LowPressure", "Infeed_Running", "Infeed_Ready", "Outfeed_Ready",
]

INT_TAGS = [
    "Press_Step", "Seq_Step", "Good_Part_Total", "Reject_Total",
    "HMI_Heartbeat", "Recipe_Number",
]

FLOAT_TAGS = [
    "Hyd_Pressure", "Hyd_Pressure_SP", "Hyd_Pressure_LowLimit",
    "Hyd_Pressure_HighLimit", "Press_Tonnage", "Infeed_Speed", "Drive_Speed_Ref",
]

ALL_TAGS = BOOL_TAGS + INT_TAGS + FLOAT_TAGS


def tag_type(name: str) -> str:
    """Return 'bool' | 'int' | 'float' for a published tag."""
    if name in _BOOL_SET:
        return "bool"
    if name in _INT_SET:
        return "int"
    return "float"


_BOOL_SET = set(BOOL_TAGS)
_INT_SET = set(INT_TAGS)
_FLOAT_SET = set(FLOAT_TAGS)

# States
STOPPED = "STOPPED"
STARTING = "STARTING"
RUNNING = "RUNNING"
FAULTED = "FAULTED"

_START_DELAY = 0.3   # s before the cell powers on
_STARTING_TIME = 0.8  # s spent in STARTING before RUNNING
_CYCLE_TIME = 3.0     # s per (cosmetic) press cycle


class Cell:
    """The PressLine_3 cell as a pure, tickable state machine."""

    def __init__(self, spec_path: Optional[str | Path] = None, seed: int = 0):
        with open(spec_path or DEFAULT_SPEC, "r", encoding="utf-8") as fh:
            self.spec = yaml.safe_load(fh)
        self.interlocks = self.spec.get("interlocks", {})
        self._rng = random.Random(seed)

        self.t = 0.0
        self._started = False
        self._cycle_latched = False
        self._phase = 0.0
        self._good = 0
        self._reject = 0
        self._heartbeat = 0
        self._hb_accum = 0.0
        self.active_fault: Optional[str] = None

        # published tag store
        self.v: Dict[str, object] = {}
        self._init_values()

    # ------------------------------------------------------------------ setup
    def _init_values(self) -> None:
        # physical inputs -- healthy defaults
        self.v.update({
            "Estop_PB1": True, "Estop_PB2": True,
            # Master_Stop_PB is a normally-closed stop button: True == not
            # pressed. The sim never presses it, so it stays True (the R02
            # master seal-in reads it, and healthy.json asserts it True).
            "Master_Stop_PB": True,
            "GuardDoor_Closed": True, "LightCurtain_Clear": True,
            "SafetyRelay_CH1": True, "SafetyRelay_CH2": True,
            "Safety_Reset_PB": False, "Reset_PB": False,
            "Press_Overtemp": False, "Drive_Fault_In": False, "Drive_Ready": True,
            "PartPresent_Eye1": True,
            "TransferArm_Extended": False, "TransferArm_Retracted": True,
            "Part_At_Outfeed": False,
        })
        # latched faults
        for f in ("Fault_InfeedJam", "Fault_PressOvertemp", "Fault_HydLowPressure",
                  "Fault_DriveFault", "Fault_GuardOpen", "Fault_LightCurtain",
                  "Fault_TransferTimeout"):
            self.v[f] = False
        # handshake latch (armed once reset; drops on E-stop)
        self._safety_reset_done = False
        self._hyd_low_inject = False
        self._infeed_jam_inject = False
        # constants / setpoints
        self.v["Hyd_Pressure_LowLimit"] = HYD_LOW_LIMIT
        self.v["Hyd_Pressure_HighLimit"] = HYD_HIGH_LIMIT
        self.v["Hyd_Pressure_SP"] = HYD_SETPOINT
        self.v["Recipe_Number"] = 1
        self.v["Infeed_Speed"] = 250.0
        self.v["Drive_Speed_Ref"] = 45.0
        self.v["Hyd_Pressure"] = HYD_SETPOINT
        self.v["Press_Tonnage"] = HYD_SETPOINT * 0.0075
        self.v["Good_Part_Total"] = 0
        self.v["Reject_Total"] = 0
        self.v["HMI_Heartbeat"] = 0
        self.v["Press_Step"] = 0
        self.v["Seq_Step"] = 0
        # compute the rest of the derived tags for a coherent power-on snapshot
        self._recompute(0.0)

    def get(self, name: str) -> object:
        return self.v.get(name)

    # -------------------------------------------------------------- interlocks
    def _eval_interlock(self, name: str) -> bool:
        """Evaluate a YAML interlock exactly as generate_l5x.compile_interlock
        renders it: all_of (series XIC) AND any_of (parallel branch) AND
        none_of (series XIO)."""
        il = self.interlocks[name]
        ok = all(bool(self.v.get(t)) for t in (il.get("all_of") or []))
        if il.get("any_of"):
            ok = ok and any(bool(self.v.get(t)) for t in il["any_of"])
        for t in (il.get("none_of") or []):
            ok = ok and not bool(self.v.get(t))
        return ok

    # -------------------------------------------------------------- the tick
    def tick(self, dt: float = 0.1) -> None:
        self.t += dt
        # power-on / auto reset
        if not self._started and self.t >= _START_DELAY:
            self._started = True
            self._do_reset()
        self._recompute(dt)
        self._advance_production(dt)

    def _recompute(self, dt: float) -> None:
        v = self.v

        # -- E-stop chain (R90) ---------------------------------------------
        v["Estop_Active"] = (not v["Estop_PB1"]) or (not v["Estop_PB2"])
        v["Estop_Chain_OK"] = bool(v["Estop_PB1"]) and bool(v["Estop_PB2"]) and not v["Estop_Active"]
        # A hard E-stop trip disarms the reset handshake (must re-arm on reset).
        if v["Estop_Active"]:
            self._safety_reset_done = False
        v["Safety_Reset_Done"] = self._safety_reset_done and self._started

        # -- Master safety OK (YAML interlock == R92 ladder) ----------------
        v["Safety_OK"] = self._eval_interlock("Safety_OK")

        # -- Mode + master seal-in (R01 / R02) ------------------------------
        # A guard / light-curtain trip drops Safety_OK (and halts the cycle) but
        # the master contactor + hydraulic pump are modelled as retentive, so the
        # diagnosis isolates cleanly to the safety chain -- exactly the shipped
        # consistent-values snapshots (guard_door_open.json keeps System_Running,
        # Hydraulics_OK, Cycle_Start_PB True). Only a hard E-stop drops the master.
        v["Mode_Auto"] = self._started and (not v["Estop_Active"])
        v["System_Running"] = self._started and (not v["Estop_Active"])
        # Cycle latch: arm once running in auto; retentive through safety trips
        # (matches guard_door_open.json, which keeps Cycle_Active True), dropped
        # only on a full stop.
        if v["System_Running"] and v["Mode_Auto"]:
            self._cycle_latched = True
        if not self._started:
            self._cycle_latched = False
        v["Cycle_Active"] = self._cycle_latched

        # -- Safety-fault detections + latches (R91) ------------------------
        v["Guard_Open_Detected"] = (not v["GuardDoor_Closed"]) and v["Cycle_Active"]
        if v["Guard_Open_Detected"]:
            v["Fault_GuardOpen"] = True
        v["LightCurtain_Broken"] = (not v["LightCurtain_Clear"]) and v["Cycle_Active"]
        if v["LightCurtain_Broken"]:
            v["Fault_LightCurtain"] = True

        # -- Overtemp latch (R31) -------------------------------------------
        if v["Press_Overtemp"]:
            v["Fault_PressOvertemp"] = True

        # -- Hydraulics (R31): pump, pressure, low-pressure latch -----------
        v["Hyd_Pump_Running"] = (v["System_Running"] and v["Mode_Auto"]
                                 and not v["Fault_PressOvertemp"])
        if self._hyd_low_inject:
            v["Hyd_Pressure"] = HYD_LOW_FAULT_PRESSURE
        v["Hyd_LowPressure"] = bool(v["Hyd_Pump_Running"]) and (
            float(v["Hyd_Pressure"]) < HYD_LOW_LIMIT)
        if v["Hyd_LowPressure"]:
            v["Fault_HydLowPressure"] = True
        v["Hydraulics_OK"] = (
            bool(v["Hyd_Pump_Running"])
            and HYD_LOW_LIMIT < float(v["Hyd_Pressure"]) < HYD_HIGH_LIMIT
            and not v["Fault_PressOvertemp"]
        )

        # -- Infeed jam (R10) -----------------------------------------------
        v["Infeed_Jam_Detected"] = self._infeed_jam_inject
        if v["Infeed_Jam_Detected"]:
            v["Fault_InfeedJam"] = True
        v["Infeed_Running"] = (v["System_Running"] and v["Mode_Auto"]
                               and not v["Fault_InfeedJam"])
        v["Infeed_Ready"] = bool(v["PartPresent_Eye1"]) and not v["Fault_InfeedJam"]

        # -- Drive fault (R40) ----------------------------------------------
        if v["Drive_Fault_In"]:
            v["Fault_DriveFault"] = True
        v["Outfeed_Ready"] = bool(v["Drive_Ready"]) and not v["Fault_DriveFault"]

        # -- Press permissive inputs (ready-to-cycle pose while healthy) ----
        v["Part_Present"] = bool(v["PartPresent_Eye1"])
        v["Transfer_Clear"] = bool(v["TransferArm_Retracted"]) and not v["Fault_TransferTimeout"]
        v["Press_At_Top"] = True
        v["Clamp_Closed"] = self._started and not v["Fault_PressOvertemp"]
        v["Lube_OK"] = self._started
        v["Auto_Sequence_Run"] = bool(v["Cycle_Active"])
        # Cycle_Start_PB is held during a healthy run so the any_of branch is
        # satisfied without relying on a momentary PB edge (matches healthy.json).
        v["Cycle_Start_PB"] = v["System_Running"] and v["Mode_Auto"]
        v["Press_Cycle_Fault"] = bool(v["Fault_PressOvertemp"]) or bool(v["Fault_HydLowPressure"])

        # -- The money-shot permissive (YAML interlock == R30 ladder) -------
        v["Press_Cycle_Start"] = self._eval_interlock("Press_Cycle_Start")

    def _advance_production(self, dt: float) -> None:
        """Cosmetic cycle animation on top of the (stable) permissive chain.

        Runs only while genuinely cycling; never perturbs the safety/permissive
        tags. Drives Press_Step / Press_Cycle_Active / analog readings / counters.
        """
        v = self.v
        self._hb_accum += dt
        while self._hb_accum >= 1.0:
            self._hb_accum -= 1.0
            self._heartbeat += 1
            v["HMI_Heartbeat"] = self._heartbeat

        if not self.is_cycling():
            v["Press_Cycle_Active"] = False
            v["Press_Step"] = 0
            if not self._hyd_low_inject:
                v["Hyd_Pressure"] = HYD_SETPOINT
            v["Press_Tonnage"] = 0.0
            return

        prev = self._phase
        self._phase = (self._phase + dt / _CYCLE_TIME) % 1.0
        wrapped = self._phase < prev

        # phase 0.0-0.15 stage, 0.15-0.55 stroke down, 0.55-0.75 dwell, 0.75-1 return
        p = self._phase
        if p < 0.15:
            step, active, tons = 0, False, 0.0
        elif p < 0.55:
            step, active, tons = 10, True, HYD_SETPOINT * 0.0075
        elif p < 0.75:
            step, active, tons = 20, True, HYD_SETPOINT * 0.0075
        else:
            step, active, tons = 30, True, HYD_SETPOINT * 0.0075 * 0.4
        v["Press_Step"] = step
        v["Press_Cycle_Active"] = active
        v["Seq_Step"] = step

        # hydraulic pressure: setpoint + small correlated noise during stroke
        noise = self._rng.uniform(-15.0, 15.0)
        base = HYD_SETPOINT + (60.0 if active else 0.0)
        if not self._hyd_low_inject:
            v["Hyd_Pressure"] = round(base + noise, 1)
        v["Press_Tonnage"] = round(tons + self._rng.uniform(-0.2, 0.2), 2)
        v["Drive_Speed_Ref"] = round(45.0 + self._rng.uniform(-0.5, 0.5), 2)

        # count a good/reject part each completed cycle
        if wrapped:
            if self._rng.random() < 0.08:
                self._reject += 1
                v["Reject_Total"] = self._reject
            else:
                self._good += 1
                v["Good_Part_Total"] = self._good
            v["Part_At_Outfeed"] = True
        else:
            v["Part_At_Outfeed"] = False

    # -------------------------------------------------------------- observers
    def any_fault(self) -> bool:
        return any(bool(self.v[f]) for f in (
            "Fault_InfeedJam", "Fault_PressOvertemp", "Fault_HydLowPressure",
            "Fault_DriveFault", "Fault_GuardOpen", "Fault_LightCurtain",
            "Fault_TransferTimeout")) or not bool(self.v["Safety_OK"]) \
            or bool(self.v["Estop_Active"])

    def state(self) -> str:
        if not self._started:
            return STOPPED
        if self.any_fault():
            return FAULTED
        if self.t < _START_DELAY + _STARTING_TIME:
            return STARTING
        return RUNNING

    def is_cycling(self) -> bool:
        """Healthy, running, permissive satisfied -- the state the gate waits for."""
        return (self.state() == RUNNING
                and bool(self.v["Cycle_Active"])
                and bool(self.v["Safety_OK"])
                and bool(self.v["Press_Cycle_Start"])
                and not self.any_fault())

    # -------------------------------------------------------------- chaos API
    def inject(self, fault: str) -> None:
        if fault not in CHAOS_FAULTS:
            raise ValueError(f"unknown fault {fault!r}; valid: {CHAOS_FAULTS}")
        self.active_fault = fault
        v = self.v
        if fault == "guard_door_open":
            v["GuardDoor_Closed"] = False
        elif fault == "light_curtain_break":
            v["LightCurtain_Clear"] = False
        elif fault == "estop":
            v["Estop_PB1"] = False
            v["Estop_PB2"] = False
        elif fault == "infeed_jam":
            self._infeed_jam_inject = True
        elif fault == "press_overtemp":
            v["Press_Overtemp"] = True
        elif fault == "drive_fault":
            v["Drive_Fault_In"] = True
        elif fault == "hydraulic_low":
            self._hyd_low_inject = True
        self._recompute(0.0)

    def clear_chaos(self) -> None:
        """Remove the physical cause AND run the reset handshake -> recover."""
        v = self.v
        v["GuardDoor_Closed"] = True
        v["LightCurtain_Clear"] = True
        v["Estop_PB1"] = True
        v["Estop_PB2"] = True
        v["Press_Overtemp"] = False
        v["Drive_Fault_In"] = False
        self._hyd_low_inject = False
        self._infeed_jam_inject = False
        v["Hyd_Pressure"] = HYD_SETPOINT
        self.active_fault = None
        self._do_reset()
        self._recompute(0.0)

    def _do_reset(self) -> None:
        """Reset_PB + Safety_Reset_PB pulse: unlatch faults, re-arm safety."""
        v = self.v
        # only clears if the physical cause is gone (mirrors the ladder resets)
        if v["GuardDoor_Closed"]:
            v["Fault_GuardOpen"] = False
        if v["LightCurtain_Clear"]:
            v["Fault_LightCurtain"] = False
        if not v["Press_Overtemp"]:
            v["Fault_PressOvertemp"] = False
        if not self._hyd_low_inject:
            v["Fault_HydLowPressure"] = False
        if not v["Drive_Fault_In"]:
            v["Fault_DriveFault"] = False
        if not self._infeed_jam_inject:
            v["Fault_InfeedJam"] = False
        v["Fault_TransferTimeout"] = False
        # re-arm the safety reset handshake if the chain is physically healthy
        chain_ok = (v["Estop_PB1"] and v["Estop_PB2"] and v["GuardDoor_Closed"]
                    and v["LightCurtain_Clear"] and v["SafetyRelay_CH1"]
                    and v["SafetyRelay_CH2"])
        if chain_ok:
            self._safety_reset_done = True
        if self._started:
            self._cycle_latched = True

    # -------------------------------------------------------------- snapshots
    def values(self, tags: Optional[List[str]] = None) -> Dict[str, object]:
        if tags is None:
            return {k: self.v[k] for k in ALL_TAGS}
        want = {t.lower() for t in tags}
        return {k: self.v[k] for k in ALL_TAGS if k.lower() in want}

    def state_summary(self) -> Dict[str, object]:
        """Compact /state payload for the chaos API and the live dashboard."""
        v = self.v
        return {
            "state": self.state(),
            "cycling": self.is_cycling(),
            "active_fault": self.active_fault,
            "elapsed_s": round(self.t, 1),
            "good_parts": self._good,
            "reject_parts": self._reject,
            "press_step": v["Press_Step"],
            "key_values": {
                "Safety_OK": v["Safety_OK"],
                "Press_Cycle_Start": v["Press_Cycle_Start"],
                "System_Running": v["System_Running"],
                "Cycle_Active": v["Cycle_Active"],
                "Estop_Active": v["Estop_Active"],
                "GuardDoor_Closed": v["GuardDoor_Closed"],
                "LightCurtain_Clear": v["LightCurtain_Clear"],
                "Hydraulics_OK": v["Hydraulics_OK"],
                "Hyd_Pressure": v["Hyd_Pressure"],
                "Press_Tonnage": v["Press_Tonnage"],
                "Fault_GuardOpen": v["Fault_GuardOpen"],
                "Fault_PressOvertemp": v["Fault_PressOvertemp"],
                "Fault_HydLowPressure": v["Fault_HydLowPressure"],
                "Fault_DriveFault": v["Fault_DriveFault"],
                "Fault_InfeedJam": v["Fault_InfeedJam"],
                "Fault_LightCurtain": v["Fault_LightCurtain"],
            },
            "faults": CHAOS_FAULTS,
        }
