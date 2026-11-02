"""全機技能快照的離線驗證。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from backup_skills import CONFIG_ENV, BackupError, Rules, export, load_rules, verify_snapshot  # noqa: E402


class BackupSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # 測試一律指向空白設定檔，避免讀到本機真實設定。
        empty = self.root / "empty-config.json"
        empty.write_text("{}", encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {CONFIG_ENV: str(empty)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_skill(self, name: str, files: dict[str, str]) -> Path:
        """建立暫存技能資料夾（含 SKILL.md 與指定檔案）。"""
        skill = self.root / "source" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# 技能\n", encoding="utf-8")
        for relative, text in files.items():
            (skill / relative).parent.mkdir(parents=True, exist_ok=True)
            (skill / relative).write_text(text, encoding="utf-8")
        return skill

    def write_config(self, data: dict) -> Path:
        path = self.root / "backup-config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def item(self, folder: Path, *, source: str = "user") -> dict:
        return {
            "kind": "skill", "source": source, "name": folder.name,
            "realPath": str(folder / "SKILL.md"), "tools": ["codex"],
            "paths": {"codex": str(folder / "SKILL.md")},
        }

    def test_exports_complete_folder_and_internal_link(self) -> None:
        skill = self.root / "source" / "sample"
        (skill / "scripts").mkdir(parents=True)
        (skill / "SKILL.md").write_text("# 技能\n", encoding="utf-8")
        (skill / "scripts" / "run.py").write_text("print('ok')\n", encoding="utf-8")
        (skill / "run-link.py").symlink_to("scripts/run.py")
        output = self.root / "backup"
        manifest = export({"a": self.item(skill)}, output)
        record = manifest["skills"][0]
        copied = output / "skills" / record["id"]
        self.assertEqual((copied / "scripts" / "run.py").read_text(), "print('ok')\n")
        self.assertEqual((copied / "run-link.py").read_text(), "print('ok')\n")
        self.assertEqual(json.loads((output / "manifest.json").read_text())["skillCount"], 1)
        self.assertEqual(verify_snapshot(output)["skillCount"], 1)

    def test_detects_corrupted_snapshot(self) -> None:
        skill = self.root / "source" / "sample"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# 技能\n", encoding="utf-8")
        output = self.root / "backup"
        export({"a": self.item(skill)}, output)
        copied = next((output / "skills").iterdir())
        (copied / "SKILL.md").write_text("損壞\n", encoding="utf-8")
        with self.assertRaises(BackupError):
            verify_snapshot(output)

    def test_private_file_is_explicitly_excluded(self) -> None:
        skill = self.root / "source" / "sample"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# 技能\n", encoding="utf-8")
        (skill / ".env").write_text("PASSWORD=not-for-upload\n", encoding="utf-8")
        output = self.root / "backup"
        manifest = export({"a": self.item(skill)}, output)
        self.assertEqual(manifest["skills"][0]["excludedSensitivePaths"], [".env"])
        self.assertFalse(next((output / "skills").iterdir()).joinpath(".env").exists())

    def test_embedded_credential_stops_snapshot(self) -> None:
        skill = self.root / "source" / "sample"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("token = 'abcdefghijklmnopqrstuvwxyz123456'\n", encoding="utf-8")
        output = self.root / "backup"
        with self.assertRaises(BackupError):
            export({"a": self.item(skill)}, output)
        self.assertFalse(output.exists())

    def test_external_link_stops_snapshot(self) -> None:
        skill = self.root / "source" / "sample"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# 技能\n", encoding="utf-8")
        (skill / "outside-link").symlink_to(self.root / "outside.txt")
        (self.root / "outside.txt").write_text("outside", encoding="utf-8")
        with self.assertRaises(BackupError):
            export({"a": self.item(skill)}, self.root / "backup")

    def test_builtin_is_optional(self) -> None:
        skill = self.root / "source" / "system"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# 內建\n", encoding="utf-8")
        items = {"a": self.item(skill, source="builtin")}
        self.assertEqual(export(items, None)["skillCount"], 0)
        self.assertEqual(export(items, None)["omittedBuiltin"], 1)
        self.assertEqual(export(items, None, include_builtin=True)["skillCount"], 1)

    def test_existing_output_is_not_overwritten(self) -> None:
        skill = self.root / "source" / "sample"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# 技能\n", encoding="utf-8")
        output = self.root / "backup"
        output.mkdir()
        with self.assertRaises(BackupError):
            export({"a": self.item(skill)}, output)

    def test_gitignore_excludes_generated_project_data(self) -> None:
        skill = self.root / "source" / "project-skill"
        skill.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(skill)], check=True)
        (skill / ".gitignore").write_text("runtime/\n", encoding="utf-8")
        (skill / "SKILL.md").write_text("# 技能\n", encoding="utf-8")
        (skill / "helper.py").write_text("print('ok')\n", encoding="utf-8")
        (skill / "runtime").mkdir()
        (skill / "runtime" / "large.wav").write_bytes(b"generated")
        output = self.root / "backup"
        manifest = export({"a": self.item(skill)}, output)
        self.assertEqual(manifest["skills"][0]["selectionPolicy"], "git-visible")
        copied = next((output / "skills").iterdir())
        self.assertTrue((copied / "helper.py").is_file())
        self.assertFalse((copied / "runtime").exists())

    def test_link_to_same_repository_dependency_is_expanded(self) -> None:
        repository = self.root / "source" / "project"
        skill = repository / ".claude" / "skills" / "sample"
        data = repository / "src" / "data"
        skill.mkdir(parents=True)
        data.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        (skill / "SKILL.md").write_text("# 技能\n", encoding="utf-8")
        (data / "guide.txt").write_text("參考內容\n", encoding="utf-8")
        (skill / "data").symlink_to(data)
        output = self.root / "backup"
        manifest = export({"a": self.item(skill)}, output)
        copied = next((output / "skills").iterdir())
        self.assertEqual((copied / "data" / "guide.txt").read_text(), "參考內容\n")
        self.assertEqual(manifest["skills"][0]["expandedLinks"], ["data"])

    # ---- 允許清單與排除目錄（技能相對路徑） ----

    FIXTURE = 'token = "expired-fixture"\n'

    def test_default_allowlist_matches_skill_relative_path(self) -> None:
        skill = self.make_skill("media-use", {"audio/scripts/gemini-pipeline.test.mjs": self.FIXTURE})
        manifest = export({"a": self.item(skill)}, self.root / "backup")
        self.assertEqual(manifest["skillCount"], 1)

    def test_allowlist_value_in_other_file_still_blocked(self) -> None:
        skill = self.make_skill("media-use", {"audio/scripts/other.test.mjs": self.FIXTURE})
        with self.assertRaises(BackupError):
            export({"a": self.item(skill)}, None)

    def test_allowlist_same_path_in_other_skill_still_blocked(self) -> None:
        skill = self.make_skill("another-skill", {"audio/scripts/gemini-pipeline.test.mjs": self.FIXTURE})
        with self.assertRaises(BackupError):
            export({"a": self.item(skill)}, None)

    def test_allowlist_other_value_in_same_file_still_blocked(self) -> None:
        skill = self.make_skill("media-use", {"audio/scripts/gemini-pipeline.test.mjs": 'token = "different-fixture"\n'})
        with self.assertRaises(BackupError):
            export({"a": self.item(skill)}, None)

    def test_default_excluded_dir_is_skipped(self) -> None:
        skill = self.make_skill("video-use", {".remotion/chrome/blob.bin": "cache", "helper.py": "print('ok')\n"})
        output = self.root / "backup"
        manifest = export({"a": self.item(skill)}, output)
        record = manifest["skills"][0]
        self.assertEqual(record["excludedPaths"], [".remotion"])
        copied = output / "skills" / record["id"]
        self.assertFalse((copied / ".remotion").exists())
        self.assertTrue((copied / "helper.py").is_file())

    def test_same_dir_name_in_other_skill_is_kept(self) -> None:
        skill = self.make_skill("other-skill", {".remotion/notes.txt": "keep"})
        manifest = export({"a": self.item(skill)}, None)
        self.assertIn(".remotion/notes.txt", [f["path"] for f in manifest["skills"][0]["files"]])

    def test_excluded_dir_inside_git_repository(self) -> None:
        skill = self.make_skill("video-use", {".remotion/blob.bin": "cache"})
        subprocess.run(["git", "init", "-q", str(skill)], check=True)
        manifest = export({"a": self.item(skill)}, None)
        self.assertEqual(manifest["skills"][0]["selectionPolicy"], "git-visible")
        self.assertIn(".remotion/blob.bin", manifest["skills"][0]["excludedPaths"])

    def test_config_from_environment_extends_defaults(self) -> None:
        config = self.write_config({
            "allowedTestValues": [{"skill": "custom", "path": "t/a.test.js", "value": "sample-fixture"}],
            "excludedDirs": [{"skill": "custom", "path": "downloads"}],
        })
        with mock.patch.dict(os.environ, {CONFIG_ENV: str(config)}):
            rules = load_rules()
        self.assertEqual(rules.source, str(config))
        self.assertTrue(rules.allows("custom", Path("t/a.test.js"), b"sample-fixture"))
        self.assertTrue(rules.allows("media-use", Path("audio/scripts/gemini-pipeline.test.mjs"), b"expired-fixture"))
        self.assertTrue(rules.excludes("custom", Path("downloads/x/y.bin")))
        self.assertTrue(rules.excludes("video-use", Path(".remotion")))
        self.assertFalse(rules.excludes("custom", Path("downloads-other/y.bin")))
        skill = self.make_skill("custom", {"t/a.test.js": 'secret = "sample-fixture"\n', "downloads/big.bin": "x"})
        manifest = export({"a": self.item(skill)}, None, rules=rules)
        self.assertEqual(manifest["skills"][0]["excludedPaths"], ["downloads"])

    def test_config_can_disable_defaults(self) -> None:
        rules = load_rules(self.write_config({"useDefaults": False}))
        self.assertEqual(rules.allowed, set())
        self.assertEqual(rules.excluded, set())

    def test_config_rejects_absolute_or_parent_paths(self) -> None:
        for bad in ("/abs/path.js", "../escape.js", "~/home.js"):
            with self.assertRaises(BackupError):
                load_rules(self.write_config({"excludedDirs": [{"skill": "x", "path": bad}]}))

    def test_explicit_missing_config_is_an_error(self) -> None:
        with mock.patch.dict(os.environ, {CONFIG_ENV: str(self.root / "missing.json")}):
            with self.assertRaises(BackupError):
                load_rules()

    def test_without_any_config_uses_defaults(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != CONFIG_ENV}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("backup_skills.REPO_CONFIG_PATH", self.root / "none-a.json"), \
                mock.patch("backup_skills.default_config_path", return_value=self.root / "none-b.json"):
            rules = load_rules()
        self.assertEqual(rules.source, "預設值")
        self.assertEqual(rules.allowed, Rules().allowed)

    def test_example_config_is_valid(self) -> None:
        example = Path(__file__).resolve().parents[1] / "config" / "backup_skills.example.json"
        rules = load_rules(example)
        self.assertTrue(rules.excludes("example-skill", Path(".cache-downloads")))


if __name__ == "__main__":
    unittest.main()
