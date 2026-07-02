"""
plc_tools.py – The tools layer for "Ask the PLC".

A :class:`PLCToolbox` wraps a parsed L5X project (``ParsedProject`` +
``DiagnosisContext``, both cached on construction) and exposes ten compact,
JSON-serializable tools that an LLM (or an MCP client) can call to reason about
the program. Every tool returns plain dicts — never raw XML, never a giant dump
— and list-returning tools cap their length while reporting a ``total`` so the
caller knows when a result was truncated.

Live values (for the "why is the machine down?" flow) come through a
:class:`LiveValueProvider` interface with two implementations:
:class:`StaticSnapshotProvider` (a JSON snapshot on disk — powers the faulted
demo today) and :class:`OpcUaProvider` (Stage-4 placeholder).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# --- Make the l5x-copilot `src` package importable ---------------------------
# The parser package is imported as `src.parser...` and expects the
# l5x-copilot/ directory on sys.path (there is no installed package).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_L5X_COPILOT = _REPO_ROOT / "l5x-copilot"
if str(_L5X_COPILOT) not in sys.path:
    sys.path.insert(0, str(_L5X_COPILOT))

from src.parser.project_model import parse_project, ParsedProject  # noqa: E402
from src.parser.cross_reference import (  # noqa: E402
    build_member_cross_reference,
    normalize_tag_name,
)
from src.parser.rung_parser import Instruction, Branch, ParsedRung  # noqa: E402
from src.analysis import (  # noqa: E402
    DiagnosisContext,
    build_condition_tree,
    evaluate_tree,
    failing_paths,
)

# Default demo file shipped with the repo.
DEFAULT_L5X = _REPO_ROOT / "demo_cell" / "build" / "PressLine_3.L5X"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


# ──────────────────────────────────────────────────────────────────────
# Live value providers
# ──────────────────────────────────────────────────────────────────────

class LiveValueProvider:
    """Interface for a source of live tag values (tri-state snapshots)."""

    name: str = "none"

    def get_values(self, tags: Optional[List[str]] = None) -> Dict[str, object]:
        raise NotImplementedError

    def available(self) -> bool:
        return False


class StaticSnapshotProvider(LiveValueProvider):
    """Live values loaded from a JSON snapshot file.

    The snapshot is a flat ``{tag_or_member_path: bool|int|float}`` map using
    the consistent-values pattern (internal coils agree with the logic that
    computes them) — this is what OPC UA would report on a real cell.
    """

    def __init__(self, path: str | Path, name: Optional[str] = None):
        self.path = Path(path)
        self.name = name or self.path.stem
        with open(self.path) as fh:
            data = json.load(fh)
        # allow either a bare map or {"values": {...}, "description": ...}
        if isinstance(data, dict) and "values" in data:
            self.description = data.get("description", "")
            self._values: Dict[str, object] = dict(data["values"])
        else:
            self.description = ""
            self._values = dict(data)

    def get_values(self, tags: Optional[List[str]] = None) -> Dict[str, object]:
        if tags is None:
            return dict(self._values)
        want = {t.lower() for t in tags}
        return {k: v for k, v in self._values.items() if k.lower() in want}

    def available(self) -> bool:
        return True


class OpcUaProvider(LiveValueProvider):
    """Placeholder OPC UA live-value provider — wired up in Stage 4."""

    name = "opcua"

    def __init__(self, endpoint: Optional[str] = None):
        self.endpoint = endpoint

    def get_values(self, tags: Optional[List[str]] = None) -> Dict[str, object]:
        raise NotImplementedError(
            "OpcUaProvider is a Stage-4 placeholder; connect a live cell to use it."
        )

    def available(self) -> bool:
        return False


# ──────────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────────

def _lc(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _cite(prog: str, rout: str, num: int) -> Dict:
    return {"program": prog, "routine": rout, "rung_number": num}


def _walk_instructions(elements) -> List[Instruction]:
    out: List[Instruction] = []
    for el in elements:
        if isinstance(el, Instruction):
            out.append(el)
        elif isinstance(el, Branch):
            for leg in el.legs:
                out.extend(_walk_instructions(leg))
    return out


# ──────────────────────────────────────────────────────────────────────
# PLCToolbox
# ──────────────────────────────────────────────────────────────────────

class PLCToolbox:
    """Cached, queryable bundle over one parsed L5X file.

    Parameters
    ----------
    l5x_path:
        Path to the ``.L5X`` file.
    live_provider:
        Optional :class:`LiveValueProvider` used by :meth:`get_live_values` and,
        when no explicit values are passed, by :meth:`trace_blockers`.
    """

    def __init__(self, l5x_path: str | Path, live_provider: Optional[LiveValueProvider] = None):
        self.l5x_path = str(l5x_path)
        self.project: ParsedProject = parse_project(self.l5x_path)
        self.diag = DiagnosisContext.from_project(self.project)
        self.member_xref = build_member_cross_reference(self.project.parsed_rungs)
        self.live_provider = live_provider
        # indices
        self._aoi_names = {_lc(a.name) for a in self.project.aois}
        self._routine_index = {}  # (prog_lc, rout_lc) -> (Program, Routine)
        for prog in self.project.programs:
            for rout in prog.routines:
                self._routine_index[(_lc(prog.name), _lc(rout.name))] = (prog, rout)

    # -- internal lookups ---------------------------------------------------

    def _find_tag(self, name: str):
        nl = _lc(name)
        # exact name match, any scope; prefer controller scope
        matches = [t for t in self.project.tags if _lc(t.name) == nl]
        if not matches:
            return None
        matches.sort(key=lambda t: 0 if _lc(t.scope) == "controller" else 1)
        return matches[0]

    def _tag_desc(self, base_name: str) -> str:
        t = self._find_tag(base_name)
        return t.description if t else ""

    def _routine(self, program: str, routine: str):
        return self._routine_index.get((_lc(program), _lc(routine)))

    def _aoi_instances(self) -> Dict[str, List[str]]:
        """AOI type name -> list of instance tag names."""
        out: Dict[str, List[str]] = {a.name: [] for a in self.project.aois}
        by_lc = {_lc(a.name): a.name for a in self.project.aois}
        for t in self.project.tags:
            key = by_lc.get(_lc(t.data_type))
            if key is not None:
                out[key].append(t.name)
        return out

    # ========================================================================
    # Tool 1: get_project_summary
    # ========================================================================
    def get_project_summary(self) -> Dict:
        m = self.project.metadata
        programs = []
        rll = st = sfc = 0
        for prog in self.project.programs:
            routines = []
            for r in prog.routines:
                if r.routine_type == "RLL":
                    rll += 1
                    count = len(r.rungs)
                elif r.routine_type == "ST":
                    st += 1
                    count = len(r.lines)
                elif r.routine_type == "SFC":
                    sfc += 1
                    count = len(r.sfc_content.steps) if r.sfc_content else 0
                else:
                    count = 0
                routines.append({
                    "name": r.name,
                    "type": r.routine_type,
                    "count": count,
                    "description": r.description,
                })
            programs.append({
                "name": prog.name,
                "main_routine": prog.main_routine_name,
                "disabled": prog.disabled,
                "routines": routines,
            })
        aoi_instances = self._aoi_instances()
        aois = [
            {"name": a.name, "description": a.description,
             "instance_count": len(aoi_instances.get(a.name, [])),
             "parameter_count": len(a.parameters)}
            for a in self.project.aois
        ]
        modules = [
            {"name": mod.name, "catalog_number": mod.catalog_number,
             "product_type": mod.product_type, "parent": mod.parent_module}
            for mod in self.project.modules
        ]
        return {
            "controller": {
                "name": m.controller_name,
                "processor_type": m.processor_type,
                "major_revision": m.major_revision,
                "minor_revision": m.minor_revision,
                "software_revision": m.software_revision,
            },
            "counts": {
                "tags": len(self.project.tags),
                "programs": len(self.project.programs),
                "routines": rll + st + sfc,
                "rll_routines": rll,
                "st_routines": st,
                "sfc_routines": sfc,
                "modules": len(self.project.modules),
                "udts": len(self.project.udts),
                "aois": len(self.project.aois),
                "parsed_rungs": len(self.project.parsed_rungs),
            },
            "documentation": {
                "coverage_pct": round(self.project.documentation_coverage, 1),
                "undocumented_tags": len(self.project.undocumented_tags),
                "unused_tags": len(self.project.unused_tags),
            },
            "programs": programs,
            "modules": modules,
            "aois": aois,
            "aoi_instances": aoi_instances,
        }

    # ========================================================================
    # Tool 2: search_tags
    # ========================================================================
    def search_tags(self, query: str, scope: Optional[str] = None, limit: int = 20) -> Dict:
        q = _lc(query)
        results = []
        for t in self.project.tags:
            if scope and _lc(t.scope) != _lc(scope):
                continue
            if q in _lc(t.name) or q in _lc(t.description):
                results.append({
                    "name": t.name,
                    "data_type": t.data_type,
                    "scope": t.scope,
                    "description": t.description,
                })
        total = len(results)
        return {"query": query, "scope": scope, "total": total,
                "returned": min(total, limit), "tags": results[:limit]}

    # ========================================================================
    # Tool 3: get_tag
    # ========================================================================
    def get_tag(self, name: str) -> Dict:
        t = self._find_tag(name)
        if t is None:
            return {"error": f"tag '{name}' not found", "name": name}
        nl = _lc(name)
        reads, writes = [], []
        for full_path, usage in self.member_xref.items():
            if _lc(normalize_tag_name(full_path)) != nl:
                continue
            for u in usage.usages:
                entry = {
                    "cite": _cite(u.program, u.routine, u.rung_number),
                    "instruction": u.instruction,
                    "member": u.full_path,
                }
                if "write" in u.access:
                    writes.append(entry)
                if "read" in u.access:
                    reads.append(entry)
        return {
            "name": t.name,
            "data_type": t.data_type,
            "tag_type": t.tag_type,
            "scope": t.scope,
            "description": t.description,
            "alias_for": t.alias_for,
            "constant": t.constant,
            "dimensions": t.dimensions,
            "is_aoi_instance": _lc(t.data_type) in self._aoi_names,
            "usage": {
                "read_count": len(reads),
                "write_count": len(writes),
                "reads": reads[:15],
                "writes": writes[:15],
            },
        }

    # ========================================================================
    # Tool 4: get_routine
    # ========================================================================
    def get_routine(self, program: str, routine: str) -> Dict:
        found = self._routine(program, routine)
        if not found:
            return {"error": f"routine '{program}/{routine}' not found"}
        prog, r = found
        out = {
            "program": prog.name,
            "routine": r.name,
            "type": r.routine_type,
            "description": r.description,
        }
        if r.routine_type == "RLL":
            out["rungs"] = [
                {"number": rg.number, "text": rg.text, "comment": rg.comment}
                for rg in r.rungs
            ]
            out["total_rungs"] = len(r.rungs)
        elif r.routine_type == "ST":
            out["lines"] = [{"number": ln.number, "text": ln.text} for ln in r.lines]
            out["total_lines"] = len(r.lines)
        elif r.routine_type == "SFC" and r.sfc_content:
            out["sfc"] = {
                "steps": [s.operand for s in r.sfc_content.steps],
                "transitions": [t.operand for t in r.sfc_content.transitions],
            }
        return out

    # ========================================================================
    # Tool 5: get_rung
    # ========================================================================
    def get_rung(self, program: str, routine: str, number: int) -> Dict:
        found = self._routine(program, routine)
        if not found:
            return {"error": f"routine '{program}/{routine}' not found"}
        prog, r = found
        if r.routine_type != "RLL":
            return {"error": f"routine '{program}/{routine}' is {r.routine_type}, not RLL"}
        rung = next((rg for rg in r.rungs if rg.number == number), None)
        if rung is None:
            return {"error": f"rung {number} not found in {program}/{routine}"}
        prung: Optional[ParsedRung] = self.project.parsed_rungs.get(
            (prog.name, r.name, number))
        instructions = []
        tags_seen = {}
        if prung is not None:
            for instr in _walk_instructions(prung.elements):
                ops = [o.value for o in instr.operands]
                instructions.append({
                    "mnemonic": instr.mnemonic,
                    "operands": ops,
                    "category": instr.category,
                    "is_condition": instr.is_condition,
                })
                for o in instr.operands:
                    if o.is_literal:
                        continue
                    base = normalize_tag_name(o.value)
                    if base and base not in tags_seen:
                        tags_seen[base] = self._tag_desc(base)
        return {
            "program": prog.name,
            "routine": r.name,
            "number": number,
            "text": rung.text,
            "comment": rung.comment,
            "instructions": instructions,
            "tags": [{"name": k, "description": v} for k, v in tags_seen.items()],
        }

    # ========================================================================
    # Tools 6: find_writers / find_readers
    # ========================================================================
    def _xref_by_access(self, tag: str, access_kind: str) -> Dict:
        nl = _lc(tag)
        hits = []
        for full_path, usage in self.member_xref.items():
            if _lc(full_path) != nl and _lc(normalize_tag_name(full_path)) != nl:
                continue
            for u in usage.usages:
                if access_kind in u.access:
                    hits.append({
                        "cite": _cite(u.program, u.routine, u.rung_number),
                        "instruction": u.instruction,
                        "member": u.full_path,
                        "access": u.access,
                    })
        return {"tag": tag, "total": len(hits), "results": hits[:30]}

    def find_writers(self, tag: str) -> Dict:
        return self._xref_by_access(tag, "write")

    def find_readers(self, tag: str) -> Dict:
        return self._xref_by_access(tag, "read")

    # ========================================================================
    # Tool 7: trace_blockers
    # ========================================================================
    def trace_blockers(self, target: str,
                       live_values: Optional[Dict[str, object]] = None) -> Dict:
        tree = build_condition_tree(target, self.diag)
        result: Dict = {"target": target, "tree": tree.to_dict()}

        values = live_values
        if values is None and self.live_provider and self.live_provider.available():
            values = self.live_provider.get_values()
            result["live_source"] = self.live_provider.name

        if values is not None:
            evaluate_tree(tree, values)
            result["tree"] = tree.to_dict()
            result["root_satisfied"] = tree.satisfied
            paths = failing_paths(tree)
            rendered = []
            for p in paths:
                chain = [{
                    "tag": n.tag,
                    "requirement": n.requirement,
                    "cite": n.cite,
                    "annotation": n.annotation,
                    "satisfied": n.satisfied,
                } for n in p if n.tag or n.annotation]
                leaf = p[-1]
                rendered.append({
                    "chain": [n.tag for n in p if n.tag],
                    "leaf_tag": leaf.tag,
                    "leaf_annotation": leaf.annotation,
                    "nodes": chain,
                })
            result["failing_paths"] = rendered
            result["failing_count"] = len(paths)
        return result

    # ========================================================================
    # Tool 8: get_aoi
    # ========================================================================
    def get_aoi(self, name: str) -> Dict:
        aoi = self.project.get_aoi(name)
        if aoi is None:
            return {"error": f"AOI '{name}' not found", "name": name}
        params = [
            {"name": p.name, "data_type": p.data_type, "usage": p.usage,
             "required": p.required, "description": p.description}
            for p in aoi.parameters
        ]
        locals_ = [
            {"name": lt.name, "data_type": lt.data_type, "description": lt.description}
            for lt in aoi.local_tags
        ]
        routines = []
        for r in aoi.routines:
            entry = {"name": r.name, "type": r.routine_type}
            if r.routine_type == "RLL":
                entry["rungs"] = [
                    {"number": rg.number, "text": rg.text, "comment": rg.comment}
                    for rg in r.rungs
                ]
            elif r.routine_type == "ST":
                entry["lines"] = [ln.text for ln in r.lines]
            routines.append(entry)
        return {
            "name": aoi.name,
            "description": aoi.description,
            "revision": aoi.revision,
            "parameters": params,
            "local_tags": locals_,
            "routines": routines,
            "instance_count": len(self._aoi_instances().get(aoi.name, [])),
            "instances": self._aoi_instances().get(aoi.name, [])[:20],
        }

    # ========================================================================
    # Tool 9: explain_context_pack
    # ========================================================================
    def explain_context_pack(self, program: str, routine: str) -> Dict:
        found = self._routine(program, routine)
        if not found:
            return {"error": f"routine '{program}/{routine}' not found"}
        prog, r = found
        rungs = []
        tags_seen: Dict[str, str] = {}
        aois_used: Dict[str, Dict] = {}
        aoi_by_lc = {_lc(a.name): a for a in self.project.aois}

        if r.routine_type == "RLL":
            for rg in r.rungs:
                rungs.append({"number": rg.number, "text": rg.text, "comment": rg.comment})
                prung = self.project.parsed_rungs.get((prog.name, r.name, rg.number))
                if prung is None:
                    continue
                for instr in _walk_instructions(prung.elements):
                    mn_lc = _lc(instr.mnemonic)
                    if instr.category == "aoi" and mn_lc in aoi_by_lc and instr.mnemonic not in aois_used:
                        a = aoi_by_lc[mn_lc]
                        aois_used[a.name] = {
                            "name": a.name,
                            "description": a.description,
                            "parameters": [
                                {"name": p.name, "usage": p.usage, "data_type": p.data_type}
                                for p in a.parameters
                            ],
                        }
                    for o in instr.operands:
                        if o.is_literal:
                            continue
                        base = normalize_tag_name(o.value)
                        if base and base not in tags_seen:
                            tags_seen[base] = self._tag_desc(base)
        elif r.routine_type == "ST":
            for ln in r.lines:
                rungs.append({"number": ln.number, "text": ln.text})

        return {
            "program": prog.name,
            "routine": r.name,
            "type": r.routine_type,
            "description": r.description,
            "rungs": rungs,
            "tags": [{"name": k, "description": v} for k, v in tags_seen.items()],
            "aoi_signatures": list(aois_used.values()),
        }

    # ========================================================================
    # Tool 10: get_live_values
    # ========================================================================
    def get_live_values(self, tags: Optional[List[str]] = None) -> Dict:
        if self.live_provider is None or not self.live_provider.available():
            return {"available": False, "source": None, "values": {},
                    "note": "no live value provider attached (attach a snapshot or OPC UA)"}
        vals = self.live_provider.get_values(tags)
        return {"available": True, "source": self.live_provider.name,
                "total": len(vals), "values": vals}
