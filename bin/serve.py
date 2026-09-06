#!/usr/bin/env python3
"""Serve the inventory website locally (no build step, no dependencies).

Usage:
  python3 bin/serve.py              # http://localhost:8765/site/ and open the browser
  python3 bin/serve.py --port 9000 --no-open
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"


def lookup_path(item_id: str) -> Path | None:
    """Only files listed in inventory.json may be opened — the id is the whitelist."""
    try:
        inv = json.loads((DATA / "inventory.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    rec = inv.get("items", {}).get(item_id) or inv.get("projects", {}).get(item_id)
    if not rec:
        return None
    raw = rec.get("realPath") or rec.get("path")
    if not raw:
        return None
    p = Path(raw.replace("~", str(Path.home()), 1) if raw.startswith("~") else raw)
    return p if p.exists() else None


def open_with(path: Path, how: str) -> tuple[bool, str]:
    """Open a file with the OS text editor / file manager / VS Code / Cursor. Returns (ok, message)."""
    system = platform.system()
    try:
        if how == "editor":  # 系統內建純文字編輯器
            if system == "Darwin":
                subprocess.Popen(["open", "-e", str(path)])
            elif system == "Windows":
                subprocess.Popen(["notepad.exe", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        elif how == "reveal":  # Finder / 檔案總管
            if system == "Darwin":
                subprocess.Popen(["open", "-R", str(path)])
            elif system == "Windows":
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        elif how in ("vscode", "cursor"):
            cli = "code" if how == "vscode" else "cursor"
            if system == "Darwin":
                app = "Visual Studio Code" if how == "vscode" else "Cursor"
                subprocess.Popen(["open", "-a", app, str(path)])
            else:
                subprocess.Popen([cli, str(path)], shell=(system == "Windows"))
        else:
            return False, f"未知的開啟方式：{how}"
        return True, "ok"
    except (OSError, FileNotFoundError) as e:
        return False, str(e)


def load_inventory() -> dict:
    try:
        return json.loads((DATA / "inventory.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def expand_home(raw: str) -> Path:
    return Path(raw.replace("~", str(Path.home()), 1) if raw.startswith("~") else raw)


def send_to_trash(path: Path) -> tuple[bool, str]:
    """Move a file or directory to the OS trash (reversible). Symlinks are unlinked, never followed."""
    system = platform.system()
    try:
        if path.is_symlink():
            path.unlink()
            return True, "unlinked"
        if not path.exists():
            return False, "不存在"
        if system == "Darwin":
            script = f'tell application "Finder" to delete POSIX file "{str(path).replace(chr(34), chr(92) + chr(34))}"'
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
            return (r.returncode == 0), (r.stderr.strip() or "trashed")
        if system == "Windows":
            kind = "DeleteDirectory" if path.is_dir() else "DeleteFile"
            ps = (f"Add-Type -AssemblyName Microsoft.VisualBasic; "
                  f"[Microsoft.VisualBasic.FileIO.FileSystem]::{kind}('{str(path).replace(chr(39), chr(39) * 2)}', 'OnlyErrorDialogs', 'SendToRecycleBin')")
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30)
            return (r.returncode == 0), (r.stderr.strip() or "recycled")
        r = subprocess.run(["gio", "trash", str(path)], capture_output=True, text=True, timeout=30)
        return (r.returncode == 0), (r.stderr.strip() or "trashed")
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def delete_targets(rec: dict, kind: str, include_target: bool) -> list[Path]:
    """All filesystem paths a delete should touch: every tool's link/path, plus the real target when requested."""
    seen: list[Path] = []

    def add(p: Path):
        if p not in seen:
            seen.append(p)

    if kind == "project":
        add(expand_home(rec.get("realPath") or rec["path"]))
        return seen
    paths = list((rec.get("paths") or {}).values()) or [rec["path"]]
    candidates: list[Path] = []
    for raw in paths:
        p = expand_home(raw)
        candidates.append(p.parent if rec["kind"] == "skill" else p)  # a skill is its folder; a rule is the file
    real = None
    if rec.get("realPath"):
        rp = expand_home(rec["realPath"])
        real = (rp.parent if rec["kind"] == "skill" else rp).resolve()
    # Three ways to reach the same thing: (a) the item itself is a symlink → unlink it; (b) the real path → trash once;
    # (c) a path that merely goes through a symlinked parent (e.g. .claude/skills -> ../.agents/skills) → same object as (b), skip.
    for c in candidates:
        if c.is_symlink():
            add(c)
    if include_target and real is not None:
        add(real)
    elif not include_target and real is not None and not any(c.is_symlink() for c in candidates):
        add(real)  # nothing to unlink, the only thing that exists is the real file
    return seen


def rescan():
    """Re-run the scanner in-process so the site reflects the deletion immediately."""
    sys.path.insert(0, str(REPO / "bin"))
    import scan  # noqa: WPS433
    cfg = scan.load_config(type("A", (), {"roots": None, "tools": None, "depth": None})())
    usage_path = DATA / "usage.json"
    usage = json.loads(usage_path.read_text(encoding="utf-8")) if usage_path.is_file() else {}
    result = scan.run(cfg, usage)
    pending = result.pop("_pending")
    pending_flows = result.pop("_pendingFlows")
    (DATA / "inventory.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "pending-summaries.json").write_text(json.dumps(pending, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "pending-flows.json").write_text(json.dumps(pending_flows, ensure_ascii=False, indent=1), encoding="utf-8")
    return result["stats"]


def folder_info(path: Path, cap: int = 200000) -> dict:
    files, size = 0, 0
    for root, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
        for n in names:
            files += 1
            try:
                size += (Path(root) / n).stat().st_size
            except OSError:
                pass
            if files >= cap:
                return {"files": files, "bytes": size, "capped": True}
    return {"files": files, "bytes": size, "capped": False}


import hashlib
from datetime import datetime

BACKUPS = DATA / "backups"
USER_SUMMARIES = DATA / "user-summaries.json"
KEEP_BACKUPS = 10


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def editable_path(rec: dict) -> Path | None:
    """The real file behind an item (symlinks resolved), so one save reaches every tool that shares it."""
    raw = rec.get("realPath") or rec.get("path")
    if not raw:
        return None
    p = expand_home(raw)
    return p if p.is_file() else None


def backup(path: Path, item_id: str):
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (BACKUPS / f"{item_id}-{stamp}{path.suffix or '.md'}").write_bytes(path.read_bytes())
    olds = sorted(BACKUPS.glob(f"{item_id}-*"))
    for old in olds[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)


def load_user_summaries() -> dict:
    try:
        return json.loads(USER_SUMMARIES.read_text(encoding="utf-8")) if USER_SUMMARIES.is_file() else {}
    except json.JSONDecodeError:
        return {}


class Handler(SimpleHTTPRequestHandler):
    def do_OPTIONS(self):  # no CORS headers → cross-origin pages cannot call the mutating endpoints
        self.send_response(403)
        self.end_headers()

    def do_POST(self):
        u = urlparse(self.path)
        if u.path not in ("/api/delete", "/api/save", "/api/summary", "/api/flow"):
            return self._json(404, {"ok": False, "error": "not found"})
        if self.headers.get("X-Requested-With") != "agent-inventory" or "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._json(400, {"ok": False, "error": "缺少必要標頭"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"ok": False, "error": "JSON 格式錯誤"})
        inv = load_inventory()
        if u.path == "/api/save":
            return self._save(inv, body)
        if u.path == "/api/summary":
            return self._summary(inv, body)
        if u.path == "/api/flow":
            return self._flow(inv, body)
        item_id = str(body.get("id", ""))
        rec = inv.get("items", {}).get(item_id)
        kind = "item"
        if rec is None:
            rec = inv.get("projects", {}).get(item_id)
            kind = "project"
        if rec is None or rec.get("kind") == "note":
            return self._json(404, {"ok": False, "error": "找不到這個項目"})
        if str(body.get("confirm", "")).strip() != rec["name"]:
            return self._json(400, {"ok": False, "error": "確認名稱不符，未刪除"})
        targets = delete_targets(rec, kind, bool(body.get("includeTarget", True)))
        results = []
        for p in targets:
            ok, msg = send_to_trash(p)
            results.append({"path": str(p), "ok": ok, "message": msg})
        try:
            stats = rescan()
        except Exception as e:  # deletion happened; report even if rescan failed
            stats = {"error": str(e)}
        return self._json(200, {"ok": all(r["ok"] for r in results), "results": results, "stats": stats})

    def _save(self, inv: dict, body: dict):
        item_id = str(body.get("id", ""))
        rec = inv.get("items", {}).get(item_id)
        if not rec or rec.get("kind") == "note":
            return self._json(404, {"ok": False, "error": "找不到這個項目"})
        path = editable_path(rec)
        if path is None:
            return self._json(404, {"ok": False, "error": "檔案已不存在"})
        current = path.read_bytes()
        if body.get("hash") and body["hash"] != file_hash(current):
            return self._json(409, {"ok": False, "error": "這個檔案在你開始編輯後被其他程式改過了。請重新載入再改，避免覆蓋別人的修改。", "hash": file_hash(current)})
        content = body.get("content")
        if not isinstance(content, str):
            return self._json(400, {"ok": False, "error": "缺少內容"})
        try:
            backup(path, item_id)
            path.write_text(content, encoding="utf-8")
        except OSError as e:
            return self._json(500, {"ok": False, "error": f"寫入失敗：{e}"})
        new_hash = file_hash(content.encode("utf-8"))
        try:
            stats = rescan()
        except Exception as e:
            stats = {"error": str(e)}
        return self._json(200, {"ok": True, "hash": new_hash, "path": str(path), "stats": stats})

    def _summary(self, inv: dict, body: dict):
        item_id = str(body.get("id", ""))
        rec = inv.get("items", {}).get(item_id) or inv.get("projects", {}).get(item_id)
        if not rec:
            return self._json(404, {"ok": False, "error": "找不到這個項目"})
        text = str(body.get("summary", "")).strip()
        us = load_user_summaries()
        if text:
            us[item_id] = {"summary": text, "at": datetime.now().astimezone().isoformat(timespec="seconds"), "name": rec.get("name")}
        else:
            us.pop(item_id, None)  # empty = hand it back to the agent
        DATA.mkdir(parents=True, exist_ok=True)
        USER_SUMMARIES.write_text(json.dumps(us, ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            stats = rescan()
        except Exception as e:
            stats = {"error": str(e)}
        return self._json(200, {"ok": True, "locked": bool(text), "stats": stats})

    def _flow(self, inv: dict, body: dict):
        item_id = str(body.get("id", ""))
        rec = inv.get("items", {}).get(item_id)
        if not rec or rec.get("kind") != "skill":
            return self._json(404, {"ok": False, "error": "找不到這個技能"})
        code = str(body.get("mermaid", "")).strip()
        if code and not any(code.startswith(k) for k in ("flowchart", "graph ", "sequenceDiagram", "stateDiagram")):
            return self._json(400, {"ok": False, "error": "Mermaid 必須以 flowchart 或 graph 開頭"})
        path = DATA / "user-flows.json"
        try:
            uf = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except json.JSONDecodeError:
            uf = {}
        if code:
            uf[item_id] = {"mermaid": code, "humanGates": [str(g).strip() for g in (body.get("humanGates") or []) if str(g).strip()],
                           "at": datetime.now().astimezone().isoformat(timespec="seconds"), "name": rec.get("name")}
        else:
            uf.pop(item_id, None)  # empty = hand it back to the agent
        DATA.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(uf, ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            stats = rescan()
        except Exception as e:
            stats = {"error": str(e)}
        return self._json(200, {"ok": True, "locked": bool(code), "stats": stats})

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/read":
            q = parse_qs(u.query)
            inv = load_inventory()
            rec = inv.get("items", {}).get(q.get("id", [""])[0])
            if not rec or rec.get("kind") == "note":
                return self._json(404, {"ok": False, "error": "找不到這個項目"})
            path = editable_path(rec)
            if path is None:
                return self._json(404, {"ok": False, "error": "檔案已不存在"})
            data = path.read_bytes()
            return self._json(200, {"ok": True, "path": str(path), "content": data.decode("utf-8", errors="replace"), "hash": file_hash(data),
                                    "sharedWith": rec.get("tools", [])})
        if u.path == "/api/info":
            q = parse_qs(u.query)
            inv = load_inventory()
            item_id = q.get("id", [""])[0]
            rec = inv.get("items", {}).get(item_id) or inv.get("projects", {}).get(item_id)
            if not rec:
                return self._json(404, {"ok": False, "error": "找不到這個項目"})
            kind = "project" if item_id.startswith("proj-") else "item"
            targets = delete_targets(rec, kind, True)
            out = {"ok": True, "targets": [{"path": str(p), "symlink": p.is_symlink(), "isDir": p.is_dir(), "exists": p.exists() or p.is_symlink()} for p in targets]}
            if kind == "project":
                out["info"] = folder_info(expand_home(rec.get("realPath") or rec["path"]))
            return self._json(200, out)
        if u.path == "/api/open":
            q = parse_qs(u.query)
            item_id, how = q.get("id", [""])[0], q.get("with", ["editor"])[0]
            path = lookup_path(item_id)
            if path is None:
                return self._json(404, {"ok": False, "error": "找不到這個項目，或檔案已不存在"})
            ok, msg = open_with(path, how)
            return self._json(200 if ok else 500, {"ok": ok, "message": msg, "path": str(path)})
        return super().do_GET()

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):  # quieter console
        if "inventory.json" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    if not (REPO / "data" / "inventory.json").is_file():
        print("找不到 data/inventory.json，請先執行 bin/scan.py。", file=sys.stderr)
    handler = partial(Handler, directory=str(REPO))
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except OSError as e:
        sys.exit(f"無法綁定 port {args.port}：{e}。可用 --port 換一個。")
    url = f"http://localhost:{args.port}/site/"
    print(f"agent-inventory 網站：{url}  （Ctrl+C 停止）")
    if not args.no_open:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
