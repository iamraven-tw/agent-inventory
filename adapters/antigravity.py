"""Google Antigravity (IDE + CLI). Global config under ~/.gemini; project config under .agent/."""
SPEC = {
    "id": "antigravity",
    "name": "Google Antigravity",
    "color": "#3B6FB6",
    "docs": "https://antigravity.google/docs/rules-workflows",
    "detect": ["~/.gemini/antigravity", "~/.gemini/antigravity-cli", "~/.gemini/antigravity-ide"],
    "global_rules": [
        {"file": "~/.gemini/GEMINI.md"},
        {"glob": "~/.gemini/antigravity/global_rules/*.md"},
        {"glob": "~/.gemini/antigravity/global_workflows/*.md", "tag": "workflow"},
    ],
    "global_skills": [
        {"dir": "~/.gemini/antigravity/skills", "depth": 1},
    ],
    "project_markers": ["GEMINI.md", ".agent"],
    "project_rules": [
        {"file": "GEMINI.md"},
        {"glob": ".agent/rules/*.md"},
        {"glob": ".agent/workflows/*.md", "tag": "workflow"},
    ],
    "project_skills": [
        {"dir": ".agent/skills", "depth": 1},
    ],
    "notes": [],
}
