# PressLine_3 -- demo PLC program for "Ask the PLC"

A fictional but Studio-5000-plausible Rockwell **CompactLogix** cell, generated from a
declarative YAML spec. It exists to be *debugged by an AI*: the file is deliberately
rich in real controls idioms and carries a clean, traceable interlock chain for the
flagship live-diagnosis demo.

The real (proprietary) customer L5X files can never ship, so this stands in for them.

## Files

| File | Role |
|---|---|
| `pressline3.yaml` | **Single source of truth.** Stations, devices, sensors, faults, interlocks, tags, AOIs, UDTs, and ladder/ST logic -- all as data. A future asyncio simulator is meant to consume the *same* file, guaranteeing program-vs-simulation consistency. |
| `generate_l5x.py` | Reads the YAML, emits `build/PressLine_3.L5X`. Compiles the `interlocks:` section into ladder rungs so the money-shot permissive chain is generated, not hand-copied. |
| `verify_scenario.py` | Regression test for the diagnostic chain (see below). Exit 0 = intact. |
| `build/PressLine_3.L5X` | Generated output. **Gitignored repo-wide (`*.L5X`)** -- the generator is the committed artifact, not the file. |

## Regenerate

```bash
# from this directory
../l5x-copilot/.venv/bin/python generate_l5x.py          # writes build/PressLine_3.L5X
../l5x-copilot/.venv/bin/python verify_scenario.py       # asserts the money-shot chain
```

Requires PyYAML in the venv: `../l5x-copilot/.venv/bin/python -m pip install pyyaml`.

## Verify against the parser

```bash
cd ../l5x-copilot
./.venv/bin/python -c "from src.parser.project_model import parse_project; print(parse_project('../demo_cell/build/PressLine_3.L5X').summary())"
./.venv/bin/python -m pytest tests/ --l5x-file ../demo_cell/build/PressLine_3.L5X -q
```

## The money-shot chain

`verify_scenario.py` asserts a backward trace from a gated output to a physical input:

```
Press_Cycle_Start   (OTE, ~11-condition permissive in P300_Press / R30_PressCycle)
  --reads--> Safety_OK        (OTE in P900_Safety / R92_SafetyOK)
    --reads--> GuardDoor_Closed   (alias -> Safety_In:1:I.Data.4, a physical input leaf)
```

Two hops, well within the demo's <=3 requirement. Break either interlock in
`pressline3.yaml` and the verifier fails.

## Cell layout

infeed conveyor -> transfer arm (pick/place) -> hydraulic press (guard door +
light curtain + dual-channel E-stop) -> outfeed conveyor with reject gate.

Programs: `MainProgram` (mode + master seal-in), `P100_Infeed`, `P200_Transfer`,
`P300_Press`, `P400_Outfeed`, `P900_Safety`. Each has a `MainRoutine` that JSRs to
its subroutines. AOIs: `FB_VALVE`, `FB_MOTOR_STARTER`, `FB_CYLINDER`, `FB_DEBOUNCE`.
UDTs: `ALARM_TYPE`, `udtStation`, `udtRecipe`.
