from dataclasses import dataclass, field
from typing import List, Optional
from lxml import etree

from .l5x_loader import L5XProject


@dataclass
class Rung:
    """Represents a single rung in a Ladder (RLL) routine."""
    number: int
    text: str         # Rung logic text, e.g. "XIC(StartBtn)OTE(Motor);"
    comment: str      # Optional comment for the rung


@dataclass
class Line:
    """Represents a single line in a Structured Text (ST) routine."""
    number: int
    text: str         # The ST source code line


@dataclass
class Routine:
    """Represents a routine within a program."""
    name: str
    routine_type: str          # "RLL" (ladder) or "ST" (structured text) or other
    description: str
    rungs: List[Rung] = field(default_factory=list)   # Populated for RLL routines
    lines: List[Line] = field(default_factory=list)   # Populated for ST routines


@dataclass
class Program:
    """Represents a program in an L5X project."""
    name: str
    main_routine_name: str
    fault_routine_name: str
    disabled: bool
    routines: List[Routine] = field(default_factory=list)


def extract_programs(project: L5XProject) -> List[Program]:
    """Extract all programs and their routines from the L5X project.

    Args:
        project: A loaded L5XProject.

    Returns:
        A list of Program objects, each containing its Routine list with
        Rung/Line content.
    """
    programs: List[Program] = []

    programs_node = project.controller.find("Programs")
    if programs_node is None:
        return programs

    for prog_node in programs_node.xpath("./Program"):
        name = prog_node.get("Name", "")
        main_routine_name = prog_node.get("MainRoutineName", "")
        fault_routine_name = prog_node.get("FaultRoutineName", "")

        disabled_str = prog_node.get("Disabled", "false").lower()
        disabled = disabled_str == "true"

        routines = _extract_routines(prog_node)

        programs.append(Program(
            name=name,
            main_routine_name=main_routine_name,
            fault_routine_name=fault_routine_name,
            disabled=disabled,
            routines=routines,
        ))

    return programs


def _extract_routines(prog_node: etree._Element) -> List[Routine]:
    """Extract all routines from a <Program> element."""
    routines: List[Routine] = []

    routines_node = prog_node.find("Routines")
    if routines_node is None:
        return routines

    for routine_node in routines_node.xpath("./Routine"):
        name = routine_node.get("Name", "")
        routine_type = routine_node.get("Type", "RLL")

        description = ""
        desc_elem = routine_node.find("Description")
        if desc_elem is not None and desc_elem.text:
            description = desc_elem.text.strip()

        rungs: List[Rung] = []
        lines: List[Line] = []

        if routine_type == "RLL":
            rungs = _extract_rungs(routine_node)
        elif routine_type == "ST":
            lines = _extract_st_lines(routine_node)

        routines.append(Routine(
            name=name,
            routine_type=routine_type,
            description=description,
            rungs=rungs,
            lines=lines,
        ))

    return routines


def _extract_rungs(routine_node: etree._Element) -> List[Rung]:
    """Extract rungs from an RLL <Routine> element.

    Skips deleted rungs (Type="D") and normalizes "(N)" suffixes to "N".
    """
    rungs: List[Rung] = []

    rll_content_node = routine_node.find("RLLContent")
    if rll_content_node is None:
        return rungs

    for rung_node in rll_content_node.xpath("./Rung"):
        # Skip deleted rungs
        rung_type = rung_node.get("Type", "N")
        if rung_type == "D":
            continue

        try:
            number = int(rung_node.get("Number", "0"))
        except ValueError:
            number = 0

        # Extract optional comment
        comment = ""
        comment_elem = rung_node.find("Comment")
        if comment_elem is not None and comment_elem.text:
            comment = comment_elem.text.strip()

        # Extract rung text
        text = ""
        text_elem = rung_node.find("Text")
        if text_elem is not None and text_elem.text:
            text = text_elem.text.strip()
            # Normalize "(N)" → "N" at the end of the text (deleted-rung marker sometimes left in text)
            if text.endswith("(N)"):
                text = text[:-3] + "N"

        rungs.append(Rung(number=number, text=text, comment=comment))

    return rungs


def _extract_st_lines(routine_node: etree._Element) -> List[Line]:
    """Extract lines from a Structured Text (ST) <Routine> element."""
    lines: List[Line] = []

    st_content_node = routine_node.find("STContent")
    if st_content_node is None:
        return lines

    for i, line_node in enumerate(st_content_node.xpath("./Line")):
        try:
            number = int(line_node.get("Number", str(i)))
        except ValueError:
            number = i

        text = ""
        if line_node.text:
            text = line_node.text.strip()

        lines.append(Line(number=number, text=text))

    return lines
