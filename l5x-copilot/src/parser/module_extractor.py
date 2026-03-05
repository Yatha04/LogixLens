from dataclasses import dataclass, field
from typing import List, Optional
from lxml import etree

from .l5x_loader import L5XProject


@dataclass
class L5XPort:
    """Represents a connection port on a hardware module."""
    id: int
    type: str  # e.g., "Ethernet", "ICP", etc.
    address: str
    upstream: bool


@dataclass
class L5XModule:
    """Represents a hardware module in an L5X project."""
    name: str
    catalog_number: str
    vendor: int
    product_type: int
    product_code: int
    major: int
    minor: int
    parent_module: str
    parent_mod_port_id: int
    ports: List[L5XPort] = field(default_factory=list)


def extract_modules(project: L5XProject) -> List[L5XModule]:
    """Extract all hardware modules from the L5X project.

    Args:
        project: A loaded L5XProject.

    Returns:
        A list of L5XModule objects representing all discovered modules.
    """
    modules = []

    modules_node = project.controller.find("Modules")
    if modules_node is None:
        return modules

    for mod_node in modules_node.xpath("./Module"):
        # Basic attributes
        name = mod_node.get("Name", "")
        catalog_number = mod_node.get("CatalogNumber", "")
        
        # Numeric attributes (default to 0 if missing)
        try:
            vendor = int(mod_node.get("Vendor", "0"))
        except ValueError:
            vendor = 0
            
        try:
            product_type = int(mod_node.get("ProductType", "0"))
        except ValueError:
            product_type = 0
            
        try:
            product_code = int(mod_node.get("ProductCode", "0"))
        except ValueError:
            product_code = 0
            
        try:
            major = int(mod_node.get("Major", "0"))
        except ValueError:
            major = 0
            
        try:
            minor = int(mod_node.get("Minor", "0"))
        except ValueError:
            minor = 0

        parent_module = mod_node.get("ParentModule", "")
        
        try:
            parent_mod_port_id = int(mod_node.get("ParentModPortId", "0"))
        except ValueError:
            parent_mod_port_id = 0

        # Ports
        ports = []
        ports_node = mod_node.find("Ports")
        if ports_node is not None:
            for port_node in ports_node.xpath("./Port"):
                try:
                    port_id = int(port_node.get("Id", "0"))
                except ValueError:
                    port_id = 0
                    
                port_type = port_node.get("Type", "")
                address = port_node.get("Address", "")
                
                upstream_str = port_node.get("Upstream", "false").lower()
                upstream = (upstream_str == "true")
                
                ports.append(L5XPort(
                    id=port_id,
                    type=port_type,
                    address=address,
                    upstream=upstream
                ))

        modules.append(L5XModule(
            name=name,
            catalog_number=catalog_number,
            vendor=vendor,
            product_type=product_type,
            product_code=product_code,
            major=major,
            minor=minor,
            parent_module=parent_module,
            parent_mod_port_id=parent_mod_port_id,
            ports=ports
        ))

    return modules
