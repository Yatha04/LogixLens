#!/usr/bin/env python3
"""
corpus/fetch_corpus.py — Reproducible fetch of real-world Rockwell L5X files
from public GitHub repos, for LogixLens parser hardening tests.

What it does
------------
1. Searches GitHub code search (`gh api search/code`) with several queries
   chosen for diversity: generic L5X signature, full-project TargetType,
   component TargetTypes (AOI/DataType/Routine), and catalog-number /
   keyword variants that tend to surface bigger projects.
2. For each hit, resolves the file via the GitHub Contents API (handles
   path-encoding correctly and gives us an exact byte size before download)
   and downloads the raw bytes from `download_url` (raw.githubusercontent.com,
   unauthenticated, default branch).
3. Skips files over 20MB.
4. Dedupes by SHA-256 of the downloaded bytes (works across queries/reruns).
5. Validates the file is well-formed XML with an <RSLogix5000Content> root;
   junk gets recorded with classification "invalid" but is KEPT on disk
   (failures are the point of this corpus).
6. Classifies by the root's TargetType attribute + a content sniff:
     controller  - full project: Controller + >=1 Program + >20 rungs total
     aoi         - AddOnInstructionDefinition export
     udt         - DataType export where the DataType's Class="User"
     datatype    - DataType export that is NOT Class="User" (predefined/other)
     routine     - single-Routine export
     rung        - single-Rung / rung-selection export
     other       - anything else structurally valid (thin/partial exports,
                   Controller exports that don't clear the rung threshold)
     invalid     - not well-formed XML, or root isn't RSLogix5000Content
7. Writes corpus/manifest.json (list of dicts, one per file) incrementally
   (crash-safe — every new file triggers a full manifest re-save).

Requires: `gh` CLI, authenticated (`gh auth status`). Uses lxml if available
(from l5x-copilot/.venv) but falls back to stdlib xml.etree if not — this
script is intentionally independent of l5x-copilot/src (corpus tooling must
not depend on, or modify, the code under test).

Usage
-----
    # from l5x-copilot's venv (has lxml) — recommended:
    ../l5x-copilot/.venv/bin/python fetch_corpus.py

    # or with system python3 (falls back to xml.etree):
    python3 fetch_corpus.py --max-total 80

Re-running is safe and incremental: existing files/manifest entries are kept,
new queries/pages only add files not already present (by repo+path and by
content hash).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

try:
    from lxml import etree as ET  # type: ignore
    _USING_LXML = True
except ImportError:  # pragma: no cover - fallback path
    import xml.etree.ElementTree as ET  # type: ignore
    _USING_LXML = False

CORPUS_DIR = Path(__file__).resolve().parent
FILES_DIR = CORPUS_DIR / "files"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
SEARCH_SLEEP = 2.5     # gh search/code: 30 req/min authenticated
CONTENTS_SLEEP = 0.4   # gh contents API: core limit, 5000/hr, be gentle anyway
DOWNLOAD_SLEEP = 0.15  # raw.githubusercontent.com, be a good citizen

# Diversity: broad signature + full-project targeting + component targeting +
# catalog-number / keyword variants that surface different repos.
QUERIES = [
    'RSLogix5000Content extension:l5x',
    '"TargetType=\\"Controller\\"" extension:l5x',
    '"TargetType=\\"AddOnInstructionDefinition\\"" extension:l5x',
    '"TargetType=\\"DataType\\"" extension:l5x',
    '"TargetType=\\"Routine\\"" extension:l5x',
    '"RLLContent" extension:l5x',
    '"5069-" extension:l5x',
    '"1756-" extension:l5x',
    '"1769-" extension:l5x',
    'Programs extension:l5x',
    '"SoftwareRevision=" extension:l5x',
    '"ProcessorType=" extension:l5x',
]

COMPONENT_CLASSES = {"aoi", "udt", "datatype", "routine", "rung"}


def log(msg: str) -> None:
    print(msg, flush=True)


def run_gh_json(cmd: list[str], max_attempts: int = 5) -> dict | None:
    """Run a `gh api ...` command, parse JSON stdout, retry on rate limits."""
    for attempt in range(1, max_attempts + 1):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                log(f"  [warn] non-JSON response for {cmd[:3]}...: {proc.stdout[:150]}")
                return None
        stderr = proc.stderr.lower()
        if "rate limit" in stderr or "secondary rate limit" in stderr or "403" in stderr:
            wait = 20 * attempt
            log(f"  [rate-limited] attempt {attempt}/{max_attempts}, sleeping {wait}s")
            time.sleep(wait)
            continue
        if "422" in stderr or "validation failed" in stderr:
            # e.g. "only the first 1000 search results are available"
            return None
        if "404" in stderr:
            return None
        log(f"  [error] {proc.stderr.strip()[:200]}")
        time.sleep(3)
    return None


def search_query(query: str, max_pages: int):
    """Yield search/code result items for a query, paging until exhausted."""
    for page in range(1, max_pages + 1):
        cmd = [
            "gh", "api", "-X", "GET", "search/code",
            "-f", f"q={query}",
            "-f", f"per_page=100",
            "-f", f"page={page}",
        ]
        data = run_gh_json(cmd)
        time.sleep(SEARCH_SLEEP)
        if data is None:
            break
        items = data.get("items", [])
        total_count = data.get("total_count", 0)
        if not items:
            break
        yield from items
        if page * 100 >= min(total_count, 1000):
            break


def gh_contents(owner: str, repo: str, path: str) -> dict | None:
    encoded = quote(path, safe="/")
    cmd = ["gh", "api", f"repos/{owner}/{repo}/contents/{encoded}"]
    data = run_gh_json(cmd)
    time.sleep(CONTENTS_SLEEP)
    return data


def download(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": "logixlens-corpus-fetch"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_FILE_SIZE:
                return None
            data = resp.read(MAX_FILE_SIZE + 1)
            if len(data) > MAX_FILE_SIZE:
                return None
            return data
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        log(f"  [download failed] {url}: {e}")
        return None
    finally:
        time.sleep(DOWNLOAD_SLEEP)


def _local_name(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _strip_ns_and_find_all(root):
    """Return root with tags stripped of namespace (mutates a copy's tags in place)."""
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = _local_name(el.tag)
    return root


def validate_and_classify(data: bytes) -> dict:
    """Best-effort structural validation + classification. Independent of l5x-copilot/src."""
    result = {
        "valid": False,
        "classification": "invalid",
        "target_type": None,
        "software_revision": None,
        "processor": None,
        "rung_count_approx": 0,
        "program_count_approx": 0,
        "error": None,
    }
    try:
        if _USING_LXML:
            parser = ET.XMLParser(recover=False)
            root = ET.fromstring(data, parser=parser)
        else:
            root = ET.fromstring(data)
    except Exception as e:  # noqa: BLE001 - want to catch every parser error type
        result["error"] = f"{type(e).__name__}: {e}"
        return result

    root = _strip_ns_and_find_all(root)
    if _local_name(root.tag) != "RSLogix5000Content":
        result["error"] = f"unexpected root tag: {_local_name(root.tag)}"
        return result

    result["valid"] = True
    tt = root.get("TargetType", "")
    result["target_type"] = tt or None
    result["software_revision"] = root.get("SoftwareRevision") or None

    controller_el = root.find("Controller")
    rung_count = len(root.findall(".//Rung"))
    program_els = root.findall(".//Programs/Program")
    result["rung_count_approx"] = rung_count
    result["program_count_approx"] = len(program_els)
    if controller_el is not None:
        result["processor"] = controller_el.get("ProcessorType") or None

    if tt == "Controller" and controller_el is not None:
        if len(program_els) >= 1 and rung_count > 20:
            result["classification"] = "controller"
        else:
            result["classification"] = "other"
    elif tt == "AddOnInstructionDefinition":
        result["classification"] = "aoi"
    elif tt == "DataType":
        dt_el = root.find(".//DataType")
        cls_attr = dt_el.get("Class") if dt_el is not None else None
        result["classification"] = "udt" if cls_attr == "User" else "datatype"
    elif tt == "Routine":
        result["classification"] = "routine"
    elif tt == "Rung":
        result["classification"] = "rung"
    else:
        # Content sniff fallback when TargetType is missing/unrecognized.
        if controller_el is not None and len(program_els) >= 1 and rung_count > 20:
            result["classification"] = "controller"
        elif root.find(".//AddOnInstructionDefinition") is not None:
            result["classification"] = "aoi"
        elif root.find(".//DataType") is not None:
            dt_el = root.find(".//DataType")
            result["classification"] = "udt" if dt_el.get("Class") == "User" else "datatype"
        elif root.find(".//Routine") is not None and controller_el is None:
            result["classification"] = "routine"
        else:
            result["classification"] = "other"

    return result


def load_manifest() -> list[dict]:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except json.JSONDecodeError:
            log("  [warn] manifest.json unreadable, starting fresh")
    return []


def save_manifest(entries: list[dict]) -> None:
    MANIFEST_PATH.write_text(json.dumps(entries, indent=2))


def component_total(stats: dict) -> int:
    return sum(stats.get(c, 0) for c in COMPONENT_CLASSES)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-total", type=int, default=80, help="stop once this many files are saved")
    ap.add_argument("--min-controller", type=int, default=12)
    ap.add_argument("--min-component", type=int, default=20)
    ap.add_argument("--max-pages-per-query", type=int, default=5, help="100 results/page, GH caps at 10 pages/1000 results")
    ap.add_argument("--queries", nargs="*", default=None, help="override the built-in query list")
    args = ap.parse_args()

    FILES_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    known_hashes = {e["sha256"] for e in manifest}
    known_paths = {(e["repo"], e["path"]) for e in manifest}
    stats: dict[str, int] = {}
    for e in manifest:
        stats[e["classification"]] = stats.get(e["classification"], 0) + 1

    total_saved = len(manifest)
    log(f"Starting with {total_saved} files already in manifest: {stats}")

    queries = args.queries if args.queries else QUERIES
    for query in queries:
        if (total_saved >= args.max_total
                and stats.get("controller", 0) >= args.min_controller
                and component_total(stats) >= args.min_component):
            log("Targets met, stopping early.")
            break
        log(f"=== query: {query} ===")
        try:
            for item in search_query(query, args.max_pages_per_query):
                if total_saved >= args.max_total:
                    break
                repo_full = item.get("repository", {}).get("full_name")
                path = item.get("path")
                if not repo_full or not path:
                    continue
                if not path.lower().endswith(".l5x"):
                    continue
                if (repo_full, path) in known_paths:
                    continue
                known_paths.add((repo_full, path))

                owner, repo = repo_full.split("/", 1)
                meta = gh_contents(owner, repo, path)
                if not meta or meta.get("type") != "file":
                    continue
                size = meta.get("size", 0)
                if size > MAX_FILE_SIZE:
                    log(f"  skip (too large, {size}b): {repo_full}/{path}")
                    continue
                download_url = meta.get("download_url")
                if not download_url:
                    continue

                data = download(download_url)
                if data is None:
                    continue
                h = hashlib.sha256(data).hexdigest()
                if h in known_hashes:
                    log(f"  dup (sha match): {repo_full}/{path}")
                    continue
                known_hashes.add(h)

                info = validate_and_classify(data)
                fname_orig = re.sub(r"[^A-Za-z0-9._-]", "_", Path(path).name)
                fname = f"{h[:16]}_{fname_orig}"
                (FILES_DIR / fname).write_bytes(data)

                entry = {
                    "filename": fname,
                    "repo": repo_full,
                    "path": path,
                    "html_url": item.get("html_url"),
                    "size": len(data),
                    "sha256": h,
                    "classification": info["classification"],
                    "valid_xml": info["valid"],
                    "target_type": info["target_type"],
                    "software_revision": info["software_revision"],
                    "processor": info["processor"],
                    "rung_count_approx": info["rung_count_approx"],
                    "program_count_approx": info["program_count_approx"],
                    "error": info["error"],
                    "query": query,
                }
                manifest.append(entry)
                total_saved += 1
                stats[entry["classification"]] = stats.get(entry["classification"], 0) + 1
                log(f"  [{entry['classification']:10}] {repo_full}/{path} ({len(data)}b)")
                save_manifest(manifest)  # crash-safe incremental save
        except KeyboardInterrupt:
            log("Interrupted, saving progress...")
            save_manifest(manifest)
            raise

    save_manifest(manifest)
    log("")
    log("=== Final composition ===")
    for cls, count in sorted(stats.items(), key=lambda kv: -kv[1]):
        log(f"  {cls:10} {count}")
    log(f"  {'TOTAL':10} {total_saved}")
    log(f"controller >= {args.min_controller}: {'OK' if stats.get('controller', 0) >= args.min_controller else 'SHORT'}")
    log(f"component  >= {args.min_component}: {'OK' if component_total(stats) >= args.min_component else 'SHORT'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
