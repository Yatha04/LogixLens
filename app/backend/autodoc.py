"""
autodoc.py – Deliverable 1: Auto-documentation ("the leave-behind") for Ask the PLC.

Undocumented tags (in the real automotive donor file, ~46% coverage) are
billable-hours drudgery for an integrator. ``generate_autodoc`` proposes a
short description for each undocumented tag and returns a reviewable row per
tag: ``{tag, data_type, scope, current_description, proposed_description,
confidence}``.

Same provider model as chat.py — mock | api | subscription — resolved by
``chat.resolve_provider``, all driving one pipeline:
- **api**: batches ~30 tags per Anthropic API call, each tag carrying rich
  context reused straight from :class:`PLCToolbox` (``get_tag`` for cited
  reads/writes, ``get_rung`` for the rung text snippet at each citation).
  The model returns strict JSON confidence-rated proposals.
- **subscription**: identical prompt and parsing, but the batch goes through
  the Claude Agent SDK one-shot ``query()`` on the local Claude Code login —
  real proposals, zero API billing.
- **mock** (``ASKPLC_MOCK=1``): a deterministic heuristic derived from the
  tag name (CamelCase/underscore word-split) plus the first usage
  instruction, always ``confidence="low"``. No network call, but it walks
  the exact same tag-selection / context-gathering / row-shaping code as the
  real paths, so the pipeline is genuinely exercised in tests.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from typing import Dict, List, Optional

from .plc_tools import PLCToolbox
from .chat import resolve_provider

# Anthropic recommends keeping batches modest so context stays cheap and the
# model doesn't drop tags from a long list; ~30 tags/call matches the design doc.
BATCH_SIZE = 30
DEFAULT_MODEL = os.environ.get("ASKPLC_MODEL", "claude-sonnet-5")


def is_mock() -> bool:
    return resolve_provider() == "mock"


def _lc(s: Optional[str]) -> str:
    return (s or "").strip().lower()


# ──────────────────────────────────────────────────────────────────────
# Tag name tokenizer (shared by the mock heuristic and the real-mode prompt)
# ──────────────────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


def split_words(name: str) -> List[str]:
    """CamelCase / underscore / dot-aware tokenizer.

    ``'GuardDoor_Closed'`` -> ``['Guard', 'Door', 'Closed']``;
    ``'PLC_IO.Data'`` -> ``['PLC', 'IO', 'Data']``.
    """
    parts = re.split(r"[_\-.]+", name)
    words: List[str] = []
    for part in parts:
        if not part:
            continue
        found = _WORD_RE.findall(part)
        words.extend(found if found else [part])
    return words


# ──────────────────────────────────────────────────────────────────────
# Context gathering (reuses PLCToolbox — the "ground truth" tools layer)
# ──────────────────────────────────────────────────────────────────────

def _usage_context(toolbox: PLCToolbox, tag_name: str, limit: int = 3) -> List[Dict]:
    """Cited usage snippets for a tag: instruction + a rung-text excerpt.

    Reuses :meth:`PLCToolbox.get_tag` (member-level cross-reference) and
    :meth:`PLCToolbox.get_rung` (raw rung text) — no new analysis code.
    """
    detail = toolbox.get_tag(tag_name)
    if "error" in detail:
        return []
    out: List[Dict] = []
    seen = set()
    for entry in detail["usage"]["writes"] + detail["usage"]["reads"]:
        cite = entry["cite"]
        key = (cite["program"], cite["routine"], cite["rung_number"])
        if key in seen:
            continue
        seen.add(key)
        rung = toolbox.get_rung(cite["program"], cite["routine"], cite["rung_number"])
        out.append({
            "instruction": entry["instruction"],
            "cite": cite,
            "rung_text": (rung.get("text") or "")[:160],
        })
        if len(out) >= limit:
            break
    return out


def _target_tags(toolbox: PLCToolbox, tags: Optional[List[str]]):
    """Undocumented tags to propose for, optionally scoped to ``tags``."""
    undocumented = {t.name.lower(): t for t in toolbox.project.undocumented_tags}
    if tags:
        out = []
        for name in tags:
            t = undocumented.get(_lc(name))
            if t is not None:
                out.append(t)
        return out
    return list(toolbox.project.undocumented_tags)


# ──────────────────────────────────────────────────────────────────────
# Mock mode: deterministic name + usage heuristic
# ──────────────────────────────────────────────────────────────────────

_WRITE_INSTRUCTIONS = {"OTE", "OTL", "OTU", "MOV", "CTU", "CTD", "TON", "TOF"}
_READ_INSTRUCTIONS = {"XIC", "XIO", "EQU", "NEQ", "GEQ", "LEQ", "GRT", "LES"}


def _heuristic_description(toolbox: PLCToolbox, tag) -> str:
    phrase = " ".join(split_words(tag.name)).strip() or tag.name
    ctx = _usage_context(toolbox, tag.name, limit=1)
    if not ctx:
        return f"{phrase} (inferred from tag name; no usage found in logic)."
    instr = ctx[0]["instruction"].upper()
    cite = ctx[0]["cite"]
    if instr in _WRITE_INSTRUCTIONS:
        verb = "written"
    elif instr in _READ_INSTRUCTIONS:
        verb = "read as a condition"
    else:
        verb = "referenced"
    return (
        f"{phrase} (inferred from tag name) — {verb} via {instr} in "
        f"{cite['program']}/{cite['routine']} rung {cite['rung_number']}."
    )


def _mock_proposals(toolbox: PLCToolbox, targets: List) -> List[Dict]:
    return [
        {
            "tag": t.name,
            "data_type": t.data_type,
            "scope": t.scope,
            "current_description": t.description or "",
            "proposed_description": _heuristic_description(toolbox, t),
            "confidence": "low",
        }
        for t in targets
    ]


# ──────────────────────────────────────────────────────────────────────
# Real mode: batched Anthropic calls
# ──────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are documenting undocumented tags in an industrial Rockwell/Allen-Bradley "
    "PLC program for a maintenance handbook. You will receive a JSON array of tag "
    "records (name, data type, scope, and up to 3 cited usage snippets: instruction "
    "+ rung text). For EACH tag, propose a short (<=12 word) plain-English "
    "description grounded ONLY in the tag name and the given usage context — never "
    "invent a physical function the context doesn't support.\n\n"
    "Return STRICT JSON ONLY (no markdown fences, no prose): a list of objects "
    '{"tag": <str>, "proposed_description": <str>, "confidence": "high"|"medium"|"low"}, '
    "one per input tag, same order. confidence=\"high\" only if the usage context "
    "clearly implies a specific physical device or function; \"medium\" if plausible "
    "from name + context; \"low\" if you are largely guessing from the name alone."
)


def _extract_json(text: str) -> str:
    """Strip an optional ```json ... ``` fence, if the model added one anyway."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"```\s*$", "", t)
    return t.strip()


def _tag_payload(toolbox: PLCToolbox, t) -> Dict:
    return {
        "tag": t.name,
        "data_type": t.data_type,
        "scope": t.scope,
        "is_aoi_instance": _lc(t.data_type) in toolbox._aoi_names,
        "usage": _usage_context(toolbox, t.name),
    }


def _parse_batch_text(text: str) -> Dict[str, Dict]:
    """Parse the model's strict-JSON proposal list into {tag: item}."""
    try:
        data = json.loads(_extract_json(text))
    except (json.JSONDecodeError, ValueError):
        data = []
    out: Dict[str, Dict] = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("tag"):
                out[item["tag"]] = item
    return out


async def _propose_batch_real(toolbox: PLCToolbox, batch: List, model: str) -> Dict[str, Dict]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()
    items = [_tag_payload(toolbox, t) for t in batch]
    resp = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(items)}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return _parse_batch_text(text)


async def _propose_batch_subscription(toolbox: PLCToolbox, batch: List,
                                      model: str) -> Dict[str, Dict]:
    """Same batch prompt, answered by the local Claude Code login (Agent SDK).

    One-shot generation: no tools, the payload already carries all context.
    """
    from claude_agent_sdk import (
        AssistantMessage, ClaudeAgentOptions, TextBlock, query,
    )
    from .chat import _SDK_DISALLOWED

    items = [_tag_payload(toolbox, t) for t in batch]
    options = ClaudeAgentOptions(
        system_prompt=_SYSTEM_PROMPT,
        disallowed_tools=_SDK_DISALLOWED,
        max_turns=2,
        model=model,
    )
    text = ""
    async for msg in query(prompt=json.dumps(items), options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    text += block.text
    return _parse_batch_text(text)


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────

async def generate_autodoc(toolbox: PLCToolbox, tags: Optional[List[str]] = None,
                           mock: Optional[bool] = None) -> List[Dict]:
    """Return proposal rows for the undocumented tags (optionally scoped to ``tags``)."""
    if mock is True:
        provider = "mock"
    elif mock is False:
        provider = "api"
    else:
        provider = resolve_provider()
    targets = _target_tags(toolbox, tags)
    if not targets:
        return []

    if provider == "mock":
        return _mock_proposals(toolbox, targets)

    propose = (_propose_batch_subscription if provider == "subscription"
               else _propose_batch_real)
    proposals_by_tag: Dict[str, Dict] = {}
    for i in range(0, len(targets), BATCH_SIZE):
        batch = targets[i:i + BATCH_SIZE]
        proposals_by_tag.update(await propose(toolbox, batch, DEFAULT_MODEL))

    out = []
    for t in targets:
        item = proposals_by_tag.get(t.name, {})
        out.append({
            "tag": t.name,
            "data_type": t.data_type,
            "scope": t.scope,
            "current_description": t.description or "",
            "proposed_description": item.get("proposed_description", ""),
            "confidence": item.get("confidence") if item.get("confidence") in
            ("high", "medium", "low") else "low",
        })
    return out


# ──────────────────────────────────────────────────────────────────────
# CSV export
# ──────────────────────────────────────────────────────────────────────

CSV_COLUMNS = ["tag", "current_description", "proposed_description", "confidence"]


def to_csv(rows: List[Dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()
