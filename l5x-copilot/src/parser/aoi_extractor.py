from dataclasses import dataclass, field
from typing import List, Optional
from lxml import etree

from .l5x_loader import L5XProject
from .routine_extractor import Routine, _extract_routines


@dataclass
class AOIParameter:
    """Represents a parameter for an Add-On Instruction."""
    name: str
    data_type: str
    usage: str  # Input, Output, InOut
    required: bool
    visible: bool
    default_data: Optional[str] = None
    description: str = ""


@dataclass
class AOILocalTag:
    """Represents an internal local tag for an Add-On Instruction."""
    name: str
    data_type: str
    description: str = ""
    dimensions: str = "0"


@dataclass
class AddOnInstruction:
    """Represents an Add-On Instruction definition."""
    name: str
    description: str
    revision: str
    parameters: List[AOIParameter] = field(default_factory=list)
    local_tags: List[AOILocalTag] = field(default_factory=list)
    routines: List[Routine] = field(default_factory=list)


def extract_aois(project: L5XProject) -> List[AddOnInstruction]:
    """Extract all Add-On Instructions from the L5X project."""
    aois: List[AddOnInstruction] = []

    aoi_defs_node = project.controller.find("AddOnInstructionDefinitions")
    if aoi_defs_node is None:
        return aois

    for aoi_node in aoi_defs_node.xpath("./AddOnInstructionDefinition"):
        name = aoi_node.get("Name", "")
        revision = aoi_node.get("Revision", "1.0")

        description = ""
        desc_node = aoi_node.find("Description")
        if desc_node is not None and desc_node.text:
            description = desc_node.text.strip()

        parameters = _extract_aoi_parameters(aoi_node)
        local_tags = _extract_aoi_local_tags(aoi_node)
        routines = _extract_routines(aoi_node)

        aois.append(AddOnInstruction(
            name=name,
            description=description,
            revision=revision,
            parameters=parameters,
            local_tags=local_tags,
            routines=routines,
        ))

    return aois


def _extract_aoi_parameters(aoi_node: etree._Element) -> List[AOIParameter]:
    """Extract parameters from an AddOnInstructionDefinition node."""
    parameters: List[AOIParameter] = []
    params_node = aoi_node.find("Parameters")
    if params_node is None:
        return parameters

    for param_node in params_node.xpath("./Parameter"):
        name = param_node.get("Name", "")
        data_type = param_node.get("DataType", "")
        usage = param_node.get("Usage", "Input")

        req_str = param_node.get("Required", "false").lower()
        required = (req_str == "true")

        vis_str = param_node.get("Visible", "false").lower()
        visible = (vis_str == "true")

        default_data = param_node.get("DefaultData")

        description = ""
        desc_node = param_node.find("Description")
        if desc_node is not None and desc_node.text:
            description = desc_node.text.strip()

        parameters.append(AOIParameter(
            name=name,
            data_type=data_type,
            usage=usage,
            required=required,
            visible=visible,
            default_data=default_data,
            description=description,
        ))

    return parameters


def _extract_aoi_local_tags(aoi_node: etree._Element) -> List[AOILocalTag]:
    """Extract local tags from an AddOnInstructionDefinition node."""
    local_tags: List[AOILocalTag] = []
    tags_node = aoi_node.find("LocalTags")
    if tags_node is None:
        return local_tags

    for tag_node in tags_node.xpath("./LocalTag"):
        name = tag_node.get("Name", "")
        data_type = tag_node.get("DataType", "")
        dimensions = tag_node.get("Dimensions", "0")

        description = ""
        desc_node = tag_node.find("Description")
        if desc_node is not None and desc_node.text:
            description = desc_node.text.strip()

        local_tags.append(AOILocalTag(
            name=name,
            data_type=data_type,
            description=description,
            dimensions=dimensions,
        ))

    return local_tags
