#!/usr/bin/env python3
"""以即時盤點結果建立可供私人 Git 倉庫保存的完整技能快照。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

import scan  # noqa: E402


class BackupError(RuntimeError):
    """備份前檢查未通過，不能產生可上傳的快照。"""


# Git 內部資料與作業系統快取不是技能執行所需檔案。
SKIP_NAMES = {
    ".git", ".DS_Store", "__pycache__", ".venv", "venv", "node_modules", ".cache",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "dist", "build",
}
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
PRIVATE_FILE_NAMES = {
    "auth.json", "credentials.json", "secrets.json", "token.json", "cookies.txt",
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
}
PRIVATE_SUFFIXES = {".pem", ".p12", ".pfx", ".key"}
SECRET_PATTERNS = (
    ("私鑰", re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("GitHub 權杖", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("AWS 存取金鑰", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("Google API 金鑰", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("OpenAI API 金鑰", re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b")),
)
ASSIGNMENT = re.compile(
    rb"(?im)(?:^|[ \t,{(])\s*[\"']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|token|secret|password|passwd)"
    rb"[\"']?\s*[:=]\s*(?:\"([^\s\"]{12,})\"|'([^\s']{12,})'|([A-Za-z0-9_-]{16,}))"
)
# 已人工確認的測試假值：只放行「技能資料夾名稱＋技能內相對路徑＋完全相同的字串」，其他檔案或其他值仍照常攔截。
# 以技能相對路徑表示，不含任何本機絕對路徑；同一個技能裝在多個位置時都適用。
# 2026-11-02：media-use 測試以過期 OAuth 假憑證模擬 HeyGen 登入過期，寫在暫存目錄中，不是真實金鑰。
# 2026-11-02：Gemini 驗證與 TTS 測試以 Mock 假權杖驗證流程與遮罩。
DEFAULT_ALLOWED_TEST_VALUES = {
    ("media-use", "audio/scripts/gemini-pipeline.test.mjs", b"expired-fixture"),
    ("media-use", "audio/scripts/lib/gemini-auth.test.mjs", b"access-token"),
    ("media-use", "audio/scripts/lib/gemini-auth_test.py", b"fixture-token"),
    ("media-use", "audio/scripts/lib/gemini-tts.test.mjs", b"secret-token"),
}
# 指定技能資料夾內不備份的整個子目錄（只限「技能名稱＋技能內相對路徑」，不是全域依名稱略過）。
# 2026-11-02：video-use 的 .remotion/ 是 Remotion 自動下載的 headless Chrome 快取（單檔超過上限），不是技能內容。
DEFAULT_EXCLUDED_DIRS = {
    ("video-use", ".remotion"),
}
# 設定檔：可再追加允許清單與排除目錄。優先順序為 --config、環境變數、repo 內 config/backup_skills.json（gitignore）、
# 使用者設定目錄 ~/.config/agent-inventory/backup_skills.json；都不存在時只用上方預設值。
CONFIG_ENV = "AGENT_INVENTORY_BACKUP_CONFIG"
REPO_CONFIG_PATH = ROOT / "config" / "backup_skills.json"


def default_config_path() -> Path:
    """使用者層級的預設設定檔位置（以家目錄為準，不寫死帳號名稱）。"""
    return Path.home() / ".config" / "agent-inventory" / "backup_skills.json"


class Rules:
    """備份時使用的允許清單與排除目錄，全部以技能相對路徑表示。"""

    def __init__(self, allowed: set[tuple[str, str, bytes]] | None = None,
                 excluded: set[tuple[str, str]] | None = None, source: str = "預設值") -> None:
        self.allowed = set(DEFAULT_ALLOWED_TEST_VALUES if allowed is None else allowed)
        self.excluded = set(DEFAULT_EXCLUDED_DIRS if excluded is None else excluded)
        self.source = source

    def allows(self, skill: str, relative: Path | None, value: bytes) -> bool:
        """精準比對允許清單：技能名稱、相對路徑與字串都必須完全相同。"""
        return relative is not None and (skill, relative.as_posix(), value) in self.allowed

    def excludes(self, skill: str, relative: Path) -> bool:
        """判斷技能內的相對路徑是否位於排除目錄內（含目錄本身）。"""
        parts = relative.parts
        for name, folder in self.excluded:
            if name != skill:
                continue
            folder_parts = Path(folder).parts
            if parts[: len(folder_parts)] == folder_parts:
                return True
        return False


def _safe_relative(raw: object, field: str) -> str:
    """設定檔中的路徑必須是技能內的相對路徑，不接受絕對路徑或 ..。"""
    if not isinstance(raw, str) or not raw.strip():
        raise BackupError(f"備份設定的 {field} 必須是非空字串。")
    path = Path(raw.strip())
    if path.is_absolute() or ".." in path.parts or raw.startswith("~"):
        raise BackupError(f"備份設定的 {field} 必須是技能內的相對路徑：{raw}")
    return path.as_posix()


def _resolve_config_path(explicit: Path | None) -> tuple[Path | None, bool]:
    """找出要讀的設定檔；明確指定（參數或環境變數）時檔案必須存在。"""
    if explicit is not None:
        return explicit.expanduser(), True
    env = os.environ.get(CONFIG_ENV)
    if env:
        return Path(env).expanduser(), True
    for candidate in (REPO_CONFIG_PATH, default_config_path()):
        if candidate.is_file():
            return candidate, False
    return None, False


def load_rules(config_path: Path | None = None) -> Rules:
    """讀取設定檔並與預設值合併；設定檔格式錯誤時停止，不以不完整的規則備份。"""
    path, required = _resolve_config_path(config_path)
    if path is None:
        return Rules()
    if not path.is_file():
        if required:
            raise BackupError(f"找不到指定的備份設定檔：{path}")
        return Rules()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BackupError(f"備份設定檔不是有效的 JSON：{path}") from exc
    if not isinstance(data, dict):
        raise BackupError(f"備份設定檔最上層必須是物件：{path}")
    use_defaults = data.get("useDefaults", True)
    allowed = set(DEFAULT_ALLOWED_TEST_VALUES) if use_defaults else set()
    excluded = set(DEFAULT_EXCLUDED_DIRS) if use_defaults else set()
    for entry in data.get("allowedTestValues", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("skill"), str) or not isinstance(entry.get("value"), str):
            raise BackupError("備份設定的 allowedTestValues 每一項都要有 skill、path、value。")
        allowed.add((entry["skill"], _safe_relative(entry.get("path"), "allowedTestValues.path"), entry["value"].encode()))
    for entry in data.get("excludedDirs", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("skill"), str):
            raise BackupError("備份設定的 excludedDirs 每一項都要有 skill、path。")
        excluded.add((entry["skill"], _safe_relative(entry.get("path"), "excludedDirs.path")))
    return Rules(allowed, excluded, source=str(path))


PLACEHOLDER_PREFIXES = (b"<", b"${", b"{{", b"={{", b"your", b"example", b"replace", b"dummy", b"placeholder", b"generate-", b"test-")


def _relative(path: Path, root: Path) -> Path:
    """確保連結目標仍在該技能資料夾內。"""
    try:
        return path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise BackupError(f"技能含有指向資料夾外或失效的捷徑：{path}") from exc


def _private_name(path: Path) -> bool:
    """辨認不應上傳的憑證檔名。"""
    name = path.name.lower()
    return name in PRIVATE_FILE_NAMES or name == ".env" or name.startswith(".env.") or path.suffix.lower() in PRIVATE_SUFFIXES


def _git_root(root: Path) -> Path | None:
    """找出技能所在的 Git 工作區，避免把忽略的工作產物當成技能。"""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _git_visible(root: Path) -> list[Path] | None:
    """Git 專案只備份追蹤中與未忽略的新檔，避開大量執行產物。"""
    if _git_root(root) is None:
        return None
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
        capture_output=True, check=False, timeout=30,
    )
    if listed.returncode != 0:
        raise BackupError(f"無法查明 Git 專案應備份的檔案：{root}")
    return sorted({Path(os.fsdecode(raw)) for raw in listed.stdout.split(b"\0") if raw}, key=str)


def _files(root: Path, expand_external: bool = True, rules: Rules | None = None,
           skill: str | None = None, prefix: Path = Path()) -> tuple[list[tuple[Path, Path, bool]], list[str], list[str], str, list[str], list[str]]:
    """列出完整技能內容，並禁止追蹤技能資料夾外的捷徑。

    skill 與 prefix 用來把依賴資料夾內的路徑換算回「技能內相對路徑」，讓排除規則一致。
    """
    rules = rules or Rules()
    skill = skill or root.name
    found: list[tuple[Path, Path, bool]] = []
    excluded: list[str] = []
    excluded_sensitive: list[str] = []
    expanded_links: list[str] = []
    missing_paths: list[str] = []
    git_visible = _git_visible(root)
    if git_visible is not None:
        repository_root = _git_root(root)
        assert repository_root is not None
        for relative in git_visible:
            path = root / relative
            if not path.exists() and not path.is_symlink():
                missing_paths.append(str(relative))
                continue
            if any(part in SKIP_NAMES for part in relative.parts) or path.name.endswith(".pyc") or rules.excludes(skill, prefix / relative):
                excluded.append(str(relative))
                continue
            if _private_name(path):
                excluded_sensitive.append(str(relative))
                continue
            if path.is_symlink():
                target = path.resolve(strict=True)
                if not target.is_relative_to(root):
                    if not expand_external or not target.is_relative_to(repository_root):
                        raise BackupError(f"技能含有指向安全範圍外的捷徑：{path}")
                    expanded_links.append(str(relative))
                    if target.is_dir():
                        dependency_files, _, dependency_sensitive, _, _, _ = _files(
                            target, expand_external=False, rules=rules, skill=skill, prefix=prefix / relative,
                        )
                        excluded_sensitive.extend(str(relative / entry) for entry in dependency_sensitive)
                        for dependency, nested_relative, _ in dependency_files:
                            resolved_dependency = dependency.resolve(strict=True)
                            if not resolved_dependency.is_file() or not resolved_dependency.is_relative_to(repository_root):
                                raise BackupError(f"技能依賴的捷徑無法安全備份：{dependency}")
                            found.append((resolved_dependency, relative / nested_relative, False))
                    elif target.is_file():
                        found.append((target, relative, False))
                    else:
                        raise BackupError(f"技能捷徑目標不是一般檔案或資料夾：{path}")
                    continue
            elif not path.is_file():
                raise BackupError(f"Git 清單中有無法備份的路徑：{path}")
            found.append((path, relative, path.is_symlink()))
        return found, sorted(excluded), sorted(excluded_sensitive), "git-visible", sorted(expanded_links), sorted(missing_paths)
    for current, directories, files in os.walk(root, followlinks=False):
        base = Path(current)
        for name in list(directories):
            path = base / name
            if name in SKIP_NAMES or rules.excludes(skill, prefix / path.relative_to(root)):
                excluded.append(str(path.relative_to(root)))
                directories.remove(name)
                continue
            if path.is_symlink():
                _relative(path, root)
                found.append((path, path.relative_to(root), True))
                directories.remove(name)
        for name in files:
            if name in SKIP_NAMES or name.endswith(".pyc"):
                excluded.append(str((base / name).relative_to(root)))
                continue
            path = base / name
            if _private_name(path):
                excluded_sensitive.append(str(path.relative_to(root)))
                continue
            if path.is_symlink():
                _relative(path, root)
            elif not path.is_file():
                raise BackupError(f"技能含有無法備份的特殊檔案：{path}")
            found.append((path, path.relative_to(root), path.is_symlink()))
    return sorted(found, key=lambda entry: str(entry[1])), sorted(excluded), sorted(excluded_sensitive), "filesystem", expanded_links, missing_paths


def _check_content(path: Path, data: bytes, rules: Rules | None = None,
                   skill: str = "", relative: Path | None = None) -> None:
    """以保守規則阻止已知憑證；不把命中的內容寫入日誌。"""
    rules = rules or Rules()
    if _private_name(path):
        raise BackupError(f"疑似敏感檔案，已停止上傳：{path}")
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(data):
            raise BackupError(f"疑似{label}，已停止上傳：{path}")
    for match in ASSIGNMENT.finditer(data):
        raw_value = next(group for group in match.groups() if group is not None)
        # 精準放行已確認的測試假值（技能名稱、技能內相對路徑與字串都必須完全相符）。
        if rules.allows(skill, relative, raw_value):
            continue
        value = raw_value.lower()
        environment_variable = re.fullmatch(rb"[A-Z][A-Z0-9_]*(?:PASSWORD|TOKEN|KEY|SECRET)", raw_value)
        documented_dummy = b"no-key-required" in value
        documented_reference = b"runtime" in value and b"from" in value and b"token" in value
        code_identifier = match.group(3) is not None and re.fullmatch(rb"[A-Za-z_][A-Za-z_0-9]*", raw_value)
        if not value.startswith(PLACEHOLDER_PREFIXES) and not environment_variable and not documented_dummy and not documented_reference and not code_identifier:
            raise BackupError(f"疑似憑證設定值，已停止上傳：{path}")


def _read_checked(path: Path, rules: Rules | None = None, skill: str = "",
                  relative: Path | None = None) -> tuple[bytes, str]:
    """讀取與檢查單一檔案，避免把大型或敏感檔案放進快照。"""
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise BackupError(f"檔案超過 {MAX_FILE_BYTES // 1024 // 1024} MiB，已停止上傳：{path}")
    data = path.read_bytes()
    _check_content(path, data, rules, skill, relative)
    return data, hashlib.sha256(data).hexdigest()


def _skill_name(item: dict, root: Path) -> str:
    """以可讀名稱及來源雜湊避免同名技能互相覆蓋。"""
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip(".-") or "skill"
    source_id = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    return f"{label}-{source_id}"


def export(items: dict, destination: Path | None, include_builtin: bool = False,
           rules: Rules | None = None) -> dict:
    """檢查所有候選技能後才建立快照；有一項失敗就不交付部分備份。

    rules 未指定時依設定檔順序載入（見 load_rules），讓既有呼叫端不必修改也會套用本機設定。
    """
    rules = rules if rules is not None else load_rules()
    selected: list[tuple[dict, Path]] = []
    omitted_builtin = 0
    for item in items.values():
        if item.get("kind") != "skill":
            continue
        if item.get("source") == "builtin" and not include_builtin:
            omitted_builtin += 1
            continue
        skill_file = Path(item["realPath"]).expanduser().resolve(strict=True)
        if skill_file.name != "SKILL.md" or not skill_file.is_file():
            raise BackupError(f"盤點中的技能檔案已移動或不符合格式：{item.get('path', '')}")
        selected.append((item, skill_file.parent))
    selected.sort(key=lambda entry: str(entry[1]))

    manifest = {
        "formatVersion": 1,
        "scanner": "agent-inventory",
        "includeBuiltin": include_builtin,
        "omittedBuiltin": omitted_builtin,
        "skills": [],
    }
    seen: set[Path] = set()
    total_bytes = 0
    copied: list[tuple[Path, Path, str | None, str, Path]] = []
    for item, root in selected:
        if root in seen:
            continue
        seen.add(root)
        skill_id = _skill_name(item, root)
        records = []
        files, excluded, excluded_sensitive, selection_policy, expanded_links, missing_paths = _files(root, rules=rules)
        if not any(relative == Path("SKILL.md") for _, relative, _ in files):
            raise BackupError(f"技能主檔被忽略或不可讀，已停止備份：{root}")
        for source, relative, is_link in files:
            if is_link:
                target = _relative(source, root)
                records.append({"path": str(relative), "linkTo": str(target)})
                copied.append((source, Path(skill_id) / relative, None, root.name, relative))
                continue
            data, digest = _read_checked(source, rules, root.name, relative)
            total_bytes += len(data)
            if total_bytes > MAX_TOTAL_BYTES:
                raise BackupError("技能總量超過 2 GiB，已停止上傳。")
            records.append({"path": str(relative), "sha256": digest, "bytes": len(data)})
            copied.append((source, Path(skill_id) / relative, digest, root.name, relative))
        manifest["skills"].append({
            "id": skill_id,
            "name": item.get("name", root.name),
            "source": item.get("source", "user"),
            "tools": item.get("tools", []),
            "sourcePath": str(root),
            "installedPaths": item.get("paths", {}),
            "files": records,
            "excludedPaths": excluded,
            "excludedSensitivePaths": excluded_sensitive,
            "selectionPolicy": selection_policy,
            "expandedLinks": expanded_links,
            "missingPaths": missing_paths,
        })

    manifest["skillCount"] = len(manifest["skills"])
    manifest["totalBytes"] = total_bytes
    if destination is None:
        return manifest
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise BackupError(f"輸出位置已存在，避免覆寫：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".skill-backup-", dir=destination.parent) as temp:
        staging = Path(temp) / "snapshot"
        for source, relative, expected_digest, skill_name, skill_relative_path in copied:
            target = staging / "skills" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if expected_digest is None:
                # 內部捷徑改成相對路徑，還原至其他電腦時仍可使用。
                skill_relative = Path(*relative.parts[1:])
                original_root = source.parents[len(skill_relative.parts) - 1]
                link_target = _relative(source, original_root)
                installed_root = staging / "skills" / relative.parts[0]
                target.symlink_to(os.path.relpath(installed_root / link_target, target.parent))
            else:
                data, current_digest = _read_checked(source, rules, skill_name, skill_relative_path)
                if current_digest != expected_digest:
                    raise BackupError(f"檢查後檔案內容變動，已停止備份：{source}")
                target.write_bytes(data)
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staging.rename(destination)
    return manifest


def verify_snapshot(destination: Path) -> dict:
    """從快照讀回每個檔案與捷徑，確認內容仍與清單一致。"""
    destination = destination.expanduser().resolve(strict=True)
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    skills = manifest.get("skills")
    if not isinstance(skills, list) or len(skills) != manifest.get("skillCount"):
        raise BackupError("快照清單的技能數量不一致。")
    for skill in skills:
        root = destination / "skills" / skill["id"]
        if not (root / "SKILL.md").is_file():
            raise BackupError(f"快照缺少技能主檔：{skill['id']}")
        for record in skill["files"]:
            path = root / record["path"]
            if "linkTo" in record:
                if not path.is_symlink() or path.resolve(strict=True) != (root / record["linkTo"]).resolve(strict=True):
                    raise BackupError(f"快照捷徑讀回不一致：{skill['id']}/{record['path']}")
            elif not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                raise BackupError(f"快照檔案讀回不一致：{skill['id']}/{record['path']}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="全新且尚不存在的快照目錄")
    parser.add_argument("--include-builtin", action="store_true", help="同時備份工具內建技能")
    parser.add_argument("--check", action="store_true", help="只重新掃描與檢查，不寫出快照")
    parser.add_argument("--verify", type=Path, help="讀回並核對既有快照，不重新掃描")
    parser.add_argument("--config", type=Path, help=f"備份設定 JSON（預設依序找 ${CONFIG_ENV}、config/backup_skills.json、~/.config/agent-inventory/backup_skills.json）")
    args = parser.parse_args()
    if not args.check and args.output is None and args.verify is None:
        parser.error("請指定 --output，或使用 --check")
    try:
        if args.verify:
            result = verify_snapshot(args.verify)
        else:
            cfg = scan.load_config(argparse.Namespace(roots=None, tools=None, depth=None))
            current = scan.run(cfg, usage={})
            rules = load_rules(args.config)
            print(f"備份設定：{rules.source}（允許 {len(rules.allowed)} 筆、排除 {len(rules.excluded)} 筆）")
            result = export(current["items"], None if args.check else args.output, args.include_builtin, rules)
            if args.output:
                verify_snapshot(args.output)
    except (BackupError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"backup failed：{exc}", file=sys.stderr)
        return 1
    print(f"技能檢查完成：{result['skillCount']} 個技能、{result['totalBytes']} 位元組；略過內建 {result['omittedBuiltin']} 個。")
    if args.output:
        print(f"快照讀回驗證完成：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
