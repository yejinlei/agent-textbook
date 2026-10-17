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
# 插图探测：两行正文之间的垂直空隙足够大，且空隙里确有视觉内容
FIG_GAP = 70.0
FIG_MIN_W = 160.0
FIG_MIN_H = 70.0
FIG_COVER_RATIO = 0.25  # 空隙里矢量/位图覆盖面积至少占 25%


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


def reorder_page_full(page, ytol: float = YTOL) -> list[list]:
    """一页 → 按版面顺序的 [x0, y0, x1, y1, text, size]。含完整 bbox，用于插图探测。"""
    rows = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            spans = ln.get("spans", []) or []
            t = "".join(s.get("text", "") for s in spans).strip()
            if not t:
                continue
            size = max((s.get("size") or 0.0) for s in spans) if spans else 0.0
            x0, y0, x1, y1 = ln["bbox"]
            rows.append([x0, y0, x1, y1, t, size])
    rows.sort(key=lambda r: (r[1], r[0]))
    out, cur = [], []
    for r in rows:
        if cur and abs(r[1] - cur[-1][1]) <= ytol:
            cur.append(r)
        else:
            if cur:
                cur.sort(key=lambda r: r[0])
                x0 = min(c[0] for c in cur)
                y0 = min(c[1] for c in cur)
                x1 = max(c[2] for c in cur)
                y1 = max(c[3] for c in cur)
                t = "".join(c[4] for c in cur)
                size = max(c[5] for c in cur)
                out.append([x0, y0, x1, y1, t, size])
            cur = [r]
    if cur:
        cur.sort(key=lambda r: r[0])
        x0 = min(c[0] for c in cur)
        y0 = min(c[1] for c in cur)
        x1 = max(c[2] for c in cur)
        y1 = max(c[3] for c in cur)
        t = "".join(c[4] for c in cur)
        size = max(c[5] for c in cur)
        out.append([x0, y0, x1, y1, t, size])
    return out


def _page_gaps(page, rows, gap: float = FIG_GAP):
    """正文区域内的文本行空隙 → 可能插图的 bbox 列表。"""
    h = page.rect.height
    body = [r for r in rows if EDGE_TOP * h < r[1] < EDGE_BOTTOM * h]
    gaps = []
    for i in range(len(body) - 1):
        lo, hi = body[i], body[i + 1]
        g = hi[1] - lo[3]
        if g < gap:
            continue
        x0 = max(0, min(lo[0], hi[0]) - 30)
        x1 = min(page.rect.width, max(lo[2], hi[2]) + 30)
        if x1 - x0 < FIG_MIN_W:
            x0, x1 = 30, page.rect.width - 30
        y0, y1 = lo[3], hi[1]
        if y1 - y0 < FIG_MIN_H:
            continue
        gaps.append([x0, y0, x1, y1])
    if not gaps:
        return []
    merged = [gaps[0]]
    for g in gaps[1:]:
        last = merged[-1]
        if g[1] <= last[3] + 4:
            last[0] = min(last[0], g[0])
            last[2] = max(last[2], g[2])
            last[3] = g[3]
        else:
            merged.append(g)
    return merged


def _has_visual_content(page, rect):
    """空隙里确实有图：非细长的矢量绘图或位图覆盖面积达到阈值。

    练习册里的填空横线、分隔线也是矢量，但它们是又细又长的矩形，直接
    排除掉，避免把练习线当插图截出来。
    """
    area = abs(rect)
    if area <= 0:
        return False
    covered = 0.0
    for d in page.get_drawings():
        r = d["rect"]
        w, h = r.width, r.height
        if min(w, h) < 4 or (min(w, h) > 0 and max(w, h) / min(w, h) > 12):
            continue
        inter = rect & r
        if not inter.is_empty:
            covered += abs(inter)
    if covered / area > FIG_COVER_RATIO:
        return True
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") == 1:
            bx = pymupdf.Rect(b["bbox"])
            inter = rect & bx
            if not inter.is_empty and abs(inter) > 1200:
                return True
    return False


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
    """一个单元（一段页范围）→ 按版面顺序的文本行（已去页眉页脚），并在行空隙处插入插图占位符。"""
    lo = int(page_from if page_from is not None else 0)
    hi = int(page_to if page_to is not None else 0)
    rows_by_page = {}
    all_rows = []
    for pno in range(max(lo, 0), min(hi, doc.page_count - 1) + 1):
        page = doc[pno]
        h = page.rect.height
        rows = reorder_page_full(page)
        rows_by_page[pno] = rows
        for r in rows:
            all_rows.append((r[1], r[0], r[4], h))
    if not all_rows:
        return []
    # 页眉页脚：在页顶/页底重复出现两次以上的整行文本丢掉
    edge = Counter(t for y, x, t, h in all_rows
                   if y < h * EDGE_TOP or y > h * EDGE_BOTTOM)
    drop = {t for t, n in edge.items() if n >= 2}
    # 按页过滤 + 在版面空隙处插入插图占位符
    out = []
    for pno in sorted(rows_by_page):
        rows = [r for r in rows_by_page[pno] if r[4] not in drop]
        page = doc[pno]
        gaps = _page_gaps(page, rows)
        # 从后往前插入占位符，避免索引错乱
        for g in reversed(gaps):
            rect = pymupdf.Rect(g[0], g[1], g[2], g[3])
            if not _has_visual_content(page, rect):
                continue
            marker = "[[figure page=%d x0=%d y0=%d x1=%d y1=%d]]" % (
                pno, int(g[0]), int(g[1]), int(g[2]), int(g[3]))
            pos = 0
            for i, r in enumerate(rows):
                if r[3] <= g[1]:
                    pos = i + 1
                else:
                    break
            rows.insert(pos, [0, g[1], 0, g[1], marker, 0])
        out.extend([r[4] for r in rows])
    return out


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
    for i, (sid, bid, pf, pt) in enumerate(rows):
        if i and i % 20 == 0 and log:
            log("重排 %s：%d/%d..." % (subject, i, len(rows)))
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
