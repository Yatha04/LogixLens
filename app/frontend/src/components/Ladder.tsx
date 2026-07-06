/**
 * Ladder.tsx — the signature SVG ladder-logic renderer.
 *
 * Pure component: (rung elements, optional live values) → an SVG rung with left
 * and right power rails, series contacts, parallel branches (recursive), coils,
 * and instruction boxes. When values are supplied it paints live power flow:
 * conducting wires bright green, blocked contacts red, indeterminate grey, and
 * the output coil glows when power reaches it.
 *
 * All energization is delegated to the tested `powerflow` module; this file is
 * layout + paint only.
 */
import { useMemo } from "react";
import type {
  RungElement,
  InstructionElement,
  ValueMap,
} from "../lib/types";
import {
  energizeChain,
  and3,
  or3,
  type Tri,
  type EnergizedChain,
  type EnergizedElement,
  type EnergizedInstruction,
} from "../lib/powerflow";

// ── Geometry ────────────────────────────────────────────────────────────
const CELL_W = 118;
const LANE_H = 86;
const RAIL_PAD = 26;
const TOP_PAD = 14;
const BOT_PAD = 14;

// ── Colors (CSS custom properties from index.css) ───────────────────────
const C_LIVE = "var(--color-live)";
const C_BLOCK = "var(--color-blocked)";
const C_IDLE = "var(--color-idle)";
const C_RAIL = "var(--color-line2)";
const C_INK = "var(--color-ink)";
const C_MUTED = "var(--color-muted)";

const C_DIM_TRUE = "var(--color-accent-dim)";

function wireColor(actual: Tri, _hasValues: boolean): string {
  // Spec: conducting green, everything non-conducting grey. Red is reserved
  // for the FIRST blocking element, never for downstream dead wire.
  return actual === true ? C_LIVE : C_IDLE;
}
/** True exactly when this element is the first one to kill a hot path. */
function isBlocking(state: Tri, actualBefore: Tri, hasValues: boolean): boolean {
  return hasValues && actualBefore === true && state === false;
}
function contactColor(state: Tri, actualBefore: Tri, hasValues: boolean): string {
  if (isBlocking(state, actualBefore, hasValues)) return C_BLOCK; // the red contact
  if (state === true && actualBefore === true) return C_LIVE; // carrying power
  if (state === true && hasValues) return C_DIM_TRUE; // closed, but path is dead
  return C_IDLE; // open downstream / unknown
}

// ── Structure measurement ───────────────────────────────────────────────
const isCompare = (i: InstructionElement) =>
  i.category === "compare" ||
  ["EQU", "NEQ", "GRT", "GEQ", "LES", "LEQ", "LIM", "MEQ"].includes(i.mnemonic.toUpperCase());
const isContact = (i: InstructionElement) => ["XIC", "XIO"].includes(i.mnemonic.toUpperCase());
const isCoil = (i: InstructionElement) => ["OTE", "OTL", "OTU"].includes(i.mnemonic.toUpperCase());

const isOneShot = (i: InstructionElement) =>
  i.category === "one_shot" || ["ONS", "OSR", "OSF"].includes(i.mnemonic.toUpperCase());

function boxWidth(instr: InstructionElement): number {
  // one-shots draw as a compact -[ONS]- block on the wire
  if (isOneShot(instr)) return 84;
  const ops = instr.operands.map((o) => o.value);
  const longest = Math.max(instr.mnemonic.length, ...ops.map((o) => o.length), 4);
  return Math.min(240, Math.max(CELL_W, 44 + longest * 7.2));
}

/** Contacts/coils widen with their tag name (real programs have names like
 * Treater_Pump[Active_Pump_Index]) so labels stay readable instead of
 * truncating at a fixed cell. Mono label is fontSize 11 ≈ 6.8px/char. */
function contactWidth(instr: InstructionElement): number {
  const tag = instr.operands[0]?.value ?? "";
  return Math.min(230, Math.max(CELL_W, tag.length * 6.8 + 26));
}

function itemWidth(it: EnergizedElement): number {
  if (it.kind === "branch") {
    return Math.max(CELL_W, ...it.legs.map(chainWidth));
  }
  const instr = it.element;
  if (isContact(instr) || isCoil(instr)) return contactWidth(instr);
  return boxWidth(instr);
}
function itemLanes(it: EnergizedElement): number {
  if (it.kind === "branch") return it.legs.reduce((s, l) => s + chainLanes(l), 0);
  return 1;
}
function chainWidth(c: EnergizedChain): number {
  return c.items.reduce((s, it) => s + itemWidth(it), 0) || CELL_W;
}
function chainLanes(c: EnergizedChain): number {
  return Math.max(1, ...c.items.map(itemLanes));
}

// ── Draw primitives ─────────────────────────────────────────────────────
function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

interface Ctx {
  hasValues: boolean;
  values?: ValueMap;
  /** base tag -> description (from the /api/rung `tags` map) */
  tags?: Record<string, string>;
  onTagClick?: (tag: string) => void;
  nodes: React.ReactNode[];
  key: number;
}

/** Base tag of an operand path: Station_Infeed.Ready -> Station_Infeed. */
function baseTag(operand: string): string {
  return operand.split(/[.[]/, 1)[0] ?? operand;
}

/** Case-insensitive live-value lookup (snapshot keys vs operand casing). */
function lookupValue(values: ValueMap | undefined, key: string): unknown {
  if (!values || !key) return undefined;
  if (key in values) return values[key];
  const lc = key.toLowerCase();
  for (const k of Object.keys(values)) if (k.toLowerCase() === lc) return values[k];
  return undefined;
}

function descLabel(ctx: Ctx, cx: number, y: number, tag: string) {
  const desc = ctx.tags?.[baseTag(tag)];
  if (!desc) return;
  ctx.nodes.push(
    <text
      key={k(ctx)}
      x={cx}
      y={y}
      textAnchor="middle"
      fontSize={8.5}
      fill="var(--color-faint)"
    >
      {truncate(desc, 32)}
      <title>{desc}</title>
    </text>
  );
}

function k(ctx: Ctx): string {
  return `n${ctx.key++}`;
}

function wire(ctx: Ctx, x1: number, y1: number, x2: number, y2: number, actual: Tri) {
  const live = actual === true;
  ctx.nodes.push(
    <line
      key={k(ctx)}
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke={wireColor(actual, ctx.hasValues)}
      strokeWidth={live ? 2.6 : 2}
      className={live ? "flow-dash" : undefined}
    />
  );
}

function tagLabel(ctx: Ctx, cx: number, y: number, tag: string, valueText?: string) {
  const clickable = !!ctx.onTagClick;
  ctx.nodes.push(
    <text
      key={k(ctx)}
      x={cx}
      y={y}
      textAnchor="middle"
      fontSize={11}
      fontFamily="var(--font-mono)"
      fill={C_INK}
      style={clickable ? { cursor: "pointer" } : undefined}
      onClick={clickable ? () => ctx.onTagClick!(tag) : undefined}
    >
      {truncate(tag, 30)}
      <title>{tag}</title>
    </text>
  );
  if (valueText !== undefined) {
    ctx.nodes.push(
      <text
        key={k(ctx)}
        x={cx}
        y={y + 13}
        textAnchor="middle"
        fontSize={9.5}
        fontFamily="var(--font-mono)"
        fill={C_MUTED}
      >
        {valueText}
      </text>
    );
  }
}

function valueText(v: unknown): string | undefined {
  if (v === undefined) return undefined;
  if (typeof v === "boolean") return v ? "1" : "0";
  return String(v);
}

// draw a single instruction glyph centered vertically at wireY across [x, x+w].
// Returns the actual power leaving the element (to feed the next in series).
function drawInstruction(
  ctx: Ctx,
  it: EnergizedInstruction,
  x: number,
  w: number,
  wireY: number,
  actualBefore: Tri
): Tri {
  const instr = it.element;
  const cx = x + w / 2;
  const mn = instr.mnemonic.toUpperCase();
  const tag = instr.operands[0]?.value ?? "";
  const v = tag ? lookupValue(ctx.values, tag) : undefined;

  if (isContact(instr)) {
    const afterActual = and3(actualBefore, it.state);
    const blocking = isBlocking(it.state, actualBefore, ctx.hasValues);
    const color = contactColor(it.state, actualBefore, ctx.hasValues);
    const gap = 9;
    const barH = 16;
    wire(ctx, x, wireY, cx - gap, wireY, actualBefore);
    wire(ctx, cx + gap, wireY, x + w, wireY, afterActual);
    const glow =
      color === C_LIVE
        ? { filter: "drop-shadow(0 0 3px rgba(51,224,138,0.8))" }
        : blocking
          ? { filter: "drop-shadow(0 0 4px rgba(255,93,97,0.85))" }
          : undefined;
    ctx.nodes.push(
      <g key={k(ctx)} className={blocking ? "animate-power" : undefined} style={glow}>
        <line x1={cx - gap} y1={wireY - barH} x2={cx - gap} y2={wireY + barH} stroke={color} strokeWidth={2.6} />
        <line x1={cx + gap} y1={wireY - barH} x2={cx + gap} y2={wireY + barH} stroke={color} strokeWidth={2.6} />
        {mn === "XIO" && (
          <line x1={cx - gap - 3} y1={wireY + barH + 2} x2={cx + gap + 3} y2={wireY - barH - 2} stroke={color} strokeWidth={2.2} />
        )}
      </g>
    );
    tagLabel(ctx, cx, wireY - barH - 8, tag, valueText(v));
    descLabel(ctx, cx, wireY + barH + 14, tag);
    return afterActual;
  }

  if (isCoil(instr)) {
    const live = actualBefore === true;
    const color = live ? C_LIVE : C_IDLE; // never red: a coil doesn't block
    const r = 15;
    wire(ctx, x, wireY, cx - r - 3, wireY, actualBefore);
    wire(ctx, cx + r + 3, wireY, x + w, wireY, actualBefore);
    ctx.nodes.push(
      <g
        key={k(ctx)}
        className={live ? "animate-power" : undefined}
        style={live ? { filter: "drop-shadow(0 0 4px rgba(51,224,138,0.8))" } : undefined}
      >
        <path d={arc(cx - r, wireY, r, true)} stroke={color} strokeWidth={2.6} fill="none" />
        <path d={arc(cx + r, wireY, r, false)} stroke={color} strokeWidth={2.6} fill="none" />
      </g>
    );
    const badge = mn === "OTL" ? "L" : mn === "OTU" ? "U" : "";
    if (badge) {
      ctx.nodes.push(
        <text key={k(ctx)} x={cx} y={wireY + 4} textAnchor="middle" fontSize={12} fontFamily="var(--font-mono)" fill={color}>
          {badge}
        </text>
      );
    }
    tagLabel(ctx, cx, wireY - r - 10, tag, valueText(v));
    descLabel(ctx, cx, wireY + r + 14, tag);
    return actualBefore;
  }

  // instruction box (timer / counter / move / math / compare / one-shot / AOI)
  return drawBox(ctx, it, x, w, wireY, actualBefore);
}

function arc(cx: number, cy: number, r: number, leftHalf: boolean): string {
  // half-circle open toward center
  const sweep = leftHalf ? 0 : 1;
  return `M ${cx} ${cy - r} A ${r} ${r} 0 0 ${sweep} ${cx} ${cy + r}`;
}

function drawBox(
  ctx: Ctx,
  it: EnergizedInstruction,
  x: number,
  w: number,
  wireY: number,
  actualBefore: Tri
): Tri {
  const instr = it.element;
  const compare = isCompare(instr);
  const oneShot = isOneShot(instr);
  const ops = oneShot ? [] : instr.operands;
  const lineCount = Math.max(oneShot ? 0 : 1, ops.length);
  const boxH = oneShot ? 24 : Math.min(LANE_H - 20, 22 + lineCount * 13);
  const bw = Math.min(w - 10, boxWidth(instr) - 8);
  const bx = x + (w - bw) / 2;
  const by = wireY - boxH / 2;

  const blocking = compare && isBlocking(it.state, actualBefore, ctx.hasValues);
  // conduction color: for compares use conduction state, else power passing
  const strokeCol = compare
    ? contactColor(it.state, actualBefore, ctx.hasValues)
    : actualBefore === true
      ? C_LIVE
      : C_IDLE;

  // lead wires
  const afterActual = compare ? and3(actualBefore, it.state) : actualBefore;
  wire(ctx, x, wireY, bx, wireY, actualBefore);
  wire(ctx, bx + bw, wireY, x + w, wireY, afterActual);

  const glow =
    strokeCol === C_LIVE
      ? { filter: "drop-shadow(0 0 3px rgba(51,224,138,0.7))" }
      : blocking
        ? { filter: "drop-shadow(0 0 4px rgba(255,93,97,0.85))" }
        : undefined;

  ctx.nodes.push(
    <g key={k(ctx)} className={blocking ? "animate-power" : undefined} style={glow}>
      <rect
        x={bx}
        y={by}
        width={bw}
        height={boxH}
        rx={4}
        fill="var(--color-surface2)"
        stroke={strokeCol}
        strokeWidth={blocking ? 2.4 : 1.6}
      />
      <text
        x={bx + bw / 2}
        y={oneShot ? wireY + 4 : by + 14}
        textAnchor="middle"
        fontSize={11}
        fontWeight={600}
        fontFamily="var(--font-mono)"
        fill={compare ? strokeCol : "var(--color-accent)"}
      >
        {instr.mnemonic}
      </text>
    </g>
  );
  if (oneShot && instr.operands[0]) {
    tagLabel(ctx, bx + bw / 2, by - 8, instr.operands[0].value);
  }
  ops.forEach((o, i) => {
    const liveV = !o.is_literal ? lookupValue(ctx.values, o.value) : undefined;
    ctx.nodes.push(
      <text
        key={k(ctx)}
        x={bx + bw / 2}
        y={by + 27 + i * 12}
        textAnchor="middle"
        fontSize={9.5}
        fontFamily="var(--font-mono)"
        fill={o.is_literal ? C_MUTED : C_INK}
        style={!o.is_literal && ctx.onTagClick ? { cursor: "pointer" } : undefined}
        onClick={!o.is_literal && ctx.onTagClick ? () => ctx.onTagClick!(o.value) : undefined}
      >
        {truncate(o.value, 22)}
        {liveV !== undefined && (
          <tspan fill={compare ? strokeCol : C_MUTED} fontSize={9}>
            {" "}={valueText(liveV)}
          </tspan>
        )}
        <title>{o.value}</title>
      </text>
    );
  });
  return afterActual;
}

// ── Recursive chain draw (threads ACTUAL power) ─────────────────────────
// Returns actual power leaving the chain and the x it ended at.
function drawChain(
  ctx: Ctx,
  chain: EnergizedChain,
  x0: number,
  topY: number,
  incomingActual: Tri
): { endX: number; out: Tri } {
  const wireY = topY + LANE_H / 2;
  let x = x0;
  let actual = incomingActual;

  for (const it of chain.items) {
    const w = itemWidth(it);
    if (it.kind === "branch") {
      const branchW = Math.max(CELL_W, ...it.legs.map(chainWidth));
      let legTop = topY;
      const legOuts: Tri[] = [];
      const legYs: number[] = [];
      for (const leg of it.legs) {
        const legWireY = legTop + LANE_H / 2;
        legYs.push(legWireY);
        const r = drawChain(ctx, leg, x, legTop, actual);
        if (r.endX < x + branchW) {
          wire(ctx, r.endX, legWireY, x + branchW, legWireY, r.out);
        }
        legOuts.push(r.out);
        legTop += chainLanes(leg) * LANE_H;
      }
      const outAct = and3(actual, legOuts.reduce<Tri>((a, b) => or3(a, b), false));
      // vertical rails join the legs at entry (x) and exit (x+branchW)
      const top = legYs[0];
      const bot = legYs[legYs.length - 1];
      vRail(ctx, x, top, bot, actual);
      vRail(ctx, x + branchW, top, bot, outAct);
      actual = outAct;
      x += branchW;
    } else {
      actual = drawInstruction(ctx, it, x, w, wireY, actual);
      x += w;
    }
  }
  return { endX: x, out: actual };
}

function vRail(ctx: Ctx, x: number, y1: number, y2: number, actual: Tri) {
  if (y1 === y2) return;
  ctx.nodes.push(
    <line
      key={k(ctx)}
      x1={x}
      y1={y1}
      x2={x}
      y2={y2}
      stroke={wireColor(actual, ctx.hasValues)}
      strokeWidth={actual === true ? 2.6 : 2}
      className={actual === true ? "flow-dash" : undefined}
    />
  );
}

// ── Public component ────────────────────────────────────────────────────
export interface LadderProps {
  elements: RungElement[];
  values?: ValueMap;
  /** base tag -> description; drawn truncated under each element */
  tags?: Record<string, string>;
  onTagClick?: (tag: string) => void;
  className?: string;
}

export function Ladder({ elements, values, tags, onTagClick, className }: LadderProps) {
  const { chain, width, height } = useMemo(() => {
    const c = energizeChain(elements, values, true);
    const w = RAIL_PAD * 2 + (chainWidth(c) || CELL_W) + 24;
    const h = TOP_PAD + BOT_PAD + Math.max(1, chainLanes(c)) * LANE_H;
    return { chain: c, width: w, height: h };
  }, [elements, values]);

  const hasValues = !!values && Object.keys(values).length > 0;
  const ctx: Ctx = { hasValues, values, tags, onTagClick, nodes: [], key: 0 };

  const leftRailX = RAIL_PAD;
  const rightRailX = width - RAIL_PAD;
  const wireY0 = TOP_PAD + LANE_H / 2;

  // left rail is always energized (bus +); wire from left rail into the chain
  const start = drawChain(ctx, chain, leftRailX + 8, TOP_PAD, hasValues ? true : null);
  // connect chain end to the right rail on the top lane
  const endActual = start.out;

  return (
    <div className={className} data-testid="ladder" data-rung-state={rungStateAttr(chain, hasValues)}>
      <svg
        width="100%"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="ladder rung"
        style={{ maxWidth: width, display: "block" }}
      >
        {/* rails */}
        <line x1={leftRailX} y1={TOP_PAD} x2={leftRailX} y2={height - BOT_PAD} stroke={hasValues ? C_LIVE : C_RAIL} strokeWidth={3} />
        <line x1={rightRailX} y1={TOP_PAD} x2={rightRailX} y2={height - BOT_PAD} stroke={C_RAIL} strokeWidth={3} />
        {/* left-rail lead-in on the top lane */}
        <line x1={leftRailX} y1={wireY0} x2={leftRailX + 8} y2={wireY0} stroke={wireColor(hasValues ? true : null, hasValues)} strokeWidth={2.4} />
        {/* chain */}
        {ctx.nodes}
        {/* end -> right rail */}
        <line
          x1={start.endX}
          y1={wireY0}
          x2={rightRailX}
          y2={wireY0}
          stroke={wireColor(endActual, hasValues)}
          strokeWidth={endActual === true ? 2.6 : 2}
          className={endActual === true ? "flow-dash" : undefined}
        />
      </svg>
    </div>
  );
}

function rungStateAttr(chain: EnergizedChain, hasValues: boolean): string {
  if (!hasValues) return "unknown";
  const coils = chain.items.filter(
    (it): it is EnergizedInstruction => it.kind === "instruction" && it.role === "coil"
  );
  const outs = coils.length ? coils.map((c) => c.powerBefore) : [chain.out];
  if (outs.some((s) => s === true)) return "conducting";
  if (outs.some((s) => s === null)) return "indeterminate";
  return "blocked";
}

export default Ladder;
