#!/usr/bin/env python3
"""Scan local AI-agent rules and skills into data/inventory.json.

Usage:
  python3 bin/scan.py                       # uses ~/.config/agent-inventory/config.json
  python3 bin/scan.py --roots ~/Developer   # override project roots (also works without a config file)
  python3 bin/scan.py --tools claude-code,codex --depth 4

Outputs (in <repo>/data/):
  inventory.json          everything the website needs
  pending-summaries.json  items that still need a written summary (for the inventory-summarize skill)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import adapters  # noqa: E402
from adapters.base import (  # noqa: E402
    HOME, SKIP_DIRS, content_hash, display_path, expand, find_skill_files, iso_mtime,
    parse_frontmatter, path_id, resolve_rule_entry,
)

CONFIG_PATH = expand(os.environ.get("AGENT_INVENTORY_CONFIG", "~/.config/agent-inventory/config.json"))
DATA_DIR = REPO / "data"
EXCERPT_CHARS = 2500
SKILL_EXCERPT_CHARS = 500
PROJECT_DOC_FILES = ["README.md", "readme.md", "CLAUDE.md", "AGENTS.md", "GEMINI.md", ".cursorrules", "package.json", "pyproject.toml"]
DEFAULT_EXCLUDE = sorted(SKIP_DIRS | {"Applications", "Movies", "Music", "Pictures", "Downloads"})


# ---------------------------------------------------------------- config

def load_config(args) -> dict:
    cfg: dict = {}
    if CONFIG_PATH.is_file():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if args.roots:
        cfg["projectRoots"] = [r for r in args.roots.split(",") if r.strip()]
    if args.tools:
        cfg["tools"] = [t.strip() for t in args.tools.split(",") if t.strip()]
    if args.depth:
        cfg["scanDepth"] = args.depth
    cfg.setdefault("tools", [s["id"] for s in adapters.ALL])
    cfg.setdefault("projectRoots", [])
    cfg.setdefault("scanDepth", 4)
    cfg.setdefault("exclude", DEFAULT_EXCLUDE)
    cfg.setdefault("language", "zh-TW")
    if not cfg["projectRoots"] and not CONFIG_PATH.is_file():
        print("尚未設定。請先執行 inventory-setup 技能，或用 --roots 指定專案根目錄。", file=sys.stderr)
    return cfg


# ---------------------------------------------------------------- items

class Inventory:
    def __init__(self, cache: dict):
        self.items: dict[str, dict] = {}
        self.cache = cache
        self.pending: dict[str, dict] = {}
        self.projects: dict[str, dict] = {}

    def add_project(self, path: Path, name: str) -> str:
        """Register a project once and queue a purpose summary for it (from README / rule files)."""
        pid = "proj-" + path_id(path.resolve())
        if pid in self.projects:
            return pid
        chunks, hasher, seen = [], [], set()
        for fname in PROJECT_DOC_FILES:
            f = path / fname
            if f.is_file() and fname.lower() not in seen:  # macOS 大小寫不分，README.md 與 readme.md 是同一檔
                seen.add(fname.lower())
                try:
                    raw = f.read_bytes()
                except OSError:
                    continue
                hasher.append(content_hash(raw))
                txt = raw.decode("utf-8", errors="replace")
                _, body = parse_frontmatter(txt)
                chunks.append(f"--- {fname} ---\n" + (body.strip() or txt)[:1400])
                if len(chunks) >= 3:
                    break
        h = content_hash(("|".join(hasher) + str(path)).encode())
        cached = self.cache.get(h)
        summary = cached["summary"] if cached and cached.get("summary") else ""
        self.projects[pid] = {
            "id": pid, "name": name, "path": display_path(path), "realPath": display_path(path.resolve()),
            "summary": summary, "summarySource": "agent" if summary else "pending", "hash": h,
            "tools": [], "rules": 0, "skills": 0,
        }
        if not summary:
            self.pending[pid] = {"id": pid, "kind": "project", "name": name, "path": display_path(path), "hash": h,
                                 "description": "", "excerpt": "\n\n".join(chunks) if chunks else "（沒有 README 或規則檔可讀）"}
        return pid

    def add(self, path: Path, *, kind: str, tool: str, scope: str, project: str | None,
            source: str = "user", tag: str | None = None, name: str | None = None) -> str:
        real = path.resolve()
        iid = path_id(real)
        item = self.items.get(iid)
        if item is None:
            item = self._build(path, real, iid, kind, name)
            item.update({"scope": scope, "project": project, "source": source, "tag": tag})
            self.items[iid] = item
        else:
            # keep the most specific labels; a user-owned copy beats compat/plugin labels
            if item["source"] in ("compat",) and source != "compat":
                item["source"] = source
            if tag and not item.get("tag"):
                item["tag"] = tag
        if tool not in item["tools"]:
            item["tools"].append(tool)
        item["paths"].setdefault(tool, display_path(path))
        return iid

    def add_note(self, *, tool: str, text: str, name: str) -> str:
        iid = path_id(Path(f"note://{tool}/{name}"))
        self.items[iid] = {
            "id": iid, "kind": "note", "name": name, "path": "", "realPath": "", "isSymlink": False,
            "tools": [tool], "paths": {}, "scope": "global", "project": None, "source": "user", "tag": None,
            "description": text, "trigger": "", "summary": text, "summarySource": "note",
            "updatedAt": "", "size": 0, "hash": "",
        }
        return iid

    def _build(self, path: Path, real: Path, iid: str, kind: str, name: str | None) -> dict:
        try:
            raw = real.read_bytes()
        except OSError:
            raw = b""
        text = raw.decode("utf-8", errors="replace")
        fm, body = parse_frontmatter(text)
        h = content_hash(raw)
        desc = str(fm.get("description", "") or "").strip()
        if kind == "skill":
            display = str(fm.get("name") or name or path.parent.name)
        else:
            display = name or path.name
        trigger = self._trigger(fm)
        imports, import_text, import_only = self._imports(real, body if body.strip() else text) if kind == "rule" else ([], "", False)
        cached = self.cache.get(h)
        if cached and cached.get("summary"):
            summary, ssrc = cached["summary"], cached.get("source", "agent")
        elif import_only:
            summary, ssrc = f"這個檔案只引用同目錄的 {'、'.join(imports)}，規則內容以被引用的檔案為準。", "import"
        else:
            # 所有摘要都必須由 agent 以設定語言重新詮釋；frontmatter description 只保留為原文
            summary, ssrc = "", "pending"
        item = {
            "id": iid, "kind": kind, "name": display,
            "path": display_path(path), "realPath": display_path(real), "isSymlink": path.is_symlink() or path.parent.is_symlink(),  # 只看檔案或技能資料夾本身，不受上層 symlink（如 ~/Developer）影響
            "tools": [], "paths": {},
            "description": desc, "trigger": trigger, "imports": imports,
            "summary": summary, "summarySource": ssrc,
            "updatedAt": iso_mtime(real), "size": len(raw), "hash": h,
        }
        if ssrc == "pending" and raw:
            excerpt = body.strip() if body.strip() else text
            if import_text:
                excerpt = excerpt + "\n\n" + import_text
            # 技能已有作者寫的 description，內文只需少量節錄；規則檔沒有 description，多給一點
            limit = SKILL_EXCERPT_CHARS if kind == "skill" and desc else EXCERPT_CHARS
            self.pending[iid] = {
                "id": iid, "kind": kind, "name": display, "path": item["path"], "hash": h,
                "description": desc, "excerpt": excerpt[:limit],
            }
        return item

    @staticmethod
    def _imports(real: Path, text: str) -> tuple[list[str], str, bool]:
        """Detect Claude Code style `@path` includes. Returns (names, inlined text, whether file is import-only)."""
        import re as _re
        names, chunks, other = [], [], []
        for line in text.splitlines():
            m = _re.match(r"^\s*@([^\s`]+)\s*$", line)
            if m:
                ref = (real.parent / os.path.expanduser(m.group(1))).resolve()
                names.append(m.group(1))
                if ref.is_file():
                    try:
                        chunks.append(f"--- 引用 {m.group(1)} ---\n" + ref.read_text(encoding="utf-8", errors="replace")[:EXCERPT_CHARS])
                    except OSError:
                        pass
            elif line.strip() and not line.strip().startswith("#"):
                other.append(line)
        return names, "\n".join(chunks), bool(names) and not other

    @staticmethod
    def _trigger(fm: dict) -> str:
        parts = []
        for key in ("trigger", "globs", "paths", "alwaysApply", "always_on", "user-invocable", "disable-model-invocation"):
            if key in fm and fm[key] not in ("", None):
                v = fm[key]
                parts.append(f"{key}: {', '.join(v) if isinstance(v, list) else v}")
        return "；".join(parts)


# ---------------------------------------------------------------- scanning

def _uniq(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    return [i for i in ids if not (i in seen or seen.add(i))]


def scan_rules(inv: Inventory, base: Path, entries: list[dict], *, tool: str, scope: str, project: str | None) -> list[str]:
    ids = []
    for e in entries:
        if "note" in e:
            ids.append(inv.add_note(tool=tool, text=e["note"], name=e.get("name", "說明")))
            continue
        for p in resolve_rule_entry(base, e):
            name = e.get("name")
            if name is None and scope == "project" and "glob" in e:
                try:
                    name = str(p.relative_to(base))
                except ValueError:
                    name = p.name
            ids.append(inv.add(p, kind="rule", tool=tool, scope=scope, project=project,
                               source=e.get("source", "user"), tag=e.get("tag"), name=name))
    return _uniq(ids)


def scan_skills(inv: Inventory, base: Path, entries: list[dict], *, tool: str, scope: str, project: str | None) -> list[str]:
    ids = []
    for e in entries:
        d = e["dir"]
        root = expand(d) if str(d).startswith(("~", "/")) else base / d
        for skill in find_skill_files(root, e.get("depth", 1), e.get("include_hidden", False)):
            tag = e.get("tag")
            if e.get("source") == "plugin" and "plugins" in skill.parts:
                # ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/skills/<name>/SKILL.md
                parts = skill.parts
                try:
                    i = parts.index("cache")
                    tag = f"plugin:{parts[i + 2]}"
                except (ValueError, IndexError):
                    pass
            ids.append(inv.add(skill, kind="skill", tool=tool, scope=scope, project=project,
                               source=e.get("source", "user"), tag=tag))
    return _uniq(ids)


def discover_projects(roots: list[str], depth: int, markers: set[str], exclude: set[str]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    def is_project(d: Path) -> bool:
        return any((d / m).exists() for m in markers)

    def walk(d: Path, level: int):
        if d in seen:
            return
        seen.add(d)
        if d != HOME and is_project(d):
            found.append(d)
        if level >= depth:
            return
        try:
            children = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for c in children:
            if not c.is_dir() or c.is_symlink() and c.resolve() in seen:
                continue
            if c.name.startswith(".") or c.name in exclude:
                continue
            walk(c, level + 1)

    for r in roots:
        root = expand(r)
        if root.is_dir():
            walk(root, 0)
    return found


def tool_installed(spec: dict) -> bool:
    return any(expand(p).exists() for p in spec.get("detect", []))


def run(cfg: dict) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / "summary-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    inv = Inventory(cache)
    specs = adapters.get(cfg["tools"])
    exclude = set(cfg["exclude"])

    all_markers = set()
    for s in specs:
        all_markers.update(s.get("project_markers", []))
    projects = discover_projects(cfg["projectRoots"], cfg["scanDepth"], all_markers, exclude)

    tools_out = []
    for s in specs:
        tool = s["id"]
        installed = tool_installed(s)
        g_rules = scan_rules(inv, HOME, s.get("global_rules", []), tool=tool, scope="global", project=None)
        g_skills = scan_skills(inv, HOME, s.get("global_skills", []), tool=tool, scope="global", project=None)
        proj_out = []
        for p in projects:
            if not any((p / m).exists() for m in s.get("project_markers", [])):
                continue
            pr = scan_rules(inv, p, s.get("project_rules", []), tool=tool, scope="project", project=display_path(p))
            ps = scan_skills(inv, p, s.get("project_skills", []), tool=tool, scope="project", project=display_path(p))
            if pr or ps:
                pid = inv.add_project(p, p.name)
                prj = inv.projects[pid]
                prj["tools"].append(tool); prj["rules"] += len(pr); prj["skills"] += len(ps)
                proj_out.append({"id": pid, "name": p.name, "path": display_path(p), "rules": pr, "skills": ps})
        if callable(s.get("extra_projects")):
            for xp in s["extra_projects"](cfg):
                base = Path(xp["path"])
                pr = scan_rules(inv, base, xp.get("rules", []), tool=tool, scope="project", project=display_path(base))
                ps = scan_skills(inv, base, xp.get("skills", []), tool=tool, scope="project", project=display_path(base))
                if pr or ps:
                    pid = inv.add_project(base, xp["name"])
                    prj = inv.projects[pid]
                    prj["tools"].append(tool); prj["rules"] += len(pr); prj["skills"] += len(ps)
                    proj_out.append({"id": pid, "name": xp["name"], "path": display_path(base), "rules": pr, "skills": ps})
        tools_out.append({
            "id": tool, "name": s["name"], "color": s.get("color", "#888"), "docs": s.get("docs", ""),
            "installed": installed, "notes": s.get("notes", []),
            "global": {"rules": g_rules, "skills": g_skills},
            "projects": proj_out,
        })

    stats = {
        "rules": sum(1 for i in inv.items.values() if i["kind"] == "rule"),
        "skills": sum(1 for i in inv.items.values() if i["kind"] == "skill"),
        "projects": len(inv.projects),
        "shared": sum(1 for i in inv.items.values() if len(i["tools"]) > 1),
        "pending": len(inv.pending),
        "installedTools": sum(1 for t in tools_out if t["installed"]),
    }
    return {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "language": cfg.get("language", "zh-TW"),
        "home": str(HOME),
        "config": {"projectRoots": cfg["projectRoots"], "scanDepth": cfg["scanDepth"], "tools": cfg["tools"]},
        "stats": stats,
        "tools": tools_out,
        "projects": inv.projects,
        "items": inv.items,
        "_pending": list(inv.pending.values()),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", help="comma-separated project roots (overrides config)")
    ap.add_argument("--tools", help="comma-separated tool ids (overrides config)")
    ap.add_argument("--depth", type=int, help="project scan depth (overrides config)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args)
    result = run(cfg)
    pending = result.pop("_pending")
    (DATA_DIR / "inventory.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA_DIR / "pending-summaries.json").write_text(json.dumps(pending, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.quiet:
        s = result["stats"]
        print(f"掃描完成 → {display_path(DATA_DIR / 'inventory.json')}")
        print(f"  規則 {s['rules']}｜技能 {s['skills']}｜專案 {s['projects']}｜跨工具共用 {s['shared']}｜待補摘要 {s['pending']}")
        for t in result["tools"]:
            flag = "✓" if t["installed"] else "✗ 未偵測到"
            print(f"  {t['name']:<22} {flag:<8} 全域規則 {len(t['global']['rules']):>3}  全域技能 {len(t['global']['skills']):>3}  "
                  f"專案 {len(t['projects']):>2}  專案規則 {sum(len(p['rules']) for p in t['projects']):>3}  "
                  f"專案技能 {sum(len(p['skills']) for p in t['projects']):>3}")


if __name__ == "__main__":
    main()
