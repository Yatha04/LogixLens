"""
mcp_server.py – FastMCP stdio server exposing the ten PLC tools.

A thin adapter over :class:`PLCToolbox` — every tool body is a one-liner that
forwards to the toolbox. Zero logic lives here.

Run:
    ./.venv/bin/python -m app.backend.mcp_server --l5x <path.L5X> [--snapshot <snap.json>]

If --l5x is omitted, the bundled PressLine_3 demo file is used. --snapshot may
be a path or a bare name (healthy | guard_door_open) resolved against the
snapshots/ directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from .plc_tools import (
    PLCToolbox,
    StaticSnapshotProvider,
    DEFAULT_L5X,
    SNAPSHOT_DIR,
)

mcp = FastMCP("plc-mcp")
_TOOLBOX: Optional[PLCToolbox] = None


def _tb() -> PLCToolbox:
    assert _TOOLBOX is not None, "toolbox not initialized"
    return _TOOLBOX


# -- the ten tools (thin forwarders) -------------------------------------

@mcp.tool()
def get_project_summary() -> dict:
    """Machine Dossier: controller metadata, program/routine tree, counts, doc coverage, and aoi_instances map."""
    return _tb().get_project_summary()


@mcp.tool()
def search_tags(query: str, scope: Optional[str] = None, limit: int = 20) -> dict:
    """Case-insensitive substring search over tag name and description. Returns a capped list with 'total'."""
    return _tb().search_tags(query, scope=scope, limit=limit)


@mcp.tool()
def get_tag(name: str) -> dict:
    """Full tag record plus member-level cited reads/writes usage summary."""
    return _tb().get_tag(name)


@mcp.tool()
def get_routine(program: str, routine: str) -> dict:
    """List every rung (number/text/comment) of an RLL routine, or every line of an ST routine."""
    return _tb().get_routine(program, routine)


@mcp.tool()
def get_rung(program: str, routine: str, number: int) -> dict:
    """One rung's text, comment, parsed instructions, and referenced tags with descriptions."""
    return _tb().get_rung(program, routine, number)


@mcp.tool()
def find_writers(tag: str) -> dict:
    """Cited list of every place that writes a tag (member-level aware)."""
    return _tb().find_writers(tag)


@mcp.tool()
def find_readers(tag: str) -> dict:
    """Cited list of every place that reads a tag (member-level aware)."""
    return _tb().find_readers(tag)


@mcp.tool()
def trace_blockers(target: str, live_values: Optional[dict] = None) -> dict:
    """Backward-chain the interlock logic driving a target; with live_values, return the minimal failing path(s)."""
    return _tb().trace_blockers(target, live_values=live_values)


@mcp.tool()
def get_aoi(name: str) -> dict:
    """An AOI definition: parameters, local tags, internal routine rungs, and instance tags."""
    return _tb().get_aoi(name)


@mcp.tool()
def explain_context_pack(program: str, routine: str) -> dict:
    """Bundled context to explain a routine: rungs+comments, referenced tags with descriptions, AOI signatures used."""
    return _tb().explain_context_pack(program, routine)


@mcp.tool()
def get_live_values(tags: Optional[List[str]] = None) -> dict:
    """Current live tag values from the attached snapshot/OPC UA provider (or a note that none is attached)."""
    return _tb().get_live_values(tags)


# -- entry point ----------------------------------------------------------

def _resolve_snapshot(name: Optional[str]):
    if not name:
        return None
    p = Path(name)
    if not p.exists():
        cand = SNAPSHOT_DIR / name
        if cand.exists():
            p = cand
        else:
            cand2 = SNAPSHOT_DIR / f"{name}.json"
            if cand2.exists():
                p = cand2
    return StaticSnapshotProvider(p)


def build_toolbox(l5x: Optional[str], snapshot: Optional[str]) -> PLCToolbox:
    return PLCToolbox(l5x or str(DEFAULT_L5X), live_provider=_resolve_snapshot(snapshot))


def main() -> None:
    global _TOOLBOX
    ap = argparse.ArgumentParser(description="Ask-the-PLC MCP server (stdio).")
    ap.add_argument("--l5x", default=None, help="Path to the .L5X file (default: PressLine_3 demo).")
    ap.add_argument("--snapshot", default=None, help="Snapshot path or name (healthy | guard_door_open).")
    args = ap.parse_args()
    _TOOLBOX = build_toolbox(args.l5x, args.snapshot)
    mcp.run()


if __name__ == "__main__":
    main()
