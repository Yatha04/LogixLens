"""
test_rung_parser.py – Tests for the rung instruction parser.

Organized in four test classes:
  - TestIsLiteral      – unit tests for _is_literal()
  - TestSplitOperands  – unit tests for _split_operands()
  - TestParseRung      – unit tests for parse_rung() patterns
  - TestIntegration    – against a real L5X file (requires --l5x-file)
"""

import pytest
from src.parser.rung_parser import (
    _is_literal,
    _split_operands,
    parse_rung,
    parse_all_rungs,
    Operand,
    Instruction,
    Branch,
    ParsedRung,
    INSTRUCTION_CATALOG,
    RungParseError,
)
from src.parser.routine_extractor import extract_programs


# ══════════════════════════════════════════════════════════════════════
# TestIsLiteral
# ══════════════════════════════════════════════════════════════════════

class TestIsLiteral:
    """Unit tests for _is_literal()."""

    def test_integer(self):
        assert _is_literal("500") is True

    def test_negative_integer(self):
        assert _is_literal("-5") is True

    def test_hex(self):
        assert _is_literal("16#FF00") is True

    def test_hex_zero(self):
        assert _is_literal("16#0") is True

    def test_float(self):
        assert _is_literal("1.5") is True

    def test_negative_float(self):
        assert _is_literal("-0.01") is True

    def test_question_mark(self):
        assert _is_literal("?") is True

    def test_tag_name(self):
        assert _is_literal("System.Tag") is False

    def test_array_tag(self):
        assert _is_literal("Trigger[0].5") is False

    def test_empty_string(self):
        assert _is_literal("") is False

    def test_zero(self):
        assert _is_literal("0") is True


# ══════════════════════════════════════════════════════════════════════
# TestSplitOperands
# ══════════════════════════════════════════════════════════════════════

class TestSplitOperands:
    """Unit tests for _split_operands()."""

    def test_simple_csv(self):
        assert _split_operands("a,b,c") == ["a", "b", "c"]

    def test_array_operand(self):
        assert _split_operands("Trigger[0].5,1000") == ["Trigger[0].5", "1000"]

    def test_nested_parens_expression(self):
        """CPT expression: parens should NOT cause a split."""
        assert _split_operands("Bit+(Word*32)") == ["Bit+(Word*32)"]

    def test_empty_string(self):
        assert _split_operands("") == []

    def test_single_operand(self):
        assert _split_operands("System.PowerOn") == ["System.PowerOn"]

    def test_mixed_nesting(self):
        """Both brackets and parens in operands."""
        assert _split_operands("tag[0],func(x)") == ["tag[0]", "func(x)"]

    def test_question_marks(self):
        assert _split_operands("timer,?,?") == ["timer", "?", "?"]

    def test_gsv_operands(self):
        result = _split_operands("Routine,r020_FlipperSeq,SFCPaused,FlipperSeq.Paused")
        assert result == ["Routine", "r020_FlipperSeq", "SFCPaused", "FlipperSeq.Paused"]


# ══════════════════════════════════════════════════════════════════════
# TestParseRung
# ══════════════════════════════════════════════════════════════════════

class TestParseRung:
    """Unit tests for parse_rung() covering representative patterns."""

    def test_simple_chain(self):
        """XIC(tag1)OTE(tag2);"""
        result = parse_rung("XIC(tag1)OTE(tag2);")

        assert isinstance(result, ParsedRung)
        assert len(result.elements) == 2

        xic = result.elements[0]
        assert isinstance(xic, Instruction)
        assert xic.mnemonic == "XIC"
        assert xic.category == "bit_io"
        assert xic.is_condition is True
        assert len(xic.operands) == 1
        assert xic.operands[0].value == "tag1"

        ote = result.elements[1]
        assert isinstance(ote, Instruction)
        assert ote.mnemonic == "OTE"
        assert ote.category == "bit_io"
        assert ote.is_condition is False

    def test_nop(self):
        """NOP();"""
        result = parse_rung("NOP();")
        assert len(result.elements) == 1
        nop = result.elements[0]
        assert nop.mnemonic == "NOP"
        assert nop.category == "program_flow"
        assert len(nop.operands) == 0

    def test_multi_operand(self):
        """MOV(src,dest);"""
        result = parse_rung("MOV(src,dest);")
        mov = result.elements[0]
        assert mov.mnemonic == "MOV"
        assert mov.category == "move"
        assert len(mov.operands) == 2
        assert mov.operands[0].value == "src"
        assert mov.operands[1].value == "dest"

    def test_branch(self):
        """[XIC(a) ,XIC(b) ]OTE(c);"""
        result = parse_rung("[XIC(a) ,XIC(b) ]OTE(c);")
        assert len(result.elements) == 2

        branch = result.elements[0]
        assert isinstance(branch, Branch)
        assert len(branch.legs) == 2

        # First leg: XIC(a)
        assert len(branch.legs[0]) == 1
        assert branch.legs[0][0].mnemonic == "XIC"
        assert branch.legs[0][0].operands[0].value == "a"

        # Second leg: XIC(b)
        assert len(branch.legs[1]) == 1
        assert branch.legs[1][0].mnemonic == "XIC"
        assert branch.legs[1][0].operands[0].value == "b"

        # Output after branch: OTE(c)
        ote = result.elements[1]
        assert isinstance(ote, Instruction)
        assert ote.mnemonic == "OTE"

    def test_nested_branch(self):
        """Nested branch structure from real data pattern."""
        rung_text = "XIC(X)[ONS(Z)[XIO(A)OTL(B),XIC(C)OTU(D)],OTU(E)];"
        result = parse_rung(rung_text)

        # Top level: XIC(X) + outer branch
        assert len(result.elements) == 2
        assert result.elements[0].mnemonic == "XIC"

        outer_branch = result.elements[1]
        assert isinstance(outer_branch, Branch)
        assert len(outer_branch.legs) == 2

        # First leg has ONS(Z) + inner branch
        first_leg = outer_branch.legs[0]
        assert first_leg[0].mnemonic == "ONS"
        inner_branch = first_leg[1]
        assert isinstance(inner_branch, Branch)
        assert len(inner_branch.legs) == 2

        # Second leg: OTU(E)
        second_leg = outer_branch.legs[1]
        assert len(second_leg) == 1
        assert second_leg[0].mnemonic == "OTU"

    def test_question_mark_operand(self):
        """TON(timer,?,?);"""
        result = parse_rung("TON(System.InitialPowerOnTmr,?,?);")
        ton = result.elements[0]
        assert ton.mnemonic == "TON"
        assert ton.category == "timer"
        assert len(ton.operands) == 3
        assert ton.operands[0].is_literal is False   # tag name
        assert ton.operands[1].value == "?"
        assert ton.operands[1].is_literal is True
        assert ton.operands[2].value == "?"
        assert ton.operands[2].is_literal is True

    def test_unknown_mnemonic_aoi(self):
        """Unknown mnemonics default to category='aoi', is_condition=False."""
        result = parse_rung("FB_DIGITAL_INPUT(in1,out1);")
        instr = result.elements[0]
        assert instr.mnemonic == "FB_DIGITAL_INPUT"
        assert instr.category == "aoi"
        assert instr.is_condition is False

    def test_cpt_expression(self):
        """CPT with an expression operand containing parens."""
        result = parse_rung("CPT(System.Messages.Number,Bit+(Word*32));")
        cpt = result.elements[0]
        assert cpt.mnemonic == "CPT"
        assert cpt.category == "math"
        assert len(cpt.operands) == 2
        assert cpt.operands[1].value == "Bit+(Word*32)"

    def test_gsv_system_call(self):
        """GSV with four operands."""
        result = parse_rung("GSV(Routine,r020_FlipperSeq,SFCPaused,FlipperSeq.Paused);")
        gsv = result.elements[0]
        assert gsv.mnemonic == "GSV"
        assert gsv.category == "system"
        assert len(gsv.operands) == 4

    def test_array_operand(self):
        """Array-indexed tag operand."""
        result = parse_rung("XIC(System_Alarms.Trigger[0].15);")
        xic = result.elements[0]
        assert xic.operands[0].value == "System_Alarms.Trigger[0].15"
        assert xic.operands[0].is_literal is False

    def test_chain_with_jmp(self):
        """XIC(System.PowerOnTmr.TT)JMP(InitialPowerUP);"""
        result = parse_rung("XIC(System.PowerOnTmr.TT)JMP(InitialPowerUP);")
        assert len(result.elements) == 2
        assert result.elements[0].mnemonic == "XIC"
        assert result.elements[1].mnemonic == "JMP"
        assert result.elements[1].category == "program_flow"

    def test_empty_rung(self):
        result = parse_rung("")
        assert result.elements == []

    def test_branch_with_jsr(self):
        """[XIC(S:FS) ,XIC(bFirstScanOverride) ]JSR(r001_Initilize,0);"""
        result = parse_rung("[XIC(S:FS) ,XIC(bFirstScanOverride) ]JSR(r001_Initilize,0);")
        assert len(result.elements) == 2

        branch = result.elements[0]
        assert isinstance(branch, Branch)
        assert len(branch.legs) == 2
        assert branch.legs[0][0].operands[0].value == "S:FS"

        jsr = result.elements[1]
        assert jsr.mnemonic == "JSR"
        assert jsr.operands[0].value == "r001_Initilize"
        assert jsr.operands[1].value == "0"
        assert jsr.operands[1].is_literal is True

    def test_hex_operand(self):
        """Test hex literal detection in context."""
        result = parse_rung("MOV(16#FF00,dest);")
        mov = result.elements[0]
        assert mov.operands[0].value == "16#FF00"
        assert mov.operands[0].is_literal is True


# ══════════════════════════════════════════════════════════════════════
# TestIntegration — requires a real L5X file (--l5x-file)
# ══════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Integration tests: parse every rung from a real L5X file."""

    VALID_CATEGORIES = {
        "bit_io", "one_shot", "timer", "counter", "compare",
        "math", "move", "program_flow", "system", "aoi",
    }

    def test_parse_all_rungs_no_failures(self, l5x_project):
        """Every rung in the real file must parse without raising."""
        programs = extract_programs(l5x_project)
        results = parse_all_rungs(programs)

        assert len(results) > 0, "Expected at least one rung"

        for key, parsed in results.items():
            assert isinstance(parsed, ParsedRung), f"Bad result for {key}"
            assert len(parsed.elements) > 0, (
                f"Rung {key} parsed to empty elements. Raw: {parsed.raw_text!r}"
            )

    def test_all_instructions_have_valid_category(self, l5x_project):
        """Every Instruction node must have a category in the known set."""
        programs = extract_programs(l5x_project)
        results = parse_all_rungs(programs)

        def _check_elements(elements, key):
            for elem in elements:
                if isinstance(elem, Instruction):
                    assert elem.category in self.VALID_CATEGORIES, (
                        f"Invalid category {elem.category!r} for "
                        f"{elem.mnemonic} in rung {key}"
                    )
                elif isinstance(elem, Branch):
                    for leg in elem.legs:
                        _check_elements(leg, key)

        for key, parsed in results.items():
            _check_elements(parsed.elements, key)
