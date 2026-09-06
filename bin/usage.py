#!/usr/bin/env python3
"""Collect skill / project usage signals from local agent logs into data/usage.json.

Sources (all read-only, all local):
  claude-code  ~/.claude/history.jsonl (prompt → cwd, time)  +  ~/.claude/projects/**/*.jsonl (Skill tool calls, SKILL.md reads)
  codex        ~/.codex/sessions/**/*.jsonl (session_meta cwd, SKILL.md reads)  +  ~/.codex/history.jsonl ($skill mentions)
  hermes       ~/.hermes/state.db (sessions.cwd, skill_view tool calls)
  antigravity  no attributable log found yet → reported as unavailable

Large transcript files are cached by (size, mtime) in data/usage-cache.json so re-runs only parse changed files.
Usage:  python3 bin/usage.py            (scan.py calls this automatically unless --no-usage)
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
HOME = Path.home()

SKILL_PATH_RE = re.compile(r"skills/([A-Za-z0-9._-]+)/SKILL\.md")
SKILL_CALL_RE = re.compile(r'"skill"\s*:\s*"([^"]+)"')
TS_RE = re.compile(r'"timestamp"\s*:\s*"([^"]+)"')


def iso(ts: float | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_iso(s: str) -> float | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


class Tally:
    def __init__(self):
        self.skills: dict[str, dict[str, dict]] = {}
        self.cwds: dict[str, dict[str, dict]] = {}
        self.sources: dict[str, dict] = {}

    @staticmethod
    def _bump(bucket: dict, key: str, tool: str, ts: float | None, n: int = 1):
        rec = bucket.setdefault(key, {}).setdefault(tool, {"count": 0, "last": 0.0})
        rec["count"] += n
        if ts and ts > rec["last"]:
            rec["last"] = ts

    def skill(self, name: str, tool: str, ts: float | None, n: int = 1):
        name = name.split(":")[-1].strip()  # "superpowers:brainstorming" → "brainstorming"
        if name:
            self._bump(self.skills, name, tool, ts, n)

    def cwd(self, path: str, tool: str, ts: float | None, n: int = 1):
        if path:
            self._bump(self.cwds, path, tool, ts, n)

    def merge_file_result(self, tool: str, res: dict):
        for name, rec in res.get("skills", {}).items():
            self._bump(self.skills, name, tool, rec.get("last"), rec.get("count", 1))
        for path, rec in res.get("cwds", {}).items():
            self._bump(self.cwds, path, tool, rec.get("last"), rec.get("count", 1))


# ---------------------------------------------------------------- file cache

CACHE_VERSION = 4  # bump whenever a parser changes, so cached per-file results are rebuilt


def load_cache() -> dict:
    p = DATA / "usage-cache.json"
    try:
        c = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except json.JSONDecodeError:
        c = {}
    if c.get("version") != CACHE_VERSION:
        c = {"version": CACHE_VERSION, "files": {}}
    return c


def save_cache(cache: dict):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "usage-cache.json").write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def cached_parse(cache: dict, path: Path, parser) -> dict:
    try:
        st = path.stat()
    except OSError:
        return {}
    key = str(path)
    ent = cache["files"].get(key)
    if ent and ent.get("size") == st.st_size and ent.get("mtime") == st.st_mtime:
        return ent["result"]
    result = parser(path)
    cache["files"][key] = {"size": st.st_size, "mtime": st.st_mtime, "result": result}
    return result


def _local_tally():
    return {"skills": {}, "cwds": {}}


def _local_bump(res: dict, kind: str, key: str, ts: float | None):
    rec = res[kind].setdefault(key, {"count": 0, "last": 0.0})
    rec["count"] += 1
    if ts and ts > rec["last"]:
        rec["last"] = ts


# ---------------------------------------------------------------- collectors

def collect_claude(t: Tally, cache: dict):
    home = HOME / ".claude"
    if not home.is_dir():
        t.sources["claude-code"] = {"available": False, "note": "找不到 ~/.claude"}
        return
    events = 0
    hist = home / "history.jsonl"
    if hist.is_file():
        with hist.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                raw = str(d.get("timestamp", ""))
                ts = float(raw) / 1000 if raw.isdigit() else None
                t.cwd(d.get("project", ""), "claude-code", ts)
                events += 1

    cwd_re = re.compile(r'"cwd"\s*:\s*"([^"]+)"')

    def parse_transcript(path: Path) -> dict:
        """One transcript = one session: its cwd counts once, with the session's last timestamp."""
        res = _local_tally()
        cwd, last_ts = None, None
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if cwd is None:
                    m_cwd = cwd_re.search(line)
                    if m_cwd:
                        cwd = m_cwd.group(1)
                m_ts = TS_RE.search(line)
                ts = parse_iso(m_ts.group(1)) if m_ts else None
                if ts and (last_ts is None or ts > last_ts):
                    last_ts = ts
                # Only actual tool calls count: the Skill tool, or a Read of a SKILL.md file.
                # Prompts and system reminders that merely list skill paths must not count as usage.
                if '"name":"Skill"' in line:
                    for m in SKILL_CALL_RE.finditer(line):
                        _local_bump(res, "skills", m.group(1).split(":")[-1], ts)
                elif '"name":"Read"' in line and "SKILL.md" in line:
                    for m in SKILL_PATH_RE.finditer(line):
                        _local_bump(res, "skills", m.group(1), ts)
        if cwd:
            _local_bump(res, "cwds", cwd, last_ts)
        return res

    for tr in sorted((home / "projects").glob("*/*.jsonl")):
        res = cached_parse(cache, tr, parse_transcript)
        t.merge_file_result("claude-code", res)
        events += sum(r["count"] for r in res.get("skills", {}).values())
    t.sources["claude-code"] = {"available": True, "note": "history.jsonl 的提問 cwd 與逐字稿裡的 Skill 呼叫、SKILL.md 讀取", "events": events}


def collect_codex(t: Tally, cache: dict):
    home = HOME / ".codex"
    if not home.is_dir():
        t.sources["codex"] = {"available": False, "note": "找不到 ~/.codex"}
        return
    events = 0

    def parse_session(path: Path) -> dict:
        res = _local_tally()
        session_ts = None
        with path.open(encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i == 0 or '"session_meta"' in line[:200]:
                    try:
                        d = json.loads(line)
                        if d.get("type") == "session_meta":
                            pl = d.get("payload", {})
                            session_ts = parse_iso(pl.get("timestamp") or d.get("timestamp") or "")
                            if pl.get("cwd"):
                                _local_bump(res, "cwds", pl["cwd"], session_ts)
                            continue
                    except json.JSONDecodeError:
                        pass
                if "SKILL.md" in line:
                    # Only real tool invocations count (a shell command or function call that reads the file).
                    # world_state / message / compacted records list every installed skill and would inflate counts.
                    if '"response_item"' not in line[:160] or ('"custom_tool_call"' not in line and '"function_call"' not in line):
                        continue
                    m_ts = TS_RE.search(line)
                    ts = parse_iso(m_ts.group(1)) if m_ts else session_ts
                    for m in SKILL_PATH_RE.finditer(line):
                        _local_bump(res, "skills", m.group(1), ts)
        # a session counts each skill once, however many times it re-read the file
        for rec in res["skills"].values():
            rec["count"] = 1
        return res

    for s in sorted((home / "sessions").rglob("*.jsonl")):
        res = cached_parse(cache, s, parse_session)
        t.merge_file_result("codex", res)
        events += 1
    hist = home / "history.jsonl"
    if hist.is_file():
        with hist.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if "$" not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = d.get("ts")
                for m in re.finditer(r"\$([a-z0-9][a-z0-9-]+)", d.get("text", "")):
                    t.skill(m.group(1), "codex", float(ts) if ts else None)
    t.sources["codex"] = {"available": True, "note": "sessions 的 cwd 與 SKILL.md 讀取、history.jsonl 的 $skill 提及", "events": events}


def collect_hermes(t: Tally, cache: dict):
    db = HOME / ".hermes" / "state.db"
    if not db.is_file():
        t.sources["hermes"] = {"available": False, "note": "找不到 ~/.hermes/state.db"}
        return
    events = 0
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        for cwd, started in con.execute("select cwd, started_at from sessions where cwd is not null and cwd != ''"):
            t.cwd(cwd, "hermes", float(started) if started else None)
            events += 1
        for tc, ts in con.execute("select tool_calls, timestamp from messages where tool_calls like '%skill_view%'"):
            try:
                calls = json.loads(tc)
            except (json.JSONDecodeError, TypeError):
                continue
            for c in calls if isinstance(calls, list) else []:
                fn = (c.get("function") or {})
                if fn.get("name") != "skill_view":
                    continue
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    continue
                if args.get("name"):
                    t.skill(args["name"], "hermes", float(ts) if ts else None)
                    events += 1
        con.close()
        t.sources["hermes"] = {"available": True, "note": "state.db 的 sessions.cwd 與 skill_view 呼叫", "events": events}
    except sqlite3.Error as e:
        t.sources["hermes"] = {"available": False, "note": f"讀取 state.db 失敗：{e}"}


def collect_antigravity(t: Tally, cache: dict):
    conv = HOME / ".gemini" / "antigravity" / "conversations"
    n = len(list(conv.glob("*.db"))) if conv.is_dir() else 0
    t.sources["antigravity"] = {"available": False, "note": "對話存成二進位資料庫，目前無法對應到專案或技能" + (f"（{n} 個對話）" if n else "")}


COLLECTORS = {"claude-code": collect_claude, "codex": collect_codex, "hermes": collect_hermes, "antigravity": collect_antigravity}


def collect(tools: list[str] | None = None) -> dict:
    t = Tally()
    cache = load_cache()
    for tool in tools or list(COLLECTORS) + ["cursor", "openclaw"]:
        fn = COLLECTORS.get(tool)
        if fn:
            try:
                fn(t, cache)
            except Exception as e:  # a broken log must never kill the scan
                t.sources[tool] = {"available": False, "note": f"收集失敗：{e}"}
        else:
            t.sources[tool] = {"available": False, "note": "尚未實作使用紀錄來源"}
    save_cache(cache)

    def fmt(bucket):
        return {k: {tool: {"count": r["count"], "last": iso(r["last"])} for tool, r in v.items()} for k, v in bucket.items()}

    out = {"generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"), "sources": t.sources,
           "skills": fmt(t.skills), "cwds": fmt(t.cwds)}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "usage.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    import time
    t0 = time.time()
    out = collect(sys.argv[1].split(",") if len(sys.argv) > 1 else None)
    print(f"usage.json 寫入完成（{time.time() - t0:.1f} 秒）")
    for tool, s in out["sources"].items():
        print(f"  {tool:<12} {'✓' if s['available'] else '✗'} {s.get('events', '')} {s['note']}")
    print(f"  技能名稱 {len(out['skills'])} 個、工作目錄 {len(out['cwds'])} 個")
