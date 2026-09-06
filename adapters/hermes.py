"""Hermes Agent (Nous Research). Skills are nested two levels (category/skill); project context is the first match in cwd."""
SPEC = {
    "id": "hermes",
    "name": "Hermes Agent",
    "color": "#4E7D5B",
    "docs": "https://github.com/NousResearch/hermes-agent",
    "detect": ["~/.hermes"],
    "global_rules": [
        {"file": "~/.hermes/SOUL.md"},
        {"file": "~/.hermes/AGENTS.md"},
    ],
    "global_skills": [
        {"dir": "~/.hermes/skills", "depth": 3},
    ],
    "project_markers": [".hermes.md", "AGENTS.md", "CLAUDE.md", ".cursorrules"],
    "project_rules": [
        {"first_of": [".hermes.md", "AGENTS.md", "CLAUDE.md", ".cursorrules"]},
    ],
    "project_skills": [],
    "notes": ["Hermes 只讀目前目錄第一個命中的脈絡檔（.hermes.md → AGENTS.md → CLAUDE.md → .cursorrules），沒有專案技能。"],
}
