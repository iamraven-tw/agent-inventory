"""Claude Code (Anthropic). Global config lives in ~/.claude; project config in CLAUDE.md and .claude/."""
SPEC = {
    "id": "claude-code",
    "name": "Claude Code",
    "color": "#C9694A",
    "docs": "https://docs.anthropic.com/en/docs/claude-code/memory",
    "detect": ["~/.claude"],
    "global_rules": [
        {"file": "~/.claude/CLAUDE.md"},
        {"glob": "~/.claude/rules/*.md"},
        {"glob": "~/.claude/output-styles/*.md", "tag": "output-style"},
    ],
    "global_skills": [
        {"dir": "~/.claude/skills", "depth": 1},
        {"dir": "~/.claude/plugins/cache", "depth": 6, "source": "plugin"},
    ],
    "project_markers": ["CLAUDE.md", ".claude"],
    "project_rules": [
        {"file": "CLAUDE.md"},
        {"file": "CLAUDE.local.md", "tag": "local"},
        {"glob": ".claude/rules/*.md"},
    ],
    "project_skills": [
        {"dir": ".claude/skills", "depth": 1},
    ],
    "notes": [],
}
