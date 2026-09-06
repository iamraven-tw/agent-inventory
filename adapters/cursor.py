"""Cursor. User Rules are stored in the app settings (not a file); project rules are .mdc files."""
SPEC = {
    "id": "cursor",
    "name": "Cursor",
    "color": "#6B5FB5",
    "docs": "https://cursor.com/docs/context/rules",
    "detect": ["~/.cursor", "~/Library/Application Support/Cursor"],
    "global_rules": [
        {"note": "Cursor 的 User Rules 存在 App 設定裡（Cursor Settings → Rules → User Rules），不是檔案，這裡無法掃描。請直接在 Cursor 內查看。",
         "name": "User Rules（App 設定）"},
        {"glob": "~/.cursor/rules/*.mdc"},
    ],
    "global_skills": [
        {"dir": "~/.cursor/skills", "depth": 1},
        {"dir": "~/.agents/skills", "depth": 1},
        {"dir": "~/.claude/skills", "depth": 1, "source": "compat"},
        {"dir": "~/.codex/skills", "depth": 1, "source": "compat"},
    ],
    "project_markers": [".cursor", ".cursorrules", "AGENTS.md"],
    "project_rules": [
        {"glob": ".cursor/rules/**/*.mdc"},
        {"file": "AGENTS.md"},
        {"file": ".cursorrules", "tag": "legacy"},
    ],
    "project_skills": [
        {"dir": ".cursor/skills", "depth": 1},
        {"dir": ".agents/skills", "depth": 1},
        {"dir": ".claude/skills", "depth": 1, "source": "compat"},
        {"dir": ".codex/skills", "depth": 1, "source": "compat"},
    ],
    "notes": ["來源標 compat 的技能是 Cursor 為相容而順帶讀取的 Claude／Codex 目錄。"],
}
