from dataclasses import dataclass
from typing import List, Optional
from lxml import etree

from .l5x_loader import L5XProject


@dataclass
class L5XTag:
    """Represents a tag (variable) in an L5X project."""
    name: str
    data_type: str
    tag_type: str  # e.g., "Base", "Alias"
    description: str
    scope: str  # "Controller" or the name of the program
    dimensions: str  # e.g., "10 5" for arrays, or "0" / "" for scalar
    alias_for: str  # The physical address or tag it aliases to, if any
    constant: bool
    external_access: str  # e.g., "Read/Write", "None", "Read Only"


def extract_tags(project: L5XProject) -> List[L5XTag]:
    """Extract all controller-scoped and program-scoped tags from the L5X project.

    Args:
        project: A loaded L5XProject.

    Returns:
        A list of L5XTag objects representing all discovered tags.
    """
    tags = []

    # Helper function to extract tags from a <Tags> parent node
    def _parse_tags(tags_node: etree._Element, scope_name: str):
        for tag_node in tags_node.xpath("./Tag"):
            name = tag_node.get("Name", "")
            data_type = tag_node.get("DataType", "")
            tag_type = tag_node.get("TagType", "Base")
            dimensions = tag_node.get("Dimensions", "0")
            alias_for = tag_node.get("AliasFor", "")
            
            # Constant is usually "true" or "false"
            constant_str = tag_node.get("Constant", "false").lower()
            constant = (constant_str == "true")
            
            external_access = tag_node.get("ExternalAccess", "Read/Write")

            # Extract Description
            description = ""
            desc_elem = tag_node.find("Description")
            if desc_elem is not None and desc_elem.text:
                # Remove surrounding CDATA artifacts if any (lxml usually strips CDATA wrapper, but just in case)
                description = desc_elem.text.strip()

            tags.append(L5XTag(
                name=name,
                data_type=data_type,
                tag_type=tag_type,
                description=description,
                scope=scope_name,
                dimensions=dimensions,
                alias_for=alias_for,
                constant=constant,
                external_access=external_access
            ))

    # 1. Controller-scoped tags
    # XPath from Controller -> Tags
    controller_tags_node = project.controller.find("Tags")
    if controller_tags_node is not None:
         _parse_tags(controller_tags_node, "Controller")

    # 2. Program-scoped tags
    # XPath from Controller -> Programs -> Program -> Tags
    programs_node = project.controller.find("Programs")
    if programs_node is not None:
        for prog_node in programs_node.xpath("./Program"):
            prog_name = prog_node.get("Name", "UnknownProgram")
            prog_tags_node = prog_node.find("Tags")
            if prog_tags_node is not None:
                _parse_tags(prog_tags_node, prog_name)

    return tags
