import pytest
from lxml import etree
from src.parser.l5x_loader import L5XProject, L5XMetadata
from src.parser.routine_extractor import extract_programs, Program, Routine, Rung, Line


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_project(xml_body: str) -> L5XProject:
    """Wrap an XML body inside a minimal L5X document and return an L5XProject."""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <RSLogix5000Content>
        <Controller Name="TestCtrl">
            {xml_body}
        </Controller>
    </RSLogix5000Content>"""
    tree = etree.ElementTree(etree.fromstring(xml.encode("utf-8")))
    root = tree.getroot()
    controller = root.find("Controller")
    metadata = L5XMetadata(
        filepath="mem", controller_name="TestCtrl", processor_type="Unknown",
        major_revision=1, minor_revision=0, software_revision="35",
        project_creation_date="", last_modified_date="",
        export_date="", target_type="Controller", schema_revision="1.0",
    )
    return L5XProject(metadata, tree, controller)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RLL_XML = """
<Programs>
    <Program Name="MainProgram" MainRoutineName="Main" FaultRoutineName="FaultHandler" Disabled="false">
        <Routines>
            <Routine Name="Main" Type="RLL">
                <Description><![CDATA[Main ladder routine]]></Description>
                <RLLContent>
                    <Rung Number="0" Type="N">
                        <Comment><![CDATA[Start conveyor]]></Comment>
                        <Text><![CDATA[XIC(StartBtn)OTE(Motor);]]></Text>
                    </Rung>
                    <Rung Number="1" Type="N">
                        <Text><![CDATA[XIC(Motor)TON(Timer1,?,?);]]></Text>
                    </Rung>
                    <Rung Number="2" Type="D">
                        <Text><![CDATA[XIC(OldTag)OTE(OldOut);]]></Text>
                    </Rung>
                </RLLContent>
            </Routine>
            <Routine Name="FaultHandler" Type="RLL">
                <RLLContent>
                    <Rung Number="0" Type="N">
                        <Text><![CDATA[OTE(FaultLight);]]></Text>
                    </Rung>
                </RLLContent>
            </Routine>
        </Routines>
    </Program>
</Programs>
"""

ST_XML = """
<Programs>
    <Program Name="STProgram" MainRoutineName="STMain" FaultRoutineName="" Disabled="false">
        <Routines>
            <Routine Name="STMain" Type="ST">
                <STContent>
                    <Line Number="0"><![CDATA[IF StartBtn THEN]]></Line>
                    <Line Number="1"><![CDATA[    Motor := 1;]]></Line>
                    <Line Number="2"><![CDATA[END_IF;]]></Line>
                </STContent>
            </Routine>
        </Routines>
    </Program>
</Programs>
"""

DISABLED_XML = """
<Programs>
    <Program Name="DisabledProg" MainRoutineName="" FaultRoutineName="" Disabled="true">
        <Routines/>
    </Program>
</Programs>
"""

EMPTY_XML = """<Programs/>"""


# ---------------------------------------------------------------------------
# Tests: Program-level extraction
# ---------------------------------------------------------------------------

class TestExtractPrograms:
    def test_no_programs_node(self):
        project = _make_project("<Tags/>")
        assert extract_programs(project) == []

    def test_empty_programs(self):
        project = _make_project(EMPTY_XML)
        assert extract_programs(project) == []

    def test_program_attributes(self):
        project = _make_project(RLL_XML)
        programs = extract_programs(project)
        assert len(programs) == 1

        prog = programs[0]
        assert prog.name == "MainProgram"
        assert prog.main_routine_name == "Main"
        assert prog.fault_routine_name == "FaultHandler"
        assert prog.disabled is False

    def test_disabled_program(self):
        project = _make_project(DISABLED_XML)
        programs = extract_programs(project)
        assert len(programs) == 1
        assert programs[0].disabled is True

    def test_multiple_programs(self):
        xml = f"{RLL_XML.replace('<Programs>', '').replace('</Programs>', '')}{ST_XML.replace('<Programs>', '').replace('</Programs>', '')}"
        combined = f"<Programs>{xml}</Programs>"
        project = _make_project(combined)
        programs = extract_programs(project)
        assert len(programs) == 2
        names = {p.name for p in programs}
        assert names == {"MainProgram", "STProgram"}


# ---------------------------------------------------------------------------
# Tests: Routine-level extraction
# ---------------------------------------------------------------------------

class TestExtractRoutines:
    def test_rll_routine_count(self):
        project = _make_project(RLL_XML)
        prog = extract_programs(project)[0]
        assert len(prog.routines) == 2

    def test_rll_routine_name_and_type(self):
        project = _make_project(RLL_XML)
        prog = extract_programs(project)[0]
        main = next(r for r in prog.routines if r.name == "Main")
        assert main.routine_type == "RLL"

    def test_rll_routine_description(self):
        project = _make_project(RLL_XML)
        prog = extract_programs(project)[0]
        main = next(r for r in prog.routines if r.name == "Main")
        assert main.description == "Main ladder routine"

    def test_routine_no_description(self):
        project = _make_project(RLL_XML)
        prog = extract_programs(project)[0]
        fault = next(r for r in prog.routines if r.name == "FaultHandler")
        assert fault.description == ""

    def test_st_routine_type(self):
        project = _make_project(ST_XML)
        prog = extract_programs(project)[0]
        assert prog.routines[0].routine_type == "ST"


# ---------------------------------------------------------------------------
# Tests: Rung extraction (RLL)
# ---------------------------------------------------------------------------

class TestExtractRungs:
    def _get_main_routine(self) -> Routine:
        project = _make_project(RLL_XML)
        prog = extract_programs(project)[0]
        return next(r for r in prog.routines if r.name == "Main")

    def test_deleted_rungs_skipped(self):
        routine = self._get_main_routine()
        # Rung 2 is Type="D" and should be excluded
        assert len(routine.rungs) == 2

    def test_rung_numbers(self):
        routine = self._get_main_routine()
        numbers = [r.number for r in routine.rungs]
        assert numbers == [0, 1]

    def test_rung_text(self):
        routine = self._get_main_routine()
        rung0 = routine.rungs[0]
        assert rung0.text == "XIC(StartBtn)OTE(Motor);"

    def test_rung_comment(self):
        routine = self._get_main_routine()
        rung0 = routine.rungs[0]
        assert rung0.comment == "Start conveyor"

    def test_rung_no_comment(self):
        routine = self._get_main_routine()
        rung1 = routine.rungs[1]
        assert rung1.comment == ""

    def test_rll_routine_has_no_lines(self):
        routine = self._get_main_routine()
        assert routine.lines == []

    def test_normalize_rung_text_n_suffix(self):
        xml = """
        <Programs>
            <Program Name="P" MainRoutineName="R" FaultRoutineName="" Disabled="false">
                <Routines>
                    <Routine Name="R" Type="RLL">
                        <RLLContent>
                            <Rung Number="0" Type="N">
                                <Text><![CDATA[XIC(Tag1)OTE(Tag2);(N)]]></Text>
                            </Rung>
                        </RLLContent>
                    </Routine>
                </Routines>
            </Program>
        </Programs>
        """
        project = _make_project(xml)
        prog = extract_programs(project)[0]
        rung = prog.routines[0].rungs[0]
        assert rung.text == "XIC(Tag1)OTE(Tag2);N"


# ---------------------------------------------------------------------------
# Tests: Line extraction (ST)
# ---------------------------------------------------------------------------

class TestExtractSTLines:
    def _get_st_routine(self) -> Routine:
        project = _make_project(ST_XML)
        prog = extract_programs(project)[0]
        return prog.routines[0]

    def test_line_count(self):
        routine = self._get_st_routine()
        assert len(routine.lines) == 3

    def test_line_numbers(self):
        routine = self._get_st_routine()
        numbers = [l.number for l in routine.lines]
        assert numbers == [0, 1, 2]

    def test_line_text(self):
        routine = self._get_st_routine()
        assert routine.lines[0].text == "IF StartBtn THEN"
        assert routine.lines[1].text == "Motor := 1;"
        assert routine.lines[2].text == "END_IF;"

    def test_st_routine_has_no_rungs(self):
        routine = self._get_st_routine()
        assert routine.rungs == []


# ---------------------------------------------------------------------------
# SFC Fixtures
# ---------------------------------------------------------------------------

SFC_SIMPLE_XML = """
<Programs>
    <Program Name="SFCProgram" MainRoutineName="SFCMain" FaultRoutineName="" Disabled="false">
        <Routines>
            <Routine Name="SFCMain" Type="SFC">
                <Description><![CDATA[Simple SFC routine]]></Description>
                <SFCContent SheetSize="Letter" SheetOrientation="Landscape">
                    <Step ID="0" X="400" Y="60" Operand="Step_001" InitialStep="true"
                     PresetUsesExpr="false" LimitHighUsesExpr="false" LimitLowUsesExpr="false"
                     ShowActions="false" HideDesc="false" DescX="0" DescY="0" DescWidth="0">
                        <Action ID="1" Operand="Action_001" Qualifier="NonStored"
                         IsBoolean="false" PresetUsesExpr="false">
                            <Body>
                                <STContent>
                                    <Line Number="0"><![CDATA[StepNo := 1;]]></Line>
                                    <Line Number="1"><![CDATA[Desc := 'Init';]]></Line>
                                </STContent>
                            </Body>
                        </Action>
                    </Step>
                    <Step ID="2" X="400" Y="240" Operand="Step_002" InitialStep="false"
                     PresetUsesExpr="false" LimitHighUsesExpr="false" LimitLowUsesExpr="false"
                     ShowActions="false" HideDesc="false" DescX="0" DescY="0" DescWidth="0">
                        <Action ID="3" Operand="Action_002" Qualifier="NonStored"
                         IsBoolean="true" PresetUsesExpr="false">
                            <Body>
                                <STContent>
                                    <Line Number="0"><![CDATA[StepNo := 2;]]></Line>
                                </STContent>
                            </Body>
                        </Action>
                        <Action ID="5" Operand="Action_002B" Qualifier="S"
                         IsBoolean="false" PresetUsesExpr="false">
                            <Body>
                                <STContent>
                                    <Line Number="0"><![CDATA[Motor := 1;]]></Line>
                                </STContent>
                            </Body>
                        </Action>
                    </Step>
                    <Step ID="4" X="400" Y="440" Operand="Step_003" InitialStep="false"
                     PresetUsesExpr="false" LimitHighUsesExpr="false" LimitLowUsesExpr="false"
                     ShowActions="true" HideDesc="false" DescX="0" DescY="0" DescWidth="0"/>
                    <Transition ID="10" X="400" Y="160" Operand="Tran_001" HideDesc="false"
                     DescX="0" DescY="0" DescWidth="0">
                        <Condition>
                            <STContent>
                                <Line Number="0"><![CDATA[Ready AND Step_001.DN;]]></Line>
                            </STContent>
                        </Condition>
                    </Transition>
                    <Transition ID="11" X="400" Y="340" Operand="Tran_002" HideDesc="false"
                     DescX="0" DescY="0" DescWidth="0">
                        <Condition>
                            <STContent>
                                <Line Number="0"><![CDATA[Done AND Step_002.DN;]]></Line>
                            </STContent>
                        </Condition>
                    </Transition>
                    <DirectedLink FromID="0" ToID="10" Show="true"/>
                    <DirectedLink FromID="10" ToID="2" Show="true"/>
                    <DirectedLink FromID="2" ToID="11" Show="true"/>
                    <DirectedLink FromID="11" ToID="4" Show="true"/>
                    <DirectedLink FromID="4" ToID="0" Show="false"/>
                </SFCContent>
            </Routine>
        </Routines>
    </Program>
</Programs>
"""

SFC_BRANCH_XML = """
<Programs>
    <Program Name="BranchProg" MainRoutineName="BranchSFC" FaultRoutineName="" Disabled="false">
        <Routines>
            <Routine Name="BranchSFC" Type="SFC">
                <SFCContent SheetSize="Letter" SheetOrientation="Landscape">
                    <Step ID="0" X="200" Y="100" Operand="Step_A" InitialStep="true"
                     PresetUsesExpr="false" LimitHighUsesExpr="false" LimitLowUsesExpr="false"
                     ShowActions="false" HideDesc="false" DescX="0" DescY="0" DescWidth="0">
                        <Action ID="1" Operand="Act_A" Qualifier="NonStored"
                         IsBoolean="false" PresetUsesExpr="false">
                            <Body>
                                <STContent>
                                    <Line Number="0"><![CDATA[x := 1;]]></Line>
                                </STContent>
                            </Body>
                        </Action>
                    </Step>
                    <Branch ID="10" Y="200" BranchType="Selection" BranchFlow="Diverge"
                     Priority="Default">
                        <Leg ID="11"/>
                        <Leg ID="12"/>
                    </Branch>
                    <Branch ID="20" Y="500" BranchType="Simultaneous" BranchFlow="Converge">
                        <Leg ID="21"/>
                        <Leg ID="22"/>
                        <Leg ID="23"/>
                    </Branch>
                    <Transition ID="30" X="200" Y="300" Operand="Tran_X" HideDesc="false"
                     DescX="0" DescY="0" DescWidth="0">
                        <Condition>
                            <STContent>
                                <Line Number="0"><![CDATA[cond;]]></Line>
                            </STContent>
                        </Condition>
                    </Transition>
                    <DirectedLink FromID="0" ToID="10" Show="true"/>
                    <DirectedLink FromID="10" ToID="30" Show="true"/>
                </SFCContent>
            </Routine>
        </Routines>
    </Program>
</Programs>
"""


# ---------------------------------------------------------------------------
# Tests: SFC extraction
# ---------------------------------------------------------------------------

class TestExtractSFC:
    # --- Steps ---
    def test_sfc_step_count(self):
        project = _make_project(SFC_SIMPLE_XML)
        routine = extract_programs(project)[0].routines[0]
        assert routine.sfc_content is not None
        assert len(routine.sfc_content.steps) == 3

    def test_sfc_step_operands(self):
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        operands = [s.operand for s in sfc.steps]
        assert operands == ["Step_001", "Step_002", "Step_003"]

    def test_sfc_initial_step(self):
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        assert sfc.steps[0].initial_step is True
        assert sfc.steps[1].initial_step is False

    def test_sfc_step_without_actions(self):
        """Step_003 is self-closing with no <Action> children."""
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        assert len(sfc.steps[2].actions) == 0

    # --- Actions ---
    def test_sfc_action_count(self):
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        # Step_001 has 1 action, Step_002 has 2 actions
        assert len(sfc.steps[0].actions) == 1
        assert len(sfc.steps[1].actions) == 2

    def test_sfc_action_attributes(self):
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        action = sfc.steps[0].actions[0]
        assert action.operand == "Action_001"
        assert action.qualifier == "NonStored"
        assert action.is_boolean is False

    def test_sfc_action_boolean(self):
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        action = sfc.steps[1].actions[0]
        assert action.is_boolean is True

    def test_sfc_action_st_lines(self):
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        lines = sfc.steps[0].actions[0].lines
        assert len(lines) == 2
        assert lines[0].text == "StepNo := 1;"
        assert lines[1].text == "Desc := 'Init';"

    def test_sfc_multiple_actions_on_step(self):
        """Step_002 has two actions with different qualifiers."""
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        a1, a2 = sfc.steps[1].actions
        assert a1.qualifier == "NonStored"
        assert a2.qualifier == "S"
        assert a2.operand == "Action_002B"

    # --- Transitions ---
    def test_sfc_transition_count(self):
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        assert len(sfc.transitions) == 2

    def test_sfc_transition_operand(self):
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        assert sfc.transitions[0].operand == "Tran_001"

    def test_sfc_transition_condition(self):
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        cond = sfc.transitions[0].condition_lines
        assert len(cond) == 1
        assert cond[0].text == "Ready AND Step_001.DN;"

    # --- Branches ---
    def test_sfc_branch_count(self):
        project = _make_project(SFC_BRANCH_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        assert len(sfc.branches) == 2

    def test_sfc_branch_selection_diverge(self):
        project = _make_project(SFC_BRANCH_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        b = sfc.branches[0]
        assert b.branch_type == "Selection"
        assert b.branch_flow == "Diverge"
        assert b.leg_ids == [11, 12]

    def test_sfc_branch_simultaneous_converge(self):
        project = _make_project(SFC_BRANCH_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        b = sfc.branches[1]
        assert b.branch_type == "Simultaneous"
        assert b.branch_flow == "Converge"
        assert b.leg_ids == [21, 22, 23]

    # --- Directed Links ---
    def test_sfc_link_count(self):
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        assert len(sfc.directed_links) == 5

    def test_sfc_link_values(self):
        project = _make_project(SFC_SIMPLE_XML)
        sfc = extract_programs(project)[0].routines[0].sfc_content
        first = sfc.directed_links[0]
        assert first.from_id == 0
        assert first.to_id == 10

    # --- Routine-level ---
    def test_sfc_routine_type(self):
        project = _make_project(SFC_SIMPLE_XML)
        routine = extract_programs(project)[0].routines[0]
        assert routine.routine_type == "SFC"

    def test_sfc_routine_description(self):
        project = _make_project(SFC_SIMPLE_XML)
        routine = extract_programs(project)[0].routines[0]
        assert routine.description == "Simple SFC routine"

    def test_sfc_routine_has_no_rungs_or_lines(self):
        project = _make_project(SFC_SIMPLE_XML)
        routine = extract_programs(project)[0].routines[0]
        assert routine.rungs == []
        assert routine.lines == []
