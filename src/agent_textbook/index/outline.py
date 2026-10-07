# -*- coding: utf-8 -*-
"""目录与结构抽取（知识库 L1）：把教材还原成「单元 → 课/栏目 → 起始页码」的骨架。

教材目录有两种版式，都必须支持：
    A 点线版   ：`1  大青树下的小学................2`（三年级及以上）
    B 无点线版 ：`1 | 天地人 | 8`，序号/标题/页码各占一行（一年级）

产物 data/outline/<book_id>.jsonl：首行 meta，其后每行一条目。

已知坑：
  * 目录页的 printed_no 字段不可信（会抓到目录里的页码数字），但正文页可信；
    所以条目的起始页码一律取自目录文本自身，不读 printed_no。
  * 目录可能跨 2~4 页，单元/栏目会跨页延续，解析必须带状态。
"""

import json
import os
import re

from .. import config

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

# 单元：`第一单元....1`（点线版带页码）/ `第一单元·识字`（无点线版带栏目后缀）
RE_UNIT = re.compile(
    r"^第([一二三四五六七八九十]+)单元\s*"
    r"(?:[·•・]\s*(\S+?))?\s*"
    r"(?:\.{2,}\s*(\d{1,3}))?\s*$"
)
# 点线条目：`3*\t 不懂就要问........................7`
RE_DOT_ENTRY = re.compile(
    r"^(?P<no>\d{1,2})\s*(?P<star>\*?)\s*(?P<title>.+?)\.{2,}\s*(?P<page>\d{1,3})\s*$"
)
# 无序号点线条目：`语文园地..................12`（栏目条目常常不带课序号）
RE_DOT_PLAIN = re.compile(r"^(?P<title>.+?)\.{2,}\s*(?P<page>\d{1,3})\s*$")
RE_INT = re.compile(r"^\d{1,3}$")
# 目录页整体检测：页眉在前，行首锚点必须开 MULTILINE 才能命中
# 「目录」两字常被排版拆开（`目  录`，中间是全角/半角空格），直接判子串会漏
RE_TOC_WORD = re.compile(r"目\s*录")
# 英语目录页眉是 `Contents`，且其条目是「标题一行 + 页码一行」的英文版式
RE_TOC_EN = re.compile(r"^\s*Contents\s*$", re.I | re.M)
RE_EN_ENTRY = re.compile(
    r"^(?P<kind>Unit|Revision|Appendix|Project|Recycle|Review|Checkout)\s*"
    r"(?P<no>\d+)?\s*[·•・:：\-—]?\s*(?P<title>.+?)\s*$", re.I
)
RE_UNIT_M = re.compile(r"^第([一二三四五六七八九十]+)单元", re.M)
RE_DOT_M = re.compile(r"^\d{1,2}\s*\*?\s*\S.*?\.{2,}\s*\d{1,3}\s*$", re.M)
RE_NOISE = re.compile(r"仅供个人学习使用|未经授权|绿色印刷|^\s*$")

# 目录里的栏目名：独立成行，统领其后的若干条目
SECTION_NAMES = (
    "阅读", "识字", "汉语拼音", "习作", "习作例文", "口语交际",
    "语文园地", "快乐读书吧", "综合性学习", "例文", "写字", "梳理与交流",
)


def _clean_lines(rec: dict) -> list[str]:
    """页文本 -> 干净的行列表（去页脚噪声、制表符、空行）。"""
    out = []
    for ln in (rec.get("text") or "").split("\n"):
        ln = ln.replace("\t", " ").strip()
        if not ln or RE_NOISE.search(ln):
            continue
        out.append(ln)
    return out


def load_book(book_id: str):
    """读 parsed/<book_id>.jsonl，返回 (meta, pages)。"""
    path = os.path.join(config.PARSED_DIR, book_id + ".jsonl")
    if not os.path.exists(path):
        return None, []
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    meta = next((r for r in rows if r.get("type") == "meta"), {})
    pages = [r for r in rows if r.get("type") == "page"]
    return meta, pages


def find_toc_pages(pages: list[dict], max_scan: int = 12) -> list[int]:
    """定位目录页：前若干页里含「目录」或单元样式的连续页。

    三年级正文首单元页会被拆成 `第 | 一 | 单 | 元`（不成词），不会误命中。
    """
    hits = []
    for i, r in enumerate(pages[:max_scan]):
        t = r.get("text") or ""
        if (RE_TOC_WORD.search(t) or RE_UNIT_M.search(t)
                or RE_DOT_M.search(t) or RE_TOC_EN.search(t)):
            hits.append(i)
    if not hits:
        return []
    # 取以首个命中开头的连续段（允许中间缺 1 页，比如整页插图）
    start = hits[0]
    out = [start]
    for h in hits[1:]:
        if h - out[-1] <= 2:
            out.append(h)
        else:
            break
    return out


def parse_toc_lines(lines: list[str], book_id: str = "") -> list[dict]:
    """解析目录行序列，带跨行/跨页状态（单元、栏目）。"""
    state = {"unit_no": None, "unit_name": None, "unit_tag": None, "section": None}
    entries = []
    seq = [0]
    i, n = 0, len(lines)

    def emit(no, title, page, elective=False):
        # ◎ 是教材里的栏目标记，不是标题的一部分
        t = re.sub(r"^[◎•]\s*", "", (title or "").strip()).strip()
        # 点线引导及其后的页码不属于标题：有的册目录把标题与页码拆成三行，
        # 点线留在本行（`北京的春节........` / `2`），不清就会带进标题里。
        t = re.sub(r"\.{2,}.*$", "", t).strip()
        seq[0] += 1
        entries.append({
            # 稳定主键：目录内序号 + 册 id。属性表靠它挂载，重跑不变。
            "lesson_id": f"{book_id}:{seq[0]:03d}",
            "seq": seq[0],
            "unit_no": state["unit_no"],
            "unit_name": state["unit_name"],
            "unit_tag": state["unit_tag"],
            "section": state["section"],
            "lesson_no": no,
            "title": t,
            "printed_start": page,
            "elective": elective,
        })

    while i < n:
        ln = lines[i]

        m = RE_UNIT.match(ln)
        if m:
            cn = m.group(1)
            state["unit_no"] = CN_NUM.get(cn)
            state["unit_name"] = f"第{cn}单元"
            state["unit_tag"] = m.group(2)
            state["section"] = m.group(2) if m.group(2) in SECTION_NAMES else None
            i += 1
            continue

        if ln in SECTION_NAMES:
            state["section"] = ln
            i += 1
            continue

        md = RE_DOT_ENTRY.match(ln)
        if md:
            emit(md.group("no"),
                 md.group("title").strip(),
                 int(md.group("page")),
                 bool(md.group("star")))
            i += 1
            continue

        mp = RE_DOT_PLAIN.match(ln)
        if mp:
            emit(None, mp.group("title").strip(), int(mp.group("page")))
            i += 1
            continue

        # 英语目录：`Unit 1  Meeting new people` 后紧跟单独一行的页码 `2`
        me = RE_EN_ENTRY.match(ln)
        if me and i + 1 < n and RE_INT.match(lines[i + 1]):
            kind = me.group("kind").capitalize()
            no = me.group("no")
            title = me.group("title").strip()
            if kind == "Unit" and no:
                state["unit_no"] = int(no)
                state["unit_name"] = f"Unit {no}"
                state["section"] = None
            else:
                # Revision / Appendix / Project 是单元之外的附录栏目
                state["unit_no"] = None
                state["unit_name"] = f"{kind} {no}" if no else kind
                state["section"] = kind
            emit(no, title, int(lines[i + 1]))
            i += 2
            continue

        # 课号单独成行 + 标题与页码同行：`1` / `北京的春节........2`（六年级多用此版式）。
        # 必须排在"三行一组"之前——否则会把**下一个课号**当成页码。
        if RE_INT.match(ln) and i + 1 < n:
            md = RE_DOT_PLAIN.match(lines[i + 1])
            if md:
                emit(ln, md.group("title").strip(), int(md.group("page")))
                i += 2
                continue

        # 无点线版：序号 / 标题 / 页码 三行一组
        if RE_INT.match(ln) and i + 2 < n and RE_INT.match(lines[i + 2]):
            title = lines[i + 1]
            if not RE_UNIT.match(title):
                emit(ln, title, int(lines[i + 2]))
                i += 3
                continue

        if ln.startswith("◎"):
            rest = ln[1:].strip()
            mp = RE_DOT_PLAIN.match(rest)
            if mp:
                emit(None, mp.group("title").strip(), int(mp.group("page")))
                i += 1
                continue
            if rest and i + 1 < n and RE_INT.match(lines[i + 1]):
                emit(None, rest, int(lines[i + 1]))
                i += 2
                continue
            if not rest and i + 2 < n and RE_INT.match(lines[i + 2]):
                emit(None, lines[i + 1], int(lines[i + 2]))
                i += 3
                continue
            if rest:
                emit(None, rest, None)
            i += 1
            continue

        i += 1

    return entries


def build_book(book_id: str) -> dict:
    """抽一册的目录骨架，返回 {meta, entries}。"""
    meta, pages = load_book(book_id)
    if meta is None:
        return {}
    idxs = find_toc_pages(pages)
    lines = []
    for i in idxs:
        lines.extend(_clean_lines(pages[i]))
    # book_id 必须传进去：lesson_id 靠它做前缀，漏传会让 12 册的
    # lesson_id 全部退化成 ":001/:002…"，跨册主键冲突、互相覆盖。
    entries = parse_toc_lines(lines, book_id)
    title = meta.get("title", "")
    term = "上册" if "上册" in title else ("下册" if "下册" in title else "")
    head = {
        "type": "meta",
        "book_id": book_id,
        "stage": meta.get("stage", ""),
        "subject": meta.get("subject", ""),
        "version": meta.get("version", ""),
        "grade": meta.get("grade", ""),
        "term": term,
        "title": title,
        "total_pages": len(pages),
        "toc_pages": [pages[i].get("page_no") for i in idxs],
        "entries": len(entries),
    }
    return {"meta": head, "entries": entries}


def save_book(result: dict) -> str:
    os.makedirs(config.OUTLINE_DIR, exist_ok=True)
    path = os.path.join(config.OUTLINE_DIR, result["meta"]["book_id"] + ".jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(result["meta"], ensure_ascii=False) + "\n")
        for e in result["entries"]:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return path


def build_all(subject: str = "", verbose: bool = True) -> list[dict]:
    """按学科抽全部册；subject 为空则全部。"""
    if not os.path.isdir(config.PARSED_DIR):
        return []
    ids = sorted(f[:-6] for f in os.listdir(config.PARSED_DIR) if f.endswith(".jsonl"))
    results = []
    for bid in ids:
        meta, _ = load_book(bid)
        if not meta:
            continue
        if subject and meta.get("subject") != subject:
            continue
        r = build_book(bid)
        if r.get("entries"):
            save_book(r)
            results.append(r)
            if verbose:
                m = r["meta"]
                print("  %s%s %-4s 目录页%s → %d 条" % (
                    m["grade"], m["term"], m["subject"], m["toc_pages"], m["entries"]))
        elif verbose:
            print("  [skip] %s 未识别到目录" % bid)
    return results
