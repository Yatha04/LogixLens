import pytest
from lxml import etree
from src.parser.l5x_loader import L5XProject, L5XMetadata
from src.parser.module_extractor import extract_modules, L5XModule, L5XPort


def create_dummy_project(xml_content: str) -> L5XProject:
    """Helper to create an L5XProject from raw XML string."""
    root = etree.fromstring(xml_content)
    # create a dummy metadata
    meta = L5XMetadata(
        filepath="dummy.L5X",
        controller_name="TestController",
        processor_type="Unknown",
        major_revision=1,
        minor_revision=0,
        software_revision="35.0",
        project_creation_date="",
        last_modified_date="",
        export_date="",
        target_type="Controller",
        schema_revision="1.0"
    )
    # L5X xml usually has Controller as root or child of RSLogix5000Content
    controller = root.find("Controller")
    if controller is None:
        if root.tag == "Controller":
            controller = root
        else:
            raise ValueError("Invalid dummy XML: missing Controller node")
    
    return L5XProject(metadata=meta, tree=etree.ElementTree(root), controller=controller)


def test_extract_modules_empty():
    xml = """
    <RSLogix5000Content>
        <Controller Use="Context" Name="TestController">
            <Modules>
            </Modules>
        </Controller>
    </RSLogix5000Content>
    """
    project = create_dummy_project(xml)
    modules = extract_modules(project)
    assert len(modules) == 0


def test_extract_modules_no_modules_node():
    xml = """
    <RSLogix5000Content>
        <Controller Use="Context" Name="TestController">
        </Controller>
    </RSLogix5000Content>
    """
    project = create_dummy_project(xml)
    modules = extract_modules(project)
    assert len(modules) == 0


def test_extract_modules_basic():
    xml = """
    <RSLogix5000Content>
        <Controller Use="Context" Name="TestController">
            <Modules>
                <Module Name="Local" CatalogNumber="5069-L310ERS2" Vendor="1" ProductType="14" ProductCode="236" Major="35" Minor="11" ParentModule="Local" ParentModPortId="1">
                    <Ports>
                        <Port Id="1" Address="0" Type="ICP" Upstream="false"/>
                        <Port Id="2" Address="192.168.1.1" Type="Ethernet" Upstream="true"/>
                    </Ports>
                </Module>
                <Module Name="ENBT" CatalogNumber="1756-ENBT" Vendor="1" ProductType="12" ProductCode="15" Major="6" Minor="1" ParentModule="Local" ParentModPortId="1">
                    <Ports>
                        <Port Id="1" Address="1" Type="ICP" Upstream="true"/>
                    </Ports>
                </Module>
            </Modules>
        </Controller>
    </RSLogix5000Content>
    """
    project = create_dummy_project(xml)
    modules = extract_modules(project)
    
    assert len(modules) == 2
    
    mod1 = modules[0]
    assert mod1.name == "Local"
    assert mod1.catalog_number == "5069-L310ERS2"
    assert mod1.vendor == 1
    assert mod1.product_type == 14
    assert mod1.product_code == 236
    assert mod1.major == 35
    assert mod1.minor == 11
    assert mod1.parent_module == "Local"
    assert mod1.parent_mod_port_id == 1
    
    assert len(mod1.ports) == 2
    assert mod1.ports[0].id == 1
    assert mod1.ports[0].type == "ICP"
    assert mod1.ports[0].address == "0"
    assert mod1.ports[0].upstream is False
    
    assert mod1.ports[1].id == 2
    assert mod1.ports[1].type == "Ethernet"
    assert mod1.ports[1].address == "192.168.1.1"
    assert mod1.ports[1].upstream is True
    
    mod2 = modules[1]
    assert mod2.name == "ENBT"
    assert mod2.catalog_number == "1756-ENBT"
    assert mod2.vendor == 1
    assert len(mod2.ports) == 1
    assert mod2.ports[0].upstream is True


def test_extract_modules_missing_attributes():
    xml = """
    <RSLogix5000Content>
        <Controller Use="Context" Name="TestController">
            <Modules>
                <Module Name="Minimal">
                </Module>
            </Modules>
        </Controller>
    </RSLogix5000Content>
    """
    project = create_dummy_project(xml)
    modules = extract_modules(project)
    
    assert len(modules) == 1
    mod = modules[0]
    assert mod.name == "Minimal"
    assert mod.catalog_number == ""
    assert mod.vendor == 0
    assert mod.product_type == 0
    assert mod.product_code == 0
    assert mod.major == 0
    assert mod.minor == 0
    assert mod.parent_module == ""
    assert mod.parent_mod_port_id == 0
    assert len(mod.ports) == 0
