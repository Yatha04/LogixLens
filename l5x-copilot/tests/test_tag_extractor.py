import pytest
from lxml import etree
from src.parser.l5x_loader import L5XProject, L5XMetadata
from src.parser.tag_extractor import extract_tags, L5XTag

@pytest.fixture
def sample_l5x_project():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <RSLogix5000Content>
        <Controller Name="TestController">
            <Tags>
                <Tag Name="GlobalMotor" TagType="Base" DataType="DINT" Dimensions="0" Constant="false" ExternalAccess="Read/Write">
                    <Description><![CDATA[Main conveyor motor]]></Description>
                </Tag>
                <Tag Name="GlobalMotorAlias" TagType="Alias" DataType="DINT" AliasFor="Local:1:O.Data.0" ExternalAccess="Read Only"/>
            </Tags>
            <Programs>
                <Program Name="ConveyorCtrl">
                    <Tags>
                        <Tag Name="LocalSpeed" TagType="Base" DataType="REAL" Dimensions="0" Constant="true" ExternalAccess="None"/>
                    </Tags>
                </Program>
            </Programs>
        </Controller>
    </RSLogix5000Content>
    """
    tree = etree.ElementTree(etree.fromstring(xml_content.encode("utf-8")))
    root = tree.getroot()
    controller = root.find("Controller")
    
    metadata = L5XMetadata(filepath="mem", controller_name="TestController", processor_type="Unknown",
                           major_revision=1, minor_revision=0, software_revision="35", project_creation_date="",
                           last_modified_date="", export_date="", target_type="Controller", schema_revision="1.0")
    
    return L5XProject(metadata, tree, controller)

def test_extract_tags(sample_l5x_project):
    tags = extract_tags(sample_l5x_project)
    
    assert len(tags) == 3
    
    # Check GlobalMotor
    global_motor = next(t for t in tags if t.name == "GlobalMotor")
    assert global_motor.scope == "Controller"
    assert global_motor.tag_type == "Base"
    assert global_motor.data_type == "DINT"
    assert global_motor.description == "Main conveyor motor"
    assert not global_motor.constant
    assert global_motor.external_access == "Read/Write"
    assert global_motor.dimensions == "0"
    
    # Check Alias
    global_alias = next(t for t in tags if t.name == "GlobalMotorAlias")
    assert global_alias.scope == "Controller"
    assert global_alias.tag_type == "Alias"
    assert global_alias.alias_for == "Local:1:O.Data.0"
    assert global_alias.external_access == "Read Only"
    
    # Check Local tag
    local_speed = next(t for t in tags if t.name == "LocalSpeed")
    assert local_speed.scope == "ConveyorCtrl"
    assert local_speed.data_type == "REAL"
    assert local_speed.constant
    assert local_speed.external_access == "None"
