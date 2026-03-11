"""
conftest.py – Shared pytest fixtures for LogixLens tests.

Usage
-----
Pass the L5X file on the command line:
    python -m pytest tests/ --l5x-file path/to/program.L5X

If you omit --l5x-file, pytest will prompt you to enter the path
interactively before the first test runs.

A summary report is written to tests/test_results.md after each run.
"""
import pytest
import os
from datetime import datetime
from src.parser.l5x_loader import load_l5x, L5XProject
from src.parser.module_extractor import extract_modules
from src.parser.routine_extractor import extract_programs
from src.parser.tag_extractor import extract_tags


# ---------------------------------------------------------------------------
# CLI option
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--l5x-file",
        action="store",
        default=None,
        help="Absolute or relative path to the .L5X file used for integration tests.",
    )


# ---------------------------------------------------------------------------
# Session-scoped fixture – loads the file once for the entire test run
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def l5x_project(request) -> L5XProject:
    """Load a real L5X file and return a loaded L5XProject.

    The file path comes from --l5x-file.  If that option was not passed,
    the user is prompted interactively (once per session).
    """
    path = request.config.getoption("--l5x-file")

    if not path:
        path = input(
            "\n[LogixLens] No --l5x-file provided.\n"
            "Enter the path to the .L5X file to test against: "
        ).strip()

    if not path:
        pytest.exit(
            "No L5X file path provided. Re-run with --l5x-file <path>.",
            returncode=1,
        )

    path = os.path.abspath(os.path.expanduser(path))

    if not os.path.isfile(path):
        pytest.exit(
            f"L5X file not found: {path}\n"
            "Check the path and try again.",
            returncode=1,
        )

    print(f"\n[LogixLens] Loading: {path}")
    project = load_l5x(path)

    # ── Collect summary stats into the pytest config stash so the
    # session-finish hook can write the report ──────────────────────────
    stats = request.config._logixlens_stats = {}

    m = project.metadata
    stats["file"]           = path
    stats["controller"]     = m.controller_name
    stats["processor"]      = m.processor_type
    stats["revision"]       = f"{m.major_revision}.{m.minor_revision}"
    stats["sw_revision"]    = m.software_revision

    modules = extract_modules(project)
    stats["module_count"]   = len(modules)
    stats["module_names"]   = [mod.name for mod in modules]

    tags = extract_tags(project)
    ctrl_tags = [t for t in tags if t.scope == "Controller"]
    prog_tags = [t for t in tags if t.scope != "Controller"]
    alias_tags = [t for t in tags if t.tag_type == "Alias"]
    stats["tag_total"]      = len(tags)
    stats["tag_controller"] = len(ctrl_tags)
    stats["tag_program"]    = len(prog_tags)
    stats["tag_alias"]      = len(alias_tags)

    # Sample: most common data types
    from collections import Counter
    type_counter = Counter(t.data_type for t in tags)
    stats["top_data_types"] = type_counter.most_common(5)

    programs = extract_programs(project)
    all_routines = [r for p in programs for r in p.routines]
    rll = [r for r in all_routines if r.routine_type == "RLL"]
    st  = [r for r in all_routines if r.routine_type == "ST"]
    sfc = [r for r in all_routines if r.routine_type == "SFC"]

    stats["program_count"]      = len(programs)
    stats["program_names"]      = [p.name for p in programs]
    stats["routine_total"]      = len(all_routines)
    stats["routine_rll"]        = len(rll)
    stats["routine_st"]         = len(st)
    stats["routine_sfc"]        = len(sfc)

    total_rungs = sum(len(r.rungs) for r in rll)
    total_lines = sum(len(r.lines) for r in st)
    stats["total_rungs"]        = total_rungs
    stats["total_st_lines"]     = total_lines

    # SFC detail
    if sfc:
        step_counts  = [len(r.sfc_content.steps)       for r in sfc if r.sfc_content]
        trans_counts = [len(r.sfc_content.transitions)  for r in sfc if r.sfc_content]
        link_counts  = [len(r.sfc_content.directed_links) for r in sfc if r.sfc_content]
        stats["sfc_total_steps"]       = sum(step_counts)
        stats["sfc_total_transitions"] = sum(trans_counts)
        stats["sfc_total_links"]       = sum(link_counts)
        stats["sfc_routine_names"]     = [r.name for r in sfc]
    else:
        stats["sfc_total_steps"]       = 0
        stats["sfc_total_transitions"] = 0
        stats["sfc_total_links"]       = 0
        stats["sfc_routine_names"]     = []

    return project


# ---------------------------------------------------------------------------
# Session-finish hook – write the markdown report
# ---------------------------------------------------------------------------

def pytest_sessionfinish(session, exitstatus):
    stats = getattr(session.config, "_logixlens_stats", None)
    if stats is None:
        return  # No real file was loaded (e.g. --collect-only)

    passed  = session.testscollected - session.testsfailed - getattr(session, "testsskipped", 0)
    failed  = session.testsfailed
    total   = session.testscollected

    # ── Resolve output path relative to the tests/ directory ─────────────
    tests_dir = os.path.join(os.path.dirname(__file__))
    out_path  = os.path.join(tests_dir, "test_results.md")

    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")

    lines = [
        "# LogixLens – Test Results",
        "",
        f"**Run:** {now}  ",
        f"**File:** `{stats['file']}`",
        "",
        "---",
        "",
        "## Controller",
        "",
        f"| Field | Value |",
        f"|---|---|",
        f"| Controller Name | `{stats['controller']}` |",
        f"| Processor Type  | `{stats['processor']}` |",
        f"| FW Revision     | `{stats['revision']}` |",
        f"| SW Revision     | `{stats['sw_revision']}` |",
        "",
        "---",
        "",
        "## Modules",
        "",
        f"**Total modules found:** {stats['module_count']}",
        "",
    ]

    if stats["module_names"]:
        lines.append("| # | Module Name |")
        lines.append("|---|---|")
        for i, name in enumerate(stats["module_names"], 1):
            lines.append(f"| {i} | `{name}` |")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines += [
        "## Tags",
        "",
        f"| Scope | Count |",
        f"|---|---|",
        f"| Controller-scoped | {stats['tag_controller']} |",
        f"| Program-scoped    | {stats['tag_program']} |",
        f"| Alias tags        | {stats['tag_alias']} |",
        f"| **Total**         | **{stats['tag_total']}** |",
        "",
        "**Top 5 data types used:**",
        "",
        "| Data Type | Occurrences |",
        "|---|---|",
    ]
    for dtype, count in stats["top_data_types"]:
        lines.append(f"| `{dtype}` | {count} |")

    lines += [
        "",
        "---",
        "",
        "## Programs & Routines",
        "",
        f"**Programs found:** {stats['program_count']}",
        "",
        "| Program Name |",
        "|---|",
    ]
    for name in stats["program_names"]:
        lines.append(f"| `{name}` |")

    lines += [
        "",
        f"**Total routines:** {stats['routine_total']}",
        "",
        "| Routine Type | Count |",
        "|---|---|",
        f"| Ladder (RLL)      | {stats['routine_rll']} |",
        f"| Structured Text   | {stats['routine_st']} |",
        f"| Seq. Function Chart (SFC) | {stats['routine_sfc']} |",
        "",
        f"**Total rungs (RLL):** {stats['total_rungs']}  ",
        f"**Total ST lines:** {stats['total_st_lines']}",
        "",
    ]

    if stats["routine_sfc"] > 0:
        lines += [
            "### SFC Detail",
            "",
            f"| Metric | Count |",
            f"|---|---|",
            f"| Steps       | {stats['sfc_total_steps']} |",
            f"| Transitions | {stats['sfc_total_transitions']} |",
            f"| Links       | {stats['sfc_total_links']} |",
            "",
            "**SFC Routines:**",
            "",
            "| Routine Name |",
            "|---|",
        ]
        for name in stats["sfc_routine_names"]:
            lines.append(f"| `{name}` |")
        lines.append("")

    lines += [
        "---",
        "",
        "## Test Run Summary",
        "",
        f"| Result | Count |",
        f"|---|---|",
        f"| ✅ Passed | {passed} |",
        f"| ❌ Failed | {failed} |",
        f"| Total     | {total} |",
        "",
        f"> {'✅ All tests passed.' if failed == 0 else f'❌ {failed} test(s) failed – review output above.'}",
        "",
    ]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n[LogixLens] Results written to: {out_path}")
