# -*- coding: utf-8 -*-
"""绘本样本审查：统计词汇、主题命中率、分级建议。"""
import json, re, sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
PB = ROOT / "data" / "picturebooks"

def wc(text):
    return re.findall(r"[A-Za-z']+", text.lower())

def audit():
    books = json.loads((PB / "books.json").read_text(encoding="utf-8"))["books"]
    topics = json.loads((PB / "topics.json").read_text(encoding="utf-8"))
    # 扁平化 topics 树：所有叶子节点 + keywords_en
    topic_map = {}
    def walk(nodes):
        for n in nodes:
            topic_map[n["id"]] = n.get("keywords_en", [])
            if n.get("children"):
                walk(n["children"])
    walk(topics if isinstance(topics, list) else topics.get("topics", []))

    print(f"{'id':<52s} {'asb':>6s} {'lvl':<18s} {'pages':>5s} {'wc':>4s} {'uniq':>5s}  primary_topic")
    print("-" * 140)
    for b in books:
        all_text = " ".join(p.get("text", "") for p in b.get("pages", []))
        words = wc(all_text)
        uniq = len(set(words))
        # topic 命中：关键词出现次数最高者胜出
        text_lower = all_text.lower()
        hits = []
        for tid, kws in topic_map.items():
            score = sum(text_lower.count(kw.lower()) for kw in kws)
            if score:
                hits.append((score, tid))
        hits.sort(reverse=True)
        top_topic = f"{hits[0][1]}({hits[0][0]})" if hits else "-"
        print(f"{b['id']:<52s} {str(b.get('asb_id','')):>6s} {str(b.get('asb_level','')):<18s} "
              f"{len(b.get('pages',[])):5d} {len(words):4d} {uniq:5d}  {top_topic}")

if __name__ == "__main__":
    audit()
