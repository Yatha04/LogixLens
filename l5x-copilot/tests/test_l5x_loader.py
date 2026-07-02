"""
test_l5x_loader.py

Tests for src/parser/l5x_loader.py

Split into two groups:
  1. Error-handling tests (use tmp_path, no real file needed) – these verify
     that the loader rejects bad inputs correctly.
  2. Integration tests (use the `l5x_project` session fixture from conftest.py)
     – these verify that a real L5X file loads and produces a valid project.

Run with a real file:
    python -m pytest tests/test_l5x_loader.py --l5x-file path/to/program.L5X
"""
import pytest
from src.parser.l5x_loader import load_l5x, L5XProject, L5XMetadata
from src.parser.exceptions import L5XParseError, L5XValidationError


# ===========================================================================
# Error-handling tests (synthetic bad inputs – no real file required)
# ===========================================================================

class TestLoaderErrorHandling:
    def test_load_nonexistent_file_raises(self):
        """Loader raises FileNotFoundError for a path that does not exist."""
        with pytest.raises(FileNotFoundError):
            load_l5x("/this/path/does/not/exist.L5X")

    def test_load_non_xml_raises(self, tmp_path):
        """Loader raises L5XParseError when the file is not valid XML."""
        bad = tmp_path / "not_xml.L5X"
        bad.write_text("this is plain text, not XML")
        with pytest.raises(L5XParseError):
            load_l5x(str(bad))

    def test_load_wrong_root_element_raises(self, tmp_path):
        """Loader raises L5XValidationError when root element is not RSLogix5000Content."""
        f = tmp_path / "wrong_root.L5X"
        f.write_text('<?xml version="1.0"?><SomeOtherRoot/>')
        with pytest.raises(L5XValidationError):
            load_l5x(str(f))

    def test_load_missing_controller_degrades_gracefully(self, tmp_path):
        """No <Controller> element (e.g. TargetType='Module' component
        exports, found in real-world corpus files) loads as an empty
        synthesized-controller project instead of raising."""
        f = tmp_path / "no_controller.L5X"
        f.write_text(
            '<?xml version="1.0"?>'
            '<RSLogix5000Content TargetType="Module" TargetName="ModX"/>'
        )
        project = load_l5x(str(f))
        assert project.metadata.controller_name == "ModX"
        assert project.metadata.target_type == "Module"
        assert project.xpath("Tags/Tag") == []

    def test_namespace_stripping(self, tmp_path):
        """Namespace is stripped so plain XPath like Tags/Tag works."""
        l5x = '''\
<?xml version="1.0" encoding="UTF-8"?>
<RSLogix5000Content
    xmlns="http://www.rockwellautomation.com/FactoryTalkLogixDesigner"
    SchemaRevision="1.0" SoftwareRevision="33.00" TargetType="Controller">
    <Controller Name="NSTest" ProcessorType="1756-L83E"
        MajorRev="33" MinorRev="0"
        ProjectCreationDate="" LastModifiedDate="">
        <Tags>
            <Tag Name="sensor_ok" DataType="BOOL"/>
        </Tags>
    </Controller>
</RSLogix5000Content>'''
        f = tmp_path / "ns.L5X"
        f.write_text(l5x)
        project = load_l5x(str(f))
        tags = project.xpath("Tags/Tag")
        assert any(t.get("Name") == "sensor_ok" for t in tags), (
            "Namespace stripping failed – could not find tag via plain XPath"
        )


# ===========================================================================
# Integration tests – require a real L5X file via the l5x_project fixture
# ===========================================================================

class TestLoaderIntegration:
    def test_returns_l5xproject_instance(self, l5x_project):
        """load_l5x returns an L5XProject instance."""
        assert isinstance(l5x_project, L5XProject)

    def test_metadata_is_l5xmetadata(self, l5x_project):
        """The project has an L5XMetadata metadata object attached."""
        assert isinstance(l5x_project.metadata, L5XMetadata)

    def test_controller_name_is_non_empty_string(self, l5x_project):
        """Controller name is a non-empty string (parsed from real XML)."""
        name = l5x_project.metadata.controller_name
        assert isinstance(name, str) and name.strip(), (
            f"Expected a non-empty controller name, got: {name!r}"
        )

    def test_processor_type_is_non_empty_string(self, l5x_project):
        """Processor type is a non-empty string."""
        ptype = l5x_project.metadata.processor_type
        assert isinstance(ptype, str) and ptype.strip(), (
            f"Expected a non-empty processor type, got: {ptype!r}"
        )

    def test_major_revision_is_positive_integer(self, l5x_project):
        """Major revision is a positive integer (real PLCs always have one)."""
        assert isinstance(l5x_project.metadata.major_revision, int)
        assert l5x_project.metadata.major_revision > 0, (
            f"Major revision should be > 0, got {l5x_project.metadata.major_revision}"
        )

    def test_minor_revision_is_non_negative_integer(self, l5x_project):
        """Minor revision is a non-negative integer."""
        assert isinstance(l5x_project.metadata.minor_revision, int)
        assert l5x_project.metadata.minor_revision >= 0

    def test_software_revision_is_non_empty_string(self, l5x_project):
        """Software revision string (e.g. '35.01') is present."""
        srev = l5x_project.metadata.software_revision
        assert isinstance(srev, str) and srev.strip(), (
            f"Expected software revision string, got: {srev!r}"
        )

    def test_filepath_points_to_existing_file(self, l5x_project):
        """Stored filepath resolves to the actual file on disk."""
        import os
        assert os.path.isfile(l5x_project.metadata.filepath), (
            f"Metadata filepath does not point to a real file: "
            f"{l5x_project.metadata.filepath!r}"
        )

    def test_controller_element_is_present(self, l5x_project):
        """The project's controller element is not None."""
        assert l5x_project.controller is not None

    def test_xpath_on_controller_works(self, l5x_project):
        """project.xpath() executes without error and returns a list."""
        result = l5x_project.xpath("Tags/Tag")
        assert isinstance(result, list)
