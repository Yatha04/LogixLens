from dataclasses import dataclass
from pathlib import Path
from lxml import etree
from .exceptions import L5XParseError, L5XValidationError


@dataclass
class L5XMetadata:
    """Top-level metadata extracted from the L5X file."""
    filepath: str
    controller_name: str
    processor_type: str           # "1769-L33ER", "1756-L83E", etc.
    major_revision: int
    minor_revision: int
    software_revision: str        # Studio 5000 version used
    project_creation_date: str
    last_modified_date: str
    export_date: str
    target_type: str              # "Controller", "Program", "Routine", etc.
    schema_revision: str


@dataclass
class L5XProject:
    """Loaded and validated L5X project."""
    metadata: L5XMetadata
    tree: etree._ElementTree
    controller: etree._Element    # The <Controller> element — root for all queries

    def xpath(self, expression: str) -> list:
        """Run an XPath query against the Controller element.

        Namespace is already stripped, so use clean XPath like "Tags/Tag".
        """
        return self.controller.xpath(expression)


def load_l5x(filepath: str) -> L5XProject:
    """Load and validate an L5X file.

    Args:
        filepath: Path to the .L5X file

    Returns:
        L5XProject with parsed XML tree and metadata

    Raises:
        FileNotFoundError: If file doesn't exist
        L5XParseError: If file is not valid XML
        L5XValidationError: If XML is not a valid L5X file
    """
    path = Path(filepath)

    if not path.exists():
        raise FileNotFoundError(f"L5X file not found: {filepath}")
    if not path.is_file():
        raise L5XParseError(f"Path is not a file: {filepath}")

    # Parse XML
    try:
        parser = etree.XMLParser(recover=False, remove_comments=True)
        tree = etree.parse(str(path), parser)
    except etree.XMLSyntaxError as e:
        raise L5XParseError(f"Invalid XML in {filepath}: {e}")

    root = tree.getroot()

    # Strip namespace if present (L5X files are inconsistent about this)
    _strip_namespace(root)

    # Validate root element
    if root.tag != "RSLogix5000Content":
        raise L5XValidationError(
            f"Not an L5X file: root element is <{root.tag}>, "
            f"expected <RSLogix5000Content>"
        )

    # Find Controller element
    controller = root.find("Controller")
    if controller is None:
        raise L5XValidationError("No <Controller> element found in L5X file")

    # Extract metadata
    metadata = L5XMetadata(
        filepath=str(path.resolve()),
        controller_name=controller.get("Name", "Unknown"),
        processor_type=controller.get("ProcessorType", "Unknown"),
        major_revision=int(controller.get("MajorRev", "0")),
        minor_revision=int(controller.get("MinorRev", "0")),
        software_revision=root.get("SoftwareRevision", "Unknown"),
        project_creation_date=controller.get("ProjectCreationDate", ""),
        last_modified_date=controller.get("LastModifiedDate", ""),
        export_date=root.get("ExportDate", ""),
        target_type=root.get("TargetType", "Controller"),
        schema_revision=root.get("SchemaRevision", "1.0"),
    )

    return L5XProject(metadata=metadata, tree=tree, controller=controller)


def _strip_namespace(root: etree._Element) -> None:
    """Remove XML namespace from all elements in-place.

    L5X files sometimes have a namespace like:
      xmlns="http://www.rockwellautomation.com/FactoryTalkLogixDesigner"

    Stripping it lets us use clean XPath like "Tags/Tag" instead of
    "{http://...}Tags/{http://...}Tag".
    """
    for elem in root.iter():
        if isinstance(elem.tag, str) and "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
        # Also strip namespace from attributes
        attribs = dict(elem.attrib)
        for key in list(attribs.keys()):
            if "}" in key:
                new_key = key.split("}", 1)[1]
                elem.attrib[new_key] = elem.attrib.pop(key)
