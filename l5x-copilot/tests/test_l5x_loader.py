import pytest
from src.parser.l5x_loader import load_l5x, L5XProject
from src.parser.exceptions import L5XParseError, L5XValidationError


def test_load_valid_l5x(tmp_path):
    """Minimal valid L5X file loads correctly."""
    l5x_content = '''<?xml version="1.0" encoding="UTF-8"?>
    <RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="32.04"
        TargetType="Controller" ExportDate="Thu Jan 23 14:22:01 2025">
        <Controller Name="TestController" ProcessorType="1769-L33ER"
            MajorRev="32" MinorRev="4"
            ProjectCreationDate="Mon Sep 12 08:00:00 2022"
            LastModifiedDate="Thu Jan 23 14:20:55 2025">
            <DataTypes/>
            <Modules/>
            <AddOnInstructionDefinitions/>
            <Tags/>
            <Programs/>
            <Tasks/>
        </Controller>
    </RSLogix5000Content>'''

    f = tmp_path / "test.L5X"
    f.write_text(l5x_content)

    project = load_l5x(str(f))

    assert isinstance(project, L5XProject)
    assert project.metadata.controller_name == "TestController"
    assert project.metadata.processor_type == "1769-L33ER"
    assert project.metadata.major_revision == 32
    assert project.metadata.minor_revision == 4
    assert project.metadata.software_revision == "32.04"
    assert project.metadata.target_type == "Controller"


def test_load_nonexistent_file():
    with pytest.raises(FileNotFoundError):
        load_l5x("/nonexistent/path.L5X")


def test_load_non_xml(tmp_path):
    f = tmp_path / "bad.L5X"
    f.write_text("this is not xml at all")
    with pytest.raises(L5XParseError):
        load_l5x(str(f))


def test_load_wrong_root_element(tmp_path):
    f = tmp_path / "wrong.L5X"
    f.write_text('<?xml version="1.0"?><SomeOtherRoot/>')
    with pytest.raises(L5XValidationError):
        load_l5x(str(f))


def test_load_missing_controller(tmp_path):
    f = tmp_path / "no_ctrl.L5X"
    f.write_text('<?xml version="1.0"?><RSLogix5000Content/>')
    with pytest.raises(L5XValidationError):
        load_l5x(str(f))


def test_load_with_namespace(tmp_path):
    """L5X files with XML namespace should still parse correctly."""
    l5x_content = '''<?xml version="1.0" encoding="UTF-8"?>
    <RSLogix5000Content
        xmlns="http://www.rockwellautomation.com/FactoryTalkLogixDesigner"
        SchemaRevision="1.0" SoftwareRevision="33.00"
        TargetType="Controller">
        <Controller Name="NSController" ProcessorType="1756-L83E"
            MajorRev="33" MinorRev="0"
            ProjectCreationDate="" LastModifiedDate="">
            <Tags/>
            <Programs/>
        </Controller>
    </RSLogix5000Content>'''

    f = tmp_path / "ns_test.L5X"
    f.write_text(l5x_content)

    project = load_l5x(str(f))
    assert project.metadata.controller_name == "NSController"
    assert project.metadata.processor_type == "1756-L83E"


def test_xpath_works_after_namespace_strip(tmp_path):
    """XPath queries should work without namespace prefixes."""
    l5x_content = '''<?xml version="1.0" encoding="UTF-8"?>
    <RSLogix5000Content
        xmlns="http://www.rockwellautomation.com/FactoryTalkLogixDesigner"
        SchemaRevision="1.0" SoftwareRevision="33.00" TargetType="Controller">
        <Controller Name="Test" ProcessorType="1769-L33ER"
            MajorRev="32" MinorRev="0">
            <Tags>
                <Tag Name="my_tag" DataType="BOOL"/>
            </Tags>
        </Controller>
    </RSLogix5000Content>'''

    f = tmp_path / "xpath_test.L5X"
    f.write_text(l5x_content)

    project = load_l5x(str(f))
    tags = project.xpath("Tags/Tag")
    assert len(tags) == 1
    assert tags[0].get("Name") == "my_tag"
