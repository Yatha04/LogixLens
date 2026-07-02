#!/usr/bin/env python3
"""
corpus/expand_repos.py — Sibling expansion: for every repo already in the
manifest, list its full git tree and download any .l5x files we don't have.

Rationale: GitHub code search surfaces component exports (small, text-matched),
but full-project exports usually sit in the SAME repos. Tree listing finds
them without more code-search quota. Prefers large files first (full projects
are big) and caps per-repo downloads to avoid AOI-library dumps.

Usage:
    ../l5x-copilot/.venv/bin/python expand_repos.py [--per-repo 15] [--max-new 120]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import fetch_corpus as fc  # reuse download / classify / manifest helpers

CORPUS_DIR = Path(__file__).resolve().parent


def gh_json(args: list[str]):
    for attempt in range(4):
        p = subprocess.run(["gh", "api"] + args, capture_output=True, text=True)
        if p.returncode == 0:
            try:
                return json.loads(p.stdout)
            except json.JSONDecodeError:
                return None
        if "rate limit" in (p.stderr or "").lower():
            time.sleep(30 * (attempt + 1))
            continue
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-repo", type=int, default=15)
    ap.add_argument("--max-new", type=int, default=120)
    args = ap.parse_args()

    manifest = fc.load_manifest()
    known_hashes = {e["sha256"] for e in manifest}
    known_paths = {(e["repo"], e["path"]) for e in manifest}
    repos = sorted({e["repo"] for e in manifest if e.get("repo")})
    print(f"{len(repos)} distinct repos in manifest; expanding trees…")

    new_count = 0
    for repo_full in repos:
        if new_count >= args.max_new:
            break
        owner, repo = repo_full.split("/", 1)
        meta = gh_json([f"repos/{owner}/{repo}"])
        if not meta:
            continue
        branch = meta.get("default_branch", "main")
        tree = gh_json([f"repos/{owner}/{repo}/git/trees/{branch}?recursive=1"])
        time.sleep(0.5)
        if not tree or "tree" not in tree:
            continue
        cand = [
            t for t in tree["tree"]
            if t.get("type") == "blob"
            and t.get("path", "").lower().endswith(".l5x")
            and (repo_full, t["path"]) not in known_paths
            and (t.get("size") or 0) <= fc.MAX_FILE_SIZE
        ]
        #

        cand.sort(key=lambda t: -(t.get("size") or 0))  # big files first
        if not cand:
            continue
        print(f"  {repo_full}: {len(cand)} new candidate(s)")
        for t in cand[: args.per_repo]:
            if new_count >= args.max_new:
                break
            path = t["path"]
            known_paths.add((repo_full, path))
            from urllib.parse import quote
            raw_url = (f"https://raw.githubusercontent.com/{owner}/{repo}/"
                       f"{quote(branch)}/{quote(path)}")
            try:
                data = fc.download(raw_url)
            except Exception as e:
                print(f"    ! download failed ({type(e).__name__}): {path}")
                data = None
            time.sleep(fc.DOWNLOAD_SLEEP)
            if not data:
                continue
            import hashlib
            digest = hashlib.sha256(data).hexdigest()
            if digest in known_hashes:
                continue
            known_hashes.add(digest)
            info = fc.validate_and_classify(data)
            safe = Path(path).name.replace(" ", "_")
            fname = f"{digest[:16]}_{safe}"
            (fc.FILES_DIR / fname).write_bytes(data)
            manifest.append({
                "filename": fname,
                "repo": repo_full,
                "path": path,
                "html_url": f"https://github.com/{repo_full}/blob/{branch}/{path}",
                "size": len(data),
                "sha256": digest,
                **info,
                "query": "tree-expansion",
            })
            fc.save_manifest(manifest)
            new_count += 1
            print(f"    + [{info.get('classification')}] {fname} ({len(data)}b)")

    from collections import Counter
    print(f"\nAdded {new_count} files. Composition now: "
          f"{Counter(e['classification'] for e in manifest)}")
    return 0


if __name__ == "__main__":
    main()
