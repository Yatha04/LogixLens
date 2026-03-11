"""
test_tag_extractor.py

Tests for src/parser/tag_extractor.py

Integration tests use a real L5X file via the `l5x_project` fixture.
All assertions are structural – they do not hard-code names or counts
that are specific to one project file.

Run with a real file:
    python -m pytest tests/test_tag_extractor.py --l5x-file path/to/program.L5X
"""
import pytest
from src.parser.tag_extractor import extract_tags, L5XTag

VALID_TAG_TYPES = {"Base", "Alias", "Produced", "Consumed"}
VALID_EXTERNAL_ACCESS = {"Read/Write", "Read Only", "None"}


class TestTagExtractorIntegration:
    @pytest.fixture(autouse=True)
    def _load(self, l5x_project):
        self.tags = extract_tags(l5x_project)
        self.project = l5x_project

    # --- Return type ---

    def test_returns_list(self):
        """extract_tags returns a list."""
        assert isinstance(self.tags, list)

    def test_tags_are_l5xtag_instances(self):
        """Every item is an L5XTag."""
        for tag in self.tags:
            assert isinstance(tag, L5XTag), (
                f"Expected L5XTag, got {type(tag).__name__}: {tag}"
            )

    # --- Real programs always have tags ---

    def test_at_least_one_tag_exists(self):
        """A real PLC project will always have at least one controller-scoped tag."""
        assert len(self.tags) > 0, "No tags found in the real L5X file."

    # --- Structural correctness ---

    def test_all_tags_have_non_empty_name(self):
        """Every tag has a non-empty name string."""
        for tag in self.tags:
            assert isinstance(tag.name, str) and tag.name.strip(), (
                f"Tag with empty name found: {tag!r}"
            )

    def test_all_tags_have_non_empty_data_type(self):
        """Every tag has a data type string (BOOL, DINT, UDT name, etc.)."""
        for tag in self.tags:
            assert isinstance(tag.data_type, str) and tag.data_type.strip(), (
                f"Tag {tag.name!r} has an empty data_type"
            )

    def test_all_tags_have_known_tag_type(self):
        """tag_type is one of the known Logix tag types."""
        for tag in self.tags:
            assert tag.tag_type in VALID_TAG_TYPES, (
                f"Tag {tag.name!r} has unexpected tag_type={tag.tag_type!r}. "
                f"Expected one of {VALID_TAG_TYPES}"
            )

    def test_all_tags_have_valid_external_access(self):
        """external_access is one of the three known Logix values."""
        for tag in self.tags:
            assert tag.external_access in VALID_EXTERNAL_ACCESS, (
                f"Tag {tag.name!r} has unexpected external_access={tag.external_access!r}. "
                f"Expected one of {VALID_EXTERNAL_ACCESS}"
            )

    def test_all_tags_constant_is_bool(self):
        """constant field is always a Python bool."""
        for tag in self.tags:
            assert isinstance(tag.constant, bool), (
                f"Tag {tag.name!r}: constant should be bool, got {type(tag.constant)}"
            )

    def test_all_tags_scope_is_string(self):
        """scope is always a non-empty string ('Controller' or a program name)."""
        for tag in self.tags:
            assert isinstance(tag.scope, str) and tag.scope.strip(), (
                f"Tag {tag.name!r} has empty scope"
            )

    # --- Scope correctness ---

    def test_controller_scoped_tags_exist(self):
        """At least some tags must be Controller-scoped."""
        ctrl_tags = [t for t in self.tags if t.scope == "Controller"]
        assert ctrl_tags, "No Controller-scoped tags found in a real L5X project."

    def test_program_scoped_tags_have_real_program_scope(self):
        """Program-scoped tags must have a scope that is not 'Controller'."""
        prog_tags = [t for t in self.tags if t.scope != "Controller"]
        for tag in prog_tags:
            assert tag.scope.strip() and tag.scope != "Controller", (
                f"Unexpected scope {tag.scope!r} for tag {tag.name!r}"
            )

    # --- Alias tags ---

    def test_alias_tags_have_alias_for(self):
        """Any tag with TagType='Alias' must have a non-empty alias_for."""
        for tag in self.tags:
            if tag.tag_type == "Alias":
                assert tag.alias_for.strip(), (
                    f"Alias tag {tag.name!r} has an empty alias_for field"
                )

    def test_non_alias_tags_alias_for_is_empty(self):
        """Non-Alias tags should have an empty alias_for."""
        for tag in self.tags:
            if tag.tag_type != "Alias":
                assert tag.alias_for == "" or tag.alias_for is None, (
                    f"Non-alias tag {tag.name!r} has alias_for={tag.alias_for!r}"
                )

    # --- Description ---

    def test_description_is_string(self):
        """description field is always a string (may be empty if no description)."""
        for tag in self.tags:
            assert isinstance(tag.description, str), (
                f"Tag {tag.name!r}: description should be str, got {type(tag.description)}"
            )

    # --- No duplicate controller-scope tag names ---

    def test_controller_tag_names_are_unique(self):
        """Controller-scoped tag names must be unique within that scope."""
        ctrl_names = [t.name for t in self.tags if t.scope == "Controller"]
        assert len(ctrl_names) == len(set(ctrl_names)), (
            f"Duplicate controller-scoped tag names: "
            f"{[n for n in ctrl_names if ctrl_names.count(n) > 1]}"
        )
