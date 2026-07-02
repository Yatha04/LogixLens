"""
tools_schema.py – JSON schemas + dispatch for the ten PLC tools.

Shared by the MCP server (``mcp_server.py``) and the chat tool-loop
(``chat.py``). Each schema is an Anthropic tool definition; ``dispatch`` runs a
tool by name against a :class:`PLCToolbox`.
"""

from __future__ import annotations

from typing import Dict, List

from .plc_tools import PLCToolbox

TOOL_SCHEMAS: List[Dict] = [
    {
        "name": "get_project_summary",
        "description": "Machine Dossier: controller metadata, program/routine tree, tag/module/AOI/UDT counts, documentation coverage, and an aoi_instances map (AOI type -> instance tag names). Call this for 'what does this machine do' / overview questions.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "search_tags",
        "description": "Case-insensitive substring search over tag name AND description. Use to discover exact tag names before making a claim. Returns a capped list with a 'total'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring to match in name or description."},
                "scope": {"type": "string", "description": "Optional scope filter: 'Controller' or a program name."},
                "limit": {"type": "integer", "description": "Max results (default 20)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_tag",
        "description": "Full record for one tag (data type, tag type, scope, description, alias, constant) plus a member-level usage summary: cited reads and writes. Use to check a tag exists and how it's used.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "get_routine",
        "description": "List every rung (number, raw ladder text, comment) of an RLL routine, or every line of an ST routine. Use to read a routine end to end.",
        "input_schema": {
            "type": "object",
            "properties": {
                "program": {"type": "string"},
                "routine": {"type": "string"},
            },
            "required": ["program", "routine"],
        },
    },
    {
        "name": "get_rung",
        "description": "One rung's raw text, comment, parsed instruction list (mnemonic + operands), and every tag it references with its description. Use to explain a specific rung.",
        "input_schema": {
            "type": "object",
            "properties": {
                "program": {"type": "string"},
                "routine": {"type": "string"},
                "number": {"type": "integer"},
            },
            "required": ["program", "routine", "number"],
        },
    },
    {
        "name": "find_writers",
        "description": "Cited list of every place that WRITES a tag (OTE/OTL/OTU/MOV/timers...). Member-level aware. Use for 'what writes X'.",
        "input_schema": {
            "type": "object",
            "properties": {"tag": {"type": "string"}},
            "required": ["tag"],
        },
    },
    {
        "name": "find_readers",
        "description": "Cited list of every place that READS a tag (XIC/XIO/compares...). Member-level aware. Use for 'what reads X / where is X used'.",
        "input_schema": {
            "type": "object",
            "properties": {"tag": {"type": "string"}},
            "required": ["tag"],
        },
    },
    {
        "name": "trace_blockers",
        "description": "THE diagnosis tool. Backward-chains the interlock logic that drives a target coil/bit and returns the condition tree (AND/OR/LEAF/FLAG/LATCH nodes with citations). If live_values are supplied (or a live snapshot is attached), it evaluates the tree and returns the minimal FAILING path(s) — the exact red contact blocking the target. Use for any 'why won't X go / why is X stopped/blocked' question.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "The output tag to explain, e.g. Press_Cycle_Start."},
                "live_values": {"type": "object", "description": "Optional {tag: bool|number} snapshot to evaluate against."},
            },
            "required": ["target"],
        },
    },
    {
        "name": "get_aoi",
        "description": "An Add-On Instruction definition: parameters (name/usage/type), local tags, internal routine rung texts, and its instance tags. Use for 'what is <AOI>' (e.g. FB_VALVE).",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "explain_context_pack",
        "description": "Bundled context to explain a whole routine in one call: its rungs+comments, every tag referenced with descriptions, and the signatures of AOIs it uses. Use for 'explain routine R / what does R do'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "program": {"type": "string"},
                "routine": {"type": "string"},
            },
            "required": ["program", "routine"],
        },
    },
    {
        "name": "get_live_values",
        "description": "Current live tag values from the attached snapshot/OPC UA provider (or a note that none is attached). Optionally filter to specific tags.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
]

TOOL_NAMES = [t["name"] for t in TOOL_SCHEMAS]


def dispatch(toolbox: PLCToolbox, name: str, arguments: Dict) -> Dict:
    """Run tool ``name`` with ``arguments`` against ``toolbox``. Never raises."""
    args = dict(arguments or {})
    try:
        fn = getattr(toolbox, name)
    except AttributeError:
        return {"error": f"unknown tool '{name}'"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
    except Exception as e:  # pragma: no cover - defensive
        return {"error": f"{name} failed: {e}"}
