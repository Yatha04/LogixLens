from __future__ import annotations

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


# ---------------------------------------------------------------------------
# SFC (Sequential Function Chart) data models
# ---------------------------------------------------------------------------

@dataclass
class SFCAction:
    """An action attached to an SFC step."""
    id: int
    operand: str          # Tag name, e.g. "Action_001"
    qualifier: str        # e.g. "NonStored", "S" (Stored), "P" (Pulse) …
    is_boolean: bool
    lines: List[Line] = field(default_factory=list)  # ST code inside the action body


@dataclass
class SFCStep:
    """A step in an SFC routine."""
    id: int
    operand: str          # Tag name, e.g. "Step_001"
    initial_step: bool
    actions: List[SFCAction] = field(default_factory=list)


@dataclass
class SFCTransition:
    """A transition between SFC steps."""
    id: int
    operand: str          # Tag name, e.g. "Tran_001"
    condition_lines: List[Line] = field(default_factory=list)  # ST expression(s)


@dataclass
class SFCBranch:
    """A branch (diverge/converge) in an SFC routine."""
    id: int
    branch_type: str      # "Selection" or "Simultaneous"
    branch_flow: str      # "Diverge" or "Converge"
    leg_ids: List[int] = field(default_factory=list)


@dataclass
class SFCDirectedLink:
    """An edge in the SFC flow graph."""
    from_id: int
    to_id: int


@dataclass
class SFCContent:
    """Container for all SFC elements within a routine."""
    steps: List[SFCStep] = field(default_factory=list)
    transitions: List[SFCTransition] = field(default_factory=list)
    branches: List[SFCBranch] = field(default_factory=list)
    directed_links: List[SFCDirectedLink] = field(default_factory=list)


@dataclass
class Routine:
    """Represents a routine within a program."""
    name: str
    routine_type: str          # "RLL", "ST", "SFC", or other
    description: str
    rungs: List[Rung] = field(default_factory=list)       # Populated for RLL routines
    lines: List[Line] = field(default_factory=list)       # Populated for ST routines
    sfc_content: Optional[SFCContent] = None              # Populated for SFC routines


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
        sfc_content: Optional[SFCContent] = None

        if routine_type == "RLL":
            rungs = _extract_rungs(routine_node)
        elif routine_type == "ST":
            lines = _extract_st_lines(routine_node)
        elif routine_type == "SFC":
            sfc_content = _extract_sfc_content(routine_node)

        routines.append(Routine(
            name=name,
            routine_type=routine_type,
            description=description,
            rungs=rungs,
            lines=lines,
            sfc_content=sfc_content,
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
    st_content_node = routine_node.find("STContent")
    if st_content_node is None:
        return []
    return _parse_st_lines(st_content_node)


def _parse_st_lines(st_content_node: etree._Element) -> List[Line]:
    """Parse <Line> children from an <STContent> element."""
    lines: List[Line] = []
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


# ---------------------------------------------------------------------------
# SFC extraction
# ---------------------------------------------------------------------------

def _extract_sfc_content(routine_node: etree._Element) -> Optional[SFCContent]:
    """Extract the full SFC content from an SFC <Routine> element."""
    sfc_node = routine_node.find("SFCContent")
    if sfc_node is None:
        return None

    steps = _extract_sfc_steps(sfc_node)
    transitions = _extract_sfc_transitions(sfc_node)
    branches = _extract_sfc_branches(sfc_node)
    directed_links = _extract_sfc_links(sfc_node)

    return SFCContent(
        steps=steps,
        transitions=transitions,
        branches=branches,
        directed_links=directed_links,
    )


def _extract_sfc_steps(sfc_node: etree._Element) -> List[SFCStep]:
    """Extract all <Step> elements from <SFCContent>."""
    steps: List[SFCStep] = []
    for step_node in sfc_node.xpath("./Step"):
        step_id = int(step_node.get("ID", "0"))
        operand = step_node.get("Operand", "")
        initial = step_node.get("InitialStep", "false").lower() == "true"

        actions: List[SFCAction] = []
        for action_node in step_node.xpath("./Action"):
            action_id = int(action_node.get("ID", "0"))
            action_operand = action_node.get("Operand", "")
            qualifier = action_node.get("Qualifier", "")
            is_bool = action_node.get("IsBoolean", "false").lower() == "true"

            # Action body contains ST lines
            action_lines: List[Line] = []
            body = action_node.find("Body")
            if body is not None:
                st_content = body.find("STContent")
                if st_content is not None:
                    action_lines = _parse_st_lines(st_content)

            actions.append(SFCAction(
                id=action_id,
                operand=action_operand,
                qualifier=qualifier,
                is_boolean=is_bool,
                lines=action_lines,
            ))

        steps.append(SFCStep(
            id=step_id,
            operand=operand,
            initial_step=initial,
            actions=actions,
        ))
    return steps


def _extract_sfc_transitions(sfc_node: etree._Element) -> List[SFCTransition]:
    """Extract all <Transition> elements from <SFCContent>."""
    transitions: List[SFCTransition] = []
    for trans_node in sfc_node.xpath("./Transition"):
        trans_id = int(trans_node.get("ID", "0"))
        operand = trans_node.get("Operand", "")

        condition_lines: List[Line] = []
        cond = trans_node.find("Condition")
        if cond is not None:
            st_content = cond.find("STContent")
            if st_content is not None:
                condition_lines = _parse_st_lines(st_content)

        transitions.append(SFCTransition(
            id=trans_id,
            operand=operand,
            condition_lines=condition_lines,
        ))
    return transitions


def _extract_sfc_branches(sfc_node: etree._Element) -> List[SFCBranch]:
    """Extract all <Branch> elements from <SFCContent>."""
    branches: List[SFCBranch] = []
    for branch_node in sfc_node.xpath("./Branch"):
        branch_id = int(branch_node.get("ID", "0"))
        branch_type = branch_node.get("BranchType", "")
        branch_flow = branch_node.get("BranchFlow", "")

        leg_ids: List[int] = []
        for leg_node in branch_node.xpath("./Leg"):
            try:
                leg_ids.append(int(leg_node.get("ID", "0")))
            except ValueError:
                pass

        branches.append(SFCBranch(
            id=branch_id,
            branch_type=branch_type,
            branch_flow=branch_flow,
            leg_ids=leg_ids,
        ))
    return branches


def _extract_sfc_links(sfc_node: etree._Element) -> List[SFCDirectedLink]:
    """Extract all <DirectedLink> elements from <SFCContent>."""
    links: List[SFCDirectedLink] = []
    for link_node in sfc_node.xpath("./DirectedLink"):
        try:
            from_id = int(link_node.get("FromID", "0"))
            to_id = int(link_node.get("ToID", "0"))
        except ValueError:
            continue
        links.append(SFCDirectedLink(from_id=from_id, to_id=to_id))
    return links
