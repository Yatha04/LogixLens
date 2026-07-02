"""
Gate 1 regression: the diagnosis engine (src/analysis) against the generated
PressLine_3.L5X — the full "why is the machine down?" scenario.

Uses CONSISTENT live-value snapshots (what OPC UA actually reports: internal
coil values agree with the logic that computes them). Asserts the failing path
descends the full causal chain to the physical input, with citations.

Run from l5x-copilot/:
    ./.venv/bin/python ../demo_cell/gate1_diagnosis_smoke.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "l5x-copilot"))

from src.parser.project_model import parse_project
from src.analysis import build_condition_tree, evaluate_tree, failing_paths

L5X = Path(__file__).resolve().parent / "build" / "PressLine_3.L5X"
TARGET = "Press_Cycle_Start"

HEALTHY = {
    # press permissive chain (P300_Press/R30_PressCycle)
    "Mode_Auto": True, "Cycle_Active": True, "Part_Present": True,
    "Transfer_Clear": True, "Press_At_Top": True, "Hydraulics_OK": True,
    "Clamp_Closed": True, "Lube_OK": True, "Safety_OK": True,
    "Cycle_Start_PB": True, "Auto_Sequence_Run": True, "Press_Cycle_Fault": False,
    # safety chain (P900_Safety/R92_SafetyOK)
    "Estop_Chain_OK": True, "GuardDoor_Closed": True, "LightCurtain_Clear": True,
    "SafetyRelay_CH1": True, "SafetyRelay_CH2": True, "Safety_Reset_Done": True,
}
# Guard door opens; the PLC recomputes Safety_OK -> consistent faulted snapshot
FAULTED = dict(HEALTHY, GuardDoor_Closed=False, Safety_OK=False)


def main():
    project = parse_project(str(L5X))

    t = evaluate_tree(build_condition_tree(TARGET, project), HEALTHY)
    healthy_ok = t.satisfied is True and not failing_paths(t)
    print(f"healthy: root={t.satisfied} failing={len(failing_paths(t))} (want True/0)")

    t = evaluate_tree(build_condition_tree(TARGET, project), FAULTED)
    paths = failing_paths(t)
    print(f"faulted: root={t.satisfied} failing={len(paths)} (want False/1)")
    chain_ok = cites_ok = False
    for p in paths:
        tags = [n.tag for n in p if n.tag]
        cites = [n.cite for n in p if n.cite]
        leaf = p[-1]
        print("  chain:", " -> ".join(tags))
        for n in p:
            print(f"    [{n.kind:5}] {n.tag or '(rung logic)':22} cite={n.cite}")
        print("  note:", (leaf.annotation or "")[:90])
        chain_ok = (tags == ["Safety_OK", "GuardDoor_Closed"]
                    and leaf.tag == "GuardDoor_Closed")
        cites_ok = len(cites) >= 2 and any(
            c.get("routine") == "R92_SafetyOK" for c in cites)

    ok_json = bool(json.dumps(t.to_dict()))
    verdict = healthy_ok and len(paths) == 1 and chain_ok and cites_ok and ok_json
    print("GATE 1:", "PASS" if verdict else "FAIL")
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
