// Real captured payload for P300_Press / R30_PressCycle rung 9 — the press
// cycle-start permissive. Used by unit + component tests so the energization
// logic is verified against the exact structure the backend emits.
// (Captured via app/backend/rung_json.py rung_payload.)

import type { RungElement, ValueMap } from "./types";

export const RUNG9_ELEMENTS: RungElement[] = [
  { type: "instruction", mnemonic: "XIC", category: "bit_io", is_condition: true, operands: [{ value: "Mode_Auto", is_literal: false }] },
  { type: "instruction", mnemonic: "XIC", category: "bit_io", is_condition: true, operands: [{ value: "Cycle_Active", is_literal: false }] },
  { type: "instruction", mnemonic: "XIC", category: "bit_io", is_condition: true, operands: [{ value: "Part_Present", is_literal: false }] },
  { type: "instruction", mnemonic: "XIC", category: "bit_io", is_condition: true, operands: [{ value: "Transfer_Clear", is_literal: false }] },
  { type: "instruction", mnemonic: "XIC", category: "bit_io", is_condition: true, operands: [{ value: "Press_At_Top", is_literal: false }] },
  { type: "instruction", mnemonic: "XIC", category: "bit_io", is_condition: true, operands: [{ value: "Hydraulics_OK", is_literal: false }] },
  { type: "instruction", mnemonic: "XIC", category: "bit_io", is_condition: true, operands: [{ value: "Clamp_Closed", is_literal: false }] },
  { type: "instruction", mnemonic: "XIC", category: "bit_io", is_condition: true, operands: [{ value: "Lube_OK", is_literal: false }] },
  { type: "instruction", mnemonic: "XIC", category: "bit_io", is_condition: true, operands: [{ value: "Safety_OK", is_literal: false }] },
  {
    type: "branch",
    legs: [
      [{ type: "instruction", mnemonic: "XIC", category: "bit_io", is_condition: true, operands: [{ value: "Cycle_Start_PB", is_literal: false }] }],
      [{ type: "instruction", mnemonic: "XIC", category: "bit_io", is_condition: true, operands: [{ value: "Auto_Sequence_Run", is_literal: false }] }],
    ],
  },
  { type: "instruction", mnemonic: "XIO", category: "bit_io", is_condition: true, operands: [{ value: "Press_Cycle_Fault", is_literal: false }] },
  { type: "instruction", mnemonic: "OTE", category: "bit_io", is_condition: false, operands: [{ value: "Press_Cycle_Start", is_literal: false }] },
];

export const RUNG9_GUARD_VALUES: ValueMap = {
  Mode_Auto: true,
  Cycle_Active: true,
  Part_Present: true,
  Transfer_Clear: true,
  Press_At_Top: true,
  Hydraulics_OK: true,
  Clamp_Closed: true,
  Lube_OK: true,
  Safety_OK: false,
  Cycle_Start_PB: true,
  Auto_Sequence_Run: true,
  Press_Cycle_Fault: false,
};

export const RUNG9_HEALTHY_VALUES: ValueMap = {
  Mode_Auto: true,
  Cycle_Active: true,
  Part_Present: true,
  Transfer_Clear: true,
  Press_At_Top: true,
  Hydraulics_OK: true,
  Clamp_Closed: true,
  Lube_OK: true,
  Safety_OK: true,
  Cycle_Start_PB: true,
  Auto_Sequence_Run: true,
  Press_Cycle_Fault: false,
};
