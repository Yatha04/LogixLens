"""
rung_parser.py – Recursive descent parser for Rockwell ladder-logic rung text.

Parses raw rung strings like ``XIC(tag1)OTE(tag2);`` into structured
instruction/branch trees, handling nested bracket syntax for parallel
(OR) branches.

Grammar
-------
::

    rung              := instruction_chain ";"
    instruction_chain := (instruction | branch)+
    branch            := "[" chain ("," chain)+ "]"
    instruction       := MNEMONIC "(" operands ")"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .routine_extractor import Program


# ──────────────────────────────────────────────────────────────────────
# Data models
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Operand:
    """A single operand inside an instruction."""
    value: str          # raw text, e.g. "System.PowerOn", "500", "?"
    is_literal: bool    # True for numeric values, hex, floats, and "?"


@dataclass
class Instruction:
    """A single PLC instruction (e.g. XIC, TON, MOV)."""
    mnemonic: str                   # e.g. "XIC", "TON", "MOV"
    operands: List[Operand]         # parsed operand list
    category: str                   # from catalog: "bit_io", "timer", etc.
    is_condition: bool              # True = input condition, False = output


@dataclass
class Branch:
    """Parallel branch (OR logic) — ``[ chain , chain ]``."""
    legs: List[List]    # each leg is list[Instruction | Branch]


@dataclass
class ParsedRung:
    """Result of parsing a single rung."""
    elements: List      # list[Instruction | Branch]
    raw_text: str       # original rung text


# ──────────────────────────────────────────────────────────────────────
# Instruction catalog
# ──────────────────────────────────────────────────────────────────────

# Each entry maps mnemonic → (category, is_condition)
INSTRUCTION_CATALOG: Dict[str, Tuple[str, bool]] = {
    # ── bit I/O ──────────────────────────────────────────────────────
    "XIC":  ("bit_io", True),
    "XIO":  ("bit_io", True),
    "OTE":  ("bit_io", False),
    "OTL":  ("bit_io", False),
    "OTU":  ("bit_io", False),
    # ── one-shot ─────────────────────────────────────────────────────
    "ONS":  ("one_shot", False),
    "OSF":  ("one_shot", False),
    "OSR":  ("one_shot", False),
    # ── timer ────────────────────────────────────────────────────────
    "TON":  ("timer", False),
    "TOF":  ("timer", False),
    "RTO":  ("timer", False),
    # ── counter ──────────────────────────────────────────────────────
    "CTU":  ("counter", False),
    "CTD":  ("counter", False),
    "RES":  ("counter", False),
    # ── compare ──────────────────────────────────────────────────────
    "EQU":  ("compare", True),
    "NEQ":  ("compare", True),
    "GEQ":  ("compare", True),
    "GRT":  ("compare", True),
    "LEQ":  ("compare", True),
    "LES":  ("compare", True),
    "LIM":  ("compare", True),
    # ── math ─────────────────────────────────────────────────────────
    "ADD":  ("math", False),
    "SUB":  ("math", False),
    "MUL":  ("math", False),
    "DIV":  ("math", False),
    "CPT":  ("math", False),
    "CLR":  ("math", False),
    "MOD":  ("math", False),
    # ── move / copy ──────────────────────────────────────────────────
    "MOV":  ("move", False),
    "COP":  ("move", False),
    "CPS":  ("move", False),
    "BTD":  ("move", False),
    # ── program flow ─────────────────────────────────────────────────
    "JSR":  ("program_flow", False),
    "JMP":  ("program_flow", False),
    "LBL":  ("program_flow", False),
    "NOP":  ("program_flow", False),
    "AFI":  ("program_flow", False),
    "SFP":  ("program_flow", False),
    "SFR":  ("program_flow", False),
    # ── system ───────────────────────────────────────────────────────
    "GSV":  ("system", False),
    "SSV":  ("system", False),
}

_DEFAULT_CATEGORY = "aoi"
_DEFAULT_IS_CONDITION = False


# ──────────────────────────────────────────────────────────────────────
# Helper: literal detection
# ──────────────────────────────────────────────────────────────────────

# Pre-compiled patterns for performance
_RE_HEX    = re.compile(r"^16#[0-9A-Fa-f]+$")
_RE_INT    = re.compile(r"^-?\d+$")
_RE_FLOAT  = re.compile(r"^-?\d+\.\d+$")


def _is_literal(value: str) -> bool:
    """Return True if *value* looks like a numeric literal or ``?``."""
    if not value:
        return False
    if value == "?":
        return True
    if _RE_HEX.match(value):
        return True
    if _RE_INT.match(value):
        return True
    if _RE_FLOAT.match(value):
        return True
    return False


# ──────────────────────────────────────────────────────────────────────
# Helper: operand splitting
# ──────────────────────────────────────────────────────────────────────

def _split_operands(text: str) -> List[str]:
    """Split a comma-separated operand string, respecting ``()`` and ``[]`` nesting.

    Examples
    --------
    >>> _split_operands("a,b,c")
    ['a', 'b', 'c']
    >>> _split_operands("Trigger[0].5,1000")
    ['Trigger[0].5', '1000']
    >>> _split_operands("Bit+(Word*32)")
    ['Bit+(Word*32)']
    >>> _split_operands("")
    []
    """
    if not text:
        return []

    parts: List[str] = []
    depth = 0
    start = 0

    for i, ch in enumerate(text):
        if ch in ("(", "["):
            depth += 1
        elif ch in (")", "]"):
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1

    # last segment
    parts.append(text[start:])
    return parts


# ──────────────────────────────────────────────────────────────────────
# Recursive descent parser
# ──────────────────────────────────────────────────────────────────────

class RungParseError(Exception):
    """Raised when a rung string cannot be parsed."""


def _parse_instruction(text: str, pos: int) -> Tuple[Instruction, int]:
    """Parse ``MNEMONIC(operands)`` starting at *pos*.

    Returns the Instruction and the new position after the closing ``)``\.
    """
    # Read the mnemonic: uppercase letters, digits, and underscores
    start = pos
    while pos < len(text) and (text[pos].isalnum() or text[pos] == "_"):
        pos += 1

    mnemonic = text[start:pos]
    if not mnemonic:
        raise RungParseError(
            f"Expected mnemonic at position {start}, got {text[start:start+10]!r}"
        )

    # Expect '(' — but Rockwell emits some zero-operand instructions bare
    # (real exports contain e.g. ``NOP;`` with no parentheses). A mnemonic
    # not followed by '(' is treated as a zero-operand instruction.
    if pos >= len(text) or text[pos] != "(":
        cat, is_cond = INSTRUCTION_CATALOG.get(
            mnemonic, (_DEFAULT_CATEGORY, _DEFAULT_IS_CONDITION)
        )
        return (
            Instruction(
                mnemonic=mnemonic, operands=[], category=cat, is_condition=is_cond
            ),
            pos,
        )
    pos += 1  # skip '('

    # Read operands until the matching ')'
    depth = 1
    op_start = pos
    while pos < len(text) and depth > 0:
        if text[pos] == "(":
            depth += 1
        elif text[pos] == ")":
            depth -= 1
        pos += 1

    operands_text = text[op_start:pos - 1]  # exclude the closing ')'

    # Parse operands
    raw_operands = _split_operands(operands_text)
    operands = [
        Operand(value=op, is_literal=_is_literal(op))
        for op in raw_operands
        if op  # skip empty strings (e.g. from NOP())
    ]

    # Look up the catalog
    cat, is_cond = INSTRUCTION_CATALOG.get(
        mnemonic, (_DEFAULT_CATEGORY, _DEFAULT_IS_CONDITION)
    )

    instr = Instruction(
        mnemonic=mnemonic,
        operands=operands,
        category=cat,
        is_condition=is_cond,
    )
    return instr, pos


def _parse_branch(text: str, pos: int) -> Tuple[Branch, int]:
    """Parse ``[ chain , chain , … ]`` starting at the ``[``.

    Returns the Branch and position after ``]``.
    """
    assert text[pos] == "["
    pos += 1  # skip '['

    legs: List[List] = []
    while True:
        chain, pos = _parse_chain(text, pos, stop_chars=",]")
        legs.append(chain)

        if pos >= len(text):
            raise RungParseError("Unexpected end of text inside branch")

        if text[pos] == ",":
            pos += 1  # skip ',' and parse next leg
            continue
        elif text[pos] == "]":
            pos += 1  # skip ']'
            break
        else:
            raise RungParseError(
                f"Unexpected character {text[pos]!r} at position {pos} inside branch"
            )

    return Branch(legs=legs), pos


def _parse_chain(text: str, pos: int, stop_chars: str = ";") -> Tuple[List, int]:
    """Parse a sequence of instructions and/or branches until a stop char.

    Returns the chain (``list[Instruction | Branch]``) and position at the
    stop character (does **not** consume the stop character).
    """
    chain: List = []

    while pos < len(text):
        # Skip whitespace
        while pos < len(text) and text[pos] in (" ", "\t", "\r", "\n"):
            pos += 1

        if pos >= len(text):
            break

        ch = text[pos]

        # Hit a stop character → done
        if ch in stop_chars:
            break

        if ch == "[":
            branch, pos = _parse_branch(text, pos)
            chain.append(branch)
        elif ch.isalnum() or ch == "_":
            instr, pos = _parse_instruction(text, pos)
            chain.append(instr)
        else:
            raise RungParseError(
                f"Unexpected character {ch!r} at position {pos} in rung: "
                f"…{text[max(0, pos-5):pos+10]}…"
            )

    return chain, pos


def parse_rung(text: str) -> ParsedRung:
    """Parse a single rung string into a :class:`ParsedRung`.

    Parameters
    ----------
    text : str
        The rung text, typically ending with ``';'``.

    Returns
    -------
    ParsedRung
        The parsed tree of instructions and branches.
    """
    raw = text
    text = text.strip()

    if not text:
        return ParsedRung(elements=[], raw_text=raw)

    # The rung should end with ';', but handle it either way
    if text.endswith(";"):
        text = text[:-1]

    elements, _ = _parse_chain(text, 0, stop_chars=";")
    return ParsedRung(elements=elements, raw_text=raw)


# ──────────────────────────────────────────────────────────────────────
# Integration helper
# ──────────────────────────────────────────────────────────────────────

def parse_all_rungs(
    programs: List[Program],
    errors: Optional[Dict[Tuple[str, str, int], str]] = None,
) -> Dict[Tuple[str, str, int], ParsedRung]:
    """Parse every rung in every RLL routine across all programs.

    Parameters
    ----------
    programs : list[Program]
        Output of :func:`routine_extractor.extract_programs`.
    errors : dict, optional
        When provided, rungs that fail to parse are recorded here as
        ``key -> error message`` and parsing continues (real-world exports
        contain malformed/legacy rung text; one bad rung must not fail the
        whole project). When ``None``, a :class:`RungParseError` propagates
        (strict mode, the historical behavior).

    Returns
    -------
    dict
        Keyed by ``(program_name, routine_name, rung_number)`` →
        :class:`ParsedRung`.
    """
    results: Dict[Tuple[str, str, int], ParsedRung] = {}

    for prog in programs:
        for routine in prog.routines:
            if routine.routine_type != "RLL":
                continue
            for rung in routine.rungs:
                key = (prog.name, routine.name, rung.number)
                try:
                    results[key] = parse_rung(rung.text)
                except RungParseError as exc:
                    if errors is None:
                        raise
                    errors[key] = str(exc)

    return results
