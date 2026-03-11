"""
test_routine_extractor.py

Tests for src/parser/routine_extractor.py

Integration tests use a real L5X file via the `l5x_project` fixture.
Tests are split by concern:
  - Programs
  - Routines (across all types: RLL, ST, SFC)
  - Rungs (for RLL routines)
  - ST Lines
  - SFC content (if the project contains SFC routines)

Assertions are structural – they hold for any valid real Logix project.

Run with a real file:
    python -m pytest tests/test_routine_extractor.py --l5x-file path/to/program.L5X
"""
import pytest
from src.parser.routine_extractor import (
    extract_programs,
    Program, Routine, Rung, Line,
    SFCContent, SFCStep, SFCTransition, SFCBranch, SFCDirectedLink, SFCAction,
)

KNOWN_ROUTINE_TYPES = {"RLL", "ST", "SFC", "FBD"}


# ===========================================================================
# Session-level extraction – done once so all test classes share the data
# ===========================================================================

@pytest.fixture(scope="session")
def programs(l5x_project):
    """Extract programs once for the entire session."""
    return extract_programs(l5x_project)


@pytest.fixture(scope="session")
def all_routines(programs):
    """Flatten all routines across all programs."""
    return [r for p in programs for r in p.routines]


@pytest.fixture(scope="session")
def rll_routines(all_routines):
    return [r for r in all_routines if r.routine_type == "RLL"]


@pytest.fixture(scope="session")
def st_routines(all_routines):
    return [r for r in all_routines if r.routine_type == "ST"]


@pytest.fixture(scope="session")
def sfc_routines(all_routines):
    return [r for r in all_routines if r.routine_type == "SFC"]


# ===========================================================================
# Tests: Program-level
# ===========================================================================

class TestPrograms:
    def test_returns_list(self, programs):
        assert isinstance(programs, list)

    def test_at_least_one_program(self, programs):
        """Any real PLC project has at least one program."""
        assert len(programs) > 0, "No programs found in the real L5X file."

    def test_programs_are_program_instances(self, programs):
        for p in programs:
            assert isinstance(p, Program), f"Expected Program, got {type(p).__name__}"

    def test_all_programs_have_non_empty_name(self, programs):
        for p in programs:
            assert isinstance(p.name, str) and p.name.strip(), (
                f"Program with empty name: {p!r}"
            )

    def test_program_disabled_is_bool(self, programs):
        for p in programs:
            assert isinstance(p.disabled, bool), (
                f"Program {p.name!r}: disabled should be bool, got {type(p.disabled)}"
            )

    def test_program_names_are_unique(self, programs):
        names = [p.name for p in programs]
        assert len(names) == len(set(names)), (
            f"Duplicate program names: {[n for n in names if names.count(n) > 1]}"
        )

    def test_program_routines_is_list(self, programs):
        for p in programs:
            assert isinstance(p.routines, list), (
                f"Program {p.name!r}: routines should be a list"
            )

    def test_main_routine_exists_in_program(self, programs):
        """If a program declares a MainRoutineName, that routine should be present."""
        for p in programs:
            if p.main_routine_name:
                routine_names = {r.name for r in p.routines}
                assert p.main_routine_name in routine_names, (
                    f"Program {p.name!r} declares MainRoutineName={p.main_routine_name!r} "
                    f"but that routine was not found. Found: {sorted(routine_names)}"
                )


# ===========================================================================
# Tests: Routine-level
# ===========================================================================

class TestRoutines:
    def test_at_least_one_routine_across_project(self, all_routines):
        """Any real project has at least one routine."""
        assert len(all_routines) > 0, "No routines found in the real L5X file."

    def test_routines_are_routine_instances(self, all_routines):
        for r in all_routines:
            assert isinstance(r, Routine), f"Expected Routine, got {type(r).__name__}"

    def test_all_routines_have_non_empty_name(self, all_routines):
        for r in all_routines:
            assert isinstance(r.name, str) and r.name.strip(), (
                f"Routine with empty name: {r!r}"
            )

    def test_all_routines_have_known_type(self, all_routines):
        for r in all_routines:
            assert r.routine_type in KNOWN_ROUTINE_TYPES, (
                f"Routine {r.name!r} has unexpected type={r.routine_type!r}. "
                f"Expected one of {KNOWN_ROUTINE_TYPES}"
            )

    def test_description_is_string(self, all_routines):
        for r in all_routines:
            assert isinstance(r.description, str), (
                f"Routine {r.name!r}: description should be str, got {type(r.description)}"
            )

    def test_rll_routines_have_no_st_lines(self, rll_routines):
        """RLL routines must not have ST lines."""
        for r in rll_routines:
            assert r.lines == [], (
                f"RLL routine {r.name!r} should have no ST lines, got {r.lines!r}"
            )

    def test_rll_routines_have_no_sfc_content(self, rll_routines):
        for r in rll_routines:
            assert r.sfc_content is None, (
                f"RLL routine {r.name!r} should have sfc_content=None"
            )

    def test_st_routines_have_no_rungs(self, st_routines):
        """ST routines must not have rungs."""
        for r in st_routines:
            assert r.rungs == [], (
                f"ST routine {r.name!r} should have no rungs, got {r.rungs!r}"
            )

    def test_st_routines_have_no_sfc_content(self, st_routines):
        for r in st_routines:
            assert r.sfc_content is None, (
                f"ST routine {r.name!r} should have sfc_content=None"
            )

    def test_sfc_routines_have_no_rungs_or_lines(self, sfc_routines):
        """SFC routines must not have rungs or ST lines."""
        for r in sfc_routines:
            assert r.rungs == [], f"SFC routine {r.name!r} should have no rungs"
            assert r.lines == [], f"SFC routine {r.name!r} should have no lines"

    def test_project_has_rll_routines(self, rll_routines):
        """Any real Logix project should have at least one RLL routine."""
        assert len(rll_routines) > 0, (
            "Expected at least one RLL routine in the real project."
        )


# ===========================================================================
# Tests: Rung-level (RLL)
# ===========================================================================

class TestRungs:
    @pytest.fixture(autouse=True)
    def _collect_rungs(self, rll_routines):
        self.all_rungs = [rung for r in rll_routines for rung in r.rungs]

    def test_rungs_are_rung_instances(self):
        for rung in self.all_rungs:
            assert isinstance(rung, Rung), f"Expected Rung, got {type(rung).__name__}"

    def test_rung_number_is_non_negative_integer(self):
        for rung in self.all_rungs:
            assert isinstance(rung.number, int) and rung.number >= 0, (
                f"Rung number {rung.number!r} is not a non-negative int"
            )

    def test_rung_text_is_string(self):
        for rung in self.all_rungs:
            assert isinstance(rung.text, str), (
                f"Rung {rung.number}: text should be str, got {type(rung.text)}"
            )

    def test_rung_comment_is_string(self):
        for rung in self.all_rungs:
            assert isinstance(rung.comment, str), (
                f"Rung {rung.number}: comment should be str, got {type(rung.comment)}"
            )

    def test_no_deleted_rungs(self):
        """Deleted rungs (Type='D') should have been filtered out by the extractor."""
        # The extractor skips deleted rungs; the (N) suffix in text is normalized to N
        for rung in self.all_rungs:
            assert not rung.text.endswith("(N)"), (
                f"Rung {rung.number} still has un-normalized '(N)' suffix: {rung.text!r}"
            )

    def test_non_empty_rungs_have_text(self):
        """Rungs with actual logic should have non-empty text ending in ';'."""
        non_empty = [r for r in self.all_rungs if r.text.strip()]
        for rung in non_empty:
            assert rung.text.endswith(";") or rung.text.endswith("N"), (
                f"Rung {rung.number} text doesn't end with ';' or 'N': {rung.text!r}"
            )

    def test_rung_numbers_are_sequential_within_routine(self, rll_routines):
        """Within each routine rung numbers should be in ascending order."""
        for r in rll_routines:
            nums = [rung.number for rung in r.rungs]
            assert nums == sorted(nums), (
                f"Routine {r.name!r}: rungs are not in ascending order: {nums}"
            )


# ===========================================================================
# Tests: ST Lines
# ===========================================================================

class TestSTLines:
    @pytest.fixture(autouse=True)
    def _collect_lines(self, st_routines):
        self.all_lines = [line for r in st_routines for line in r.lines]
        self.st_routines = st_routines

    def test_lines_are_line_instances(self):
        for line in self.all_lines:
            assert isinstance(line, Line), f"Expected Line, got {type(line).__name__}"

    def test_line_number_is_non_negative_int(self):
        for line in self.all_lines:
            assert isinstance(line.number, int) and line.number >= 0, (
                f"Line number {line.number!r} is not a non-negative int"
            )

    def test_line_text_is_string(self):
        for line in self.all_lines:
            assert isinstance(line.text, str), (
                f"Line {line.number}: text should be str, got {type(line.text)}"
            )

    def test_line_numbers_are_sequential_within_routine(self):
        for r in self.st_routines:
            nums = [l.number for l in r.lines]
            assert nums == sorted(nums), (
                f"ST Routine {r.name!r}: lines not in ascending order: {nums}"
            )


# ===========================================================================
# Tests: SFC Content
# ===========================================================================

class TestSFCContent:
    @pytest.fixture(autouse=True)
    def _collect_sfc(self, sfc_routines):
        self.sfc_routines = sfc_routines
        self.skip_if_none = len(sfc_routines) == 0

    def test_sfc_routines_have_sfc_content(self):
        """Every SFC routine must have a non-None sfc_content object."""
        if self.skip_if_none:
            pytest.skip("No SFC routines in this project – skipping SFC tests")
        for r in self.sfc_routines:
            assert r.sfc_content is not None, (
                f"SFC routine {r.name!r} has sfc_content=None"
            )
            assert isinstance(r.sfc_content, SFCContent), (
                f"sfc_content should be SFCContent, got {type(r.sfc_content)}"
            )

    def test_each_sfc_has_at_least_one_step(self):
        """A valid SFC must have at least one step."""
        if self.skip_if_none:
            pytest.skip("No SFC routines in this project")
        for r in self.sfc_routines:
            assert len(r.sfc_content.steps) > 0, (
                f"SFC routine {r.name!r} has zero steps"
            )

    def test_sfc_steps_are_sfcstep_instances(self):
        if self.skip_if_none:
            pytest.skip("No SFC routines in this project")
        for r in self.sfc_routines:
            for step in r.sfc_content.steps:
                assert isinstance(step, SFCStep), (
                    f"Expected SFCStep, got {type(step).__name__}"
                )

    def test_sfc_step_operand_is_string(self):
        if self.skip_if_none:
            pytest.skip("No SFC routines in this project")
        for r in self.sfc_routines:
            for step in r.sfc_content.steps:
                assert isinstance(step.operand, str), (
                    f"Step {step.id}: operand should be str"
                )

    def test_sfc_step_initial_step_is_bool(self):
        if self.skip_if_none:
            pytest.skip("No SFC routines in this project")
        for r in self.sfc_routines:
            for step in r.sfc_content.steps:
                assert isinstance(step.initial_step, bool), (
                    f"Step {step.id}: initial_step should be bool"
                )

    def test_exactly_one_initial_step_per_sfc(self):
        """Every SFC routine must have exactly one initial step."""
        if self.skip_if_none:
            pytest.skip("No SFC routines in this project")
        for r in self.sfc_routines:
            initial_steps = [s for s in r.sfc_content.steps if s.initial_step]
            assert len(initial_steps) == 1, (
                f"SFC routine {r.name!r} has {len(initial_steps)} initial steps "
                f"(expected exactly 1)"
            )

    def test_sfc_transitions_are_sfctransition_instances(self):
        if self.skip_if_none:
            pytest.skip("No SFC routines in this project")
        for r in self.sfc_routines:
            for t in r.sfc_content.transitions:
                assert isinstance(t, SFCTransition), (
                    f"Expected SFCTransition, got {type(t).__name__}"
                )

    def test_sfc_transition_condition_lines_are_lines(self):
        if self.skip_if_none:
            pytest.skip("No SFC routines in this project")
        for r in self.sfc_routines:
            for t in r.sfc_content.transitions:
                for line in t.condition_lines:
                    assert isinstance(line, Line), (
                        f"Transition {t.id}: condition_line should be Line"
                    )

    def test_sfc_directed_links_are_sfcdirectedlink_instances(self):
        if self.skip_if_none:
            pytest.skip("No SFC routines in this project")
        for r in self.sfc_routines:
            for link in r.sfc_content.directed_links:
                assert isinstance(link, SFCDirectedLink), (
                    f"Expected SFCDirectedLink, got {type(link).__name__}"
                )

    def test_sfc_branches_are_sfcbranch_instances(self):
        if self.skip_if_none:
            pytest.skip("No SFC routines in this project")
        for r in self.sfc_routines:
            for branch in r.sfc_content.branches:
                assert isinstance(branch, SFCBranch), (
                    f"Expected SFCBranch, got {type(branch).__name__}"
                )

    def test_sfc_action_is_boolean_is_bool(self):
        if self.skip_if_none:
            pytest.skip("No SFC routines in this project")
        for r in self.sfc_routines:
            for step in r.sfc_content.steps:
                for action in step.actions:
                    assert isinstance(action.is_boolean, bool), (
                        f"Action {action.id}: is_boolean should be bool"
                    )
