"""
chat.py – The streaming tool-use loop for Ask the PLC.

``run_chat`` is an async generator that yields JSON-serializable frames as the
conversation progresses. Three model providers, all driving the exact same
tool dispatch / frame / citation machinery:

  api           the Anthropic API (needs ANTHROPIC_API_KEY)
  subscription  the local Claude Code login via the Claude Agent SDK — real
                Claude, tools run in-process against this session's toolbox,
                zero API billing
  mock          a deterministic fake model (CI / no-network)

Provider resolution (see ``resolve_provider``): ASKPLC_MOCK=1 forces mock;
ASKPLC_PROVIDER picks explicitly; otherwise an API key means ``api``, an
installed ``claude`` CLI means ``subscription``, else ``mock``.

Frame protocol (each frame is one dict):
  {"type": "text_delta", "text": str}
  {"type": "tool_call", "tool": str, "args": dict}
  {"type": "tool_result_summary", "tool": str, "args": dict, "result_bytes": int, "breadcrumb": str}
  {"type": "citations", "citations": [{"program","routine","rung_number"}, ...]}
  {"type": "done", "stop_reason": str, "text": str}
  {"type": "error", "message": str}
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from typing import AsyncIterator, Dict, List, Optional

from .plc_tools import PLCToolbox
from .prompts import build_system_prompt
from .tools_schema import TOOL_SCHEMAS, dispatch

DEFAULT_MODEL = os.environ.get("ASKPLC_MODEL", "claude-sonnet-5")
MAX_TOOL_ITERATIONS = 8
# The Agent SDK spends turns on its own tool plumbing (e.g. ToolSearch loads),
# so its budget must be far looser than the API loop's tool-iteration cap.
SUBSCRIPTION_MAX_TURNS = 30

_SUBSCRIPTION_ALIASES = {"subscription", "claude-cli", "agent-sdk", "agent", "claude_agent"}


def resolve_provider() -> str:
    """Pick the chat model provider: 'mock' | 'api' | 'subscription'."""
    if os.environ.get("ASKPLC_MOCK") == "1":
        return "mock"
    explicit = os.environ.get("ASKPLC_PROVIDER", "").strip().lower()
    if explicit in _SUBSCRIPTION_ALIASES:
        return "subscription"
    if explicit in ("api", "mock"):
        return explicit
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    if shutil.which("claude"):
        return "subscription"
    return "mock"


def is_mock() -> bool:
    return resolve_provider() == "mock"


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _collect_citations(obj, out: List[Dict], seen: set) -> None:
    """Recursively harvest {program, routine, rung_number} cite dicts."""
    if isinstance(obj, dict):
        if {"program", "routine", "rung_number"} <= obj.keys():
            key = (obj["program"], obj["routine"], obj["rung_number"])
            if key not in seen:
                seen.add(key)
                out.append({"program": obj["program"], "routine": obj["routine"],
                            "rung_number": obj["rung_number"]})
        for v in obj.values():
            _collect_citations(v, out, seen)
    elif isinstance(obj, list):
        for v in obj:
            _collect_citations(v, out, seen)


def _collect_result_citations(tool: str, result: Dict, out: List[Dict], seen: set) -> None:
    """Harvest citations for one tool result, noise-reduced for ``trace_blockers``.

    A live-evaluated ``trace_blockers`` tree carries a citation on every node —
    satisfied branches included — so a naive full-tree harvest buries the one
    or two rungs that actually matter under a pile of "this contact was fine"
    citations. When the trace produced failing path(s), cite only the nodes on
    those failing paths (the root-cause chain); otherwise fall back to
    harvesting every citation in the result, as before.
    """
    if tool == "trace_blockers":
        paths = result.get("failing_paths")
        if paths:
            for p in paths:
                for n in p.get("nodes", []):
                    cite = n.get("cite")
                    if not cite:
                        continue
                    key = (cite["program"], cite["routine"], cite["rung_number"])
                    if key not in seen:
                        seen.add(key)
                        out.append({"program": cite["program"], "routine": cite["routine"],
                                    "rung_number": cite["rung_number"]})
            return
    _collect_citations(result, out, seen)


def _breadcrumb(tool: str, args: Dict, result: Dict) -> str:
    """A short 'checked X for Y' style breadcrumb for the UI."""
    key = args.get("target") or args.get("tag") or args.get("name") or args.get("query")
    if tool in ("get_routine", "get_rung", "explain_context_pack"):
        key = f"{args.get('program','')}/{args.get('routine','')}"
        if "number" in args:
            key += f" rung {args['number']}"
    if tool == "trace_blockers" and "failing_count" in result:
        return f"traced blockers for {key}: {result['failing_count']} failing path(s)"
    if "total" in result:
        return f"{tool}({key}): {result['total']} result(s)"
    if "error" in result:
        return f"{tool}({key}): {result['error']}"
    return f"{tool}({key})" if key else tool


def _summary_frame(tool: str, args: Dict, result: Dict) -> Dict:
    return {
        "type": "tool_result_summary",
        "tool": tool,
        "args": {k: v for k, v in args.items() if k != "live_values"},
        "result_bytes": len(json.dumps(result, default=str)),
        "breadcrumb": _breadcrumb(tool, args, result),
    }


# ──────────────────────────────────────────────────────────────────────
# Real Claude loop
# ──────────────────────────────────────────────────────────────────────

async def _run_real(toolbox: PLCToolbox, message: str, audience: str,
                    model: str) -> AsyncIterator[Dict]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()
    system = build_system_prompt(audience)
    messages: List[Dict] = [{"role": "user", "content": message}]
    cites: List[Dict] = []
    seen: set = set()
    final_text = ""
    stop_reason = "end_turn"

    for _ in range(MAX_TOOL_ITERATIONS):
        async with client.messages.stream(
            model=model,
            max_tokens=2048,
            system=system,
            tools=TOOL_SCHEMAS,
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    final_text += event.delta.text
                    yield {"type": "text_delta", "text": event.delta.text}
            response = await stream.get_final_message()

        stop_reason = response.stop_reason
        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            break

        tool_results = []
        for tu in tool_uses:
            args = dict(tu.input or {})
            yield {"type": "tool_call", "tool": tu.name, "args":
                   {k: v for k, v in args.items() if k != "live_values"}}
            result = dispatch(toolbox, tu.name, args)
            _collect_result_citations(tu.name, result, cites, seen)
            yield _summary_frame(tu.name, args, result)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str),
            })
        messages.append({"role": "user", "content": tool_results})

    if cites:
        yield {"type": "citations", "citations": cites}
    yield {"type": "done", "stop_reason": stop_reason, "text": final_text}


# ──────────────────────────────────────────────────────────────────────
# Subscription loop — Claude Agent SDK over the local Claude Code login.
# The 11 tools are registered as an in-process SDK MCP server bound to THIS
# session's toolbox, so uploaded files and snapshots work identically and
# citations are harvested at dispatch time, exactly like the API loop.
# ──────────────────────────────────────────────────────────────────────

_SDK_DISALLOWED = [
    "Bash", "Read", "Write", "Edit", "Glob", "Grep",
    "WebFetch", "WebSearch", "Task", "TodoWrite", "NotebookEdit",
]


def _sdk_tools(toolbox: PLCToolbox, cites: List[Dict], seen: set,
               summaries: "asyncio.Queue[Dict]"):
    """Wrap TOOL_SCHEMAS as SDK tools closing over the session toolbox."""
    from claude_agent_sdk import tool as sdk_tool

    wrapped = []
    for schema in TOOL_SCHEMAS:
        def make(name: str, description: str, input_schema: Dict):
            @sdk_tool(name, description, input_schema)
            async def _t(args: Dict) -> Dict:
                call_args = dict(args or {})
                result = dispatch(toolbox, name, call_args)
                _collect_result_citations(name, result, cites, seen)
                summaries.put_nowait(_summary_frame(name, call_args, result))
                return {"content": [
                    {"type": "text", "text": json.dumps(result, default=str)}
                ]}
            return _t
        wrapped.append(make(schema["name"], schema["description"], schema["input_schema"]))
    return wrapped


async def _run_subscription(toolbox: PLCToolbox, message: str, audience: str,
                            model: str) -> AsyncIterator[Dict]:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
        create_sdk_mcp_server,
    )

    cites: List[Dict] = []
    seen: set = set()
    summaries: "asyncio.Queue[Dict]" = asyncio.Queue()
    final_text = ""
    stop_reason = "end_turn"

    server = create_sdk_mcp_server(
        name="plc", tools=_sdk_tools(toolbox, cites, seen, summaries))
    options = ClaudeAgentOptions(
        system_prompt=build_system_prompt(audience),
        mcp_servers={"plc": server},
        allowed_tools=[f"mcp__plc__{s['name']}" for s in TOOL_SCHEMAS],
        disallowed_tools=_SDK_DISALLOWED,
        permission_mode="bypassPermissions",
        max_turns=SUBSCRIPTION_MAX_TURNS,
        model=model,
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(message)
        async for msg in client.receive_response():
            # Tool summaries queue up while the SDK runs our tools between
            # messages — drain them in stream order.
            while not summaries.empty():
                yield summaries.get_nowait()
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        final_text += block.text
                        yield {"type": "text_delta", "text": block.text}
                    elif isinstance(block, ToolUseBlock):
                        # Only surface OUR tools; SDK plumbing (ToolSearch
                        # loading the MCP schemas, etc.) is noise in the UI.
                        if not block.name.startswith("mcp__plc__"):
                            continue
                        args = {k: v for k, v in (block.input or {}).items()
                                if k != "live_values"}
                        yield {"type": "tool_call",
                               "tool": block.name.removeprefix("mcp__plc__"),
                               "args": args}
            elif isinstance(msg, ResultMessage):
                stop_reason = "error" if msg.is_error else "end_turn"
        while not summaries.empty():
            yield summaries.get_nowait()

    if not final_text.strip():
        # Turn-limit or transport hiccup: never leave the user a blank bubble.
        fallback = ("I ran out of turns before writing the answer — the tool "
                    "breadcrumbs and citations above show what was checked. "
                    "Ask again (or narrower) and I'll pick it up from there.")
        final_text = fallback
        yield {"type": "text_delta", "text": fallback}

    if cites:
        yield {"type": "citations", "citations": cites}
    yield {"type": "done", "stop_reason": stop_reason, "text": final_text}


# ──────────────────────────────────────────────────────────────────────
# Mock loop (deterministic; exercises real dispatch + frames)
# ──────────────────────────────────────────────────────────────────────

_WHY_RE = re.compile(r"\b(why|won'?t|not\s+(cycl|start|run|energ|mov)|stopp?ed|blocked|down)\b",
                     re.IGNORECASE)


def _pick_target(toolbox: PLCToolbox, message: str) -> str:
    """Pick the most plausible output tag mentioned in the message."""
    ml = message.lower()
    # explicit tag name present in the project?
    candidates = [t.name for t in toolbox.project.tags if t.name.lower() in ml]
    if candidates:
        candidates.sort(key=len, reverse=True)
        return candidates[0]
    if "press" in ml or "cycl" in ml or "machine" in ml or "down" in ml:
        return "Press_Cycle_Start"
    return "Press_Cycle_Start"


async def _run_mock(toolbox: PLCToolbox, message: str, audience: str) -> AsyncIterator[Dict]:
    cites: List[Dict] = []
    seen: set = set()

    if _WHY_RE.search(message):
        target = _pick_target(toolbox, message)
        args = {"target": target}
        yield {"type": "tool_call", "tool": "trace_blockers", "args": args}
        result = dispatch(toolbox, "trace_blockers", args)
        _collect_result_citations("trace_blockers", result, cites, seen)
        yield _summary_frame("trace_blockers", args, result)

        # template the failing path into text
        paths = result.get("failing_paths") or []
        if paths:
            p = paths[0]
            chain = " -> ".join(p.get("chain") or []) or target
            leaf = p.get("leaf_tag") or "?"
            leaf_cite = None
            for n in p.get("nodes", []):
                if n.get("cite"):
                    leaf_cite = n["cite"]
            cite_str = ""
            if leaf_cite:
                cite_str = f" ({leaf_cite['program']} / {leaf_cite['routine']} rung {leaf_cite['rung_number']})"
            text = (f"[mock] {target} is blocked. Failing chain: {chain}. "
                    f"The blocking condition is {leaf}{cite_str}.")
            ann = (p.get("leaf_annotation") or "").strip()
            if ann:
                text += f" Note: {ann}"
        elif result.get("root_satisfied") is True:
            text = f"[mock] {target} is satisfied — no blocking condition under the current values."
        else:
            text = (f"[mock] Traced {target}; interlock tree returned "
                    f"(no live values to evaluate a failing path).")
        for chunk in _chunk(text):
            yield {"type": "text_delta", "text": chunk}
    else:
        args: Dict = {}
        yield {"type": "tool_call", "tool": "get_project_summary", "args": args}
        result = dispatch(toolbox, "get_project_summary", args)
        _collect_result_citations("get_project_summary", result, cites, seen)
        yield _summary_frame("get_project_summary", args, result)
        c = result.get("controller", {})
        counts = result.get("counts", {})
        progs = ", ".join(p["name"] for p in result.get("programs", []))
        text = (f"[mock] Controller {c.get('name')} ({c.get('processor_type')}): "
                f"{counts.get('tags')} tags across {counts.get('programs')} programs "
                f"({progs}), {counts.get('aois')} AOIs. "
                f"This is the PressLine_3 cell — infeed, transfer, hydraulic press, outfeed.")
        for chunk in _chunk(text):
            yield {"type": "text_delta", "text": chunk}

    if cites:
        yield {"type": "citations", "citations": cites}
    yield {"type": "done", "stop_reason": "end_turn", "text": text}


def _chunk(text: str, size: int = 48):
    for i in range(0, len(text), size):
        yield text[i:i + size]


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────

async def run_chat(toolbox: PLCToolbox, message: str, audience: str = "maintenance",
                   model: Optional[str] = None,
                   mock: Optional[bool] = None,
                   provider: Optional[str] = None) -> AsyncIterator[Dict]:
    """Stream frames for one user message.

    ``mock=True/False`` (legacy arg) still forces mock / the API loop;
    otherwise ``provider`` or environment resolution picks the model source.
    """
    if mock is True:
        chosen = "mock"
    elif mock is False:
        chosen = "api"
    else:
        chosen = provider or resolve_provider()

    if chosen == "mock":
        async for frame in _run_mock(toolbox, message, audience):
            yield frame
    elif chosen == "subscription":
        async for frame in _run_subscription(toolbox, message, audience,
                                             model or DEFAULT_MODEL):
            yield frame
    else:
        async for frame in _run_real(toolbox, message, audience, model or DEFAULT_MODEL):
            yield frame
