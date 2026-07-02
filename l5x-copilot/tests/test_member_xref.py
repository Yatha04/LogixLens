"""
test_member_xref.py – Tests for the member-level cross-reference (Deliverable 1).

All synthetic: rungs are built via parse_rung() on hand-written rung strings.
"""

from src.parser.rung_parser import parse_rung
from src.parser.cross_reference import (
    build_cross_reference,
    build_member_cross_reference,
    UsageEntry,
)


def _rungs(*texts):
    return {("P", "R", i): parse_rung(t) for i, t in enumerate(texts)}


def test_usage_entry_has_full_path_default():
    """full_path is additive with a safe default (existing constructions unaffected)."""
    e = UsageEntry(program="P", routine="R", rung_number=0, instruction="XIC", access="read")
    assert e.full_path == ""


def test_base_xref_now_carries_full_path():
    rungs = _rungs("XIC(Station3.CycleActive)OTE(Out1);")
    base = build_cross_reference(rungs)
    # Base index still keyed by base tag
    assert "Station3" in base
    # ...but each usage now carries the original operand path
    assert base["Station3"].usages[0].full_path == "Station3.CycleActive"


def test_member_index_keys_on_full_path():
    rungs = _rungs("XIC(Station3.CycleActive)XIC(Station3.Fault)OTE(Out1);")
    member = build_member_cross_reference(rungs)
    assert "Station3.CycleActive" in member
    assert "Station3.Fault" in member
    # Base collapse would have merged these; member keeps them distinct.
    assert "Station3" not in member


def test_member_index_distinguishes_bits_of_same_word():
    rungs = _rungs("XIC(B3.0)OTE(A);", "XIC(B3.1)OTE(B);")
    member = build_member_cross_reference(rungs)
    assert "B3.0" in member
    assert "B3.1" in member
    assert member["B3.0"].usages[0].access == "read"


def test_member_index_write_access_recorded():
    rungs = _rungs("XIC(Start)OTE(Motor.Run);")
    member = build_member_cross_reference(rungs)
    assert "Motor.Run" in member
    assert member["Motor.Run"].usages[0].access == "write"
    assert member["Motor.Run"].usages[0].instruction == "OTE"


def test_member_index_skips_literals():
    rungs = _rungs("MOV(500,Dest.Value);")
    member = build_member_cross_reference(rungs)
    assert "500" not in member
    assert "Dest.Value" in member


def test_member_index_cite_fields():
    rungs = {("MyProg", "MyRout", 7): parse_rung("XIC(A.B)OTE(C);")}
    member = build_member_cross_reference(rungs)
    u = member["A.B"].usages[0]
    assert u.program == "MyProg"
    assert u.routine == "MyRout"
    assert u.rung_number == 7
    assert u.full_path == "A.B"
