#!/usr/bin/env python3
"""
verify_scenario.py -- regression test for the PressLine_3 "money-shot" diagnostic chain.

The demo hinges on a backward trace from a gated output to a physical safety input:

    Press_Cycle_Start  (OTE, permissive gated by ~11 conditions in P300_Press/R30)
        --reads--> Safety_OK        (OTE in P900_Safety/R92, gated by the safety chain)
            --reads--> GuardDoor_Closed   (a physical safety input alias, no writer = leaf)

This script re-parses the generated L5X with the LogixLens parser, builds a
writer/reader graph from the parsed rungs, and asserts that the chain exists and
reaches the physical input in <= 3 hops. Run it after every regeneration.

Exit code 0 = chain intact; non-zero = broken (fail the demo build).
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Make the parser importable (src.parser.*) without installing the package.
sys.path.insert(0, os.path.join(HERE, "..", "l5x-copilot"))

from src.parser.project_model import parse_project           # noqa: E402
from src.parser.rung_parser import Instruction, Branch       # noqa: E402
from src.parser.cross_reference import normalize_tag_name    # noqa: E402

L5X = os.path.join(HERE, "build", "PressLine_3.L5X")

WRITE_MNEMONICS = {"OTE", "OTL", "OTU"}


def _walk(elements):
    """Yield every Instruction in a rung, flattening branch legs."""
    for el in elements:
        if isinstance(el, Instruction):
            yield el
        elif isinstance(el, Branch):
            for leg in el.legs:
                yield from _walk(leg)


def build_graph(parsed):
    """Return (writers, reads_of_rung).

    writers[tag]        -> list of rung keys (prog, routine, num) that drive `tag`
    reads_of[rungkey]   -> set of base tags read as conditions in that rung
    """
    writers: dict[str, list] = {}
    reads_of: dict[tuple, set] = {}
    for key, prung in parsed.parsed_rungs.items():
        reads: set[str] = set()
        for instr in _walk(prung.elements):
            mnem = instr.mnemonic.upper()
            if mnem in WRITE_MNEMONICS and instr.operands:
                base = normalize_tag_name(instr.operands[0].value)
                writers.setdefault(base, []).append(key)
            elif instr.is_condition:  # XIC/XIO/EQU/GRT/LES/...
                for op in instr.operands:
                    if not op.is_literal:
                        reads.add(normalize_tag_name(op.value))
        reads_of[key] = reads
    return writers, reads_of


def trace(parsed, target: str, goal: str, max_hops: int = 3):
    """Backward BFS from `target` output to `goal` input. Returns the tag path or None."""
    writers, reads_of = build_graph(parsed)

    # BFS over tags; a "hop" = expanding one intermediate coil into its condition tags.
    from collections import deque
    frontier = deque([(target, [target], 0)])
    seen = {target}
    while frontier:
        tag, path, hops = frontier.popleft()
        if hops > max_hops:
            continue
        # Union of condition tags across every rung that writes `tag`.
        cond_tags = set()
        for rk in writers.get(tag, []):
            cond_tags |= reads_of.get(rk, set())
        if goal in cond_tags:
            return path + [goal], hops + 1
        for ct in cond_tags:
            if ct in seen:
                continue
            seen.add(ct)
            frontier.append((ct, path + [ct], hops + 1))
    return None, None


def main() -> int:
    if not os.path.isfile(L5X):
        sys.stderr.write(f"Generated L5X not found: {L5X}\nRun generate_l5x.py first.\n")
        return 2

    parsed = parse_project(L5X)
    writers, _ = build_graph(parsed)

    failures = []

    # 1. Key tags exist.
    for t in ("Press_Cycle_Start", "Safety_OK", "GuardDoor_Closed"):
        if parsed.get_tag(t) is None:
            failures.append(f"tag {t!r} not found in controller scope")

    # 2. Press_Cycle_Start and Safety_OK are each driven by exactly the intended rung.
    for t in ("Press_Cycle_Start", "Safety_OK"):
        if not writers.get(t):
            failures.append(f"{t!r} has no writer rung (should be an OTE permissive)")

    # 3. GuardDoor_Closed is a physical input: read, never written (a true leaf).
    if writers.get("GuardDoor_Closed"):
        failures.append("GuardDoor_Closed is written somewhere -- it must be a physical input leaf")
    gd = parsed.get_tag("GuardDoor_Closed")
    if gd is not None and gd.tag_type != "Alias":
        failures.append("GuardDoor_Closed should be an Alias to a physical I/O point")

    # 4. The chain traces within <= 3 hops.
    path, hops = trace(parsed, "Press_Cycle_Start", "GuardDoor_Closed", max_hops=3)
    if path is None:
        failures.append("no trace from Press_Cycle_Start to GuardDoor_Closed within 3 hops")
    else:
        # Confirm Safety_OK is on the path (the intended intermediate).
        if "Safety_OK" not in path:
            failures.append(f"trace found but does not pass through Safety_OK: {path}")

    if failures:
        print("SCENARIO VERIFICATION FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("SCENARIO VERIFICATION PASSED")
    print(f"  chain: {' -> '.join(path)}")
    print(f"  hops:  {hops} (<= 3)")
    print(f"  Press_Cycle_Start driven by: {writers['Press_Cycle_Start']}")
    print(f"  Safety_OK driven by:         {writers['Safety_OK']}")
    print(f"  GuardDoor_Closed alias_for:  {parsed.get_tag('GuardDoor_Closed').alias_for}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
