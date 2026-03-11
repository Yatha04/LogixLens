import pytest
from lxml import etree
from src.parser.l5x_loader import L5XProject, L5XMetadata
from src.parser.aoi_extractor import extract_aois, AddOnInstruction, AOIParameter, AOILocalTag

@pytest.fixture
def mock_aoi_project():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <RSLogix5000Content>
        <Controller Name="TestController">
            <AddOnInstructionDefinitions>
                <AddOnInstructionDefinition Name="MotorControl" Revision="1.2">
                    <Description><![CDATA[Controls a standard motor]]></Description>
                    <Parameters>
                        <Parameter Name="EnableIn" DataType="BOOL" Usage="Input" Required="false" Visible="true" DefaultData="1">
                            <Description><![CDATA[Enable Input]]></Description>
                        </Parameter>
                        <Parameter Name="Start" DataType="BOOL" Usage="Input" Required="true" Visible="true" DefaultData="0"/>
                        <Parameter Name="MotorRun" DataType="BOOL" Usage="Output" Required="true" Visible="true" DefaultData="0"/>
                    </Parameters>
                    <LocalTags>
                        <LocalTag Name="Timer" DataType="TON" Dimensions="0">
                            <Description><![CDATA[Run Timer]]></Description>
                        </LocalTag>
                        <LocalTag Name="FaultBits" DataType="DINT" Dimensions="10"/>
                    </LocalTags>
                    <Routines>
                        <Routine Name="Logic" Type="RLL">
                            <RLLContent>
                                <Rung Number="0" Type="N">
                                    <Comment><![CDATA[Start Motor]]></Comment>
                                    <Text><![CDATA[XIC(EnableIn)XIC(Start)OTE(MotorRun);]]></Text>
                                </Rung>
                                <Rung Number="1" Type="D">
                                    <Text><![CDATA[XIC(Timer.DN)OTE(FaultBits[0]);(N)]]></Text>
                                </Rung>
                            </RLLContent>
                        </Routine>
                    </Routines>
                </AddOnInstructionDefinition>
                
                <AddOnInstructionDefinition Name="EmptyAOI" Revision="1.0">
                </AddOnInstructionDefinition>
            </AddOnInstructionDefinitions>
        </Controller>
    </RSLogix5000Content>
    """
    tree = etree.fromstring(xml_content.encode("utf-8"))
    controller = tree.find("Controller")
    metadata = L5XMetadata(
        filepath="dummy.L5X",
        controller_name="TestController",
        processor_type="Unknown",
        major_revision=1,
        minor_revision=0,
        software_revision="35.00",
        project_creation_date="",
        last_modified_date="",
        export_date="",
        target_type="Controller",
        schema_revision="1.0"
    )
    return L5XProject(metadata=metadata, tree=etree.ElementTree(tree), controller=controller)

def test_extract_aois_basic(mock_aoi_project):
    aois = extract_aois(mock_aoi_project)
    assert len(aois) == 2
    
    motor_aoi = aois[0]
    assert motor_aoi.name == "MotorControl"
    assert motor_aoi.revision == "1.2"
    assert motor_aoi.description == "Controls a standard motor"
    
    assert len(motor_aoi.parameters) == 3
    assert len(motor_aoi.local_tags) == 2
    assert len(motor_aoi.routines) == 1
    
    empty_aoi = aois[1]
    assert empty_aoi.name == "EmptyAOI"
    assert empty_aoi.revision == "1.0"
    assert empty_aoi.description == ""
    assert len(empty_aoi.parameters) == 0
    assert len(empty_aoi.local_tags) == 0
    assert len(empty_aoi.routines) == 0

def test_aoi_parameters(mock_aoi_project):
    aois = extract_aois(mock_aoi_project)
    params = aois[0].parameters
    
    assert params[0].name == "EnableIn"
    assert params[0].data_type == "BOOL"
    assert params[0].usage == "Input"
    assert params[0].required is False
    assert params[0].visible is True
    assert params[0].default_data == "1"
    assert params[0].description == "Enable Input"
    
    assert params[1].name == "Start"
    assert params[1].required is True
    
    assert params[2].name == "MotorRun"
    assert params[2].usage == "Output"

def test_aoi_local_tags(mock_aoi_project):
    aois = extract_aois(mock_aoi_project)
    tags = aois[0].local_tags
    
    assert tags[0].name == "Timer"
    assert tags[0].data_type == "TON"
    assert tags[0].dimensions == "0"
    assert tags[0].description == "Run Timer"
    
    assert tags[1].name == "FaultBits"
    assert tags[1].data_type == "DINT"
    assert tags[1].dimensions == "10"
    assert tags[1].description == ""

def test_aoi_routines(mock_aoi_project):
    aois = extract_aois(mock_aoi_project)
    routines = aois[0].routines
    
    assert len(routines) == 1
    assert routines[0].name == "Logic"
    assert routines[0].routine_type == "RLL"
    
    # Check that deleted rungs are skipped and rung text is parsed
    assert len(routines[0].rungs) == 1
    rung = routines[0].rungs[0]
    assert rung.number == 0
    assert rung.text == "XIC(EnableIn)XIC(Start)OTE(MotorRun);"
    assert rung.comment == "Start Motor"
