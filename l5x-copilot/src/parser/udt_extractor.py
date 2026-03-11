from dataclasses import dataclass, field
from typing import List
from lxml import etree

from .l5x_loader import L5XProject


@dataclass
class UDTMember:
    """Represents a member field within a User-Defined Type."""
    name: str
    data_type: str
    dimension: str
    radix: str
    hidden: bool
    external_access: str
    description: str = ""


@dataclass
class UserDefinedType:
    """Represents a User-Defined Type (UDT) definition."""
    name: str
    description: str
    family: str
    class_type: str
    members: List[UDTMember] = field(default_factory=list)


def extract_udts(project: L5XProject) -> List[UserDefinedType]:
    """Extract all User-Defined Types (UDTs) from the L5X project.
    
    Skips built-in atomics and filters out hidden padding members.

    Args:
        project: A loaded L5XProject.

    Returns:
        A list of UserDefinedType objects representing all discovered UDTs.
    """
    udts: List[UserDefinedType] = []

    datatypes_node = project.controller.find("DataTypes")
    if datatypes_node is None:
        return udts

    # Extract only Class="User" DataTypes
    for dt_node in datatypes_node.xpath("./DataType[@Class='User']"):
        name = dt_node.get("Name", "")
        family = dt_node.get("Family", "NoFamily")
        class_type = dt_node.get("Class", "User")
        
        description = ""
        desc_node = dt_node.find("Description")
        if desc_node is not None and desc_node.text:
            description = desc_node.text.strip()

        members = _extract_udt_members(dt_node)
        
        udts.append(UserDefinedType(
            name=name,
            description=description,
            family=family,
            class_type=class_type,
            members=members
        ))

    return udts


def _extract_udt_members(dt_node: etree._Element) -> List[UDTMember]:
    """Extract members from a DataType node, skipping padding."""
    members: List[UDTMember] = []
    
    members_node = dt_node.find("Members")
    if members_node is None:
        return members
        
    for mem_node in members_node.xpath("./Member"):
        name = mem_node.get("Name", "")
        
        # Filter out hidden padding members (Names starting with ZZZZZZZZZZ)
        if name.startswith("ZZZZZZZZZZ"):
            continue
            
        data_type = mem_node.get("DataType", "")
        dimension = mem_node.get("Dimension", "0")
        radix = mem_node.get("Radix", "Decimal")
        
        hidden_str = mem_node.get("Hidden", "false").lower()
        hidden = (hidden_str == "true")
        
        external_access = mem_node.get("ExternalAccess", "Read/Write")
        
        description = ""
        desc_node = mem_node.find("Description")
        if desc_node is not None and desc_node.text:
            description = desc_node.text.strip()
            
        members.append(UDTMember(
            name=name,
            data_type=data_type,
            dimension=dimension,
            radix=radix,
            hidden=hidden,
            external_access=external_access,
            description=description
        ))
        
    return members
