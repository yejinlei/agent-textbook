# -*- coding: utf-8 -*-
"""给已抓取但 level/topic 为空的绘本自动标注。
输入：books.json（含 asb_id 与 pages）
输出：就地更新 books.json，写入 word_count / unique_words / reading_time_min /
      level / primary_topic（保守打分，人可再复核）。
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PB = ROOT / "data" / "picturebooks"
BOOKS = PB / "books.json"
TOPICS = PB / "topics.json"
ONTOLOGY = PB / "ontology.json"

def wc(text):
    return re.findall(r"[A-Za-z']+", text.lower())

def grade(unique_words: int, wpp: float, n_pages: int) -> str:
    """按 ontology.levels 打分，选 unique_words 匹配度最高的一档。"""
    levels = json.loads(ONTOLOGY.read_text(encoding="utf-8"))["levels"]
    best, best_score = None, -1
    for lv in levels:
        lo, hi = lv["unique_words"]
        lo_p, hi_p = lv["pages"]
        # unique_words 落在范围内 → +100；否则按偏离度衰减
        if lo <= unique_words <= hi:
            s = 100
        else:
            s = max(0, 100 - abs(unique_words - (lo + hi) / 2) * 0.5)
        if lo_p <= n_pages <= hi_p:
            s += 20
        # wpp 加分
        lo_w, hi_w = lv["words_per_page"]
        if lo_w <= wpp <= hi_w:
            s += 20
        if s > best_score:
            best, best_score = lv["id"], s
    return best or "PB2"

def topic_hits(text: str, topics_data: dict):
    hits = []
    def walk(nodes):
        for n in nodes:
            kws = n.get("keywords_en", [])
            score = 0
            for kw in kws:
                # 单词用词边界；短语直接子串
                if " " in kw:
                    score += text.count(kw)
                else:
                    score += len(re.findall(r"\b" + re.escape(kw) + r"\b", text))
            if score:
                hits.append((score, n["id"]))
        hits.sort(reverse=True)
    walk(topics_data["topics"])
    return hits

def main():
    store = json.loads(BOOKS.read_text(encoding="utf-8"))
    topics = json.loads(TOPICS.read_text(encoding="utf-8"))
    updated = 0
    for b in store["books"]:
        pages = b.get("pages", [])
        if not pages:
            continue
        text = " ".join(p.get("text", "") for p in pages)
        words = wc(text)
        total = len(words)
        uniq = len(set(words))
        n = len(pages)
        wpp = total / max(n, 1)
        # 只在缺 level/topic 时写；已标注的不动
        if b.get("level") is None:
            b["level"] = grade(uniq, wpp, n)
        if b.get("primary_topic") is None and text.strip():
            hits = topic_hits(text.lower(), topics)
            if hits:
                b["primary_topic"] = hits[0][1]
                b["secondary_topics"] = [h[1] for h in hits[1:4]]
        b["word_count"] = total
        b["unique_words"] = uniq
        b["reading_time_min"] = max(1, round(total / 150))
        updated += 1

    store["_updated"] = "2026-10-13"
    BOOKS.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"annotated {updated} books")

if __name__ == "__main__":
    main()
