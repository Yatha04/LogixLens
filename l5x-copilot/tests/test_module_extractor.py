"""
test_module_extractor.py

Tests for src/parser/module_extractor.py

Integration tests use a real L5X file via the `l5x_project` fixture.
All assertions are structural – they do not hard-code counts or names
that depend on a specific project file.

Run with a real file:
    python -m pytest tests/test_module_extractor.py --l5x-file path/to/program.L5X
"""
import pytest
from src.parser.module_extractor import extract_modules, L5XModule, L5XPort


# ===========================================================================
# Integration tests – require a real L5X file
# ===========================================================================

class TestModuleExtractorIntegration:
    @pytest.fixture(autouse=True)
    def _load(self, l5x_project):
        """Extract modules once for all tests in this class."""
        self.modules = extract_modules(l5x_project)

    # --- Return type ---

    def test_returns_list(self):
        """extract_modules returns a list."""
        assert isinstance(self.modules, list)

    def test_modules_are_l5xmodule_instances(self):
        """Every item in the list is an L5XModule."""
        for mod in self.modules:
            assert isinstance(mod, L5XModule), (
                f"Expected L5XModule, got {type(mod).__name__}: {mod}"
            )

    # --- At least one module (all real controllers have at least the backplane) ---

    def test_at_least_one_module(self):
        """A real PLC project always has at least one module (the local backplane)."""
        assert len(self.modules) > 0, (
            "Expected at least one module in a real L5X project"
        )

    # --- Structural correctness of each module ---

    def test_all_modules_have_non_empty_name(self):
        """Every module has a non-empty name string."""
        for mod in self.modules:
            assert isinstance(mod.name, str) and mod.name.strip(), (
                f"Module with empty name found: {mod!r}"
            )

    def test_all_modules_have_non_empty_catalog_number(self):
        """Every module has a catalog number string (may be empty for virtual/internal,
        but the field itself must be a string)."""
        for mod in self.modules:
            assert isinstance(mod.catalog_number, str), (
                f"catalog_number should be str, got {type(mod.catalog_number)} for {mod.name!r}"
            )

    def test_all_modules_vendor_is_integer(self):
        """vendor field is always an integer."""
        for mod in self.modules:
            assert isinstance(mod.vendor, int), (
                f"vendor should be int for module {mod.name!r}, got {type(mod.vendor)}"
            )

    def test_all_modules_major_minor_are_non_negative(self):
        """Major and minor firmware versions are non-negative integers."""
        for mod in self.modules:
            assert isinstance(mod.major, int) and mod.major >= 0, (
                f"Invalid major={mod.major!r} for module {mod.name!r}"
            )
            assert isinstance(mod.minor, int) and mod.minor >= 0, (
                f"Invalid minor={mod.minor!r} for module {mod.name!r}"
            )

    def test_ports_are_l5xport_instances(self):
        """Every port on every module is an L5XPort instance."""
        for mod in self.modules:
            for port in mod.ports:
                assert isinstance(port, L5XPort), (
                    f"Expected L5XPort, got {type(port).__name__} in module {mod.name!r}"
                )

    def test_port_ids_are_positive_integers(self):
        """Port IDs are positive integers."""
        for mod in self.modules:
            for port in mod.ports:
                assert isinstance(port.id, int) and port.id > 0, (
                    f"Port id={port.id!r} is not a positive int in module {mod.name!r}"
                )

    def test_port_type_is_string(self):
        """Port type is always a string."""
        for mod in self.modules:
            for port in mod.ports:
                assert isinstance(port.type, str), (
                    f"Port type is not a string in module {mod.name!r}"
                )

    def test_port_upstream_is_bool(self):
        """Port upstream flag is always a boolean."""
        for mod in self.modules:
            for port in mod.ports:
                assert isinstance(port.upstream, bool), (
                    f"Port upstream={port.upstream!r} is not bool in module {mod.name!r}"
                )

    # --- Relationship checks ---

    def test_local_module_present(self):
        """There should be a module named 'Local' (the controller's own backplane)."""
        names = {m.name for m in self.modules}
        assert "Local" in names, (
            f"Expected a 'Local' module in the project. Found: {sorted(names)}"
        )

    def test_module_names_are_unique(self):
        """Module names must be unique within a project."""
        names = [m.name for m in self.modules]
        assert len(names) == len(set(names)), (
            f"Duplicate module names found: "
            f"{[n for n in names if names.count(n) > 1]}"
        )

    def test_at_least_one_module_has_ports(self):
        """At least one module (the local backplane) should have at least one port."""
        modules_with_ports = [m for m in self.modules if m.ports]
        assert modules_with_ports, "No module had any ports in a real project."
