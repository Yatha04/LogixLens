"""
run_eval.py – Gold Q&A eval harness for Ask the PLC.

Runs each gold question through the REAL chat tool-loop (the actual dispatch +
streaming machinery). Uses the real Claude model when ANTHROPIC_API_KEY is set,
otherwise the deterministic --mock model. Checks expected-evidence assertions
(which tool was used, evidence substrings in the answer, expected citation) and
prints a scoreboard.

Answer-content and citation checks are skipped for questions not marked
``mock_runnable`` when running in mock mode (the fake model can't satisfy them).
Tool-usage checks are always run for runnable questions.

Exit code 0 only if every RUNNABLE check passed.

Run:
    cd l5x-copilot
    ASKPLC_MOCK=1 ./.venv/bin/python -m app.backend.eval.run_eval      # from repo root works too
    ./.venv/bin/python -m app.backend.eval.run_eval --mock
    ./.venv/bin/python -m app.backend.eval.run_eval                    # real model if key present
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import yaml

# ensure repo root on path when run as a script
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.backend.plc_tools import (  # noqa: E402
    PLCToolbox, StaticSnapshotProvider, DEFAULT_L5X, SNAPSHOT_DIR,
)
from app.backend.chat import run_chat  # noqa: E402

GOLD = Path(__file__).resolve().parent / "gold_questions.yaml"
_TB_CACHE: dict = {}


def _toolbox(snapshot):
    key = snapshot or ""
    if key not in _TB_CACHE:
        prov = None
        if snapshot:
            prov = StaticSnapshotProvider(SNAPSHOT_DIR / f"{snapshot}.json")
        _TB_CACHE[key] = PLCToolbox(str(DEFAULT_L5X), live_provider=prov)
    return _TB_CACHE[key]


async def _collect(toolbox, question, audience, mock):
    tools_used, text, cites = [], "", []
    async for f in run_chat(toolbox, question, audience, mock=mock):
        t = f["type"]
        if t == "tool_call":
            tools_used.append(f["tool"])
        elif t == "text_delta":
            text += f["text"]
        elif t == "citations":
            cites = f["citations"]
        elif t == "done" and f.get("text"):
            if f["text"] not in text:
                text += f["text"]
    return tools_used, text, cites


def _check(q, tools_used, text, cites, mock):
    """Return (list of (name, ok, detail), runnable_bool)."""
    exp = q.get("expect", {})
    runnable = (not mock) or q.get("mock_runnable", False)
    checks = []
    if not runnable:
        return checks, False

    text_lc = text.lower()

    any_tools = exp.get("tools_any")
    if any_tools:
        ok = any(t in tools_used for t in any_tools)
        checks.append((f"tools_any {any_tools}", ok, f"used={tools_used}"))

    all_tools = exp.get("tools_all")
    if all_tools:
        ok = all(t in tools_used for t in all_tools)
        checks.append((f"tools_all {all_tools}", ok, f"used={tools_used}"))

    # answer-content checks (skipped in mock unless mock_runnable — already gated)
    for sub in exp.get("answer_contains", []):
        ok = sub.lower() in text_lc
        checks.append((f"answer contains '{sub}'", ok, ""))

    cr = exp.get("cites_routine")
    if cr:
        in_cites = any(c.get("routine") == cr for c in cites)
        ok = in_cites or cr.lower() in text_lc
        checks.append((f"cites routine {cr}", ok, f"cites={[c.get('routine') for c in cites][:6]}"))

    return checks, True


async def main_async(args):
    data = yaml.safe_load(GOLD.read_text())
    questions = data["questions"]
    mock = args.mock or not os.environ.get("ANTHROPIC_API_KEY")
    mode = "MOCK" if mock else "REAL"
    print(f"=== Ask-the-PLC eval ({mode} model) — {len(questions)} questions ===\n")

    total_checks = passed_checks = 0
    skipped = 0
    q_results = []

    for q in questions:
        tb = _toolbox(q.get("snapshot"))
        tools_used, text, cites = await _collect(
            tb, q["question"], q.get("audience", "maintenance"), mock)
        checks, runnable = _check(q, tools_used, text, cites, mock)
        if not runnable:
            skipped += 1
            print(f"[SKIP] {q['id']}  (not mock-runnable)")
            continue
        q_ok = all(ok for _, ok, _ in checks)
        q_results.append((q["id"], q_ok))
        for name, ok, detail in checks:
            total_checks += 1
            passed_checks += 1 if ok else 0
            mark = "ok " if ok else "XX "
            line = f"  [{mark}] {name}"
            if not ok and detail:
                line += f"   <{detail}>"
            print(line)
        head = "PASS" if q_ok else "FAIL"
        print(f"[{head}] {q['id']}: \"{q['question']}\"\n")

    print("=" * 60)
    print(f"Questions run: {len(q_results)}  (skipped {skipped})")
    print(f"Checks: {passed_checks}/{total_checks} passed")
    failed_q = [i for i, ok in q_results if not ok]
    if failed_q:
        print("FAILED questions:", ", ".join(failed_q))
    all_ok = passed_checks == total_checks and total_checks > 0
    print("VERDICT:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="Force the deterministic mock model.")
    args = ap.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
