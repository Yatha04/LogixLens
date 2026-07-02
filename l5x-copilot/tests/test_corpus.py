"""
test_corpus.py — Corpus regression gate.

Runs the full pipeline over every real-world L5X file in ../corpus/files/
(if the corpus has been fetched) and asserts ZERO hard failures:

  * every file loads (or is a recorded, catchable variant)
  * every file parse_project()s
  * every parseable RLL rung parses (malformed real-world rung text is
    allowed only via ParsedProject.rung_parse_errors — never an exception)
  * diagnosis runs clean on written tags of every controller-class file

Skips (whole module) when the corpus is absent, so CI without the corpus
still passes. Fetch with: cd corpus && python fetch_corpus.py
"""
import json
from pathlib import Path

import pytest

CORPUS = Path(__file__).resolve().parents[2] / "corpus"
MANIFEST = CORPUS / "manifest.json"

if not MANIFEST.exists():  # pragma: no cover
    pytest.skip("corpus not fetched", allow_module_level=True)

from src.analysis import build_condition_tree  # noqa: E402
from src.parser.project_model import parse_project  # noqa: E402

_entries = [
    e for e in json.loads(MANIFEST.read_text())
    if (CORPUS / "files" / e["filename"]).exists()
    and e.get("classification") != "invalid"
]


@pytest.mark.parametrize("entry", _entries, ids=lambda e: e["filename"][:40])
def test_corpus_file_full_pipeline(entry):
    path = CORPUS / "files" / entry["filename"]

    project = parse_project(str(path))  # must never raise on corpus files

    # Tolerated-but-recorded malformed rungs must be the only rung failures.
    for key, msg in project.rung_parse_errors.items():
        assert isinstance(msg, str) and msg, f"empty error for {key}"

    # Diagnosis must run clean on controller-class files.
    if entry.get("classification") == "controller":
        written = [
            name
            for name, usage in project.cross_reference.items()
            if any("write" in u.access for u in usage.usages)
        ][:10]
        for tag in written:
            tree = build_condition_tree(tag, project)
            json.dumps(tree.to_dict())
