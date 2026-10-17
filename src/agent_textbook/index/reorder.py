# -*- coding: utf-8 -*-
"""按 PDF 版面坐标重排课文（治"串行"）。

当年抽文本层时只留下了字符串，坐标没保存，于是图、表、对话气泡里的字
和正文句子挤在一条流里输出（"晴 / 阴 / 多云 / 天数"夹在两句话中间），
读起来就是串行。PDF 还在，PyMuPDF 能拿回每个文本行的 bbox，所以这里
按版面重建阅读顺序：

    先按 y 聚成"视觉行"（同行的题号 7 和题干会并到一起），
    行内再按 x 从左到右。

两处必须处理的版面噪音：
- 页眉页脚：贴着页顶/页底且跨页重复（单元名页眉、印刷页码、版权行），
  整单元内出现两次以上就整行丢掉。
- 表格：单元格按 y/x 排会交错（日历"一 2 二 3"）。这些是孤词和数字，
  交给 build.py 的图文分离归到"图表上的字"，不进正文。

表格交错治不了（按 y/x 排是版面顺序，不是表格的读法顺序），但正文句
的顺序是对的——这才是"串行"真正影响阅读的部分。
"""

from __future__ import annotations

import json
import os
from collections import Counter

import pymupdf

from .. import config

# 同一视觉行的 y 容差（pt）：教材行高 20~26pt，题号与题干常差 1~3pt
YTOL = 8.0
# 页眉页脚判定：贴着页顶/页底这一段范围内
EDGE_TOP = 0.08
EDGE_BOTTOM = 0.92


def _meta(book_id: str) -> dict | None:
    """解析产物的 meta 行（里面有 PDF 相对路径）。"""
    p = os.path.join(config.DATA_DIR, "parsed", book_id + ".jsonl")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        for ln in f:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("type") == "meta":
                return r
    return None


def pdf_path(book_id: str) -> str | None:
    """book_id → 教材 PDF 的绝对路径（找不到就 None）。"""
    m = _meta(book_id)
    if not m:
        return None
    rel = (m.get("rel_path") or "").replace("\\", "/")
    if not rel:
        return None
    p = os.path.join(config.BOOKS_DIR, *rel.split("/"))
    return p if os.path.exists(p) else None


def reorder_page(page, ytol: float = YTOL) -> list[list]:
    """一页 → 按版面顺序的 [[y, x, text, size], ...]。

    size 取该行最大字号：古诗文的注释是明显更小的字，靠它能把注释从正文里摘掉。
    """
    rows = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:            # 只要文本块，图跳过
            continue
        for ln in b.get("lines", []):
            spans = ln.get("spans", []) or []
            t = "".join(s.get("text", "") for s in spans).strip()
            if not t:
                continue
            size = max((s.get("size") or 0.0) for s in spans) if spans else 0.0
            rows.append([ln["bbox"][1], ln["bbox"][0], t, size])
    rows.sort(key=lambda r: (r[0], r[1]))
    # 行聚类：y 相近的算同一行，行内改按 x 排（题号在左、题干在右）
    out, cur = [], []
    for r in rows:
        if cur and abs(r[0] - cur[-1][0]) <= ytol:
            cur.append(r)
        else:
            if cur:
                out += sorted(cur, key=lambda r: r[1])
            cur = [r]
    if cur:
        out += sorted(cur, key=lambda r: r[1])
    return out


def unit_lines(doc, page_from, page_to) -> list[str]:
    """一个单元（一段页范围）→ 按版面顺序的文本行（已去页眉页脚）。"""
    lo = int(page_from if page_from is not None else 0)
    hi = int(page_to if page_to is not None else 0)
    all_rows = []
    for pno in range(max(lo, 0), min(hi, doc.page_count - 1) + 1):
        page = doc[pno]
        h = page.rect.height
        for r in reorder_page(page):
            all_rows.append((r[0], r[1], r[2], h))
    if not all_rows:
        return []
    edge = Counter(t for y, x, t, h in all_rows
                   if y < h * EDGE_TOP or y > h * EDGE_BOTTOM)
    drop = {t for t, n in edge.items() if n >= 2}
    return [t for y, x, t, h in all_rows if t not in drop]


def _blocks(lines: list[str]) -> list[dict]:
    """按栏目锚点分块（复用索引层的规则，保证与原来一致）。"""
    from . import sections
    return sections._blocks(lines)


def reorder_sections(con, subject: str, log=print) -> int:
    """重排某学科所有单元的课文，直接改知识库里的 section_text。"""
    rows = con.execute(
        "select section_id, book_id, page_from, page_to from section_text "
        "where subject=? and unit_no is not null", [subject]).fetchall()
    docs, n, skipped = {}, 0, 0
    for sid, bid, pf, pt in rows:
        if bid not in docs:
            p = pdf_path(bid)
            docs[bid] = pymupdf.open(p) if p else None
        doc = docs[bid]
        if doc is None:
            skipped += 1
            continue
        lines = unit_lines(doc, pf, pt)
        if not lines:
            skipped += 1
            continue
        con.execute("update section_text set text=?, blocks=? where section_id=?",
                    ["\n".join(lines),
                     json.dumps(_blocks(lines), ensure_ascii=False), sid])
        n += 1
    for d in docs.values():
        if d:
            d.close()
    if log:
        log("重排 %s：%d 个单元（跳过 %d 个：找不到 PDF 或没抽到文本）"
            % (subject, n, skipped))
    return n


def unit_lines_body(doc, page_from, page_to, size_ratio: float = 0.85) -> list[str]:
    """篇目正文：在版面顺序之上再去掉小字注释。

    古诗文页的老问题——页下注释、旁注和正文挤成一条流，抽出来就成了
    "……轻烟散入五侯家。者不详，写作时代大约在东汉末年。汉，银河。"
    注释的字号明显小于正文，用众数字号当基准就能摘掉。
    """
    lo = int(page_from if page_from is not None else 0)
    hi = int(page_to if page_to is not None else 0)
    rows = []
    for pno in range(max(lo, 0), min(hi, doc.page_count - 1) + 1):
        page = doc[pno]
        h = page.rect.height
        for r in reorder_page(page):
            rows.append((r[0], r[1], r[2], r[3], h))
    if not rows:
        return []
    edge = Counter(r[2] for r in rows
                   if r[0] < r[4] * EDGE_TOP or r[0] > r[4] * EDGE_BOTTOM)
    drop = {t for t, n in edge.items() if n >= 2}
    rows = [r for r in rows if r[2] not in drop]
    if not rows:
        return []
    main = Counter(round(r[3], 1) for r in rows).most_common(1)[0][0]
    return [r[2] for r in rows if r[3] >= main * size_ratio]


def reorder_pieces(con, log=print) -> int:
    """重排语文古诗文（piece）：注释不再混进正文。"""
    rows = con.execute(
        "select p.piece_id, p.title, l.book_id, l.page_from, l.page_to "
        "from piece p join lesson_text l on p.lesson_id = l.lesson_id"
    ).fetchall()
    docs, n, skipped = {}, 0, 0
    for pid, title, bid, pf, pt in rows:
        if bid not in docs:
            p = pdf_path(bid)
            docs[bid] = pymupdf.open(p) if p else None
        doc = docs[bid]
        if doc is None:
            skipped += 1
            continue
        lines = unit_lines_body(doc, pf, pt)
        if not lines:
            skipped += 1
            continue
        con.execute("update piece set text=? where piece_id=?",
                    ["\n".join(lines), pid])
        n += 1
    for d in docs.values():
        if d:
            d.close()
    if log:
        log("重排 古诗文：%d 篇（跳过 %d 篇：找不到 PDF 或没抽到文本）" % (n, skipped))
    return n
