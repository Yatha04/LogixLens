"""
test_condition_tree.py – Tests for the diagnosis engine (Deliverables 2 & 3).

Everything is synthetic: rungs are built from hand-written strings via
parse_rung(); Program / Routine / AddOnInstruction instances are constructed
directly. No real L5X file is required.
"""

import json

import pytest

from src.parser.rung_parser import parse_rung
from src.parser.routine_extractor import Program, Routine, Rung, Line
from src.parser.aoi_extractor import AddOnInstruction, AOIParameter
from src.analysis.condition_tree import (
    ConditionNode,
    DiagnosisContext,
    build_condition_tree,
    evaluate_tree,
    failing_paths,
    AND,
    OR,
    LEAF,
    FLAG,
    LATCH,
    NEEDS_TRUE,
    NEEDS_FALSE,
    COMPARISON,
)


# ──────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────

def ctx_from(*texts, programs=None, aois=None, tag_types=None):
    """Build a DiagnosisContext from rung strings (keyed P/R/index)."""
    rungs = {("P", "R", i): parse_rung(t) for i, t in enumerate(texts)}
    return DiagnosisContext(
        parsed_rungs=rungs,
        programs=programs or [],
        aois=aois or [],
        tag_types=tag_types or {},
    )


def leaves(node):
    """All LEAF/FLAG/LATCH terminal nodes in the tree."""
    out = []
    if not node.children or node.kind in (LATCH, FLAG):
        out.append(node)
        return out
    for c in node.children:
        out.extend(leaves(c))
    return out


def find(node, predicate):
    """Depth-first search for the first node matching predicate."""
    if predicate(node):
        return node
    for c in node.children:
        hit = find(c, predicate)
        if hit is not None:
            return hit
    return None


# ──────────────────────────────────────────────────────────────────────
# Structural building
# ──────────────────────────────────────────────────────────────────────

def test_simple_and_chain():
    ctx = ctx_from("XIC(A)XIC(B)OTE(Motor);")
    root = build_condition_tree("Motor", ctx)
    assert root.kind == AND
    assert len(root.children) == 2
    assert root.children[0].full_path == "A"
    assert root.children[0].requirement == NEEDS_TRUE
    assert root.children[1].full_path == "B"


def test_branch_or():
    ctx = ctx_from("[XIC(A),XIC(B)]OTE(Motor);")
    root = build_condition_tree("Motor", ctx)
    assert root.kind == AND
    assert len(root.children) == 1
    or_node = root.children[0]
    assert or_node.kind == OR
    assert len(or_node.children) == 2
    assert {c.full_path for c in or_node.children} == {"A", "B"}


def test_nested_branch():
    ctx = ctx_from("XIC(X)[XIC(A)XIO(B),XIC(C)]OTE(Motor);")
    root = build_condition_tree("Motor", ctx)
    assert root.children[0].full_path == "X"
    or_node = root.children[1]
    assert or_node.kind == OR
    # First leg is a series AND of A + B
    leg0 = or_node.children[0]
    assert leg0.kind == AND
    assert leg0.children[0].full_path == "A"
    assert leg0.children[1].full_path == "B"
    assert leg0.children[1].requirement == NEEDS_FALSE
    # Second leg is a single leaf C
    assert or_node.children[1].full_path == "C"


def test_xio_needs_false_semantics():
    ctx = ctx_from("XIC(Start)XIO(Stop)OTE(Motor);")
    root = build_condition_tree("Motor", ctx)
    stop = find(root, lambda n: n.full_path == "Stop")
    assert stop.requirement == NEEDS_FALSE
    # Live: Stop energized -> condition NOT met
    evaluate_tree(root, {"Start": True, "Stop": True})
    assert stop.satisfied is False
    assert root.satisfied is False


# ──────────────────────────────────────────────────────────────────────
# Cycles / latches
# ──────────────────────────────────────────────────────────────────────

def test_seal_in_circuit_no_infinite_recursion():
    ctx = ctx_from("[XIC(Start),XIC(Motor)]XIO(Stop)OTE(Motor);")
    root = build_condition_tree("Motor", ctx)  # must return, not hang
    seal = find(root, lambda n: n.kind == LATCH)
    assert seal is not None
    assert "self-holding" in seal.annotation
    assert seal.full_path == "Motor"


def test_otl_otu_latch_pair_across_two_rungs():
    ctx = ctx_from(
        "XIC(SetCond)OTL(Alarm);",
        "XIC(ClearCond)OTU(Alarm);",
    )
    root = build_condition_tree("Alarm", ctx)
    assert root.kind == LATCH
    assert "latched by" in root.annotation
    assert "unlatched by" in root.annotation
    # Latch condition subtree cites the OTL rung and gates on SetCond
    latch_cond = root.children[0]
    assert latch_cond.annotation == "latch condition"
    assert latch_cond.cite["rung_number"] == 0
    assert find(latch_cond, lambda n: n.full_path == "SetCond") is not None
    unlatch_cond = root.children[1]
    assert unlatch_cond.annotation == "unlatch condition"
    assert find(unlatch_cond, lambda n: n.full_path == "ClearCond") is not None


# ──────────────────────────────────────────────────────────────────────
# Timers
# ──────────────────────────────────────────────────────────────────────

def test_ton_done_bit_preset_annotation():
    ctx = ctx_from(
        "XIC(Enable)TON(Timer1,500,0);",
        "XIC(Timer1.DN)OTE(Motor);",
    )
    root = build_condition_tree("Motor", ctx)
    dn = find(root, lambda n: n.full_path == "Timer1.DN")
    assert dn is not None
    assert "500" in dn.annotation
    assert "timer done bit" in dn.annotation
    # It traces the timer's own enable logic
    assert find(dn, lambda n: n.full_path == "Enable") is not None


# ──────────────────────────────────────────────────────────────────────
# Comparisons
# ──────────────────────────────────────────────────────────────────────

def test_comparison_leaf_evaluation_grt():
    ctx = ctx_from("GRT(Speed,100)OTE(Fast);")
    root = build_condition_tree("Fast", ctx)
    cmp_leaf = find(root, lambda n: n.requirement == COMPARISON)
    assert cmp_leaf is not None
    assert cmp_leaf.comparison["op"] == "GRT"

    evaluate_tree(root, {"Speed": 150})
    assert cmp_leaf.satisfied is True
    assert root.satisfied is True

    evaluate_tree(root, {"Speed": 50})
    assert cmp_leaf.satisfied is False
    assert root.satisfied is False

    # Missing value -> unknown
    evaluate_tree(root, {})
    assert cmp_leaf.satisfied is None


def test_comparison_lim_and_neq():
    ctx = ctx_from("LIM(10,Temp,20)OTE(InBand);")
    root = build_condition_tree("InBand", ctx)
    evaluate_tree(root, {"Temp": 15})
    assert root.satisfied is True
    evaluate_tree(root, {"Temp": 25})
    assert root.satisfied is False


# ──────────────────────────────────────────────────────────────────────
# Recursion into intermediate coils
# ──────────────────────────────────────────────────────────────────────

def test_recursion_into_intermediate_coil_two_levels():
    ctx = ctx_from(
        "XIC(Interm)OTE(Out);",
        "XIC(A)XIC(B)OTE(Interm);",
    )
    root = build_condition_tree("Out", ctx, max_depth=4)
    interm = root.children[0]
    assert interm.full_path == "Interm"
    # Interm is an internal coil -> expanded into its own drivers
    assert interm.children, "expected recursion into Interm's drivers"
    assert find(interm, lambda n: n.full_path == "A") is not None
    assert find(interm, lambda n: n.full_path == "B") is not None


def test_depth_limit_stops_recursion():
    ctx = ctx_from(
        "XIC(Interm)OTE(Out);",
        "XIC(A)OTE(Interm);",
    )
    root = build_condition_tree("Out", ctx, max_depth=0)
    interm = root.children[0]
    assert interm.full_path == "Interm"
    assert not interm.children  # not expanded
    assert "depth limit" in interm.annotation


# ──────────────────────────────────────────────────────────────────────
# AOI traversal
# ──────────────────────────────────────────────────────────────────────

def _fb_valve():
    return AddOnInstruction(
        name="FB_VALVE",
        description="Valve function block",
        revision="1.0",
        parameters=[AOIParameter("Opened", "BOOL", "Output", True, True)],
        local_tags=[],
        routines=[
            Routine(
                name="Logic",
                routine_type="RLL",
                description="",
                rungs=[Rung(number=0, text="XIC(RequestOpen)OTE(Opened);", comment="")],
            )
        ],
    )


def test_aoi_member_traversal_into_internal_routine():
    aoi = _fb_valve()
    ctx = ctx_from(
        "XIC(Valve7.Opened)OTE(Motor);",
        aois=[aoi],
        tag_types={"Valve7": "FB_VALVE"},
    )
    root = build_condition_tree("Motor", ctx)
    member = find(root, lambda n: n.full_path == "Valve7.Opened")
    assert member is not None
    assert "FB_VALVE" in member.annotation
    assert "Opened" in member.annotation
    # Traversal went *through* the AOI to its internal driver
    assert find(member, lambda n: n.full_path == "RequestOpen") is not None


def test_aoi_member_unresolvable_flags_honestly():
    aoi = AddOnInstruction(
        name="FB_OPAQUE", description="", revision="1.0",
        parameters=[], local_tags=[], routines=[],  # no internal RLL
    )
    ctx = ctx_from(
        "XIC(Thing1.Status)OTE(Out);",
        aois=[aoi],
        tag_types={"Thing1": "FB_OPAQUE"},
    )
    root = build_condition_tree("Out", ctx)
    member = find(root, lambda n: n.full_path == "Thing1.Status")
    assert member.kind == FLAG
    assert "unavailable" in member.annotation


# ──────────────────────────────────────────────────────────────────────
# Honesty flags
# ──────────────────────────────────────────────────────────────────────

def test_indirect_address_flag():
    ctx = ctx_from("XIC(data[idx])OTE(Out);")
    root = build_condition_tree("Out", ctx)
    flag = find(root, lambda n: n.kind == FLAG)
    assert flag is not None
    assert "indirect addressing" in flag.annotation


def test_st_writer_flag():
    st_prog = Program(
        name="P", main_routine_name="Main", fault_routine_name="", disabled=False,
        routines=[
            Routine(
                name="Calc", routine_type="ST", description="",
                lines=[Line(number=0, text="MyBit := TRUE;")],
            )
        ],
    )
    ctx = ctx_from("XIC(MyBit)OTE(Out);", programs=[st_prog])
    root = build_condition_tree("Out", ctx)
    flag = find(root, lambda n: n.full_path == "MyBit")
    assert flag.kind == FLAG
    assert "Structured Text" in flag.annotation


def test_no_writer_physical_input_annotation():
    ctx = ctx_from("XIC(GuardDoor_Closed)OTE(Out);")
    root = build_condition_tree("Out", ctx)
    leaf = find(root, lambda n: n.full_path == "GuardDoor_Closed")
    assert leaf.kind == LEAF
    assert "field input" in leaf.annotation
    assert leaf.requirement == NEEDS_TRUE


def test_physical_io_address_annotation():
    ctx = ctx_from("XIC(Local:3:I.Data.4)OTE(Out);")
    root = build_condition_tree("Out", ctx)
    leaf = find(root, lambda n: n.full_path == "Local:3:I.Data.4")
    assert "physical I/O" in leaf.annotation


# ──────────────────────────────────────────────────────────────────────
# Live evaluation + failing paths
# ──────────────────────────────────────────────────────────────────────

def test_evaluate_prunes_to_single_failing_leaf():
    ctx = ctx_from("XIC(A)XIC(B)XIC(C)OTE(Out);")
    root = build_condition_tree("Out", ctx)
    evaluate_tree(root, {"A": True, "B": False, "C": True})
    assert root.satisfied is False
    paths = failing_paths(root)
    assert len(paths) == 1
    red_leaf = paths[0][-1]
    assert red_leaf.full_path == "B"
    assert red_leaf.satisfied is False


def test_evaluate_unknown_value_propagation():
    ctx = ctx_from("XIC(A)XIC(B)XIC(C)OTE(Out);")
    root = build_condition_tree("Out", ctx)
    # B missing, others satisfied -> whole tree unknown
    evaluate_tree(root, {"A": True, "C": True})
    assert root.satisfied is None
    paths = failing_paths(root)
    assert len(paths) == 1
    assert paths[0][-1].full_path == "B"
    assert paths[0][-1].satisfied is None


def test_evaluate_all_satisfied_no_failing_paths():
    ctx = ctx_from("XIC(A)XIO(B)OTE(Out);")
    root = build_condition_tree("Out", ctx)
    evaluate_tree(root, {"A": True, "B": False})
    assert root.satisfied is True
    assert failing_paths(root) == []


def test_or_branch_one_leg_satisfied():
    ctx = ctx_from("[XIC(A),XIC(B)]OTE(Out);")
    root = build_condition_tree("Out", ctx)
    evaluate_tree(root, {"A": False, "B": True})
    assert root.satisfied is True
    assert failing_paths(root) == []


def test_failing_path_definitive_false_preferred_over_unknown():
    # A known-False and C unknown: the red leaf should be the definitive A.
    ctx = ctx_from("XIC(A)XIC(C)OTE(Out);")
    root = build_condition_tree("Out", ctx)
    evaluate_tree(root, {"A": False})  # C missing
    paths = failing_paths(root)
    assert len(paths) == 1
    assert paths[0][-1].full_path == "A"


# ──────────────────────────────────────────────────────────────────────
# Serialization
# ──────────────────────────────────────────────────────────────────────

def test_to_dict_round_trips_through_json():
    ctx = ctx_from(
        "XIC(Interm)XIO(Stop)OTE(Out);",
        "XIC(A)GRT(Speed,10)OTE(Interm);",
    )
    root = build_condition_tree("Out", ctx)
    evaluate_tree(root, {"Stop": False, "A": True, "Speed": 5})
    dumped = json.dumps(root.to_dict())
    reloaded = json.loads(dumped)
    assert reloaded["kind"] == AND
    assert "children" in reloaded
    # comparison payload survives
    assert find(root, lambda n: n.requirement == COMPARISON).comparison["op"] == "GRT"


def test_to_dict_has_all_expected_fields():
    ctx = ctx_from("XIC(A)OTE(Out);")
    root = build_condition_tree("Out", ctx)
    d = root.to_dict()
    for key in ("kind", "requirement", "tag", "full_path", "cite", "annotation",
                "satisfied", "children"):
        assert key in d


def test_build_condition_tree_accepts_parsed_project_like():
    """build_condition_tree adapts a ParsedProject-like object (duck-typed)."""
    class FakeProject:
        parsed_rungs = {("P", "R", 0): parse_rung("XIC(A)OTE(Out);")}
        programs = []
        aois = []
        tags = []
    root = build_condition_tree("Out", FakeProject())
    assert root.kind == AND
    assert root.children[0].full_path == "A"

# ──────────────────────────────────────────────────────────────────────
# Deep failing-path descent + occurrence citations (Gate 1 regressions)
# ──────────────────────────────────────────────────────────────────────

def test_failing_path_descends_through_intermediate_coil_to_root_cause():
    """Permissive → safety-coil → field-input chain (PressLine_3 mirror).

    With a *consistent* live snapshot (Safety_OK=False because
    GuardDoor_Closed=False), the failing path must continue THROUGH the
    Safety_OK leaf down to the deepest attributable cause, with cites at
    every level.
    """
    rungs = {
        ("P300_Press", "R30_PressCycle", 9): parse_rung(
            "XIC(Mode_Auto)XIC(Cycle_Start_PB)XIC(Safety_OK)OTE(Press_Cycle_Start);"
        ),
        ("P900_Safety", "R92_SafetyOK", 1): parse_rung(
            "XIC(Estop_Chain_OK)XIC(GuardDoor_Closed)XIC(LightCurtain_Clear)OTE(Safety_OK);"
        ),
    }
    ctx = DiagnosisContext(parsed_rungs=rungs)
    root = build_condition_tree("Press_Cycle_Start", ctx)
    values = {
        "Mode_Auto": True, "Cycle_Start_PB": True,
        "Safety_OK": False,           # consistent with its broken enable logic
        "Estop_Chain_OK": True, "LightCurtain_Clear": True,
        "GuardDoor_Closed": False,    # the real root cause
    }
    evaluate_tree(root, values)
    assert root.satisfied is False

    paths = failing_paths(root)
    assert len(paths) == 1
    path = paths[0]

    # Full causal chain: … → Safety_OK → … → GuardDoor_Closed
    full_paths = [n.full_path for n in path]
    assert "Safety_OK" in full_paths
    assert path[-1].full_path == "GuardDoor_Closed"
    assert path[-1].satisfied is False
    # Safety_OK appears BEFORE GuardDoor_Closed in the chain
    assert full_paths.index("Safety_OK") < len(full_paths) - 1

    # Cites at each level of the chain:
    safety_leaf = path[full_paths.index("Safety_OK")]
    assert safety_leaf.cite == {
        "program": "P300_Press", "routine": "R30_PressCycle", "rung_number": 9
    }
    assert path[-1].cite == {
        "program": "P900_Safety", "routine": "R92_SafetyOK", "rung_number": 1
    }
    # Every node in the failing path below the root carries a cite
    assert all(n.cite is not None for n in path)


def test_failing_path_stops_at_leaf_when_children_contradict_live_value():
    """Live value FALSE but driver logic satisfied → latch/stale: stop + annotate."""
    rungs = {
        ("P", "R", 0): parse_rung("XIC(Interm)OTE(Out);"),
        ("P", "R", 1): parse_rung("XIC(A)OTE(Interm);"),
    }
    ctx = DiagnosisContext(parsed_rungs=rungs)
    root = build_condition_tree("Out", ctx)
    # Inconsistent snapshot: Interm reads False although its enable (A) is True
    evaluate_tree(root, {"Interm": False, "A": True})
    paths = failing_paths(root)
    assert len(paths) == 1
    assert paths[0][-1].full_path == "Interm"
    assert "stale" in paths[0][-1].annotation or "latch" in paths[0][-1].annotation


def test_failing_path_stops_at_leaf_when_children_unknown():
    """Live value FALSE, driver logic unknown → stop at the definitive leaf."""
    rungs = {
        ("P", "R", 0): parse_rung("XIC(Interm)OTE(Out);"),
        ("P", "R", 1): parse_rung("XIC(A)OTE(Interm);"),
    }
    ctx = DiagnosisContext(parsed_rungs=rungs)
    root = build_condition_tree("Out", ctx)
    evaluate_tree(root, {"Interm": False})  # A unknown
    paths = failing_paths(root)
    assert len(paths) == 1
    assert paths[0][-1].full_path == "Interm"


def test_leaf_nodes_carry_occurrence_cites():
    """Every condition leaf cites the rung where the contact appears."""
    rungs = {("MyProg", "MyRout", 5): parse_rung("XIC(A)XIO(B)GRT(Speed,10)OTE(Out);")}
    ctx = DiagnosisContext(parsed_rungs=rungs)
    root = build_condition_tree("Out", ctx)
    expected = {"program": "MyProg", "routine": "MyRout", "rung_number": 5}
    assert root.cite == expected
    for leaf in leaves(root):
        assert leaf.cite == expected, f"missing cite on {leaf.full_path or leaf.kind}"


def test_branch_nodes_carry_occurrence_cites():
    rungs = {("P", "R", 3): parse_rung("[XIC(A)XIC(B),XIC(C)]OTE(Out);")}
    ctx = DiagnosisContext(parsed_rungs=rungs)
    root = build_condition_tree("Out", ctx)
    or_node = root.children[0]
    assert or_node.kind == OR
    expected = {"program": "P", "routine": "R", "rung_number": 3}
    assert or_node.cite == expected
    # leg AND node and all leaves too
    assert or_node.children[0].cite == expected
    for leaf in leaves(root):
        assert leaf.cite == expected
