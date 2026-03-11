import pytest
from lxml import etree
from src.parser.udt_extractor import UDTMember, UserDefinedType, extract_udts, _extract_udt_members
from src.parser.l5x_loader import L5XProject, load_l5x

def test_extract_udt_members_with_padding():
    """Test extracting members filters out padding (Names starting with ZZZZZZZZZZ)."""
    xml = """
    <DataType Name="TEST_UDT" Family="NoFamily" Class="User">
        <Members>
            <Member Name="ValidField" DataType="DINT" Dimension="0" Radix="Decimal" Hidden="false" ExternalAccess="Read/Write">
                <Description>A valid field</Description>
            </Member>
            <Member Name="ZZZZZZZZZZUDT_PAD" DataType="SINT" Dimension="0" Radix="Decimal" Hidden="true" ExternalAccess="Read/Write" />
            <Member Name="AnotherField" DataType="REAL" Dimension="0" Radix="Float" Hidden="false" ExternalAccess="Read Only" />
        </Members>
    </DataType>
    """
    dt_node = etree.fromstring(xml)
    
    members = _extract_udt_members(dt_node)
    
    assert len(members) == 2
    assert members[0].name == "ValidField"
    assert members[0].data_type == "DINT"
    assert members[0].description == "A valid field"
    
    assert members[1].name == "AnotherField"
    assert members[1].data_type == "REAL"
    assert members[1].radix == "Float"
    assert members[1].external_access == "Read Only"


def test_extract_udts_filters_builtins():
    """Test extract_udts only extracts DataType rows with Class='User'."""
    xml = """
    <RSLogix5000Content>
        <Controller Name="TestController">
            <DataTypes>
                <DataType Name="BuiltInType" Family="NoFamily" Class="Atomic" />
                <DataType Name="MyUDT" Family="NoFamily" Class="User">
                    <Description>My valid UDT</Description>
                    <Members>
                        <Member Name="Field1" DataType="DINT" Dimension="0" Radix="Decimal" Hidden="false" ExternalAccess="Read/Write" />
                    </Members>
                </DataType>
            </DataTypes>
        </Controller>
    </RSLogix5000Content>
    """
    tree = etree.ElementTree(etree.fromstring(xml))
    
    # Mock an L5XProject
    class DummyProject:
        def __init__(self, t):
            self.tree = t
            self.controller = t.find("Controller")
            
    project = DummyProject(tree)
    
    udts = extract_udts(project)
    
    assert len(udts) == 1
    assert udts[0].name == "MyUDT"
    assert udts[0].description == "My valid UDT"
    assert len(udts[0].members) == 1
    assert udts[0].members[0].name == "Field1"

def test_extract_udts_real_file(l5x_project):
    """Integration test checking UDT extraction on the real file."""
    udts = extract_udts(l5x_project)
    
    # We know ALARM_TYPE exists based on previous investigation
    assert len(udts) > 0
    
    alarm_type = next((u for u in udts if u.name == "ALARM_TYPE"), None)
    assert alarm_type is not None
    assert len(alarm_type.members) == 7
    
    # Ensure padding is actually gone across all parsed UDTs
    for udt in udts:
        for member in udt.members:
            assert not member.name.startswith("ZZZZZZZZZZ")
