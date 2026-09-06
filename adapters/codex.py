"""OpenAI Codex — the CLI and the ChatGPT desktop app share ~/.codex."""
SPEC = {
    "id": "codex",
    "name": "Codex（ChatGPT App）",
    "color": "#2F2F2F",
    "docs": "https://developers.openai.com/codex/guides/agents-md",
    "detect": ["~/.codex"],
    "global_rules": [
        {"file": "~/.codex/AGENTS.md"},
    ],
    "global_skills": [
        {"dir": "~/.codex/skills", "depth": 1},
        {"dir": "~/.agents/skills", "depth": 1},
        {"dir": "~/.codex/skills/.system", "depth": 1, "source": "builtin"},
    ],
    "project_markers": ["AGENTS.md", ".agents", ".codex"],
    "project_rules": [
        {"file": "AGENTS.md"},
    ],
    "project_skills": [
        {"dir": ".agents/skills", "depth": 1},
        {"dir": ".codex/skills", "depth": 1},
    ],
    "notes": [],
}
