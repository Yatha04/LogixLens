/**
 * powerflow.ts — pure, deterministic ladder-logic energization.
 *
 * Given a parsed rung (nested Instruction/Branch elements from
 * app/backend/rung_json.py) and an optional map of live tag values, compute
 * left-to-right power flow exactly the way a PLC scan resolves a rung:
 *
 *   • An XIC contact conducts when its tag is TRUE; XIO when its tag is FALSE.
 *   • A comparison (EQU/GEQ/LES/…) conducts when it evaluates true.
 *   • Output / pass-through instructions (coils, timers, moves, JSR, ONS…) are
 *     transparent to power: they receive power but never block it.
 *   • A series chain conducts iff every element conducts.
 *   • A parallel branch conducts iff ANY leg conducts (a leg = series AND).
 *   • Unknown values propagate as `null` (indeterminate) and only collapse to a
 *     definite result when the tri-state logic forces one (a single FALSE in an
 *     AND blocks; a single TRUE in an OR conducts).
 *
 * The result annotates every element with its own conduction state plus the
 * power on the wire before/after it, so the renderer can paint conducting
 * segments green, blocked elements red, and indeterminate ones grey — and glow
 * an output coil only when power actually reaches it.
 *
 * This module is UI-free and fully unit-tested (powerflow.test.ts).
 */

import type {
  RungElement,
  InstructionElement,
  BranchElement,
  ValueMap,
  TagValue,
} from "./types";

/** Tri-state: true = conducts, false = blocked, null = indeterminate. */
export type Tri = boolean | null;

export const COIL_MNEMONICS = ["OTE", "OTL", "OTU"];
const COMPARE_MNEMONICS = ["EQU", "NEQ", "GRT", "GEQ", "LES", "LEQ", "LIM", "MEQ"];

// ── Tri-state algebra ───────────────────────────────────────────────────
export function and3(a: Tri, b: Tri): Tri {
  if (a === false || b === false) return false;
  if (a === null || b === null) return null;
  return true;
}

export function or3(a: Tri, b: Tri): Tri {
  if (a === true || b === true) return true;
  if (a === null || b === null) return null;
  return false;
}

// ── Value lookup ────────────────────────────────────────────────────────
function lookup(values: ValueMap | undefined, key: string): TagValue | undefined {
  if (!values) return undefined;
  if (key in values) return values[key];
  const lc = key.toLowerCase();
  for (const k of Object.keys(values)) {
    if (k.toLowerCase() === lc) return values[k];
  }
  return undefined;
}

function toNum(v: TagValue | undefined): number | null {
  if (v === undefined || v === null) return null;
  if (typeof v === "boolean") return v ? 1 : 0;
  if (typeof v === "number") return v;
  const s = String(v).trim();
  if (s.toLowerCase().startsWith("16#")) {
    const n = parseInt(s.slice(3), 16);
    return Number.isNaN(n) ? null : n;
  }
  const n = Number(s);
  return Number.isNaN(n) ? null : n;
}

function truthy(v: TagValue | undefined): Tri {
  if (v === undefined) return null;
  if (typeof v === "boolean") return v;
  const n = toNum(v);
  return n === null ? null : n !== 0;
}

// ── Element classification ──────────────────────────────────────────────
export type ElementRole = "condition" | "comparison" | "coil" | "passthrough";

export function classifyInstruction(instr: InstructionElement): ElementRole {
  const mn = instr.mnemonic.toUpperCase();
  if (COIL_MNEMONICS.includes(mn)) return "coil";
  if (instr.category === "compare" || COMPARE_MNEMONICS.includes(mn)) return "comparison";
  if (mn === "XIC" || mn === "XIO") return "condition";
  // Everything else that is not a condition (TON, MOV, JSR, ONS, AOI, …) is a
  // pass-through output: transparent to series power flow.
  if (!instr.is_condition) return "passthrough";
  // Unknown condition-shaped instruction: treat conservatively as passthrough.
  return "passthrough";
}

// ── Element evaluation (the element's own conduction) ───────────────────
function evalComparison(instr: InstructionElement, values: ValueMap | undefined): Tri {
  const op = instr.mnemonic.toUpperCase();
  const nums = instr.operands.map((o) =>
    o.is_literal ? toNum(o.value) : toNum(lookup(values, o.value))
  );
  if (nums.some((n) => n === null)) return null;
  const n = nums as number[];
  switch (op) {
    case "GRT":
      return n[0] > n[1];
    case "GEQ":
      return n[0] >= n[1];
    case "LES":
      return n[0] < n[1];
    case "LEQ":
      return n[0] <= n[1];
    case "EQU":
      return n[0] === n[1];
    case "NEQ":
      return n[0] !== n[1];
    case "LIM": {
      const [low, test, high] = n;
      return low <= high ? low <= test && test <= high : test >= low || test <= high;
    }
    case "MEQ": {
      const [src, mask, cmp] = n.map((x) => Math.trunc(x));
      return (src & mask) === (cmp & mask);
    }
    default:
      return null;
  }
}

function evalContact(instr: InstructionElement, values: ValueMap | undefined): Tri {
  const mn = instr.mnemonic.toUpperCase();
  const operand = instr.operands[0]?.value ?? "";
  const t = truthy(lookup(values, operand));
  if (t === null) return null;
  return mn === "XIO" ? !t : t;
}

// ── Energized result model ──────────────────────────────────────────────
export interface EnergizedInstruction {
  kind: "instruction";
  element: InstructionElement;
  role: ElementRole;
  /** The element's own conduction (contact/compare); for coils/passthrough,
   *  equals the incoming power (they don't gate). */
  state: Tri;
  powerBefore: Tri;
  powerAfter: Tri;
}

export interface EnergizedBranch {
  kind: "branch";
  element: BranchElement;
  /** OR of the legs' conduction. */
  state: Tri;
  powerBefore: Tri;
  powerAfter: Tri;
  legs: EnergizedChain[];
}

export type EnergizedElement = EnergizedInstruction | EnergizedBranch;

export interface EnergizedChain {
  items: EnergizedElement[];
  /** Power at the right end of the chain (conduction of the whole series). */
  out: Tri;
}

/**
 * Energize a series chain. `incoming` is the power arriving at the left of the
 * chain (the left rail is `true`).
 */
export function energizeChain(
  elements: RungElement[],
  values: ValueMap | undefined,
  incoming: Tri = true
): EnergizedChain {
  let power: Tri = incoming;
  const items: EnergizedElement[] = [];

  for (const el of elements) {
    const powerBefore = power;
    if (el.type === "branch") {
      // Each leg conducts on its own merits (measured from a powered rail);
      // the branch passes power iff any leg conducts.
      const legs = el.legs.map((leg) => energizeChain(leg, values, true));
      const branchConduction = legs.reduce<Tri>((acc, l) => or3(acc, l.out), false);
      const powerAfter = and3(powerBefore, branchConduction);
      items.push({
        kind: "branch",
        element: el,
        state: branchConduction,
        powerBefore,
        powerAfter,
        legs,
      });
      power = powerAfter;
    } else {
      const role = classifyInstruction(el);
      if (role === "coil" || role === "passthrough") {
        // Transparent to power: energized iff power reached it; passes power on.
        items.push({
          kind: "instruction",
          element: el,
          role,
          state: powerBefore,
          powerBefore,
          powerAfter: powerBefore,
        });
      } else {
        const conduction = role === "comparison" ? evalComparison(el, values) : evalContact(el, values);
        const powerAfter = and3(powerBefore, conduction);
        items.push({
          kind: "instruction",
          element: el,
          role,
          state: conduction,
          powerBefore,
          powerAfter,
        });
        power = powerAfter;
      }
    }
  }

  return { items, out: power };
}

// ── Rung-level classification ───────────────────────────────────────────
export type RungState = "conducting" | "blocked" | "indeterminate" | "unknown";

export interface RungEnergization {
  chain: EnergizedChain;
  /** Energization of each top-level output coil (state = power reaching it). */
  coilStates: Tri[];
  /** Aggregate rung state derived from the output coils. */
  state: RungState;
}

/**
 * Energize a whole rung and classify it. With no values, returns `"unknown"`.
 * The rung is `"conducting"` when any output coil is energized, `"blocked"`
 * when all coils are de-energized, and `"indeterminate"` when at least one
 * coil's power is unknown and none are definitely energized.
 */
export function energizeRung(
  elements: RungElement[],
  values?: ValueMap
): RungEnergization {
  const chain = energizeChain(elements, values, true);
  const coilStates: Tri[] = chain.items
    .filter(
      (it): it is EnergizedInstruction => it.kind === "instruction" && it.role === "coil"
    )
    .map((it) => it.powerBefore);

  let state: RungState;
  if (!values || Object.keys(values).length === 0) {
    state = "unknown";
  } else {
    // Consider coils if present, otherwise fall back to the chain output.
    const outputs = coilStates.length > 0 ? coilStates : [chain.out];
    if (outputs.some((s) => s === true)) state = "conducting";
    else if (outputs.some((s) => s === null)) state = "indeterminate";
    else state = "blocked";
  }

  return { chain, coilStates, state };
}

/** Convenience for tests: classify a rung to one of the RungState strings. */
export function classifyRung(elements: RungElement[], values?: ValueMap): RungState {
  return energizeRung(elements, values).state;
}
