# -*- coding: utf-8 -*-
"""课外阅读/绘本语法指纹构建脚本（a5）

输入：
  data/readings/catalog.json        27 本英文经典（正文在 data/readings/texts/{id}.txt）
  data/picturebooks/books.json       5 本绘本（正文在 pages[].text）

输出：
  写回原文件，追加 facets 字段：
    - facets.grammar_fingerprint: {grammar_points, writing_features, top_ids}  （完整指纹）
    - facets.supports_grammar:    把 book 顶层 supports_grammar 提升为 facets.supports_grammar
  同时顶层 supports_grammar 保留（兼容旧消费方），值改写为新的规范 id 列表

规则：
  - 检测函数用 tools/grammar_rules.detect()
  - 老 supports_grammar（grammar.tense / grammar.there_be 之类）映射到新的 id 集合
  - 正文太短（<80 词）视为样本量不足，跳过指纹
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.grammar_rules import detect  # noqa: E402


CATALOG = ROOT / "data" / "readings" / "catalog.json"
CATALOG_TEXTS = ROOT / "data" / "readings" / "texts"
PICKY = ROOT / "data" / "picturebooks" / "books.json"


# 老 id → 新 id 集合（保留语义）
LEGACY_GRAMMAR_MAP: dict[str, list[str]] = {
    "grammar.tense":     ["tense.present_simple", "tense.present_progressive",
                          "tense.past_simple", "tense.future_going_to", "be.was_were"],
    "grammar.there_be":  ["there.be"],
    "grammar.modal":     ["modal.can_could"],
    "grammar.be_verb":   ["be.am_is_are", "be.was_were", "be.contraction"],
    "grammar.pronouns":  ["pron.possessive", "pron.possessive_noun", "pron.these_those"],
    "grammar.plurals":   ["noun.plural_s"],
    "grammar.comparatives": ["comparative"],
    "grammar.questions": ["question.wh_words", "question.be_verb_invert", "question.do_verb_invert"],
    "grammar.negation":  ["negation"],
    "grammar.prepositions": ["prep.common"],
    "grammar.articles":  ["article.a_an", "article.the"],
    "grammar.conjunctions": ["conj.and_or_but"],
    "grammar.exclamations": ["exclamation"],
    "grammar.imperative": ["imperative"],
}


MIN_WORDS = 80


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z']+", text))


def build_fingerprint(text: str) -> dict | None:
    """检测函数，正文太短返回 None。"""
    if word_count(text) < MIN_WORDS:
        return None
    fp = detect(text)
    gpts_sorted = sorted(fp["grammar_points"], key=lambda x: -x["count"])
    return {
        "grammar_points": [
            {"id": g["id"], "count": g["count"], "evidence": g["evidence"]}
            for g in gpts_sorted
        ],
        "writing_features": [
            {"id": w["id"], "value": w["value"]}
            for w in fp["writing_features"]
        ],
        "top_ids": [g["id"] for g in gpts_sorted[:6]],
        "word_count": word_count(text),
    }


def normalize_supports_grammar(old: list[str], fp: dict | None) -> list[str]:
    """把老 supports_grammar 展开到新 id；并合并 fp.top_ids 中出现的 id（去重）。"""
    ids: list[str] = []
    for legacy in old or []:
        if legacy in LEGACY_GRAMMAR_MAP:
            ids.extend(LEGACY_GRAMMAR_MAP[legacy])
        else:
            ids.append(legacy)  # 已经是新 id 形式，保留
    if fp:
        for gid in fp["top_ids"]:
            if gid not in ids:
                ids.append(gid)
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ---------------- 处理 readings ----------------
def process_readings():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    stats = {"total": 0, "done": 0, "skipped_short": 0, "skipped_notext": 0}
    for b in data["books"]:
        stats["total"] += 1
        bid = b["id"]
        text_file = CATALOG_TEXTS / f"{bid}.txt"
        if not text_file.exists():
            stats["skipped_notext"] += 1
            print(f"  [skip] {bid} 无正文文件")
            continue
        text = text_file.read_text(encoding="utf-8", errors="ignore")
        fp = build_fingerprint(text)
        if fp is None:
            stats["skipped_short"] += 1
            print(f"  [skip] {bid} 正文过短（{word_count(text)} 词）")
            continue

        old_supports = b.get("supports_grammar") or []
        new_supports = normalize_supports_grammar(old_supports, fp)
        b["supports_grammar"] = new_supports  # 顶层保留（兼容）

        b.setdefault("facets", {})
        b["facets"]["supports_grammar"] = new_supports
        b["facets"]["grammar_fingerprint"] = fp
        stats["done"] += 1
        print(f"  [ok] {bid:35s} wc={fp['word_count']:6d}  "
              f"top_ids={fp['top_ids'][:4]}")

    CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[readings] 总 {stats['total']}，成功 {stats['done']}，"
          f"跳过(无正文){stats['skipped_notext']}，跳过(过短){stats['skipped_short']}")


# ---------------- 处理 picturebooks ----------------
def process_picturebooks():
    data = json.loads(PICKY.read_text(encoding="utf-8"))
    books = data["books"] if isinstance(data, dict) else data
    stats = {"total": 0, "done": 0, "skipped_short": 0}
    for b in books:
        stats["total"] += 1
        bid = b["id"]
        pages = b.get("pages") or []
        text = "\n".join((p.get("text") or "") for p in pages)
        fp = build_fingerprint(text)
        if fp is None:
            stats["skipped_short"] += 1
            print(f"  [skip] {bid} 正文过短（{word_count(text)} 词）")
            continue

        old_supports = b.get("supports_grammar") or []
        new_supports = normalize_supports_grammar(old_supports, fp)
        b["supports_grammar"] = new_supports

        b.setdefault("facets", {})
        b["facets"]["supports_grammar"] = new_supports
        b["facets"]["grammar_fingerprint"] = fp
        stats["done"] += 1
        print(f"  [ok] {bid:35s} wc={fp['word_count']:6d}  "
              f"top_ids={fp['top_ids'][:4]}")

    if isinstance(data, dict):
        PICKY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        PICKY.write_text(json.dumps(books, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[picturebooks] 总 {stats['total']}，成功 {stats['done']}，"
          f"跳过(过短){stats['skipped_short']}")


def main():
    print("=" * 60)
    print("[step 1] process readings/catalog.json (27 本)")
    process_readings()
    print("=" * 60)
    print("[step 2] process picturebooks/books.json (5 本)")
    process_picturebooks()


if __name__ == "__main__":
    main()
