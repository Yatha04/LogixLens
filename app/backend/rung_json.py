"""
rung_json.py – Serialize cached ParsedRung objects into the nested JSON the
frontend ladder renderer draws.

The shape (consumed by app/frontend/src/lib/powerflow.ts):

    {
      "program": str, "routine": str, "number": int,
      "text": str, "comment": str,
      "elements": [
        {"type": "instruction", "mnemonic": "XIC", "category": "bit_io",
         "is_condition": true, "operands": [{"value": "Safety_OK", "is_literal": false}]},
        {"type": "branch", "legs": [[<element>, ...], ...]},
        ...
      ],
      "tags": {base_tag_name: description},          # for the sub-labels
      "values": {operand_path: value}                # only when a snapshot is given
    }

Serialization is pure — it walks the ParsedRung structure already cached in
``ParsedProject.parsed_rungs`` (never re-parses rung text).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .plc_tools import PLCToolbox, Instruction, Branch, ParsedRung
from src.parser.cross_reference import normalize_tag_name  # noqa: E402  (path set up by plc_tools)


# ──────────────────────────────────────────────────────────────────────
# Element serialization (recursive)
# ──────────────────────────────────────────────────────────────────────

def serialize_element(el) -> Dict:
    """Instruction | Branch → plain dict (recursive for branch legs)."""
    if isinstance(el, Instruction):
        return {
            "type": "instruction",
            "mnemonic": el.mnemonic,
            "category": el.category,
            "is_condition": el.is_condition,
            "operands": [
                {"value": o.value, "is_literal": o.is_literal} for o in el.operands
            ],
        }
    if isinstance(el, Branch):
        return {
            "type": "branch",
            "legs": [[serialize_element(e) for e in leg] for leg in el.legs],
        }
    raise TypeError(f"unknown rung element: {type(el).__name__}")


def serialize_elements(elements: List) -> List[Dict]:
    return [serialize_element(el) for el in elements]


# ──────────────────────────────────────────────────────────────────────
# Operand collection (for tag descriptions + snapshot values)
# ──────────────────────────────────────────────────────────────────────

def collect_tag_operands(elements: List) -> List[str]:
    """Every non-literal operand path in the rung, in draw order, deduped."""
    out: List[str] = []
    seen = set()

    def _walk(els):
        for el in els:
            if isinstance(el, Instruction):
                for o in el.operands:
                    if o.is_literal:
                        continue
                    if o.value and o.value not in seen:
                        seen.add(o.value)
                        out.append(o.value)
            elif isinstance(el, Branch):
                for leg in el.legs:
                    _walk(leg)

    _walk(elements)
    return out


def _values_for(operands: List[str], snapshot_values: Dict[str, object]) -> Dict[str, object]:
    """Case-insensitive lookup of each operand path (then its base tag) in the
    snapshot. Keys in the result are the operand paths exactly as they appear
    in the rung, so the renderer needs no normalization."""
    by_lc = {k.lower(): v for k, v in snapshot_values.items()}
    out: Dict[str, object] = {}
    for op in operands:
        v = by_lc.get(op.lower())
        if v is None and op.lower() not in by_lc:
            base = normalize_tag_name(op)
            if base and base.lower() != op.lower():
                v = by_lc.get(base.lower())
                if v is None and base.lower() not in by_lc:
                    continue
            else:
                continue
        out[op] = v
    return out


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────

def rung_payload(
    toolbox: PLCToolbox,
    program: str,
    routine: str,
    number: int,
    snapshot_values: Optional[Dict[str, object]] = None,
) -> Dict:
    """Full nested parse structure of one rung, from the toolbox's cache.

    Returns ``{"error": ...}`` when the routine/rung doesn't exist or the
    routine isn't ladder.
    """
    found = toolbox._routine(program, routine)
    if not found:
        return {"error": f"routine '{program}/{routine}' not found"}
    prog, r = found
    if r.routine_type != "RLL":
        return {"error": f"routine '{program}/{routine}' is {r.routine_type}, not RLL"}
    rung = next((rg for rg in r.rungs if rg.number == number), None)
    if rung is None:
        return {"error": f"rung {number} not found in {program}/{routine}"}

    prung: Optional[ParsedRung] = toolbox.project.parsed_rungs.get(
        (prog.name, r.name, number)
    )
    elements = serialize_elements(prung.elements) if prung is not None else []
    operands = collect_tag_operands(prung.elements) if prung is not None else []

    tags: Dict[str, str] = {}
    for op in operands:
        base = normalize_tag_name(op)
        if base and base not in tags:
            tags[base] = toolbox._tag_desc(base)

    payload: Dict = {
        "program": prog.name,
        "routine": r.name,
        "number": number,
        "text": rung.text,
        "comment": rung.comment,
        "elements": elements,
        "tags": tags,
    }
    if snapshot_values is not None:
        payload["values"] = _values_for(operands, snapshot_values)
    return payload
