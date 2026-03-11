"""
cross_reference.py – Builds a tag usage cross-reference index.

Analyzes parsed rungs to find where and how tags are used 
(read, write, read+write).
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .rung_parser import Instruction, Branch, ParsedRung


@dataclass
class UsageEntry:
    program: str
    routine: str
    rung_number: int
    instruction: str
    access: str  # "read", "write", "read+write"


@dataclass
class TagUsage:
    tag_name: str
    usages: List[UsageEntry] = field(default_factory=list)

    @property
    def is_read_only(self) -> bool:
        """True if the tag is only ever read (e.g., a physical input)."""
        if not self.usages:
            return False
        return all("read" in u.access and "write" not in u.access for u in self.usages)

    @property
    def is_write_only(self) -> bool:
        """True if the tag is only ever written (e.g., a physical output)."""
        if not self.usages:
            return False
        return all("write" in u.access and "read" not in u.access for u in self.usages)


def normalize_tag_name(operand_value: str) -> str:
    """Normalize operand values to base tag names.
    
    Examples:
    - Target: B3.22 -> Base: B3
    - Target: data[5] -> Base: data
    - Target: Station3.CycleActive -> Base: Station3
    """
    if not operand_value:
        return ""
    # Split on first '.', '[', or other boundary character that makes sense
    base = re.split(r'[\.\[]', operand_value)[0]
    return base


def classify_usage(instruction: Instruction, operand_index: int) -> str:
    """Classify whether the operand is being read, written, or both."""
    mn = instruction.mnemonic.upper()
    cat = instruction.category

    # Bit I/O
    if cat == "bit_io":
        if mn in ("XIC", "XIO"):
            return "read"
        if mn in ("OTE", "OTL", "OTU"):
            return "write"

    # Compare
    if cat == "compare":
        return "read"

    # Timer/Counter (first operand is the structure itself being updated)
    if cat in ("timer", "counter"):
        if operand_index == 0:
            return "read+write"
        return "read"

    # Move / Math / System (GSV out) -> usually last operand is destination
    if cat in ("move", "math") or mn == "GSV":
        if operand_index == len(instruction.operands) - 1:
            return "write"
        return "read"

    # Catch-all
    if instruction.is_condition:
        return "read"
    else:
        # Assuming most output instructions write to their first/only operands if not matched above
        # But this can be tweaked
        return "read"


def walk_elements(elements: List) -> List[Instruction]:
    """Recursively yield all instructions from elements (Instructions + Branches)."""
    instrs = []
    for el in elements:
        if isinstance(el, Instruction):
            instrs.append(el)
        elif isinstance(el, Branch):
            for leg in el.legs:
                instrs.extend(walk_elements(leg))
    return instrs


def build_cross_reference(
    parsed_rungs: Dict[Tuple[str, str, int], ParsedRung]
) -> Dict[str, TagUsage]:
    """Build a cross-reference index of all tags used across all parsed rungs.
    
    Parameters
    ----------
    parsed_rungs:
        Keyed by (program, routine, rung_number), value is ParsedRung.
        
    Returns
    -------
    dict:
        Mapping of normalized tag name -> TagUsage object.
    """
    index: Dict[str, TagUsage] = {}

    for (prog_name, rout_name, rung_num), prung in parsed_rungs.items():
        instructions = walk_elements(prung.elements)
        
        for instr in instructions:
            for idx, op in enumerate(instr.operands):
                if op.is_literal:
                    continue  # We don't cross-reference literal numbers like 500

                base_tag = normalize_tag_name(op.value)
                if not base_tag:
                    continue

                access = classify_usage(instr, idx)

                entry = UsageEntry(
                    program=prog_name,
                    routine=rout_name,
                    rung_number=rung_num,
                    instruction=instr.mnemonic,
                    access=access
                )

                if base_tag not in index:
                    index[base_tag] = TagUsage(tag_name=base_tag)
                
                index[base_tag].usages.append(entry)

    return index
