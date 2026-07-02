"""
condition_tree.py – The diagnosis engine for "Ask the PLC".

Given a target coil/bit, backward-chain through the parsed ladder logic to build
a **condition tree**: an AND/OR tree of the leaf conditions (contacts, compares,
timer done-bits) that must hold for the target to be energized. The tree can then
be evaluated against a live snapshot of tag values (tri-state) and pruned to the
minimal set of *failing* leaf conditions — the "one red contact" that a
maintenance tech is looking for.

This is pure, deterministic static analysis over the existing
:class:`~src.parser.rung_parser.ParsedRung` structures — it never guesses. Cases
it cannot resolve (indirect addressing, ST/FBD writers, MOV-masked bits) are
surfaced explicitly as ``FLAG`` nodes rather than glossed over.

Public API
----------
``build_condition_tree(target, project_data, max_depth=4) -> ConditionNode``
``evaluate_tree(node, values) -> ConditionNode``
``failing_paths(node) -> list[list[ConditionNode]]``

Node model
----------
:class:`ConditionNode` – ``kind`` ∈ {AND, OR, LEAF, FLAG, LATCH};
``requirement`` ∈ {needs_true, needs_false, comparison, none}; plus ``tag`` /
``full_path`` / ``cite`` / ``annotation`` / ``children`` / ``satisfied`` and a
``to_dict()`` that is ``json.dumps``-able.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..parser.rung_parser import (
    Branch,
    Instruction,
    ParsedRung,
    parse_rung,
)
from ..parser.cross_reference import (
    TagUsage,
    build_member_cross_reference,
    normalize_tag_name,
)

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

# kinds
AND = "AND"
OR = "OR"
LEAF = "LEAF"
FLAG = "FLAG"
LATCH = "LATCH"

# requirements
NEEDS_TRUE = "needs_true"
NEEDS_FALSE = "needs_false"
COMPARISON = "comparison"
NONE = "none"

_COIL_MNEMONICS = ("OTE", "OTL", "OTU")
_MOV_MNEMONICS = ("MOV", "COP", "CPS", "BTD")
_TIMER_MNEMONICS = ("TON", "TOF", "RTO")
_COUNTER_MNEMONICS = ("CTU", "CTD")
_COMPARE_MNEMONICS = ("EQU", "NEQ", "GRT", "GEQ", "LES", "LEQ", "LIM", "MEQ")
_DONE_BITS = ("DN", "TT", "EN", "ACC")

_DEFAULT_MAX_DEPTH = 4


# ──────────────────────────────────────────────────────────────────────
# Node model
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ConditionNode:
    """A node in a backward-chained condition tree.

    Attributes
    ----------
    kind:
        One of ``AND`` / ``OR`` / ``LEAF`` / ``FLAG`` / ``LATCH``.
    requirement:
        For leaves: ``needs_true`` / ``needs_false`` / ``comparison`` / ``none``.
        Grouping nodes use ``none``.
    tag:
        The base tag name this node concerns (if any).
    full_path:
        The original, un-normalized operand text (e.g. ``Timer1.DN``).
    cite:
        ``{"program", "routine", "rung_number"}`` for nodes tied to a rung.
    annotation:
        Human-readable note (latch semantics, honesty flags, timer presets…).
    comparison:
        For comparison leaves: ``{"op", "operands": [{"value", "is_literal"}]}``.
    children:
        Sub-nodes.
    satisfied:
        Tri-state result filled by :func:`evaluate_tree` (True / False / None).
    """

    kind: str
    requirement: str = NONE
    tag: Optional[str] = None
    full_path: Optional[str] = None
    cite: Optional[Dict] = None
    annotation: str = ""
    comparison: Optional[Dict] = None
    children: List["ConditionNode"] = field(default_factory=list)
    satisfied: Optional[bool] = None

    def to_dict(self) -> Dict:
        """Return a plain, ``json.dumps``-able dict of the whole subtree."""
        d: Dict = {
            "kind": self.kind,
            "requirement": self.requirement,
            "tag": self.tag,
            "full_path": self.full_path,
            "cite": self.cite,
            "annotation": self.annotation,
            "satisfied": self.satisfied,
            "children": [c.to_dict() for c in self.children],
        }
        if self.comparison is not None:
            d["comparison"] = self.comparison
        return d


# ──────────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────────

def _key(text: str) -> str:
    """Case-insensitive canonical key for an operand/tag path."""
    return (text or "").strip().lower()


def _cite_str(cite: Optional[Dict]) -> str:
    if not cite:
        return "?"
    return f"{cite.get('program')}/{cite.get('routine')} rung {cite.get('rung_number')}"


_RE_BRACKET = re.compile(r"\[([^\]]*)\]")
_RE_INT = re.compile(r"^-?\d+$")
_RE_IO = re.compile(r":[IO]\b|:[IO]\.|Local:\d+:[IO]", re.IGNORECASE)


def _is_indirect(operand: str) -> bool:
    """True if the operand uses indirect addressing (``data[index]``)."""
    for content in _RE_BRACKET.findall(operand or ""):
        content = content.strip()
        if content and not _RE_INT.match(content):
            return True
    return False


def _is_io_address(operand: str) -> bool:
    """Heuristic: does the operand look like a physical I/O address?"""
    return bool(_RE_IO.search(operand or ""))


def _is_bit_member(operand: str) -> bool:
    """True for a numeric bit member of a word, e.g. ``Word.3``."""
    parts = (operand or "").rsplit(".", 1)
    return len(parts) == 2 and parts[1].isdigit()


def _output_kind(instr: Instruction) -> Optional[str]:
    """Classify an instruction as a writer: coil / mov / timer / counter."""
    mn = instr.mnemonic.upper()
    if mn in _COIL_MNEMONICS:
        return "coil"
    if mn in _MOV_MNEMONICS:
        return "mov"
    if mn in _TIMER_MNEMONICS:
        return "timer"
    if mn in _COUNTER_MNEMONICS:
        return "counter"
    return None


def _branch_has_output(branch: Branch) -> bool:
    for leg in branch.legs:
        for el in leg:
            if isinstance(el, Instruction) and _output_kind(el) is not None:
                return True
            if isinstance(el, Branch) and _branch_has_output(el):
                return True
    return False


def _collect_all_outputs(elements: List, prefix: List) -> List[Tuple[Instruction, List]]:
    """Walk a chain and pair each output instruction with its enable conditions.

    Returns a list of ``(output_instruction, condition_elements)`` where the
    condition elements are the (Instruction | Branch) conditions gating that
    output — including any enclosing-chain conditions passed via *prefix*.

    Ladder semantics: outputs in series pass power through, so a later output's
    enable is the accumulation of preceding *condition* elements only. A branch
    that itself contains an output is an output branch (recurse into legs); a
    branch of pure conditions is an OR gate that joins the enable.
    """
    conds = list(prefix)
    results: List[Tuple[Instruction, List]] = []

    for el in elements:
        if isinstance(el, Instruction):
            if el.is_condition or el.category == "one_shot":
                conds.append(el)
            elif _output_kind(el) is not None:
                results.append((el, list(conds)))
            # else: pass-through output (JSR, GSV, …) – ignore
        elif isinstance(el, Branch):
            if _branch_has_output(el):
                for leg in el.legs:
                    results.extend(_collect_all_outputs(leg, conds))
            else:
                conds.append(el)

    return results


# ──────────────────────────────────────────────────────────────────────
# DiagnosisContext – the queryable bundle
# ──────────────────────────────────────────────────────────────────────

@dataclass
class DiagnosisContext:
    """Everything the condition-tree builder needs, in a testable shape.

    Construct directly from synthetic pieces, or via :meth:`from_project`.

    Parameters
    ----------
    parsed_rungs:
        ``{(program, routine, rung_number): ParsedRung}``.
    programs:
        Optional list of :class:`~src.parser.routine_extractor.Program` — used
        only to detect ST-routine writers (honesty flags).
    aois:
        Optional list of :class:`~src.parser.aoi_extractor.AddOnInstruction` —
        enables tracing *through* AOI instances.
    tag_types:
        Optional ``{tag_name: data_type}`` — lets the engine recognise which
        tags are AOI instances (so ``Valve7.Opened`` can be traced inside the
        ``FB_VALVE`` definition).
    member_xref:
        Optional pre-built member-level cross reference; built on demand if
        omitted.
    """

    parsed_rungs: Dict[Tuple[str, str, int], ParsedRung]
    programs: List = field(default_factory=list)
    aois: List = field(default_factory=list)
    tag_types: Dict[str, str] = field(default_factory=dict)
    member_xref: Optional[Dict[str, TagUsage]] = None

    def __post_init__(self) -> None:
        self._tag_types_lc = {_key(k): v for k, v in self.tag_types.items()}
        self._aoi_by_name = {}
        for aoi in self.aois:
            self._aoi_by_name[_key(aoi.name)] = aoi
        self._build_output_index()
        if self.member_xref is None:
            self.member_xref = build_member_cross_reference(self.parsed_rungs)
        self._st_writers = self._scan_st_writers()

    # -- index construction -------------------------------------------------

    def _build_output_index(self) -> None:
        self._coil_index: Dict[str, List[Tuple[Dict, List, str]]] = {}
        self._mov_index: Dict[str, List[Tuple[Dict, str]]] = {}
        self._timer_index: Dict[str, Tuple[Dict, str, List]] = {}

        for (prog, rout, num), prung in self.parsed_rungs.items():
            cite = {"program": prog, "routine": rout, "rung_number": num}
            for instr, conds in _collect_all_outputs(prung.elements, []):
                kind = _output_kind(instr)
                if not instr.operands:
                    continue
                if kind == "coil":
                    k = _key(instr.operands[0].value)
                    self._coil_index.setdefault(k, []).append(
                        (cite, conds, instr.mnemonic.upper())
                    )
                elif kind == "mov":
                    k = _key(instr.operands[-1].value)
                    self._mov_index.setdefault(k, []).append((cite, instr.mnemonic.upper()))
                elif kind == "timer":
                    k = _key(instr.operands[0].value)
                    preset = (
                        instr.operands[1].value if len(instr.operands) > 1 else "?"
                    )
                    self._timer_index.setdefault(k, (cite, preset, conds))

    def _scan_st_writers(self) -> Dict[str, List[Dict]]:
        """Scan ST routine lines for ``tag := …`` assignments (string-level)."""
        writers: Dict[str, List[Dict]] = {}
        assign_re = re.compile(r"^\s*([A-Za-z_][\w\.\[\]]*)\s*:=")
        for prog in self.programs:
            for rout in getattr(prog, "routines", []):
                if getattr(rout, "routine_type", "") != "ST":
                    continue
                for line in getattr(rout, "lines", []):
                    m = assign_re.match(line.text or "")
                    if not m:
                        continue
                    lhs = m.group(1)
                    cite = {"program": prog.name, "routine": rout.name, "line": line.number}
                    for k in (_key(lhs), _key(normalize_tag_name(lhs))):
                        writers.setdefault(k, []).append(cite)
        return writers

    # -- queries ------------------------------------------------------------

    def find_coil_drivers(self, target: str) -> List[Tuple[Dict, List, str]]:
        """Return ``[(cite, enable_conditions, mnemonic)]`` for OTE/OTL/OTU of target."""
        return list(self._coil_index.get(_key(target), []))

    def find_mov_writers(self, target: str) -> List[Tuple[Dict, str]]:
        """MOV/COP writers of the target path, or of its parent word (bit member)."""
        hits = list(self._mov_index.get(_key(target), []))
        if _is_bit_member(target):
            parent = target.rsplit(".", 1)[0]
            hits += list(self._mov_index.get(_key(parent), []))
        return hits

    def find_st_writers(self, target: str) -> List[Dict]:
        hits = list(self._st_writers.get(_key(target), []))
        base = normalize_tag_name(target)
        if _key(base) != _key(target):
            hits += list(self._st_writers.get(_key(base), []))
        return hits

    def is_timer(self, tag: str) -> bool:
        return _key(tag) in self._timer_index

    def timer_info(self, tag: str) -> Optional[Tuple[Dict, str, List]]:
        return self._timer_index.get(_key(tag))

    def is_aoi_instance(self, base: str) -> bool:
        dtype = self._tag_types_lc.get(_key(base))
        return bool(dtype) and _key(dtype) in self._aoi_by_name

    def get_aoi_for_instance(self, base: str):
        dtype = self._tag_types_lc.get(_key(base))
        if not dtype:
            return None
        return self._aoi_by_name.get(_key(dtype))

    # -- constructors -------------------------------------------------------

    @classmethod
    def from_project(cls, project) -> "DiagnosisContext":
        """Build a context from a :class:`ParsedProject`."""
        tag_types = {t.name: t.data_type for t in getattr(project, "tags", [])}
        return cls(
            parsed_rungs=project.parsed_rungs,
            programs=list(getattr(project, "programs", [])),
            aois=list(getattr(project, "aois", [])),
            tag_types=tag_types,
        )

    @classmethod
    def for_aoi(cls, aoi) -> "DiagnosisContext":
        """Build a context over an AOI's *internal* RLL routines."""
        rungs: Dict[Tuple[str, str, int], ParsedRung] = {}
        for rout in getattr(aoi, "routines", []):
            if getattr(rout, "routine_type", "") != "RLL":
                continue
            for rung in getattr(rout, "rungs", []):
                rungs[(aoi.name, rout.name, rung.number)] = parse_rung(rung.text)
        return cls(parsed_rungs=rungs)


# ──────────────────────────────────────────────────────────────────────
# Tree building
# ──────────────────────────────────────────────────────────────────────

def build_condition_tree(
    target: str,
    project_data,
    max_depth: int = _DEFAULT_MAX_DEPTH,
) -> ConditionNode:
    """Backward-chain the ladder logic to explain *what drives ``target`` true*.

    Parameters
    ----------
    target:
        The tag / member path to explain (e.g. ``Press_Cycle_Start``).
    project_data:
        A :class:`DiagnosisContext`, or a ``ParsedProject`` (auto-adapted).
    max_depth:
        Recursion depth into intermediate coils (default 4). Seal-in / latch
        cycles are detected and never recurse regardless of depth.

    Returns
    -------
    ConditionNode
        The root of the condition tree.
    """
    ctx = project_data
    if not isinstance(ctx, DiagnosisContext):
        ctx = DiagnosisContext.from_project(project_data)
    return _drivers_node(target, ctx, max_depth, ())


def _drivers_node(
    target: str,
    ctx: DiagnosisContext,
    depth: int,
    path: Tuple[str, ...],
) -> ConditionNode:
    """Node describing every driver of *target*."""
    coil = ctx.find_coil_drivers(target)
    if not coil:
        return _no_driver_leaf(target, ctx)

    otl = [d for d in coil if d[2] == "OTL"]
    otu = [d for d in coil if d[2] == "OTU"]
    ote = [d for d in coil if d[2] == "OTE"]

    if otl or otu:
        return _latch_node(target, otl, otu, ote, ctx, depth, path)

    new_path = path + (_key(target),)
    driver_nodes = [
        _driver_and(cite, conds, ctx, depth, new_path,
                    label=f"energized by {_cite_str(cite)}")
        for (cite, conds, _mn) in ote
    ]
    if len(driver_nodes) == 1:
        return driver_nodes[0]
    return ConditionNode(
        kind=OR,
        tag=normalize_tag_name(target),
        full_path=target,
        annotation=f"{target} is driven by {len(driver_nodes)} rungs (any energizes it)",
        children=driver_nodes,
    )


def _driver_and(
    cite: Dict,
    conds: List,
    ctx: DiagnosisContext,
    depth: int,
    path: Tuple[str, ...],
    label: str,
) -> ConditionNode:
    """AND node for one driving rung's enable logic."""
    children = [_build_element_node(el, ctx, depth, path, cite) for el in conds]
    return ConditionNode(kind=AND, cite=cite, annotation=label, children=children)


def _latch_node(target, otl, otu, ote, ctx, depth, path) -> ConditionNode:
    """LATCH node representing OTL/OTU (and any OTE) drivers of a retentive bit."""
    node = ConditionNode(
        kind=LATCH,
        tag=normalize_tag_name(target),
        full_path=target,
    )
    parts = []
    if otl:
        parts.append("latched by " + ", ".join(_cite_str(c) for c, _, _ in otl))
    if otu:
        parts.append("unlatched by " + ", ".join(_cite_str(c) for c, _, _ in otu))
    if ote:
        parts.append("also driven by " + ", ".join(_cite_str(c) for c, _, _ in ote))
    node.annotation = (
        "; ".join(parts)
        + ". State is retentive — actual value depends on latch history."
    )

    new_path = path + (_key(target),)
    for (cite, conds, _mn) in otl:
        node.children.append(_driver_and(cite, conds, ctx, depth, new_path, "latch condition"))
    for (cite, conds, _mn) in otu:
        node.children.append(_driver_and(cite, conds, ctx, depth, new_path, "unlatch condition"))
    for (cite, conds, _mn) in ote:
        node.children.append(_driver_and(cite, conds, ctx, depth, new_path, "energize condition"))
    return node


def _build_element_node(el, ctx, depth, path, cite: Optional[Dict]) -> ConditionNode:
    """Turn one enable element (Instruction | Branch) into a ConditionNode.

    *cite* is the rung where this condition element occurs — stamped on every
    node built from it so the UI/LLM can cite the exact occurrence.
    """
    if isinstance(el, Branch):
        legs = [_build_leg_node(leg, ctx, depth, path, cite) for leg in el.legs]
        return ConditionNode(
            kind=OR,
            cite=cite,
            annotation="parallel branch (any leg conducts)",
            children=legs,
        )
    return _build_leaf(el, ctx, depth, path, cite)


def _build_leg_node(leg: List, ctx, depth, path, cite: Optional[Dict]) -> ConditionNode:
    """A branch leg → AND of its condition elements (or the single element)."""
    nodes = [_build_element_node(e, ctx, depth, path, cite) for e in leg]
    if len(nodes) == 1:
        return nodes[0]
    return ConditionNode(
        kind=AND, cite=cite, annotation="series within branch leg", children=nodes
    )


def _build_leaf(instr: Instruction, ctx, depth, path, cite: Optional[Dict]) -> ConditionNode:
    """Build a leaf node for a single condition instruction.

    Every node gets ``cite`` = the rung where the condition instruction
    appears (its occurrence citation); expanded child subtrees carry their own
    driver-rung cites.
    """
    node = _build_leaf_inner(instr, ctx, depth, path)
    if node.cite is None:
        node.cite = cite
    return node


def _build_leaf_inner(instr: Instruction, ctx, depth, path) -> ConditionNode:
    """Build a leaf node for a single condition instruction (cite stamped by caller)."""
    mn = instr.mnemonic.upper()
    cat = instr.category

    # Comparison instructions
    if cat == "compare" or mn in _COMPARE_MNEMONICS:
        operands = [{"value": o.value, "is_literal": o.is_literal} for o in instr.operands]
        return ConditionNode(
            kind=LEAF,
            requirement=COMPARISON,
            annotation=f"{mn}({', '.join(o.value for o in instr.operands)})",
            comparison={"op": mn, "operands": operands},
        )

    # One-shots — pass-through, informational only
    if cat == "one_shot":
        operand = instr.operands[0].value if instr.operands else ""
        return ConditionNode(
            kind=LEAF,
            requirement=NONE,
            tag=normalize_tag_name(operand),
            full_path=operand or None,
            annotation=f"{mn} one-shot (rising/falling edge) — pass-through",
        )

    # Bit contacts
    if mn in ("XIC", "XIO") and instr.operands:
        operand = instr.operands[0].value
        req = NEEDS_TRUE if mn == "XIC" else NEEDS_FALSE
        node = ConditionNode(
            kind=LEAF,
            requirement=req,
            tag=normalize_tag_name(operand),
            full_path=operand,
        )

        # Indirect addressing → honesty flag
        if _is_indirect(operand):
            node.kind = FLAG
            node.requirement = NONE
            node.annotation = (
                f"indirect addressing '{operand}' — index is a tag; "
                "cannot resolve statically"
            )
            return node

        base = normalize_tag_name(operand)

        # Timer/counter done bit → trace the timer and note its preset
        if mn == "XIC" and "." in operand:
            parent = operand.rsplit(".", 1)[0]
            member = operand.rsplit(".", 1)[1].upper()
            if member in _DONE_BITS and ctx.is_timer(parent):
                cite, preset, conds = ctx.timer_info(parent)
                node.annotation = (
                    f"timer done bit — '{parent}' must stay enabled for {preset} ms"
                )
                if depth > 0:
                    node.children = [
                        _driver_and(cite, conds, ctx, depth - 1,
                                    path + (_key(parent),), "timer enable")
                    ]
                return node

        # AOI instance member → trace inside the AOI definition
        if "." in operand and ctx.is_aoi_instance(base):
            return _aoi_member_node(operand, base, ctx, depth, path)

        # Seal-in / self-holding cycle → stop, annotate as latch reference
        if _key(operand) in path:
            return ConditionNode(
                kind=LATCH,
                requirement=req,
                tag=base,
                full_path=operand,
                annotation=(
                    f"self-holding: '{operand}' appears in its own enable logic "
                    "(seal-in) — traversal stopped to avoid a cycle"
                ),
            )

        # Recurse into an intermediate coil
        if ctx.find_coil_drivers(operand):
            if depth <= 0:
                node.annotation = "depth limit reached — not expanded further"
                return node
            node.children = [_drivers_node(operand, ctx, depth - 1, path)]
            return node

        # No coil driver → honesty flags / field-input annotation
        _apply_no_writer(node, operand, ctx)
        return node

    # Fallback — an unrecognised condition (shouldn't normally reach here)
    operand = instr.operands[0].value if instr.operands else ""
    return ConditionNode(
        kind=LEAF,
        requirement=NONE,
        tag=normalize_tag_name(operand) if operand else None,
        full_path=operand or None,
        annotation=f"{mn} — treated as pass-through",
    )


def _apply_no_writer(node: ConditionNode, operand: str, ctx: DiagnosisContext) -> None:
    """Attach honesty flags / field-input annotation to a leaf with no coil driver."""
    st = ctx.find_st_writers(operand)
    if st:
        node.kind = FLAG
        node.requirement = NONE
        where = ", ".join(f"{c['program']}/{c['routine']}" for c in st)
        node.annotation = (
            f"written by Structured Text ({where}) — ST is not parsed into logic; "
            "value cannot be traced statically"
        )
        return

    mov = ctx.find_mov_writers(operand)
    if mov and _is_bit_member(operand):
        node.kind = FLAG
        node.requirement = NONE
        where = ", ".join(_cite_str(c) for c, _ in mov)
        node.annotation = (
            f"parent word written by MOV/COP ({where}); this bit is masked into a "
            "word write — bit-level driver not resolvable"
        )
        return
    if mov:
        where = ", ".join(_cite_str(c) for c, _ in mov)
        node.annotation = f"written via MOV/COP ({where}) — value-level write"
        return

    if _is_io_address(operand):
        node.annotation = f"physical I/O point '{operand}' — check the field device"
        return

    node.annotation = (
        f"field input '{operand}' — no logic writers found; "
        "likely a physical input, check the device"
    )


def _aoi_member_node(operand, base, ctx, depth, path) -> ConditionNode:
    """Trace an AOI instance member into the AOI's internal routines."""
    aoi = ctx.get_aoi_for_instance(base)
    member = operand.split(".", 1)[1] if "." in operand else operand
    param = member.split(".")[0].split("[")[0]

    node = ConditionNode(
        kind=LEAF,
        requirement=NEEDS_TRUE,
        tag=base,
        full_path=operand,
        annotation=(
            f"AOI member — instance '{base}' of type '{aoi.name}', "
            f"parameter '{param}'"
        ),
    )

    sub = DiagnosisContext.for_aoi(aoi)
    if not sub.parsed_rungs:
        node.kind = FLAG
        node.requirement = NONE
        node.annotation += "; internal RLL routines unavailable — cannot resolve"
        return node

    if depth <= 0:
        node.annotation += "; depth limit reached"
        return node

    inner = _drivers_node(param, sub, depth - 1, ())
    node.children = [inner]
    node.annotation += f"; traced parameter '{param}' inside the AOI definition"
    return node


def _no_driver_leaf(target: str, ctx: DiagnosisContext) -> ConditionNode:
    """Terminal node for a target with no coil driver (top-level / AOI param)."""
    node = ConditionNode(
        kind=LEAF,
        requirement=NEEDS_TRUE,
        tag=normalize_tag_name(target),
        full_path=target,
    )
    if _is_indirect(target):
        node.kind = FLAG
        node.requirement = NONE
        node.annotation = (
            f"indirect addressing '{target}' — cannot resolve statically"
        )
        return node
    _apply_no_writer(node, target, ctx)
    return node


# ──────────────────────────────────────────────────────────────────────
# Live evaluation
# ──────────────────────────────────────────────────────────────────────

def evaluate_tree(node: ConditionNode, values: Dict) -> ConditionNode:
    """Tri-state evaluation of a condition tree against live tag *values*.

    ``values`` maps tag / member paths (case-insensitive) to bool | int | float.
    Missing values propagate as ``None`` (unknown). Mutates ``node`` in place
    (sets ``satisfied`` on every node) and returns it.
    """
    lut = {_key(k): v for k, v in values.items()}
    _eval(node, lut)
    return node


def _and(states: List[Optional[bool]]) -> Optional[bool]:
    if any(s is False for s in states):
        return False
    if any(s is None for s in states):
        return None
    return True


def _or(states: List[Optional[bool]]) -> Optional[bool]:
    if not states:
        return None
    if any(s is True for s in states):
        return True
    if any(s is None for s in states):
        return None
    return False


def _lookup(lut: Dict, node: ConditionNode):
    for k in (node.full_path, node.tag):
        if k and _key(k) in lut:
            return lut[_key(k)]
    return None


def _num(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s.lower().startswith("16#"):
        try:
            return int(s[3:], 16)
        except ValueError:
            return None
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


def _eval_comparison(node: ConditionNode, lut: Dict) -> Optional[bool]:
    comp = node.comparison or {}
    op = comp.get("op")
    vals = []
    for o in comp.get("operands", []):
        if o.get("is_literal"):
            vals.append(_num(o.get("value")))
        else:
            raw = lut.get(_key(o.get("value", "")))
            vals.append(_num(raw) if raw is not None else None)
    if any(v is None for v in vals):
        return None
    try:
        if op == "GRT":
            return vals[0] > vals[1]
        if op == "GEQ":
            return vals[0] >= vals[1]
        if op == "LES":
            return vals[0] < vals[1]
        if op == "LEQ":
            return vals[0] <= vals[1]
        if op == "EQU":
            return vals[0] == vals[1]
        if op == "NEQ":
            return vals[0] != vals[1]
        if op == "LIM":  # LowLimit, Test, HighLimit
            low, test, high = vals[0], vals[1], vals[2]
            if low <= high:
                return low <= test <= high
            return test >= low or test <= high
        if op == "MEQ":  # Source, Mask, Compare
            src, mask, cmp = int(vals[0]), int(vals[1]), int(vals[2])
            return (src & mask) == (cmp & mask)
    except (IndexError, TypeError, ValueError):
        return None
    return None


def _eval_leaf(node: ConditionNode, lut: Dict) -> Optional[bool]:
    req = node.requirement
    if req == COMPARISON:
        return _eval_comparison(node, lut)
    if req == NONE:
        node._value_known = True  # pass-through never blocks  # type: ignore[attr-defined]
        return True

    v = _lookup(lut, node)
    if v is not None:
        node._value_known = True  # type: ignore[attr-defined]
        truth = bool(v)
        return truth if req == NEEDS_TRUE else (not truth)

    node._value_known = False  # type: ignore[attr-defined]
    if node.children:
        child_sat = _and([c.satisfied for c in node.children])
        if req == NEEDS_TRUE:
            return child_sat
        return None if child_sat is None else (not child_sat)
    return None


def _eval(node: ConditionNode, lut: Dict) -> Optional[bool]:
    for c in node.children:
        _eval(c, lut)

    if node.kind == AND:
        node.satisfied = _and([c.satisfied for c in node.children])
    elif node.kind == OR:
        node.satisfied = _or([c.satisfied for c in node.children])
    elif node.kind == LATCH:
        v = _lookup(lut, node)
        node.satisfied = (bool(v) if v is not None else None)
        node._value_known = v is not None  # type: ignore[attr-defined]
    elif node.kind == FLAG:
        node.satisfied = None
        node._value_known = False  # type: ignore[attr-defined]
    else:  # LEAF
        node.satisfied = _eval_leaf(node, lut)

    return node.satisfied


# ──────────────────────────────────────────────────────────────────────
# Failing-path extraction
# ──────────────────────────────────────────────────────────────────────

def failing_paths(node: ConditionNode) -> List[List[ConditionNode]]:
    """Return the minimal set of root→leaf paths that block the target.

    Each path is a list of :class:`ConditionNode` from the root to the deepest
    attributable unsatisfied condition. When an unsatisfied leaf has expanded
    driver logic (children) and that logic *explains* the failure (it also
    evaluates unsatisfied/unknown with the supplied values), the path descends
    through it to the deepest cause — e.g. Press_Cycle_Start → Safety_OK →
    GuardDoor_Closed. If the driver logic contradicts the live value (children
    satisfied while the value says false — latch / stale state), the path stops
    at the leaf with an annotation. Unknown (``None``) leaves are only reported
    when no definitive ``False`` exists on that branch.
    """
    out: List[List[ConditionNode]] = []
    _fail(node, [], out)
    return out


def _is_terminal(node: ConditionNode) -> bool:
    if getattr(node, "_value_known", False):
        return True
    if node.kind in (LATCH, FLAG):
        return True
    if not node.children:
        return True
    return False


_STALE_NOTE = (
    "live value is FALSE but its driver logic evaluates satisfied/unknown — "
    "possible latch, one-shot, or stale state; stopped here"
)
_ENERGIZED_NOTE = (
    "blocking: live value is TRUE (required FALSE) — its driver logic is "
    "energized; see the cited driver rung(s) in children"
)


def _explained_by_children(node: ConditionNode) -> bool:
    """True if an unsatisfied leaf's expanded driver logic explains the failure.

    A ``needs_true`` leaf that reads FALSE is *explained* when its driver
    subtree also evaluates FALSE (the enable logic really is broken) — in that
    case the failing path should descend to the deepest cause. A satisfied or
    unknown driver subtree does not explain a definitive FALSE (latch/stale
    state), and a ``needs_false`` leaf blocked by an *energized* tag has no
    failing sub-conditions to descend into.
    """
    if node.kind != LEAF or not node.children:
        return False
    if node.satisfied is not False:
        return False
    if node.requirement != NEEDS_TRUE:
        return False
    child_sat = _and([c.satisfied for c in node.children])
    return child_sat is False


def _fail(node: ConditionNode, prefix: List[ConditionNode], out: List) -> None:
    prefix = prefix + [node]
    if node.satisfied is True:
        return

    # Unsatisfied leaf with expanded driver logic: descend when the children
    # explain the failure; otherwise stop here (annotated).
    if node.kind == LEAF and node.children and getattr(node, "_value_known", False):
        if _explained_by_children(node):
            for c in node.children:
                if c.satisfied is not True:
                    _fail(c, prefix, out)
            return
        note = _ENERGIZED_NOTE if node.requirement == NEEDS_FALSE else _STALE_NOTE
        if note not in node.annotation:
            node.annotation = f"{node.annotation}; {note}" if node.annotation else note
        out.append(prefix)
        return

    if _is_terminal(node):
        out.append(prefix)
        return

    if node.kind == OR:
        emitted = False
        for c in node.children:
            if c.satisfied is not True:
                emitted = True
                _fail(c, prefix, out)
        if not emitted:
            out.append(prefix)
        return

    # AND / LEAF-with-children / driver grouping
    false_children = [c for c in node.children if c.satisfied is False]
    targets = false_children or [c for c in node.children if c.satisfied is None]
    if not targets:
        out.append(prefix)
        return
    for c in targets:
        _fail(c, prefix, out)
