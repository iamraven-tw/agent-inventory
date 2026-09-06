"""Shared helpers for adapters and the scanner: path expansion, frontmatter parsing, skill discovery.

Adapter SPEC contract (all keys optional except id/name):
  id, name, color, docs
  detect:          list of paths; tool counts as installed if any exists
  global_rules:    list of rule entries (see below)
  global_skills:   list of skill-dir entries
  project_markers: file/dir names whose presence makes a directory a "project" for this tool
  project_rules:   list of rule entries, relative to a project dir
  project_skills:  list of skill-dir entries, relative to a project dir
  extra_projects:  callable(config) -> list of {"name", "path", "rules": [entries], "skills": [entries]}
                   for tools whose "projects" are not discovered by walking roots (e.g. OpenClaw workspaces)

Rule entry forms:
  {"file": "CLAUDE.md"}                          single file
  {"glob": ".cursor/rules/**/*.mdc"}            glob (relative to base)
  {"first_of": ["AGENTS.md", "CLAUDE.md"]}     first existing file wins
  {"note": "..."}                                non-file item, shown as a hint
Skill-dir entry forms:
  {"dir": "~/.claude/skills", "depth": 1}       find */SKILL.md up to depth (default 1)
  {"dir": "...", "include_hidden": true}        also descend into dot-directories
Any entry may carry "source" (user|plugin|builtin|compat|bundled) and "tag" (free label).
"""
from __future__ import annotations

import json
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "dist", "build", ".venv", "venv", ".Trash", "Library", ".cache"}


def expand(p: str | Path) -> Path:
    return Path(os.path.expanduser(str(p)))


def display_path(p: Path) -> str:
    s = str(p)
    home = str(HOME)
    return "~" + s[len(home):] if s.startswith(home) else s


def iso_mtime(p: Path) -> str:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except OSError:
        return ""


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def path_id(real: Path) -> str:
    return hashlib.sha1(str(real).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- frontmatter

def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_simple_yaml(lines: list[str]) -> dict:
    """Minimal YAML subset: scalars, block scalars (| and >), one level of nested mapping, simple lists."""
    out: dict = {}
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*:\s*(.*)$", raw)
        if not m or raw.startswith((" ", "\t")):
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val in ("|", ">", "|-", ">-"):
            block = []
            i += 1
            while i < n and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            joiner = "\n" if val.startswith("|") else " "
            out[key] = joiner.join(b for b in block).strip()
            continue
        if val == "":
            # nested mapping or list
            sub: list[str] = []
            i += 1
            while i < n and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                sub.append(lines[i])
                i += 1
            items = [s.strip() for s in sub if s.strip()]
            if items and all(s.startswith("- ") for s in items):
                out[key] = [_unquote(s[2:]) for s in items]
            else:
                nested: dict = {}
                for s in items:
                    mm = re.match(r"^([A-Za-z0-9_\-\.]+)\s*:\s*(.*)$", s)
                    if mm:
                        nested[mm.group(1)] = _unquote(mm.group(2))
                out[key] = nested
            continue
        if val.startswith("[") and val.endswith("]"):
            out[key] = [_unquote(x) for x in val[1:-1].split(",") if x.strip()]
        else:
            out[key] = _unquote(val)
        i += 1
    return out


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    end = None
    for idx in range(1, min(len(lines), 200)):
        if lines[idx].strip() in ("---", "..."):
            end = idx
            break
    if end is None:
        return {}, text
    return parse_simple_yaml(lines[1:end]), "\n".join(lines[end + 1:])


# ---------------------------------------------------------------- discovery

def find_skill_files(root: Path, depth: int = 1, include_hidden: bool = False) -> list[Path]:
    """Return SKILL.md files under root, where root/<a>/SKILL.md is depth 1."""
    root = expand(root)
    if not root.is_dir():
        return []
    found: list[Path] = []

    def walk(d: Path, level: int):
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for e in entries:
            if not e.is_dir():
                continue
            if e.name in SKIP_DIRS or (e.name.startswith(".") and not include_hidden):
                continue
            skill = e / "SKILL.md"
            if skill.is_file():
                found.append(skill)
            elif level < depth:
                walk(e, level + 1)

    walk(root, 1)
    return found


def resolve_rule_entry(base: Path, entry: dict) -> list[Path]:
    if "file" in entry:
        p = base / expand(entry["file"]) if not str(entry["file"]).startswith(("~", "/")) else expand(entry["file"])
        return [p] if p.is_file() else []
    if "glob" in entry:
        pat = entry["glob"]
        if pat.startswith(("~", "/")):
            pat = str(expand(pat))
            anchor = Path(pat[: pat.index("*")]).parent if "*" in pat else Path(pat).parent
            rel = os.path.relpath(pat, anchor)
            return sorted(p for p in anchor.glob(rel) if p.is_file())
        return sorted(p for p in base.glob(pat) if p.is_file())
    if "first_of" in entry:
        for name in entry["first_of"]:
            p = base / name
            if p.is_file():
                return [p]
        return []
    return []


# ---------------------------------------------------------------- config location

def config_path() -> Path:
    """~/.config/agent-inventory/config.json；可用環境變數 AGENT_INVENTORY_CONFIG 覆寫（測試或多份設定時用）。"""
    return expand(os.environ.get("AGENT_INVENTORY_CONFIG", "~/.config/agent-inventory/config.json"))


def remember_repo_root(repo: Path) -> None:
    """把這份 clone 的絕對路徑寫進設定檔的 repoRoot。

    技能被複製或 symlink 到全域技能目錄後，agent 從任何目錄都能靠 repoRoot 找到 bin/ 與 data/。
    設定檔不存在時不建立（那是 inventory-setup 的工作）；寫入失敗一律忽略，不影響掃描。
    """
    p = config_path()
    if not p.is_file():
        return
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict) or cfg.get("repoRoot") == str(repo):
            return
        cfg["repoRoot"] = str(repo)
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError):
        return
