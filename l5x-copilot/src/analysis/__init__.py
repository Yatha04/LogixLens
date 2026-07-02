"""
analysis – Static + live diagnosis engine for Ask-the-PLC.

The core public surface:

- :class:`ConditionNode`      – the backward-chained condition tree node model.
- :class:`DiagnosisContext`   – the queryable bundle the builder walks over.
- :func:`build_condition_tree` – "what would it take for <tag> to be true?".
- :func:`evaluate_tree`       – tri-state evaluation against live tag values.
- :func:`failing_paths`       – the minimal set of red leaves blocking a target.
"""

from .condition_tree import (
    ConditionNode,
    DiagnosisContext,
    build_condition_tree,
    evaluate_tree,
    failing_paths,
)

__all__ = [
    "ConditionNode",
    "DiagnosisContext",
    "build_condition_tree",
    "evaluate_tree",
    "failing_paths",
]
