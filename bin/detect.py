#!/usr/bin/env python3
"""Detect installed AI-agent tools and candidate project roots. Output is for the inventory-setup skill.

Usage:
  python3 bin/detect.py            # human-readable summary (for the agent to relay to the user)
  python3 bin/detect.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import adapters  # noqa: E402
from adapters.base import HOME, SKIP_DIRS, display_path, expand  # noqa: E402

MARKER_FILES = ["CLAUDE.md", "AGENTS.md", "GEMINI.md", ".cursorrules", ".hermes.md"]
MARKER_DIRS = [".claude", ".cursor", ".agent", ".agents", ".codex"]
COMMON_ROOTS = ["~/Developer", "~/Projects", "~/projects", "~/Code", "~/code", "~/dev", "~/src", "~/GitHub", "~/github",
                "~/workspace", "~/Workspace", "~/repos", "~/Documents/GitHub", "~/Sites"]
TOOL_HOMES = [".claude", ".codex", ".gemini", ".cursor", ".openclaw", ".hermes", ".agents", ".config"]
EXCLUDE_SEGMENTS = SKIP_DIRS | {"Library", ".Trash", "Applications", "node_modules", ".git"}


def detect_tools() -> list[dict]:
    out = []
    for spec in adapters.ALL:
        hits = [display_path(expand(p)) for p in spec.get("detect", []) if expand(p).exists()]
        out.append({"id": spec["id"], "name": spec["name"], "installed": bool(hits), "evidence": hits})
    return out





def home_links() -> list[tuple[Path, Path]]:
    """Top-level entries of HOME that are symlinks to somewhere else (e.g. ~/Developer -> /Volumes/...)."""
    out = []
    try:
        for e in HOME.iterdir():
            if e.is_symlink() and e.is_dir() and not e.name.startswith("."):
                out.append((e, e.resolve()))
    except OSError:
        pass
    return out


def unresolve(p: Path) -> Path:
    """Map a resolved path back under HOME through a top-level symlink when possible, so roots read as ~/Developer."""
    for link, target in home_links():
        try:
            return link / p.relative_to(target)
        except ValueError:
            continue
    return p


def _ok(p: Path) -> bool:
    p = unresolve(p)
    try:
        rel = p.relative_to(HOME)
    except ValueError:
        rel = p
    parts = rel.parts
    if not parts:
        return False
    if parts[0] in TOOL_HOMES:
        return False
    if len(parts) >= 2 and parts[0] == "go" and parts[1] == "pkg":  # Go module cache
        return False
    return not any(seg in EXCLUDE_SEGMENTS or (seg.startswith(".") and seg not in MARKER_DIRS) for seg in parts)


def spotlight_projects() -> list[Path]:
    if not shutil.which("mdfind"):
        return []
    found: set[Path] = set()
    scopes = [HOME] + [t for _, t in home_links() if not str(t).startswith(str(HOME))]
    for scope in scopes:
        for name in MARKER_FILES:
            try:
                res = subprocess.run(["mdfind", "-onlyin", str(scope), f"kMDItemFSName == '{name}'"],
                                     capture_output=True, text=True, timeout=30)
            except (subprocess.TimeoutExpired, OSError):
                continue
            for line in res.stdout.splitlines():
                p = unresolve(Path(line).parent)
                if _ok(p):
                    found.add(p)
    return sorted(found)


def find_projects(roots: list[str], depth: int = 5) -> list[Path]:
    found: set[Path] = set()
    for r in roots:
        root = expand(r)
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            d = Path(dirpath)
            level = len(d.relative_to(root).parts)
            dirnames[:] = [x for x in dirnames if not x.startswith(".") and x not in EXCLUDE_SEGMENTS] if level < depth else []
            if d != HOME and _ok(d) and (any(f in filenames for f in MARKER_FILES) or any((d / m).exists() for m in MARKER_DIRS)):
                found.add(d)
    return sorted(found)


def suggest_roots(projects: list[Path]) -> list[dict]:
    """Group projects by their nearest common parent under HOME (depth 1–2) and count."""
    counter: Counter[Path] = Counter()
    for p in projects:
        try:
            rel = p.relative_to(HOME)
        except ValueError:
            rel = None
        if rel and len(rel.parts) >= 1:
            counter[HOME / rel.parts[0]] += 1
        else:
            counter[p.parent] += 1
    for r in COMMON_ROOTS:
        rp = expand(r)
        if rp.is_dir() and rp not in counter:
            counter[rp] = 0
    return [{"path": display_path(k), "projects": v} for k, v in counter.most_common()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-spotlight", action="store_true")
    args = ap.parse_args()

    tools = detect_tools()
    projects = set() if args.no_spotlight else set(spotlight_projects())
    # Spotlight skips dot-directories and may miss external volumes; a shallow walk of common roots fills the gaps.
    projects |= set(find_projects(COMMON_ROOTS, depth=4))
    projects = sorted(projects)
    roots = suggest_roots(projects)
    result = {"home": display_path(HOME), "tools": tools, "candidateRoots": roots,
              "projects": [display_path(p) for p in projects]}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return
    print("偵測到的 AI agent 工具：")
    for t in tools:
        print(f"  [{'x' if t['installed'] else ' '}] {t['id']:<12} {t['name']}" + (f"  ← {', '.join(t['evidence'])}" if t["evidence"] else ""))
    print(f"\n候選專案根目錄（底下含規則／技能的專案數）：")
    for r in roots:
        print(f"  {r['path']:<40} {r['projects']:>3} 個專案")
    print(f"\n共找到 {len(projects)} 個含規則或技能的資料夾。加 --json 可取得完整清單。")


if __name__ == "__main__":
    main()
