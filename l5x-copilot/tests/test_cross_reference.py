"""
Unit tests for the cross-reference builder.
"""

from src.parser.rung_parser import Instruction, ParsedRung, Operand, Branch
from src.parser.cross_reference import (
    normalize_tag_name,
    classify_usage,
    build_cross_reference,
    TagUsage,
    UsageEntry
)


def test_normalize_tag_name():
    assert normalize_tag_name("Station3.CycleActive") == "Station3"
    assert normalize_tag_name("data[5]") == "data"
    assert normalize_tag_name("B3.22") == "B3"
    assert normalize_tag_name("MyTag") == "MyTag"


def test_classify_usage_xic():
    instr = Instruction(mnemonic="XIC", operands=[Operand("Switch1", False)], category="bit_io", is_condition=True)
    assert classify_usage(instr, 0) == "read"


def test_classify_usage_ote():
    instr = Instruction(mnemonic="OTE", operands=[Operand("Motor", False)], category="bit_io", is_condition=False)
    assert classify_usage(instr, 0) == "write"


def test_classify_usage_timer():
    instr = Instruction(
        mnemonic="TON", 
        operands=[Operand("MyTimer", False), Operand("1000", True), Operand("0", True)], 
        category="timer", 
        is_condition=False
    )
    assert classify_usage(instr, 0) == "read+write"
    assert classify_usage(instr, 1) == "read"


def test_classify_usage_mov():
    instr = Instruction(
        mnemonic="MOV",
        operands=[Operand("Source", False), Operand("Dest", False)],
        category="move",
        is_condition=False
    )
    assert classify_usage(instr, 0) == "read"
    assert classify_usage(instr, 1) == "write"


def test_build_cross_reference():
    rungs = {
        ("MainProgram", "MainRoutine", 0): ParsedRung(
            raw_text="XIC(Input1)OTE(Output1);",
            elements=[
                Instruction(mnemonic="XIC", operands=[Operand("Input1", False)], category="bit_io", is_condition=True),
                Instruction(mnemonic="OTE", operands=[Operand("Output1", False)], category="bit_io", is_condition=False)
            ]
        ),
        ("MainProgram", "MainRoutine", 1): ParsedRung(
            raw_text="MOV(Input1, Data[0]);",
            elements=[
                Instruction(mnemonic="MOV", operands=[Operand("Input1", False), Operand("Data[0]", False)], category="move", is_condition=False)
            ]
        )
    }

    index = build_cross_reference(rungs)
    
    assert "Input1" in index
    assert "Output1" in index
    assert "Data" in index

    input1_usage = index["Input1"]
    assert input1_usage.is_read_only is True
    assert input1_usage.is_write_only is False
    assert len(input1_usage.usages) == 2

    output1_usage = index["Output1"]
    assert output1_usage.is_read_only is False
    assert output1_usage.is_write_only is True

    data_usage = index["Data"]
    assert data_usage.is_read_only is False
    assert data_usage.is_write_only is True
    assert len(data_usage.usages) == 1
    assert data_usage.usages[0].access == "write"
    assert data_usage.usages[0].instruction == "MOV"

def test_branch_traversal():
    # [ XIC(A) , XIC(B) ] OTE(C)
    rung = ParsedRung(
        raw_text="[XIC(A),XIC(B)]OTE(C);",
        elements=[
            Branch(legs=[
                [Instruction("XIC", [Operand("A", False)], "bit_io", True)],
                [Instruction("XIC", [Operand("B", False)], "bit_io", True)]
            ]),
            Instruction("OTE", [Operand("C", False)], "bit_io", False)
        ]
    )

    rungs = {("Prog", "Rout", 0): rung}
    index = build_cross_reference(rungs)

    assert "A" in index
    assert index["A"].usages[0].access == "read"
    
    assert "B" in index
    assert index["B"].usages[0].access == "read"

    assert "C" in index
    assert index["C"].usages[0].access == "write"
