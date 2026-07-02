"""
mcp_smoketest.py – Verify the PLC-MCP stdio server end to end.

Spawns ``python -m app.backend.mcp_server`` over stdio, runs tools/list and a
couple of tools/call requests through the official mcp client, and prints the
results. Exit 0 on success.

Run (from repo root):
    ./l5x-copilot/.venv/bin/python -m app.backend.mcp_smoketest
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_REPO_ROOT = Path(__file__).resolve().parents[2]


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.backend.mcp_server", "--snapshot", "guard_door_open"],
        cwd=str(_REPO_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"tools/list -> {len(names)} tools: {names}")
            # 11 tool functions: the design's item 6 is find_writers + find_readers.
            assert len(names) == 11, f"expected 11 tools, got {len(names)}"
            assert "trace_blockers" in names

            summary = await session.call_tool("get_project_summary", {})
            text = summary.content[0].text
            assert "PressLine_3" in text
            print("tools/call get_project_summary -> ok (PressLine_3 found)")

            trace = await session.call_tool("trace_blockers", {"target": "Press_Cycle_Start"})
            ttext = trace.content[0].text
            assert "GuardDoor_Closed" in ttext, ttext[:200]
            print("tools/call trace_blockers(Press_Cycle_Start) -> ok "
                  "(GuardDoor_Closed failing path found)")

    print("MCP SMOKETEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
