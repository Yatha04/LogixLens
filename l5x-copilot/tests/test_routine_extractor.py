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
