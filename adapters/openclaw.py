"""OpenClaw. Unit of configuration is an agent *workspace* (a folder of markdown files), not a project."""
import json
import re
from pathlib import Path

from .base import expand

WORKSPACE_FILES = ["AGENTS.md", "SOUL.md", "TOOLS.md", "USER.md", "IDENTITY.md", "HEARTBEAT.md", "BOOT.md", "BOOTSTRAP.md", "MEMORY.md"]


def _workspaces() -> list[Path]:
    """Default workspace plus any listed in openclaw.json (agents.list[].workspace) or matching ~/.openclaw/workspace*."""
    found: list[Path] = []
    state = expand("~/.openclaw")
    if not state.is_dir():
        return found
    default = state / "workspace"
    cfg = state / "openclaw.json"
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8", errors="replace")
        try:
            data = json.loads(text)
            d = data.get("agents", {}).get("defaults", {}).get("workspace")
            if d:
                default = expand(d)
            for a in data.get("agents", {}).get("list", []) or []:
                if a.get("workspace"):
                    found.append(expand(a["workspace"]))
        except json.JSONDecodeError:  # JSON5 with comments: fall back to regex
            for m in re.finditer(r'"workspace"\s*:\s*"([^"]+)"', text):
                found.append(expand(m.group(1)))
    found.insert(0, default)
    for p in sorted(state.glob("workspace*")):
        if p.is_dir():
            found.append(p)
    uniq: list[Path] = []
    for p in found:
        if p.is_dir() and p not in uniq:
            uniq.append(p)
    return uniq


def extra_projects(config: dict) -> list[dict]:
    projects = []
    for ws in _workspaces()[1:]:  # first one is the default workspace, reported as global
        projects.append({
            "name": f"workspace：{ws.name}",
            "path": ws,
            "rules": [{"file": f} for f in WORKSPACE_FILES],
            "skills": [{"dir": "skills", "depth": 1}, {"dir": ".agents/skills", "depth": 1}],
        })
    return projects


def _default_ws() -> str:
    ws = _workspaces()
    return str(ws[0]) if ws else "~/.openclaw/workspace"


SPEC = {
    "id": "openclaw",
    "name": "OpenClaw",
    "color": "#B5533C",
    "docs": "https://docs.openclaw.ai/concepts/agent-workspace",
    "detect": ["~/.openclaw"],
    "global_rules": [{"file": f"{_default_ws()}/{f}"} for f in WORKSPACE_FILES],
    "global_skills": [
        {"dir": f"{_default_ws()}/skills", "depth": 1},
        {"dir": f"{_default_ws()}/.agents/skills", "depth": 1},
        {"dir": "~/.agents/skills", "depth": 1},
        {"dir": "~/.openclaw/skills", "depth": 1, "source": "plugin"},
    ],
    "project_markers": [],
    "project_rules": [],
    "project_skills": [],
    "extra_projects": extra_projects,
    "notes": ["OpenClaw 沒有「專案」概念，這裡把預設 workspace 當全域，其他 agent 的 workspace 當專案列出。"],
}
