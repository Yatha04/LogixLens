import pytest
from src.parser.project_model import parse_project, ParsedProject
from src.parser.l5x_loader import L5XProject

def test_parse_project_integration(parsed_project: ParsedProject):
    """Integration test: parse the entire project and verify structural integrity."""
    assert isinstance(parsed_project, ParsedProject)
    
    # Verify counts roughly match what we expect
    assert len(parsed_project.tags) > 0
    assert len(parsed_project.programs) >= 0
    assert len(parsed_project.modules) >= 0
    assert len(parsed_project.udts) >= 0
    assert len(parsed_project.aois) >= 0
    assert len(parsed_project.parsed_rungs) >= 0
    assert len(parsed_project.cross_reference) >= 0

def test_project_model_lookups(parsed_project: ParsedProject):
    """Test get_tag, get_udt, get_aoi convenience methods."""
    if parsed_project.tags:
        sample_tag = parsed_project.tags[0]
        found = parsed_project.get_tag(sample_tag.name, sample_tag.scope)
        assert found == sample_tag
        
        # Test case insensitivity
        found_lower = parsed_project.get_tag(sample_tag.name.lower(), sample_tag.scope.lower())
        assert found_lower == sample_tag
        
    if parsed_project.udts:
        sample_udt = parsed_project.udts[0]
        found = parsed_project.get_udt(sample_udt.name)
        assert found == sample_udt
        
    if parsed_project.aois:
        sample_aoi = parsed_project.aois[0]
        found = parsed_project.get_aoi(sample_aoi.name)
        assert found == sample_aoi

def test_project_model_computed_properties(parsed_project: ParsedProject):
    """Test computed properties for tags and coverage."""
    # Coverage
    assert 0.0 <= parsed_project.documentation_coverage <= 100.0
    
    # Undocumented tags
    undocumented = parsed_project.undocumented_tags
    assert len(undocumented) <= len(parsed_project.tags)
    for tag in undocumented:
        assert not tag.description.strip()
        
    # Xref properties (if xref is built)
    if parsed_project.cross_reference:
        unused = parsed_project.unused_tags
        assert len(unused) <= len(parsed_project.tags)
        
        read_only = parsed_project.read_only_tags
        for tag in read_only:
             assert parsed_project.cross_reference[tag.name].is_read_only

def test_project_summary(parsed_project: ParsedProject):
    """Test the summary() method returns a non-empty string with key info."""
    summ = parsed_project.summary()
    assert isinstance(summ, str)
    assert parsed_project.metadata.controller_name in summ
    assert f"Tags:            {len(parsed_project.tags)}" in summ
