"""
run_eval_cli.py – Gold Q&A eval harness driven by headless Claude Code.

Same expected-evidence assertions as run_eval.py, but instead of calling the
Anthropic API directly, each question is answered by ``claude -p`` with the
LogixLens MCP server attached (--mcp-config / --strict-mcp-config). Tokens are
paid by the local Claude subscription — no ANTHROPIC_API_KEY needed.

The MCP tool names arrive as ``mcp__plc__<tool>``; the prefix is stripped so
the same ``tools_any`` / ``tools_all`` assertions work across both harnesses.
Citations have no structured frame here, so ``cites_routine`` is checked
against the answer text.

Question files may set per-question ``l5x`` (path relative to repo root) and
``snapshot``; ``defaults:`` at the top of the file applies to all questions.
Every transcript is saved under eval/transcripts/ (gitignored) for review.

Run (from repo root):
    ./l5x-copilot/.venv/bin/python -m app.backend.eval.run_eval_cli
    ./l5x-copilot/.venv/bin/python -m app.backend.eval.run_eval_cli \
        --questions app/backend/eval/corpus_questions.yaml --only grain
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.backend.plc_tools import DEFAULT_L5X  # noqa: E402
from app.backend.prompts import build_system_prompt  # noqa: E402

GOLD = Path(__file__).resolve().parent / "gold_questions.yaml"
TRANSCRIPT_DIR = Path(__file__).resolve().parent / "transcripts"
VENV_PYTHON = _REPO_ROOT / "l5x-copilot" / ".venv" / "bin" / "python"
TOOL_PREFIX = "mcp__plc__"


def _mcp_config(l5x: str | None, snapshot: str | None) -> str:
    args = ["-m", "app.backend.mcp_server"]
    if l5x:
        args += ["--l5x", str((_REPO_ROOT / l5x).resolve())]
    if snapshot:
        args += ["--snapshot", snapshot]
    return json.dumps({
        "mcpServers": {
            "plc": {
                "command": str(VENV_PYTHON),
                "args": args,
                "cwd": str(_REPO_ROOT),
            }
        }
    })


def ask(question: str, *, l5x: str | None, snapshot: str | None,
        audience: str, model: str, max_turns: int, timeout: int):
    """Run one question through headless claude. Returns (tools, text, meta)."""
    cmd = [
        "claude", "-p", question,
        "--mcp-config", _mcp_config(l5x, snapshot),
        "--strict-mcp-config",
        "--allowedTools", "mcp__plc",
        "--disallowedTools", "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task",
        "--model", model,
        "--max-turns", str(max_turns),
        "--output-format", "stream-json",
        "--verbose",
        "--append-system-prompt", build_system_prompt(audience),
    ]
    t0 = time.time()
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=_REPO_ROOT,
    )
    elapsed = round(time.time() - t0, 1)

    tools_used: list[str] = []
    text = ""
    meta = {"elapsed_s": elapsed, "num_turns": None, "events": []}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        meta["events"].append(ev)
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    name = block.get("name", "")
                    tools_used.append(name.removeprefix(TOOL_PREFIX))
        elif ev.get("type") == "result":
            text = ev.get("result") or ""
            meta["num_turns"] = ev.get("num_turns")
            meta["is_error"] = ev.get("is_error", False)
    if not text and proc.returncode != 0:
        meta["is_error"] = True
        text = f"[claude exited {proc.returncode}] {proc.stderr[-500:]}"
    return tools_used, text, meta


def check(q: dict, tools_used: list[str], text: str):
    """Same expected-evidence assertions as run_eval.py."""
    exp = q.get("expect", {})
    text_lc = text.lower()
    checks = []

    any_tools = exp.get("tools_any")
    if any_tools:
        ok = any(t in tools_used for t in any_tools)
        checks.append((f"tools_any {any_tools}", ok, f"used={tools_used}"))

    all_tools = exp.get("tools_all")
    if all_tools:
        ok = all(t in tools_used for t in all_tools)
        checks.append((f"tools_all {all_tools}", ok, f"used={tools_used}"))

    for sub in exp.get("answer_contains", []):
        checks.append((f"answer contains '{sub}'", sub.lower() in text_lc, ""))

    any_subs = exp.get("answer_contains_any")
    if any_subs:
        ok = any(s.lower() in text_lc for s in any_subs)
        checks.append((f"answer contains any of {any_subs}", ok, ""))

    for sub in exp.get("answer_not_contains", []):
        checks.append((f"answer avoids '{sub}'", sub.lower() not in text_lc, ""))

    cr = exp.get("cites_routine")
    if cr:
        checks.append((f"cites routine {cr}", cr.lower() in text_lc, ""))

    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(GOLD), help="Question YAML file.")
    ap.add_argument("--only", default=None, help="Run only question ids containing this substring.")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--timeout", type=int, default=360, help="Per-question timeout (s).")
    args = ap.parse_args()

    if not shutil.which("claude"):
        print("ERROR: `claude` CLI not found on PATH — install Claude Code and log in.")
        return 2

    data = yaml.safe_load(Path(args.questions).read_text())
    defaults = data.get("defaults", {})
    questions = data["questions"]
    if args.only:
        questions = [q for q in questions if args.only in q["id"]]

    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    print(f"=== Ask-the-PLC eval (claude CLI / {args.model}) — {len(questions)} questions ===\n")

    total = passed = 0
    q_results = []
    for q in questions:
        l5x = q.get("l5x", defaults.get("l5x"))
        snapshot = q.get("snapshot", defaults.get("snapshot"))
        if l5x is None and DEFAULT_L5X and not Path(DEFAULT_L5X).exists():
            print(f"[SKIP] {q['id']}  (default L5X not built — run `make demo-l5x`)")
            continue
        try:
            tools_used, text, meta = ask(
                q["question"], l5x=l5x, snapshot=snapshot,
                audience=q.get("audience", defaults.get("audience", "maintenance")),
                model=args.model, max_turns=args.max_turns, timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            tools_used, text, meta = [], "[timeout]", {"elapsed_s": args.timeout}

        (TRANSCRIPT_DIR / f"{q['id']}.json").write_text(json.dumps(
            {"question": q["question"], "l5x": l5x, "snapshot": snapshot,
             "tools_used": tools_used, "answer": text, **meta}, indent=1))

        checks = check(q, tools_used, text)
        q_ok = all(ok for _, ok, _ in checks)
        q_results.append((q["id"], q_ok))
        for name, ok, detail in checks:
            total += 1
            passed += 1 if ok else 0
            mark = "ok " if ok else "XX "
            line = f"  [{mark}] {name}"
            if not ok and detail:
                line += f"   <{detail}>"
            print(line)
        head = "PASS" if q_ok else "FAIL"
        print(f"[{head}] {q['id']}  ({meta.get('elapsed_s')}s, "
              f"{meta.get('num_turns')} turns): \"{q['question']}\"\n")

    print("=" * 60)
    print(f"Questions run: {len(q_results)}")
    print(f"Checks: {passed}/{total} passed")
    failed_q = [i for i, ok in q_results if not ok]
    if failed_q:
        print("FAILED questions:", ", ".join(failed_q))
    all_ok = passed == total and total > 0
    print("VERDICT:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
