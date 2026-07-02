import { describe, it, expect } from "vitest";
import {
  and3,
  or3,
  classifyRung,
  energizeRung,
  energizeChain,
} from "./powerflow";
import type { RungElement, ValueMap } from "./types";
import {
  RUNG9_ELEMENTS,
  RUNG9_GUARD_VALUES,
  RUNG9_HEALTHY_VALUES,
} from "./fixtures";

// ── Element constructors for readable tests ─────────────────────────────
const xic = (tag: string): RungElement => ({
  type: "instruction",
  mnemonic: "XIC",
  category: "bit_io",
  is_condition: true,
  operands: [{ value: tag, is_literal: false }],
});
const xio = (tag: string): RungElement => ({
  type: "instruction",
  mnemonic: "XIO",
  category: "bit_io",
  is_condition: true,
  operands: [{ value: tag, is_literal: false }],
});
const ote = (tag: string): RungElement => ({
  type: "instruction",
  mnemonic: "OTE",
  category: "bit_io",
  is_condition: false,
  operands: [{ value: tag, is_literal: false }],
});
const geq = (a: string, b: string): RungElement => ({
  type: "instruction",
  mnemonic: "GEQ",
  category: "compare",
  is_condition: true,
  operands: [
    { value: a, is_literal: false },
    { value: b, is_literal: /^-?\d/.test(b) },
  ],
});
const branch = (...legs: RungElement[][]): RungElement => ({ type: "branch", legs });

describe("tri-state algebra", () => {
  it("AND: any false short-circuits, unknown otherwise dominates true", () => {
    expect(and3(true, true)).toBe(true);
    expect(and3(true, false)).toBe(false);
    expect(and3(null, false)).toBe(false);
    expect(and3(true, null)).toBe(null);
  });
  it("OR: any true short-circuits, unknown otherwise dominates false", () => {
    expect(or3(false, false)).toBe(false);
    expect(or3(false, true)).toBe(true);
    expect(or3(null, true)).toBe(true);
    expect(or3(false, null)).toBe(null);
  });
});

describe("series chain", () => {
  const rung = [xic("A"), xic("B"), ote("Out")];
  it("conducts when every contact is true", () => {
    expect(classifyRung(rung, { A: true, B: true })).toBe("conducting");
  });
  it("blocks when any contact is false", () => {
    expect(classifyRung(rung, { A: true, B: false })).toBe("blocked");
  });
  it("is indeterminate when a contact is unknown and nothing forces false", () => {
    expect(classifyRung(rung, { A: true })).toBe("indeterminate");
  });
  it("cuts the wire at the first blocking contact", () => {
    const { chain } = energizeRung(rung, { A: false, B: true });
    // A blocks -> powerAfter false; B never sees power; coil de-energized.
    expect((chain.items[0] as any).state).toBe(false);
    expect((chain.items[1] as any).powerBefore).toBe(false);
    expect((chain.items[2] as any).powerBefore).toBe(false); // coil
  });
});

describe("parallel branch (OR)", () => {
  const rung = [branch([xic("A")], [xic("B")]), ote("Out")];
  it("conducts if any leg conducts", () => {
    expect(classifyRung(rung, { A: false, B: true })).toBe("conducting");
    expect(classifyRung(rung, { A: true, B: false })).toBe("conducting");
  });
  it("blocks only when every leg blocks", () => {
    expect(classifyRung(rung, { A: false, B: false })).toBe("blocked");
  });
  it("a known-true leg wins over an unknown leg (OR short-circuit)", () => {
    expect(classifyRung(rung, { B: true })).toBe("conducting");
  });
  it("is indeterminate when the only non-false leg is unknown", () => {
    expect(classifyRung(rung, { A: false })).toBe("indeterminate");
  });
});

describe("nested branch inside a branch leg", () => {
  // [ A AND [B, C] , D ] -> Out
  const rung = [
    branch([xic("A"), branch([xic("B")], [xic("C")])], [xic("D")]),
    ote("Out"),
  ];
  it("leg with a nested OR conducts when A and (B or C)", () => {
    expect(classifyRung(rung, { A: true, B: false, C: true, D: false })).toBe("conducting");
  });
  it("blocks when neither the compound leg nor D conduct", () => {
    expect(classifyRung(rung, { A: true, B: false, C: false, D: false })).toBe("blocked");
  });
  it("the other leg (D) alone can carry the branch", () => {
    expect(classifyRung(rung, { A: false, B: false, C: false, D: true })).toBe("conducting");
  });
});

describe("XIO (normally-closed) semantics", () => {
  const rung = [xio("Fault"), ote("Out")];
  it("conducts when the tag is FALSE", () => {
    expect(classifyRung(rung, { Fault: false })).toBe("conducting");
  });
  it("blocks when the tag is TRUE", () => {
    expect(classifyRung(rung, { Fault: true })).toBe("blocked");
  });
});

describe("comparison leaves", () => {
  const rung = [geq("Speed", "100"), ote("Out")];
  it("evaluates when both operands are known", () => {
    expect(classifyRung(rung, { Speed: 150 })).toBe("conducting");
    expect(classifyRung(rung, { Speed: 50 })).toBe("blocked");
  });
  it("is indeterminate when an operand value is missing", () => {
    expect(classifyRung(rung, { Unrelated: 1 })).toBe("indeterminate");
  });
});

describe("unknown propagation and no-values", () => {
  it("returns 'unknown' when no values are supplied", () => {
    expect(classifyRung([xic("A"), ote("Out")])).toBe("unknown");
  });
  it("a single false in a long AND collapses the whole rung to blocked", () => {
    const rung = [xic("A"), xic("B"), xic("C"), ote("Out")];
    expect(classifyRung(rung, { A: true, C: true })).toBe("indeterminate"); // B unknown
    expect(classifyRung(rung, { A: true, B: false })).toBe("blocked"); // B false wins
  });
});

// ── The acceptance case: R30_PressCycle rung 9 ──────────────────────────
describe("R30_PressCycle rung 9 (press cycle-start permissive)", () => {
  it("computes 'blocked' with guard_door_open values (Safety_OK=false)", () => {
    expect(classifyRung(RUNG9_ELEMENTS, RUNG9_GUARD_VALUES)).toBe("blocked");
  });
  it("computes 'conducting' with healthy values", () => {
    expect(classifyRung(RUNG9_ELEMENTS, RUNG9_HEALTHY_VALUES)).toBe("conducting");
  });
  it("pinpoints Safety_OK as the blocking contact under guard_door_open", () => {
    const { chain } = energizeRung(RUNG9_ELEMENTS, RUNG9_GUARD_VALUES);
    const safety = chain.items.find(
      (it) => it.kind === "instruction" && it.element.operands[0]?.value === "Safety_OK"
    );
    expect((safety as any).state).toBe(false);
    // The branch downstream of Safety_OK never receives power.
    const br = chain.items.find((it) => it.kind === "branch");
    expect((br as any).powerBefore).toBe(false);
  });
  it("the OR branch conducts on its own (both permissives true)", () => {
    const values: ValueMap = { Cycle_Start_PB: false, Auto_Sequence_Run: true };
    const leg = energizeChain([RUNG9_ELEMENTS[9]], values, true);
    expect((leg.items[0] as any).state).toBe(true); // branch conducts via leg 2
  });
});
