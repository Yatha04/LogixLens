"""
test_corpus_hardening.py

Regression tests for real-world constructs discovered by the corpus baseline
(corpus/REPORT.md). Every rung text here was found verbatim in a public L5X
file that the parser previously failed on.
"""
import pytest

from src.parser.rung_parser import (
    Instruction,
    RungParseError,
    parse_all_rungs,
    parse_rung,
)
from src.parser.routine_extractor import Program, Routine, Rung


# --- Zero-operand instructions without parentheses (LearnPLC_NoHardware,
# --- Beginner_Guide, Beginner_Guide_Annotated) ---

def test_bare_nop_parses():
    """Rockwell emits ``NOP;`` with no parentheses."""
    rung = parse_rung("NOP;")
    assert len(rung.elements) == 1
    instr = rung.elements[0]
    assert isinstance(instr, Instruction)
    assert instr.mnemonic == "NOP"
    assert instr.operands == []


def test_bare_mnemonic_in_chain():
    """Zero-operand instruction in series with normal instructions."""
    rung = parse_rung("XIC(Start)NOP OTE(Motor);")
    mnemonics = [e.mnemonic for e in rung.elements if isinstance(e, Instruction)]
    assert mnemonics == ["XIC", "NOP", "OTE"]


def test_paren_nop_still_parses():
    """The existing ``NOP()`` form keeps working."""
    rung = parse_rung("NOP();")
    assert rung.elements[0].operands == []


# --- Malformed rung text must not kill a whole project (test.L5X from the
# --- corpus contains deliberately-invalid rung strings) ---

MALFORMED_REAL_TEXTS = [
    "[Computer(?,?,?);",   # unterminated branch
    "[Succeed();",          # unterminated branch
]


@pytest.mark.parametrize("text", MALFORMED_REAL_TEXTS)
def test_malformed_rungs_still_raise(text):
    """Genuinely invalid rung text keeps raising in strict parse_rung."""
    with pytest.raises(RungParseError):
        parse_rung(text)


def _program_with_rungs(texts):
    rungs = [Rung(number=i, text=t, comment="") for i, t in enumerate(texts)]
    routine = Routine(
        name="R01", routine_type="RLL", description="", rungs=rungs, lines=[]
    )
    return Program(
        name="P1",
        main_routine_name="R01",
        fault_routine_name="",
        disabled=False,
        routines=[routine],
    )


def test_parse_all_rungs_tolerant_mode_skips_bad_rungs():
    """One malformed rung must not fail the project: good rungs parse,
    bad ones land in the errors dict."""
    prog = _program_with_rungs(
        ["XIC(A)OTE(B);", "[Computer(?,?,?);", "XIC(C)OTE(D);"]
    )
    errors = {}
    parsed = parse_all_rungs([prog], errors=errors)
    assert ("P1", "R01", 0) in parsed
    assert ("P1", "R01", 2) in parsed
    assert ("P1", "R01", 1) not in parsed
    assert list(errors) == [("P1", "R01", 1)]
    assert "branch" in errors[("P1", "R01", 1)]


def test_parse_all_rungs_strict_mode_still_raises():
    """Without an errors dict, historical strict behavior is preserved."""
    prog = _program_with_rungs(["[Succeed();"])
    with pytest.raises(RungParseError):
        parse_all_rungs([prog])


# --- Controller-less component exports (TargetType="Module") ---

MODULE_EXPORT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="31.02"
    TargetName="C06_PNT" TargetType="Module" ContainsContext="false">
<Module Use="Target" Name="C06_PNT" CatalogNumber="1734-AENTR"
    Vendor="1" ProductType="12" ProductCode="93" Major="5" Minor="1"
    ParentModule="Local" ParentModPortId="2">
<Ports>
<Port Id="1" Address="1" Type="PointIO" Upstream="true"/>
</Ports>
</Module>
</RSLogix5000Content>
"""


def test_module_export_loads_and_parses(tmp_path):
    """A TargetType='Module' export (no <Controller>) loads gracefully and
    yields its module instead of raising L5XValidationError."""
    from src.parser.l5x_loader import load_l5x
    from src.parser.project_model import parse_project

    f = tmp_path / "module_export.L5X"
    f.write_bytes(MODULE_EXPORT_XML)

    project = load_l5x(str(f))
    assert project.metadata.target_type == "Module"
    assert project.metadata.controller_name == "C06_PNT"

    parsed = parse_project(str(f))
    assert parsed.tags == []
    assert parsed.programs == []
    assert len(parsed.modules) == 1
    assert parsed.modules[0].catalog_number == "1734-AENTR"
