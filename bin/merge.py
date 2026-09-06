#!/usr/bin/env python3
"""Merge agent-written summaries and flowcharts into the inventory and their caches.

Summaries — the inventory-summarize skill writes data/summaries/*.json, each either
  {"<itemId>": "summary text", ...}      or      [{"id": "...", "summary": "..."}, ...]

Flowcharts — the inventory-flow skill writes data/flows/*.json, each
  {"<skillId>": {"mermaid": "flowchart TD ...", "humanGates": ["..."]}, "<skillId2>": null, ...}
  A null (or an empty mermaid) records "checked, this skill has no multi-step workflow" so it stops
  showing up as pending.

Both are keyed by the file's content hash in data/summary-cache.json / data/flow-cache.json, so they
survive re-scans and are only rewritten when the underlying file actually changes. Anything the user
hand-edited on the website (data/user-summaries.json, data/user-flows.json) is never overwritten.
Processed batch files move to <dir>/done/.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
DIAGRAM_KEYWORDS = ("flowchart", "graph ", "sequenceDiagram", "stateDiagram")


def read_batches(dirname: str) -> tuple[dict, list[Path]]:
    """Read every JSON batch in data/<dirname>/ into one dict, newest file last."""
    merged: dict = {}
    files = sorted(p for p in (DATA / dirname).glob("*.json") if p.is_file())
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"略過 {f.name}：JSON 解析失敗（{e}）", file=sys.stderr)
            continue
        if isinstance(data, dict):
            merged.update(data)
        elif isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and row.get("id"):
                    merged[row["id"]] = row
    return merged, files


def archive(files: list[Path], dirname: str):
    if not files:
        return
    done = DATA / dirname / "done"
    done.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for f in files:
        f.rename(done / f"{stamp}-{f.name}")


def user_ids(filename: str) -> set:
    p = DATA / filename
    try:
        return set(json.loads(p.read_text(encoding="utf-8")).keys()) if p.is_file() else set()
    except json.JSONDecodeError:
        return set()


# ---------------------------------------------------------------- summaries

def apply_summaries(inv: dict) -> tuple[int, int, list, list[Path]]:
    raw, files = read_batches("summaries")
    summaries = {}
    for k, v in raw.items():
        text = str(v.get("summary", "") if isinstance(v, dict) else v).strip()
        if text:
            summaries[k] = text
    protected = user_ids("user-summaries.json")
    cache_path = DATA / "summary-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    applied, kept, unknown = 0, 0, []
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for iid, text in summaries.items():
        item = inv["items"].get(iid) or inv.get("projects", {}).get(iid)
        if not item:
            unknown.append(iid)
            continue
        if iid in protected:  # hand-edited on the website; agents never overwrite it
            kept += 1
            continue
        item["summary"] = text
        item["summarySource"] = "agent"
        if item.get("hash"):
            cache[item["hash"]] = {"summary": text, "source": "agent", "at": now, "name": item["name"]}
        applied += 1
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    prune_pending("pending-summaries.json", set(summaries))
    return applied, kept, unknown, files


# ---------------------------------------------------------------- flowcharts

def normalise_flow(value) -> tuple[dict | None, str]:
    """Accept {mermaid, humanGates} / a bare mermaid string / null. Returns (record or None, error)."""
    if value is None:
        return None, ""
    if isinstance(value, str):
        value = {"mermaid": value}
    if not isinstance(value, dict):
        return None, "格式不是物件或字串"
    code = str(value.get("mermaid") or "").strip()
    if not code:
        return None, ""  # explicitly "no workflow"
    if not any(code.lstrip().startswith(k) for k in DIAGRAM_KEYWORDS):
        return None, "mermaid 必須以 flowchart／graph 開頭"
    gates = [str(g).strip() for g in (value.get("humanGates") or []) if str(g).strip()]
    if gates and ":::human" not in code:
        print("  提醒：有 humanGates 但流程圖沒有任何 :::human 節點", file=sys.stderr)
    return {"mermaid": code, "humanGates": gates}, ""


def apply_flows(inv: dict) -> tuple[int, int, int, list, list[Path]]:
    raw, files = read_batches("flows")
    protected = user_ids("user-flows.json")
    cache_path = DATA / "flow-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    applied, none_marked, kept, unknown = 0, 0, 0, []
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for iid, value in raw.items():
        item = inv["items"].get(iid)
        if not item or item.get("kind") != "skill":
            unknown.append(iid)
            continue
        if iid in protected:
            kept += 1
            continue
        rec, err = normalise_flow(value)
        if err:
            print(f"略過 {item['name']}：{err}", file=sys.stderr)
            continue
        item["flow"] = rec
        item["flowSource"] = "agent" if rec else "none"
        if item.get("hash"):
            entry = {"mermaid": rec["mermaid"], "humanGates": rec["humanGates"]} if rec else {"mermaid": "", "humanGates": []}
            entry.update({"at": now, "name": item["name"]})
            cache[item["hash"]] = entry
        applied += 1 if rec else 0
        none_marked += 0 if rec else 1
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    prune_pending("pending-flows.json", set(raw))
    return applied, none_marked, kept, unknown, files


def prune_pending(filename: str, done_ids: set):
    p = DATA / filename
    if not p.is_file():
        return
    try:
        old = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    p.write_text(json.dumps([x for x in old if x.get("id") not in done_ids], ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    inv_path = DATA / "inventory.json"
    if not inv_path.is_file():
        sys.exit("找不到 data/inventory.json，請先執行 bin/scan.py")
    inv = json.loads(inv_path.read_text(encoding="utf-8"))

    s_applied, s_kept, s_unknown, s_files = apply_summaries(inv)
    f_applied, f_none, f_kept, f_unknown, f_files = apply_flows(inv)

    pending = [i for i in list(inv["items"].values()) + list(inv.get("projects", {}).values()) if i.get("summarySource") == "pending"]
    pending_flows = [i for i in inv["items"].values() if i.get("kind") == "skill" and i.get("flowSource") == "pending"]
    inv["stats"]["pending"] = len(pending)
    inv["stats"]["pendingFlows"] = len(pending_flows)
    inv["stats"]["withFlow"] = sum(1 for i in inv["items"].values() if i.get("flow"))
    inv_path.write_text(json.dumps(inv, ensure_ascii=False, indent=1), encoding="utf-8")

    archive(s_files, "summaries")
    archive(f_files, "flows")

    if s_files or s_applied:
        print(f"摘要：套用 {s_applied} 筆，尚待補 {len(pending)} 筆。" + (f" 另有 {s_kept} 筆是使用者手改的，保留不覆蓋。" if s_kept else ""))
    if f_files or f_applied or f_none:
        print(f"流程圖：套用 {f_applied} 筆，標記為無流程 {f_none} 筆，尚待補 {len(pending_flows)} 筆。" + (f" 另有 {f_kept} 筆是使用者手改的，保留不覆蓋。" if f_kept else ""))
    for label, unknown in (("摘要", s_unknown), ("流程圖", f_unknown)):
        if unknown:
            print(f"{label}有 {len(unknown)} 個 id 對不到（可能已重新掃描）：{', '.join(unknown[:5])}", file=sys.stderr)


if __name__ == "__main__":
    main()
