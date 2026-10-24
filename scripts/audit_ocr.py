# -*- coding: utf-8 -*-
"""语文课文 OCR 错位离线扫描器。

零依赖、离线、纯规则：扫 data/attrs/lesson_text.jsonl，标记 7 类错乱，
输出 CSV 供人工筛和后续 VLM 精修排队。

用法：
    python scripts/audit_ocr.py                       # 全量扫，输出到 data/audit/ocr_issues.csv
    python scripts/audit_ocr.py --sample              # 只打印前 40 条到 stdout
    python scripts/audit_ocr.py --book 06422d77       # 按 book_id 前缀过滤
    python scripts/audit_ocr.py --type page_num       # 只看某类错乱

错乱类型（issue_type）：
    page_num          页码/图注串入正文（如 "2    北京的春节"、"（图）盛锡珊"）
    newchars_leak     生字条污染正文（一段里出现"醋饺摊拌筝眨宵燃"这种无标点单字串）
    repeat_paragraph  段落内或段落间重复
    note_glue         注释粘连正文（``〔 〕〕）
    author_glue       作者行粘连（"本文作者..."）
    multi_lesson_page 一课多诗（多课共享 page_from，正文相同）
    text_drift        text 与 text_plain 差异异常大（清洗过度/清洗不足）
    empty_exercise    exercises 里有空字符串
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from difflib import SequenceMatcher

ROOT = Path(__file__).resolve().parents[1]
LESSON_TEXT = ROOT / "data" / "attrs" / "lesson_text.jsonl"
OUT_DIR = ROOT / "data" / "audit"


# ---------- 规则 ----------

# 页码/图注串字：数字 + 若干空白 + 标题；或孤立"（图）"、"（配图）"
RE_PAGE_NUM = re.compile(r"(?<!\d)\d{1,3}\s{2,}[^\s\d][^。；，]{0,15}$")
RE_FIG_TAG = re.compile(r"（\s*图\s*）[^，。；]{0,20}")
RE_TITLE_IN_TEXT = re.compile(r"[、。；，]?\s{2,}[^\s\d，。；]{2,8}(?=\s|$)")
# 数字误插：中文字之间夹 1-2 位数字（如"色味双1北京的春节"里的"1"），
# 排除年份/数字名词，靠上下文启发式（数字前后都是汉字）
RE_NUM_IN_ZH = re.compile(r"([一-龥])\d{1,2}([一-龥])")

# 生字条污染：连续汉字（无标点）长度 >= 8，且其中 >= 5 个字命中 newchars 数组
RE_ZH_RUN = re.compile(r"[一-龥]{8,}")

# 注释粘连
RE_NOTE = re.compile(r"[〔［【（](?:[①②③④⑤⑥⑦⑧⑨⑩]|[0-9]+|[一二三四五六七八九十])[〕］】）]?[^。；]{0,80}")

# 作者行
RE_AUTHOR = re.compile(r"本文作者[^，。]{0,15}[，,]?")
RE_AUTHOR2 = re.compile(r"[《【]?[^》】]{2,8}[》】]?(?:原文|课文|有改动|节选)")

# 一课多诗：page_from==page_to 但同 unit 下有多个课，且 text 完全一样
# 用 hash 判重
def _sig(s: str) -> str:
    return re.sub(r"\s+", "", s)[:80]


def detect_in_text(text: str, lesson: dict) -> list:
    """对单条 text 做规则扫描。"""
    issues = []
    if not text:
        return issues
    lines = text.split("\n")
    newchars = set(lesson.get("newchars") or [])

    # 1) 页码/图注串字（在 text 里出现即脏，text 应该是清洗后的）
    for ln_no, ln in enumerate(lines, 1):
        m = RE_FIG_TAG.search(ln)
        if m:
            issues.append(("page_num", ln_no, f"图注串入：{m.group()}"))
        m = RE_PAGE_NUM.search(ln.strip())
        if m and not ln.strip().startswith(("\n", "，", "。")):
            issues.append(("page_num", ln_no, f"页码/标题串入：{m.group()!r}"))

    # 2) 生字条污染：
    #    - 连续汉字串 >= 6 字
    #    - 其中 >= 5 个字命中 newchars
    #    - 命中率 >= 70%（正常句子不可能这么高）
    #    - 该串必须被标点/换行/边界隔离（前面无汉字，后面无汉字），
    #      即真·孤立生字条，而不是句中夹带
    if newchars:
        for m in RE_ZH_RUN.finditer(text):
            run = m.group()
            if len(run) < 6:
                continue
            pre = text[m.start() - 1] if m.start() > 0 else "\n"
            post = text[m.end()] if m.end() < len(text) else "\n"
            # 前后必须是标点/换行/空白，不是汉字
            if re.match(r"[一-龥]", pre) or re.match(r"[一-龥]", post):
                continue
            hits = sum(1 for ch in run if ch in newchars)
            if hits >= 5 and hits / len(run) >= 0.7:
                issues.append((
                    "newchars_leak", 0,
                    f"生字条污染({hits}/{len(run)})：{run[:40]!r}"
                ))

    # 3) 注释粘连
    if "〔" in text or "[①" in text or "①" in text:
        m = RE_NOTE.search(text)
        if m:
            issues.append(("note_glue", 0, f"注释粘连：{m.group()[:40]!r}"))

    # 4) 作者行残留
    m = RE_AUTHOR.search(text)
    if m:
        issues.append(("author_glue", 0, f"作者行残留：{m.group()!r}"))

    return issues


def detect_repeats(lesson: dict) -> list:
    """重复段落检测。"""
    paras = lesson.get("paragraphs") or []
    sigs = [p for p in paras if p]
    cnt = Counter(sigs)
    dupes = [p for p, c in cnt.items() if c >= 2 and len(p) >= 20]
    issues = []
    for p in dupes:
        issues.append(("repeat_paragraph", 0, f"重复段落：{p[:60]!r}"))
    return issues


def detect_text_drift(lesson: dict) -> list:
    """text vs text_plain 差异。"""
    issues = []
    text = lesson.get("text") or ""
    plain = lesson.get("text_plain") or ""
    if not plain:
        return issues
    ratio = SequenceMatcher(None, _sig(text), _sig(plain)).ratio()
    # 差异超过 30% 且原文长度 > 100，可能是清洗丢失关键内容或清洗不彻底
    plain_len = len(_sig(plain))
    text_len = len(_sig(text))
    if plain_len > 200 and ratio < 0.75:
        issues.append((
            "text_drift", 0,
            f"text/plain 相似度={ratio:.2f} (text={text_len}字, plain={plain_len}字)"
        ))
    # 空 text
    if text_len < 30 and plain_len > 200:
        issues.append(("text_drift", 0, f"text 过短：{text_len}字 vs plain {plain_len}字"))
    return issues


def detect_multi_lesson(book_lessons: list) -> list:
    """一课多诗：同 book 下多课共享 page_from 且 text 完全相同。"""
    issues = []
    by_page = defaultdict(list)
    for L in book_lessons:
        pf = L.get("page_from")
        if pf:
            by_page[pf].append(L)
    for pf, group in by_page.items():
        if len(group) < 2:
            continue
        sigs = defaultdict(list)
        for L in group:
            sigs[_sig(L.get("text") or "")].append(L)
        for sig, dup in sigs.items():
            if len(dup) >= 2 and len(sig) >= 30:
                ids = [d["lesson_id"][-6:] for d in dup]
                titles = [d.get("title", "?") for d in dup]
                issues.append((
                    "multi_lesson_page", pf,
                    f"共页同文：p{pf} {'/'.join(ids)} {'/'.join(titles)}"
                ))
    return issues


def detect_empty_exercise(lesson: dict) -> list:
    issues = []
    for i, e in enumerate(lesson.get("exercises") or []):
        if e is None or (isinstance(e, str) and e.strip() == ""):
            issues.append(("empty_exercise", i, f"exercises[{i}] 空"))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="只打印前 40 条到 stdout")
    ap.add_argument("--book", help="按 book_id 前缀过滤")
    ap.add_argument("--type", help="只看某类错乱 issue_type")
    ap.add_argument("--out", default=str(OUT_DIR / "ocr_issues.csv"))
    args = ap.parse_args()

    if not LESSON_TEXT.exists():
        print(f"[ERROR] 找不到 {LESSON_TEXT}", file=sys.stderr)
        sys.exit(1)

    all_issues = []
    by_book = defaultdict(list)
    type_count = Counter()
    book_count = Counter()

    with LESSON_TEXT.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            L = json.loads(line)
            if args.book and not L.get("book_id", "").startswith(args.book):
                continue

            lid = L["lesson_id"]
            book_id = L["book_id"]
            title = L.get("title", "")
            label = f"{L.get('grade','')}{L.get('term','')} U{L.get('unit_no','?')} " \
                    f"L{L.get('lesson_no','?')}《{title}》"
            book_count[book_id] += 1

            found = []
            # 1) 在 text 里扫描
            found.extend(detect_in_text(L.get("text") or "", L))
            # 2) 重复段落
            found.extend(detect_repeats(L))
            # 3) text vs plain 漂移
            found.extend(detect_text_drift(L))
            # 4) exercises 空
            found.extend(detect_empty_exercise(L))

            for itype, loc, msg in found:
                all_issues.append({
                    "book_id": book_id,
                    "lesson_id": lid,
                    "lesson_label": label,
                    "issue_type": itype,
                    "location": str(loc),
                    "detail": msg,
                })
                type_count[itype] += 1

            by_book[book_id].append(L)

    # 一课多诗：按 book 分组检测
    for book_id, lessons in by_book.items():
        for itype, loc, msg in detect_multi_lesson(lessons):
            all_issues.append({
                "book_id": book_id,
                "lesson_id": "",
                "lesson_label": f"{book_id[:8]} 全册",
                "issue_type": itype,
                "location": str(loc),
                "detail": msg,
            })
            type_count[itype] += 1

    if args.type:
        all_issues = [x for x in all_issues if x["issue_type"] == args.type]

    # 输出
    if args.sample:
        print(f"共扫描 {sum(book_count.values())} 篇课文，"
              f"发现 {len(all_issues)} 条问题：")
        for t, c in type_count.most_common():
            print(f"  {t:20s} {c}")
        print("\n--- 前 40 条示例 ---")
        for row in all_issues[:40]:
            loc = str(row["location"])[:6]
            print(f"[{row['issue_type']:18s}] {row['lesson_label'][:32]:32s} "
                  f"loc={loc:<6s} {row['detail'][:100]}")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "book_id", "lesson_id", "lesson_label",
            "issue_type", "location", "detail",
        ])
        w.writeheader()
        for row in all_issues:
            w.writerow(row)

    print(f"扫描完成：{sum(book_count.values())} 篇课文 → {len(all_issues)} 条问题")
    print(f"输出到 {out}")
    print("\n按类型统计：")
    for t, c in type_count.most_common():
        print(f"  {t:20s} {c}")
    print("\n按册统计（top 10）：")
    book_issue = Counter(r["book_id"] for r in all_issues)
    for bid, c in book_issue.most_common(10):
        print(f"  {bid[:8]}...  {c:4d} 条问题 / {book_count[bid]:3d} 篇")


if __name__ == "__main__":
    main()
