"""
project_model.py – Unified project model and orchestration.

Orchestrates all parser components to provide a single entry point
for L5X analysis.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set

from .l5x_loader import load_l5x, L5XMetadata, L5XProject
from .tag_extractor import extract_tags, L5XTag
from .module_extractor import extract_modules, L5XModule
from .routine_extractor import extract_programs, Program
from .udt_extractor import extract_udts, UserDefinedType
from .aoi_extractor import extract_aois, AddOnInstruction
from .rung_parser import parse_all_rungs, ParsedRung
from .cross_reference import build_cross_reference, TagUsage


@dataclass
class ParsedProject:
    """Unified project model containing all extracted and analyzed data."""
    metadata: L5XMetadata
    tags: List[L5XTag]
    modules: List[L5XModule]
    programs: List[Program]
    udts: List[UserDefinedType]
    aois: List[AddOnInstruction]
    parsed_rungs: Dict[Tuple[str, str, int], ParsedRung]
    cross_reference: Dict[str, TagUsage]

    # --- Convenience Lookups ---

    def get_tag(self, name: str, scope: str = "Controller") -> Optional[L5XTag]:
        """Look up a tag by name and scope."""
        for tag in self.tags:
            if tag.name.upper() == name.upper() and tag.scope.upper() == scope.upper():
                return tag
        return None

    def get_udt(self, name: str) -> Optional[UserDefinedType]:
        """Look up a UDT definition by name."""
        for udt in self.udts:
            if udt.name.upper() == name.upper():
                return udt
        return None

    def get_aoi(self, name: str) -> Optional[AddOnInstruction]:
        """Look up an AOI definition by name."""
        for aoi in self.aois:
            if aoi.name.upper() == name.upper():
                return aoi
        return None

    # --- Computed Properties ---

    @property
    def undocumented_tags(self) -> List[L5XTag]:
        """Tags that have no description."""
        return [tag for tag in self.tags if not tag.description.strip()]

    @property
    def unused_tags(self) -> List[L5XTag]:
        """Tags that are not referenced in any parsed ladder logic."""
        return [tag for tag in self.tags if tag.name not in self.cross_reference]

    @property
    def read_only_tags(self) -> List[L5XTag]:
        """Tags that are only ever read (never written to)."""
        return [
            tag for tag in self.tags 
            if tag.name in self.cross_reference and self.cross_reference[tag.name].is_read_only
        ]

    @property
    def write_only_tags(self) -> List[L5XTag]:
        """Tags that are only ever written to (never read)."""
        return [
            tag for tag in self.tags 
            if tag.name in self.cross_reference and self.cross_reference[tag.name].is_write_only
        ]

    @property
    def documentation_coverage(self) -> float:
        """Percentage of tags that have descriptions."""
        if not self.tags:
            return 0.0
        documented_count = len(self.tags) - len(self.undocumented_tags)
        return (documented_count / len(self.tags)) * 100.0

    # --- Summary ---

    def summary(self) -> str:
        """Return a human-readable overview of the project."""
        lines = [
            f"Project Summary: {self.metadata.controller_name}",
            f"Processor:       {self.metadata.processor_type} (Rev {self.metadata.major_revision}.{self.metadata.minor_revision})",
            f"L5X File:        {self.metadata.filepath}",
            "-" * 40,
            f"Tags:            {len(self.tags)}",
            f"  Undocumented:  {len(self.undocumented_tags)} ({self.documentation_coverage:.1f}% coverage)",
            f"  Unused:        {len(self.unused_tags)}",
            f"  Read-Only:     {len(self.read_only_tags)}",
            f"  Write-Only:    {len(self.write_only_tags)}",
            f"Programs:        {len(self.programs)}",
            f"Modules:         {len(self.modules)}",
            f"UDTs:            {len(self.udts)}",
            f"AOIs:            {len(self.aois)}",
            f"Parsed Rungs:    {len(self.parsed_rungs)}",
            "-" * 40,
        ]
        return "\n".join(lines)


def parse_project(filepath: str) -> ParsedProject:
    """Orchestrate the parsing of an L5X project file.
    
    Args:
        filepath: Path to the .L5X file.
        
    Returns:
        A ParsedProject object containing all extracted and analyzed data.
    """
    # 1. Load project
    project = load_l5x(filepath)
    
    # 2. Extract structural data
    tags = extract_tags(project)
    modules = extract_modules(project)
    programs = extract_programs(project)
    udts = extract_udts(project)
    aois = extract_aois(project)
    
    # 3. Parse ladder logic rungs
    parsed_rungs = parse_all_rungs(programs)
    
    # 4. Build cross-reference index
    cross_reference = build_cross_reference(parsed_rungs)
    
    return ParsedProject(
        metadata=project.metadata,
        tags=tags,
        modules=modules,
        programs=programs,
        udts=udts,
        aois=aois,
        parsed_rungs=parsed_rungs,
        cross_reference=cross_reference
    )