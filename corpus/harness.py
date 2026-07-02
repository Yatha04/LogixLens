#!/usr/bin/env python3
"""
corpus/harness.py — Baseline pipeline runner over the real-world L5X corpus.

For every file in corpus/files/ (driven by manifest.json), runs the full
LogixLens pipeline stage by stage, catching everything, and produces:

  corpus/report.json  — machine-readable per-file, per-stage results
  corpus/REPORT.md    — human summary: composition, pass rates, and a ranked
                        hardening worklist of distinct failure signatures

Stages per file
---------------
  load       load_l5x()
  parse      parse_project() + entity counts
  rungs      parse_rung() on every RLL rung text individually — coverage % and
             distinct failure signatures (the hardening targets)
  diagnosis  (controller files only) build_condition_tree + to_dict +
             json.dumps on up to 10 written tags from the cross-reference

This harness never modifies parser code and never fixes anything — it is the
measuring stick. Run it twice; results must be identical.

Usage:
    ../l5x-copilot/.venv/bin/python harness.py            # full corpus
    ../l5x-copilot/.venv/bin/python harness.py --only <filename-substring>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
FILES_DIR = CORPUS_DIR / "files"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"
REPORT_JSON = CORPUS_DIR / "report.json"
REPORT_MD = CORPUS_DIR / "REPORT.md"

# Make l5x-copilot importable (src layout, no install step).
sys.path.insert(0, str(CORPUS_DIR.parent / "l5x-copilot"))

from src.parser.l5x_loader import load_l5x  # noqa: E402
from src.parser.project_model import parse_project  # noqa: E402
from src.parser.rung_parser import parse_rung  # noqa: E402
from src.analysis import build_condition_tree  # noqa: E402

SLOW_FILE_S = 5.0
MAX_DIAG_TARGETS = 10

_NUM_RE = re.compile(r"\b\d+\b")
_QUOTED_RE = re.compile(r"'[^']{1,60}'|\"[^\"]{1,60}\"")
_HEXPOS_RE = re.compile(r"position \S+")


def signature(exc: BaseException) -> str:
    """Normalize an exception into a dedupe-able failure signature."""
    msg = str(exc)
    msg = _QUOTED_RE.sub("<id>", msg)
    msg = _HEXPOS_RE.sub("position <n>", msg)
    msg = _NUM_RE.sub("<n>", msg)
    return f"{type(exc).__name__}: {msg[:140]}"


def tb_tail(limit: int = 6) -> str:
    return "".join(traceback.format_exception(*sys.exc_info(), limit=-limit))[-1500:]


def run_file(path: Path, classification: str) -> dict:
    result: dict = {"file": path.name, "classification": classification, "stages": {}}
    t0 = time.perf_counter()

    # Stage 1: load
    try:
        load_l5x(str(path))
        result["stages"]["load"] = {"ok": True}
    except Exception as e:
        result["stages"]["load"] = {"ok": False, "sig": signature(e), "tb": tb_tail()}
        result["elapsed_s"] = round(time.perf_counter() - t0, 3)
        return result

    # Stage 2: parse_project
    try:
        project = parse_project(str(path))
        rll_rungs = [
            (prog.name, r.name, rung)
            for prog in project.programs
            for r in prog.routines
            if r.routine_type == "RLL"
            for rung in r.rungs
        ]
        result["stages"]["parse"] = {
            "ok": True,
            "counts": {
                "tags": len(project.tags),
                "programs": len(project.programs),
                "routines": sum(len(p.routines) for p in project.programs),
                "rll_rungs": len(rll_rungs),
                "modules": len(project.modules),
                "aois": len(project.aois),
                "udts": len(project.udts),
            },
        }
    except Exception as e:
        result["stages"]["parse"] = {"ok": False, "sig": signature(e), "tb": tb_tail()}
        result["elapsed_s"] = round(time.perf_counter() - t0, 3)
        return result

    # Stage 3: per-rung parse coverage. parse_project is now tolerant —
    # rungs whose text fails to parse land in project.rung_parse_errors
    # instead of failing the project. An unhandled exception is a FAILURE;
    # a recorded bad rung is a DEGRADATION (tracked, reported, not fatal).
    rung_fail_sigs: Counter = Counter()
    rung_fail_examples: dict[str, str] = {}
    errs = getattr(project, "rung_parse_errors", {}) or {}
    for (pn, rn, num), msg in errs.items():
        norm = _NUM_RE.sub("<n>", _QUOTED_RE.sub("<id>", msg))[:140]
        sig = f"RungParseError(recorded): {norm}"
        rung_fail_sigs[sig] += 1
        rung_fail_examples.setdefault(sig, f"{pn}/{rn}#{num}")
    total_rungs = len(rll_rungs)
    ok_rungs = len(project.parsed_rungs)
    result["stages"]["rungs"] = {
        "ok": True,
        "degraded": bool(errs),
        "total": total_rungs,
        "parsed": ok_rungs,
        "coverage": round(ok_rungs / total_rungs, 4) if total_rungs else None,
        "fail_sigs": dict(rung_fail_sigs),
        "fail_examples": rung_fail_examples,
    }

    # Stage 4: diagnosis on written tags (controller files only)
    if classification == "controller":
        diag: dict = {"targets": 0, "ok": 0, "failures": {}}
        written = [
            name
            for name, usage in project.cross_reference.items()
            if any("write" in u.access for u in usage.usages)
        ][:MAX_DIAG_TARGETS]
        for tag in written:
            diag["targets"] += 1
            try:
                tree = build_condition_tree(tag, project)
                json.dumps(tree.to_dict())
                diag["ok"] += 1
            except Exception as e:
                sig = signature(e)
                diag["failures"].setdefault(sig, {"count": 0, "example": tag, "tb": tb_tail()})
                diag["failures"][sig]["count"] += 1
        diag["all_ok"] = diag["targets"] == diag["ok"]
        result["stages"]["diagnosis"] = diag

    result["elapsed_s"] = round(time.perf_counter() - t0, 3)
    return result


def build_markdown(results: list[dict], manifest_by_file: dict) -> str:
    comp = Counter(r["classification"] for r in results)
    lines = ["# Corpus Baseline Report", ""]
    lines.append(f"Files: **{len(results)}** — " + ", ".join(f"{k}: {v}" for k, v in comp.most_common()))
    lines.append("")

    # Stage pass rates
    lines.append("## Stage pass rates")
    lines.append("")
    lines.append("| stage | applicable | pass | rate |")
    lines.append("|---|---|---|---|")
    for stage in ("load", "parse", "rungs", "diagnosis"):
        app = [r for r in results if stage in r["stages"]]
        if stage == "diagnosis":
            ok = [r for r in app if r["stages"][stage].get("all_ok")]
        else:
            ok = [r for r in app if r["stages"][stage].get("ok")]
        rate = f"{100 * len(ok) / len(app):.0f}%" if app else "—"
        lines.append(f"| {stage} | {len(app)} | {len(ok)} | {rate} |")
    lines.append("")

    # Rung coverage aggregate
    tot = sum(r["stages"].get("rungs", {}).get("total") or 0 for r in results)
    parsed = sum(r["stages"].get("rungs", {}).get("parsed") or 0 for r in results)
    if tot:
        lines.append(f"**Aggregate rung parse coverage: {parsed}/{tot} ({100 * parsed / tot:.2f}%)**")
        lines.append("")

    # Controller files table
    ctrl = [r for r in results if r["classification"] == "controller"]
    if ctrl:
        lines.append("## Full-project (controller) files")
        lines.append("")
        lines.append("| file | repo | tags | rungs | coverage | diagnosis | time |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in ctrl:
            m = manifest_by_file.get(r["file"], {})
            c = r["stages"].get("parse", {}).get("counts", {})
            rg = r["stages"].get("rungs", {})
            dg = r["stages"].get("diagnosis", {})
            cov = f"{100 * (rg.get('coverage') or 0):.1f}%" if rg.get("total") else "—"
            dstr = f"{dg.get('ok', 0)}/{dg.get('targets', 0)}" if dg else "—"
            lines.append(
                f"| {r['file'][:40]} | {m.get('repo', '?')} | {c.get('tags', '—')} "
                f"| {rg.get('total', '—')} | {cov} | {dstr} | {r.get('elapsed_s')}s |"
            )
        lines.append("")

    # Ranked hardening worklist
    lines.append("## Hardening worklist (ranked distinct failure signatures)")
    lines.append("")
    agg: dict[str, dict] = defaultdict(lambda: {"files": set(), "count": 0, "example": "", "stage": ""})
    for r in results:
        for stage in ("load", "parse"):
            s = r["stages"].get(stage)
            if s and not s.get("ok"):
                a = agg[s["sig"]]
                a["files"].add(r["file"]); a["count"] += 1
                a["stage"] = stage
                a["example"] = a["example"] or f"{r['file']}\n```\n{s.get('tb', '')[-600:]}\n```"
        rg = r["stages"].get("rungs", {})
        for sig, n in rg.get("fail_sigs", {}).items():
            a = agg[sig]
            a["files"].add(r["file"]); a["count"] += n
            a["stage"] = "rungs"
            a["example"] = a["example"] or f"`{rg['fail_examples'].get(sig, '')}`"
        dg = r["stages"].get("diagnosis", {})
        for sig, info in dg.get("failures", {}).items():
            a = agg[sig]
            a["files"].add(r["file"]); a["count"] += info["count"]
            a["stage"] = "diagnosis"
            a["example"] = a["example"] or f"{r['file']} target `{info['example']}`\n```\n{info.get('tb', '')[-600:]}\n```"
    if not agg:
        lines.append("*(no failures — corpus fully green)*")
    for i, (sig, a) in enumerate(
        sorted(agg.items(), key=lambda kv: (len(kv[1]["files"]), kv[1]["count"]), reverse=True), 1
    ):
        lines.append(f"### {i}. [{a['stage']}] `{sig}`")
        lines.append(f"- occurrences: {a['count']} across {len(a['files'])} file(s)")
        lines.append(f"- files: {', '.join(sorted(a['files'])[:6])}{' …' if len(a['files']) > 6 else ''}")
        lines.append(f"- example: {a['example']}")
        lines.append("")

    # Timing outliers
    slow = [r for r in results if r.get("elapsed_s", 0) > SLOW_FILE_S]
    if slow:
        lines.append("## Timing outliers (>5s)")
        for r in sorted(slow, key=lambda x: -x["elapsed_s"]):
            lines.append(f"- {r['file']}: {r['elapsed_s']}s")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="filename substring filter")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest_by_file = {e["filename"]: e for e in manifest}

    results = []
    for entry in manifest:
        fname = entry["filename"]
        if args.only and args.only not in fname:
            continue
        path = FILES_DIR / fname
        if not path.exists():
            results.append({"file": fname, "classification": entry.get("classification", "?"),
                            "stages": {"load": {"ok": False, "sig": "FileNotFoundError: missing from files/"}}})
            continue
        results.append(run_file(path, entry.get("classification", "?")))
        print(f"[{len(results)}/{len(manifest)}] {fname}: "
              + ", ".join(f"{k}={'ok' if v.get('ok', v.get('all_ok', True)) else 'FAIL'}"
                          for k, v in results[-1]["stages"].items()))

    REPORT_JSON.write_text(json.dumps(results, indent=1))
    REPORT_MD.write_text(build_markdown(results, manifest_by_file))
    print(f"\nWrote {REPORT_JSON} and {REPORT_MD}")

    n_fail = sum(
        1 for r in results
        for k, v in r["stages"].items()
        if not v.get("ok", v.get("all_ok", True))
    )
    print(f"Files: {len(results)}, stage failures: {n_fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
