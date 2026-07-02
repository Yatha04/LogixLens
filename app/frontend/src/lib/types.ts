// Shared types mirroring the FastAPI backend response shapes.
// See app/backend/server.py, plc_tools.py, rung_json.py, condition_tree.py.

// ── Rung parse structure (GET /api/rung/...) ────────────────────────────
export interface Operand {
  value: string;
  is_literal: boolean;
}

export interface InstructionElement {
  type: "instruction";
  mnemonic: string;
  category: string;
  is_condition: boolean;
  operands: Operand[];
}

export interface BranchElement {
  type: "branch";
  legs: RungElement[][];
}

export type RungElement = InstructionElement | BranchElement;

/** A live tag value from a snapshot: boolean bit, or numeric for compares. */
export type TagValue = boolean | number | string;
export type ValueMap = Record<string, TagValue>;

export interface RungPayload {
  program: string;
  routine: string;
  number: number;
  text: string;
  comment: string;
  elements: RungElement[];
  tags: Record<string, string>;
  values?: ValueMap;
}

// ── Session / Dossier (POST /api/session, GET /api/dossier/...) ──────────
export interface Controller {
  name: string;
  processor_type: string;
  major_revision: number | string;
  minor_revision: number | string;
  software_revision: string;
}

export interface Counts {
  tags: number;
  programs: number;
  routines: number;
  rll_routines: number;
  st_routines: number;
  sfc_routines: number;
  modules: number;
  udts: number;
  aois: number;
  parsed_rungs: number;
}

export interface Documentation {
  coverage_pct: number;
  undocumented_tags: number;
  unused_tags: number;
}

export interface RoutineMeta {
  name: string;
  type: "RLL" | "ST" | "SFC" | string;
  count: number;
  description: string;
}

export interface ProgramMeta {
  name: string;
  main_routine: string | null;
  disabled: boolean;
  routines: RoutineMeta[];
}

export interface ModuleMeta {
  name: string;
  catalog_number: string;
  product_type: string;
  parent: string | null;
}

export interface AoiMeta {
  name: string;
  description: string;
  instance_count: number;
  parameter_count: number;
}

export interface Dossier {
  session_id: string;
  controller: Controller;
  counts: Counts;
  documentation: Documentation;
  aoi_instances: Record<string, string[]>;
  programs: ProgramMeta[];
  modules: ModuleMeta[];
  aois: AoiMeta[];
}

export interface SessionResponse {
  session_id: string;
  l5x: string;
  snapshot: string | null;
  mock: boolean;
  summary: {
    controller: Controller;
    counts: Counts;
    documentation: Documentation;
    aoi_instances: Record<string, string[]>;
    programs: ProgramMeta[];
    modules: ModuleMeta[];
    aois: AoiMeta[];
  };
}

// ── Routine read (GET /api/routine/...) ─────────────────────────────────
export interface RungSummary {
  number: number;
  text: string;
  comment: string;
}

export interface RoutinePayload {
  program: string;
  routine: string;
  type: string;
  description: string;
  rungs?: RungSummary[];
  total_rungs?: number;
  lines?: { number: number; text: string }[];
  total_lines?: number;
  sfc?: { steps: string[]; transitions: string[] };
}

// ── Trace / interlock tree (GET /api/trace/...) ─────────────────────────
export type Satisfied = boolean | null;

export interface Cite {
  program: string;
  routine: string;
  rung_number: number;
}

export interface ConditionNode {
  kind: "AND" | "OR" | "LEAF" | "FLAG" | "LATCH";
  requirement: "needs_true" | "needs_false" | "comparison" | "none";
  tag: string | null;
  full_path: string | null;
  cite: Cite | null;
  annotation: string;
  satisfied: Satisfied;
  comparison?: { op: string; operands: Operand[] };
  children: ConditionNode[];
}

export interface FailingPathNode {
  tag: string | null;
  requirement: string;
  cite: Cite | null;
  annotation: string;
  satisfied: Satisfied;
}

export interface FailingPath {
  chain: string[];
  leaf_tag: string | null;
  leaf_annotation: string;
  nodes: FailingPathNode[];
}

export interface TracePayload {
  target: string;
  tree: ConditionNode;
  live_source?: string;
  root_satisfied?: Satisfied;
  failing_paths?: FailingPath[];
  failing_count?: number;
}

// ── Auto-doc (POST /api/autodoc/..., GET /api/autodoc/.../export.csv) ────
export type Confidence = "high" | "medium" | "low";

export interface AutodocProposal {
  tag: string;
  data_type: string;
  scope: string;
  current_description: string;
  proposed_description: string;
  confidence: Confidence;
}

export interface AutodocResponse {
  session_id: string;
  mode: "mock" | "real";
  total: number;
  proposals: AutodocProposal[];
}

// ── Chat WebSocket frames ───────────────────────────────────────────────
export type Audience = "operator" | "maintenance" | "controls_engineer";

export type ChatFrame =
  | { type: "text_delta"; text: string }
  | { type: "tool_call"; tool: string; args: Record<string, unknown> }
  | {
      type: "tool_result_summary";
      tool: string;
      args: Record<string, unknown>;
      result_bytes: number;
      breadcrumb: string;
    }
  | { type: "citations"; citations: Cite[] }
  | { type: "done"; stop_reason: string; text: string }
  | { type: "error"; message: string };
