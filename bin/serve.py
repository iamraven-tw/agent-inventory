#!/usr/bin/env python3
"""Serve the inventory website locally (no build step, no dependencies).

Usage:
  python3 bin/serve.py              # http://localhost:8765/site/ and open the browser
  python3 bin/serve.py --port 9000 --no-open
"""
from __future__ import annotations

import argparse
import json
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


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
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
