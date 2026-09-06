#!/usr/bin/env python3
"""Merge agent-written summaries into the inventory and the summary cache.

The inventory-summarize skill writes files to data/summaries/*.json, each either
  {"<itemId>": "summary text", ...}      or      [{"id": "...", "summary": "..."}, ...]
This script folds them into data/summary-cache.json (keyed by content hash, so they survive re-scans),
updates data/inventory.json in place, rewrites data/pending-summaries.json, and moves processed files to data/summaries/done/.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"


def load_batches() -> tuple[dict[str, str], list[Path]]:
    merged: dict[str, str] = {}
    files = sorted(p for p in (DATA / "summaries").glob("*.json") if p.is_file())
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"略過 {f.name}：JSON 解析失敗（{e}）", file=sys.stderr)
            continue
        if isinstance(data, dict):
            merged.update({k: str(v).strip() for k, v in data.items() if str(v).strip()})
        elif isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and row.get("id") and str(row.get("summary", "")).strip():
                    merged[row["id"]] = str(row["summary"]).strip()
    return merged, files


def main():
    inv_path = DATA / "inventory.json"
    if not inv_path.is_file():
        sys.exit("找不到 data/inventory.json，請先執行 bin/scan.py")
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    cache_path = DATA / "summary-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    summaries, files = load_batches()

    applied, unknown = 0, []
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for iid, text in summaries.items():
        item = inv["items"].get(iid) or inv.get("projects", {}).get(iid)
        if not item:
            unknown.append(iid)
            continue
        item["summary"] = text
        item["summarySource"] = "agent"
        if item.get("hash"):
            cache[item["hash"]] = {"summary": text, "source": "agent", "at": now, "name": item["name"]}
        applied += 1

    pending = [i for i in list(inv["items"].values()) + list(inv.get("projects", {}).values()) if i.get("summarySource") == "pending"]
    inv["stats"]["pending"] = len(pending)
    inv_path.write_text(json.dumps(inv, ensure_ascii=False, indent=1), encoding="utf-8")
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    pend_path = DATA / "pending-summaries.json"
    if pend_path.is_file():
        old = json.loads(pend_path.read_text(encoding="utf-8"))
        pend_path.write_text(json.dumps([p for p in old if p["id"] not in summaries], ensure_ascii=False, indent=1), encoding="utf-8")

    done = DATA / "summaries" / "done"
    done.mkdir(parents=True, exist_ok=True)
    for f in files:
        f.rename(done / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{f.name}")

    print(f"已套用 {applied} 筆摘要，快取共 {len(cache)} 筆，尚待補 {len(pending)} 筆。")
    if unknown:
        print(f"有 {len(unknown)} 個 id 在 inventory 裡找不到（可能已重新掃描）：{', '.join(unknown[:5])}", file=sys.stderr)


if __name__ == "__main__":
    main()
