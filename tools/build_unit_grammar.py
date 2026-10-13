# -*- coding: utf-8 -*-
"""教材语法指纹构建脚本（a4）

输入：data/attrs/section_text.jsonl（教材权威源）
输出：data/attrs/unit_grammar.json
    {
      "02736c70-9509-438f-8e16-2902feaf5ed8:001": {
        "unit_key": "02736c70-9509-438f-8e16-2902feaf5ed8:001",
        "grade": "四年级", "term": "上册", "unit_no": 1, "title": "Helping at home",
        "grammar_points": [...],
        "writing_features": [...],
        "top_ids": [最多出现的前若干 grammar id]
      },
      ...
    }

规则：
  1. 只处理英语教材
  2. 复用 tools/grammar_rules.detect() 检测语法点 + 写作特征
  3. top_ids 按 count 降序，取 top 6，供 pair_extensions 快速 overlap 用
"""
from __future__ import annotations
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# 让脚本无论从哪儿运行都能 import tools.*
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.grammar_rules import detect  # noqa: E402


SRC = ROOT / "data" / "attrs" / "section_text.jsonl"
OUT = ROOT / "data" / "attrs" / "unit_grammar.json"


def load_sections() -> list[dict]:
    out = []
    with open(SRC, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def build(sec: dict) -> dict | None:
    """处理单个 section → unit_grammar 条目。非英语返回 None。"""
    if sec.get("subject") != "英语":
        return None
    if not sec.get("grade") or not sec.get("term"):
        return None  # 排除年级/学期为空的（附录等）
    if not sec.get("unit_no"):
        return None  # 排除 unit_no 为空的（附录等）

    text = sec.get("text") or ""
    if not text.strip():
        return None

    fp = detect(text)
    # top_ids：按出现次数降序
    gpts_sorted = sorted(fp["grammar_points"], key=lambda x: -x["count"])
    top_ids = [g["id"] for g in gpts_sorted[:6]]

    # 精简 grammar_points：只留 id + count（label 存规则表里，不重复）
    grammar_points_lite = [
        {"id": g["id"], "count": g["count"], "evidence": g["evidence"]}
        for g in gpts_sorted
    ]
    writing_features_lite = [
        {"id": w["id"], "value": w["value"]}
        for w in fp["writing_features"]
    ]

    return {
        "unit_key": sec["section_id"],
        "book_id": sec["book_id"],
        "grade": sec["grade"],
        "term": sec["term"],
        "unit_no": sec["unit_no"],
        "unit_name": sec["unit_name"],
        "title": sec["title"],
        "n_pages": sec.get("n_pages"),
        "chars": sec.get("chars"),
        "grammar_points": grammar_points_lite,
        "writing_features": writing_features_lite,
        "top_ids": top_ids,
    }


def main():
    secs = load_sections()
    print(f"[scan] 共读入 {len(secs)} 段")

    entries: dict[str, dict] = {}
    skipped_en = 0
    for sec in secs:
        entry = build(sec)
        if entry is None:
            skipped_en += 1
            continue
        entries[entry["unit_key"]] = entry

    # 汇总：按 (grade, term, unit_no) 分组打印
    by_gt: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in entries.values():
        by_gt[(e["grade"], e["term"])].append(e)

    print(f"[out ] 英语单元条目 {len(entries)} 条，跳过 {skipped_en} 条非英语")
    for (grade, term), lst in sorted(by_gt.items(), key=lambda x: (x[0][0], x[0][1])):
        lst.sort(key=lambda x: x["unit_no"])
        print(f"  {grade}{term}: {len(lst)} 单元  "
              f"[{lst[0]['unit_name']} → {lst[-1]['unit_name']}]")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print(f"[wrote] {OUT}  ({os.path.getsize(OUT)} bytes)")

    # 打印样例（三上 Unit 1）
    sample_keys = [k for k in entries if "三年级" in entries[k]["grade"]
                   and entries[k]["unit_no"] == 1 and entries[k]["term"] == "上册"]
    if sample_keys:
        s = entries[sample_keys[0]]
        print(f"\n[示例] {s['grade']}{s['term']} {s['unit_name']}  {s['title']}")
        print(f"  top_ids: {s['top_ids']}")
        print(f"  语法点 {len(s['grammar_points'])} 个, 写作特征 {len(s['writing_features'])} 个")
        for g in s["grammar_points"][:8]:
            print(f"    {g['id']:28s} n={g['count']:3d}  ev={g['evidence']!r}")
        for w in s["writing_features"]:
            print(f"    WF {w['id']:20s} v={w['value']}")


if __name__ == "__main__":
    main()
