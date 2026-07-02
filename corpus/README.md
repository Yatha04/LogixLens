# Real-World L5X Corpus

A corpus of real Rockwell L5X files fetched from public GitHub repositories,
used to validate and harden the LogixLens parser against programs we didn't
write. This is the difference between "works on our demo file" and "works on
yours."

## Contents

- `fetch_corpus.py` — reproducible fetch via GitHub code search (`gh` CLI,
  authenticated). Incremental and crash-safe; re-running only adds new files.
- `expand_repos.py` — sibling expansion: lists the full git tree of every
  repo already in the manifest and downloads L5X files code search missed
  (full projects usually sit next to the searchable component exports).
- `harness.py` — the measuring stick. Runs the full pipeline per file
  (load → parse → per-rung coverage → diagnosis on written tags) and writes
  `report.json` + `REPORT.md` with a ranked hardening worklist.
- `manifest.json` — provenance for every file: repo, path, URL, size, SHA-256,
  classification, firmware revision, processor.
- `files/` — the L5X files themselves (**gitignored**, rebuild with the
  scripts above).

## Usage

```bash
# fetch / extend the corpus (needs gh auth)
../l5x-copilot/.venv/bin/python fetch_corpus.py
../l5x-copilot/.venv/bin/python expand_repos.py

# run the baseline harness
../l5x-copilot/.venv/bin/python harness.py            # full corpus
../l5x-copilot/.venv/bin/python harness.py --only <substr>
```

The corpus also gates the test suite: `l5x-copilot/tests/test_corpus.py`
parametrizes over every manifest entry and asserts the pipeline never raises
(skips wholesale when the corpus hasn't been fetched).

## Failure policy

- An **unhandled exception** anywhere in the pipeline is a failure.
- A **recorded degradation** (e.g. a genuinely malformed rung captured in
  `ParsedProject.rung_parse_errors`) is tolerated, reported, and tracked —
  some public files contain deliberately-invalid rung text.

## Provenance & licensing

All files were publicly posted on GitHub by their authors and are fetched
here solely for local compatibility testing of the parser. They are never
redistributed (the `files/` directory is gitignored) and never used for any
other purpose. `manifest.json` records the exact source of every file.
