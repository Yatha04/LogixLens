"""
gate4_live_smoke.py -- the Stage-4 live end-to-end gate (fully automated).

Reproduces the Gate-1 diagnosis flow, but over a *live OPC UA connection* to the
running PressLine_3 simulator instead of a static JSON snapshot:

  1. start the simulator as a subprocess,
  2. wait (condition-based, timed) for a healthy cycling machine,
  3. build a PLCToolbox with an OpcUaProvider and assert trace_blockers(
     "Press_Cycle_Start") has 0 failing paths (root satisfied),
  4. POST /chaos guard_door_open, wait for the cascade, and assert the failing
     path is EXACTLY Safety_OK -> GuardDoor_Closed with the field-input note,
  5. POST /chaos/clear (clear + reset handshake), wait for recovery, assert the
     trace is satisfied again,
  6. shut the simulator down cleanly.

Run from the repo root:
    ./l5x-copilot/.venv/bin/python -m app.simulator.gate4_live_smoke
or:
    ./l5x-copilot/.venv/bin/python app/simulator/gate4_live_smoke.py

Prints PASS/FAIL and exits 0/1 accordingly. All waits are condition-based with
timeouts -- no bare sleeps -- so it is safe to run repeatedly.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
L5X = _REPO_ROOT / "demo_cell" / "build" / "PressLine_3.L5X"

OPC_PORT = 4841
HTTP_PORT = 8091
OPC_ENDPOINT = f"opc.tcp://127.0.0.1:{OPC_PORT}/pressline3/"
HTTP_BASE = f"http://127.0.0.1:{HTTP_PORT}"

# make `app.backend...` importable
sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------- HTTP helpers
def _get(path: str, timeout: float = 3.0):
    with urllib.request.urlopen(HTTP_BASE + path, timeout=timeout) as r:
        return json.load(r)


def _post(path: str, body=None, timeout: float = 3.0):
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(
        HTTP_BASE + path, data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _wait(predicate, deadline_s: float, poll_s: float = 0.15, label: str = ""):
    """Poll `predicate()` (bool) until True or the deadline; returns success."""
    end = time.time() + deadline_s
    last = None
    while time.time() < end:
        try:
            last = predicate()
            if last:
                return True
        except (urllib.error.URLError, ConnectionError, OSError, ValueError):
            pass
        time.sleep(poll_s)
    if label:
        print(f"  [timeout] waiting for: {label}")
    return False


def _guard_chain_ok(result: dict) -> bool:
    """True iff the trace shows exactly Safety_OK -> GuardDoor_Closed failing."""
    if result.get("root_satisfied") is not False:
        return False
    paths = result.get("failing_paths", [])
    if len(paths) != 1:
        return False
    p = paths[0]
    if p.get("chain") != ["Safety_OK", "GuardDoor_Closed"]:
        return False
    if p.get("leaf_tag") != "GuardDoor_Closed":
        return False
    annot = (p.get("leaf_annotation") or "").lower()
    return "field input" in annot


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool):
        checks.append((name, bool(ok)))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    proc = subprocess.Popen(
        [sys.executable, "-m", "app.simulator",
         "--port", str(OPC_PORT), "--http-port", str(HTTP_PORT)],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    from app.backend.plc_tools import PLCToolbox, OpcUaProvider  # noqa: E402
    prov = OpcUaProvider(OPC_ENDPOINT)

    try:
        # 1) simulator up + cycling
        up = _wait(lambda: _get("/health").get("ok"), 15.0, label="HTTP API up")
        check("simulator HTTP API responds", up)
        cycling = _wait(lambda: _get("/state").get("cycling"), 15.0,
                        label="healthy cycling state")
        check("machine reaches healthy RUNNING/cycling state", cycling)

        # 2) OPC UA client connects
        connected = _wait(prov.available, 10.0, label="OPC UA connect")
        check("OpcUaProvider connects to live server", connected)

        tb = PLCToolbox(str(L5X), live_provider=prov)

        # 3) healthy trace -> 0 failing paths
        healthy_ok = _wait(
            lambda: tb.trace_blockers("Press_Cycle_Start").get("root_satisfied") is True,
            10.0, label="healthy trace satisfied")
        rh = tb.trace_blockers("Press_Cycle_Start")
        check("healthy: live trace source is OPC UA", rh.get("live_source") == "opcua")
        check("healthy: Press_Cycle_Start root satisfied", rh.get("root_satisfied") is True)
        check("healthy: 0 failing paths", rh.get("failing_count") == 0 and healthy_ok)

        # 4) inject guard_door_open -> cascade -> exact money-shot chain
        resp = _post("/chaos", {"fault": "guard_door_open"})
        check("chaos guard_door_open accepted", resp.get("active_fault") == "guard_door_open")
        cascaded = _wait(
            lambda: _guard_chain_ok(tb.trace_blockers("Press_Cycle_Start")),
            10.0, label="guard-open cascade in trace")
        rg = tb.trace_blockers("Press_Cycle_Start")
        check("guard: root NOT satisfied", rg.get("root_satisfied") is False)
        check("guard: exactly Safety_OK -> GuardDoor_Closed failing chain",
              cascaded and _guard_chain_ok(rg))
        # latched fault present over the live link
        gv = prov.get_values(["Fault_GuardOpen", "Safety_OK", "GuardDoor_Closed"])
        check("guard: Fault_GuardOpen latched (live)", gv.get("Fault_GuardOpen") is True)
        check("guard: Safety_OK=False and GuardDoor_Closed=False (live)",
              gv.get("Safety_OK") is False and gv.get("GuardDoor_Closed") is False)

        # 5) clear + reset -> recovery
        _post("/chaos/clear")
        recovered = _wait(
            lambda: (_get("/state").get("cycling") is True
                     and tb.trace_blockers("Press_Cycle_Start").get("root_satisfied") is True),
            15.0, label="recovery to cycling + satisfied trace")
        rr = tb.trace_blockers("Press_Cycle_Start")
        check("recovery: root satisfied again", rr.get("root_satisfied") is True)
        check("recovery: 0 failing paths", rr.get("failing_count") == 0 and recovered)

    except Exception as exc:  # noqa: BLE001
        check(f"no unexpected exception ({exc!r})", False)
    finally:
        try:
            prov.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    passed = all(ok for _, ok in checks)
    print()
    print(f"GATE 4: {'PASS' if passed else 'FAIL'} "
          f"({sum(ok for _, ok in checks)}/{len(checks)} checks)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
