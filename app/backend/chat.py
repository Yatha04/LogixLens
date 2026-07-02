"""
chat.py – The streaming tool-use loop for Ask the PLC.

``run_chat`` is an async generator that yields JSON-serializable frames as the
conversation progresses. It runs a real Claude tool-use loop over a
:class:`PLCToolbox` (direct Python tool calls — not MCP transport), or, in
``--mock`` mode (env ``ASKPLC_MOCK=1``), a deterministic fake model that still
exercises the *entire* real machinery: tool dispatch, frame streaming, citation
collection. Only the model call itself is faked.

Frame protocol (each frame is one dict):
  {"type": "text_delta", "text": str}
  {"type": "tool_call", "tool": str, "args": dict}
  {"type": "tool_result_summary", "tool": str, "args": dict, "result_bytes": int, "breadcrumb": str}
  {"type": "citations", "citations": [{"program","routine","rung_number"}, ...]}
  {"type": "done", "stop_reason": str, "text": str}
  {"type": "error", "message": str}
"""

from __future__ import annotations

import json
import os
import re
from typing import AsyncIterator, Dict, List, Optional

from .plc_tools import PLCToolbox
from .prompts import build_system_prompt
from .tools_schema import TOOL_SCHEMAS, dispatch

DEFAULT_MODEL = os.environ.get("ASKPLC_MODEL", "claude-sonnet-5")
MAX_TOOL_ITERATIONS = 8


def is_mock() -> bool:
    return os.environ.get("ASKPLC_MOCK") == "1"


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
            _collect_citations(result, cites, seen)
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
        _collect_citations(result, cites, seen)
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
        _collect_citations(result, cites, seen)
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
                   mock: Optional[bool] = None) -> AsyncIterator[Dict]:
    """Stream frames for one user message. Mock mode is chosen by ``mock`` arg,
    else by the ``ASKPLC_MOCK`` env var."""
    use_mock = is_mock() if mock is None else mock
    if use_mock:
        async for frame in _run_mock(toolbox, message, audience):
            yield frame
    else:
        async for frame in _run_real(toolbox, message, audience, model or DEFAULT_MODEL):
            yield frame
