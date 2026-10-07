# -*- coding: utf-8 -*-
"""数学/科学的小节切分：把骨架里的条目还原成「一节正文 + 例题/练习/实验」。

为什么不能直接复用 ``lessons.py``
--------------------------------
那一层是照语文长出来的：拼音行合并、生字条剥离、作者与朝代、古诗断句……
数学和科学一条都用不上，反而会误伤——数学正文里的 ``1.``、``＋ － × ÷``、
科学正文里的实验步骤编号，都会被当成课文的段落标记处理掉。

所以这里另起一层，只做三件事，且都可判定：
  1. 按骨架的印刷页码切出每小节的页区间；
  2. 洗掉页眉页脚与重复页眉，还原正文；
  3. 按教材自身的栏目词（例1 / 做一做 / 练习 / 实验 / 研讨）分块，
     供检索时直接定位"这节的例题在哪"。

产物 data/attrs/section_text.jsonl，主键 section_id（= 骨架的 lesson_id）。
"""

from __future__ import annotations

import json
import os
import re

from .. import config
from . import lessons as L
from . import outline as ol

SECTION_FILE = os.path.join(config.ATTRS_DIR, "section_text.jsonl")

# 页眉：年级/学科/书名/版本常成行出现在每页顶部，保留会污染正文
RE_HEAD = re.compile(
    r"^(义务教育教科书|义务教育|数学|科学|年级|上册|下册|全一册"
    r"|人教版|教科版|北师大版|苏教版|人民教育出版社|浙江教育出版社)"
)
# 栏目锚点：教材自己写的分块标记，比任何启发式都可靠
RE_EXAMPLE = re.compile(r"^\s*例\s*题?\s*(\d+)?|^\s*例\s*(\d+)")
RE_DRILL = re.compile(r"^\s*(做一做|做—做|练一练)")
RE_EXERCISE = re.compile(r"^\s*练\s*习\s*([一二三四五六七八九十\d]+)?"
                         r"|^\s*复习\s*([一二三四五六七八九十\d]+)?"
                         r"|^\s*整理和?复习|^\s*复习与关联")
# 科学的栏目：实验/观察/研讨/拓展/探究/制作
RE_SCI = re.compile(r"^\s*(实验|观察|研讨|拓展|探究|制作|交流|调查|游戏)")
# 题号行：数学正文大量 `1.` `2.` `（1）`，是天然的分块起点
RE_ITEM = re.compile(r"^\s*(?:\d{1,2}[.、．]|[（(]\s*\d{1,2}\s*[)）])")


def _clean(lines: list[str]) -> list[str]:
    """去页眉页脚、空行与印刷页码孤行。"""
    out = []
    for ln in lines:
        s = ln.strip()
        if not s or L.RE_FOOTER.search(s) or RE_HEAD.match(s):
            continue
        out.append(s)
    return out


def _blocks(lines: list[str]) -> list[dict]:
    """按栏目锚点分块：例题 / 练习 / 实验等，检索时能直接定位。"""
    out, cur = [], {"kind": "正文", "lines": []}

    def flush():
        if cur["lines"]:
            out.append({"kind": cur["kind"], "text": "\n".join(cur["lines"])})
        cur["lines"] = []

    for ln in lines:
        if RE_EXAMPLE.match(ln):
            flush()
            cur["kind"] = "例题"
        elif RE_EXERCISE.search(ln):
            flush()
            cur["kind"] = "练习"
        elif RE_DRILL.match(ln):
            flush()
            cur["kind"] = "随堂练"
        elif RE_SCI.match(ln):
            flush()
            cur["kind"] = RE_SCI.match(ln).group(1)
        cur["lines"].append(ln)
    flush()
    return [b for b in out if b["text"].strip()]


def _norm(s: str) -> str:
    """单元名归一化：全角波浪/空格/破折号的不同写法会让页眉字符串对不上。

    实测一年级单元"6~10的认识和加、减法"在目录里是半角 `~`、版面上印全角
    `～`，不做归一化时整单元的锚点为 0，区间只能靠夹逼补出来。
    """
    s = (s or "").replace("～", "~").replace("－", "-").replace("　", "")
    # 引号：目录是 VLM 看图抄的，抄成直引号 `Mike's`；教材正文印的是弯引号
    # `Mike’s`。不统一的话整条锚点落空——六下 Recycle 就因此丢了起点，只能靠
    # 夹逼顶到上一单元的尾巴上（Then and now 被挤成 2 页）。
    for a, b in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"')):
        s = s.replace(a, b)
    return re.sub(r"\s+", "", s)


def unit_anchor_spans(pages: list[dict], entries: list[dict], toc_pages=None,
                      max_gap: int = 4, min_cover: float = 0.6,
                      tol: int = 3) -> dict | None:
    """用**页眉上的单元名**给每个目录条目定位页区间。

    为什么要绕开印刷页码
    --------------------
    数学册的页末没有独立页码行（页脚是"仅供个人学习使用"），``_guess_printed_no``
    抓到的是版面里的题号，于是 printed_no 序列忽大忽小，按它切出来的单元会
    张冠李戴——三年级上册"观察物体"的正文里塞进了"分数的初步认识"的内容。

    页眉单元名是教材自己印的：一单元里的每一页（至少每隔一页）都会重复一次。
    取每个单元名命中的**最长连续簇**（复习页会提到别的单元名，是离群点），
    再按目录顺序夹逼，就能得到单调、不重叠的页区间。

    返回 {lesson_id: (page_from, page_to)}；锚点不足以覆盖 min_cover 的条目时
    返回 None，调用方回退到印刷页码方案。
    """
    toc = set(toc_pages or ())
    body = [p for p in pages if isinstance(p.get("page_no"), int)
            and p.get("page_no") not in toc]
    if len(body) < 2 or len(entries) < 2:
        return None
    texts = {p["page_no"]: _norm(p.get("text") or "") for p in body}
    nos = sorted(texts)
    lo, hi = nos[0], nos[-1]
    # 目录给出的预测区间（印刷页码 + 偏移）：单元名会在**别的**单元里被提到
    # （复习页回顾、Recycle 故事跨单元），只取"最长簇"会让簇跨到邻单元去——
    # 实测六下 Recycle「Mike's happy days」的锚点一路铺到 p38，把上一单元挤没了。
    # 故只保留预测区间附近的命中；预测本身不准时（数学的印刷页码就是乱的）
    # 过滤会清空，那时回退到全部命中。
    off = _page_offset(pages, entries, toc_pages)

    def _predict(i: int):
        s = entries[i].get("printed_start")
        if off is None or not isinstance(s, int):
            return None
        e2 = entries[i + 1].get("printed_start") if i + 1 < len(entries) else None
        pe = (e2 + off - 1) if isinstance(e2, int) and e2 > s else hi
        return (max(lo, s + off), min(hi, pe))

    spans: list = []
    for i, e in enumerate(entries):
        name = _norm(e.get("title") or "")
        if len(name) < 2:
            spans.append(None)
            continue
        hits = [n for n in nos if name in texts[n]]
        pr = _predict(i)
        if pr:
            near = [n for n in hits if pr[0] - tol <= n <= pr[1] + tol]
            if near:
                hits = near
        if not hits:
            spans.append(None)
            continue
        best, cur = [hits[0]], [hits[0]]
        for n in hits[1:]:
            if n - cur[-1] <= max_gap:
                cur.append(n)
            else:
                if len(cur) > len(best):
                    best = cur
                cur = [n]
        if len(cur) > len(best):
            best = cur
        spans.append((best[0], best[-1]))

    if sum(1 for s in spans if s) < len(entries) * min_cover:
        return None

    n = len(entries)
    start = [(spans[i][0] if spans[i] else None) for i in range(n)]
    end = [(spans[i][1] if spans[i] else None) for i in range(n)]
    # 前向：缺锚点的单元从上一单元结束的下一页开始
    prev = lo
    for i in range(n):
        if start[i] is None or start[i] < prev:
            start[i] = prev
        prev = (end[i] if end[i] and end[i] >= start[i] else start[i]) + 1
    # 后向：终点一律收到下一单元起点前一页，保证区间单调不重叠。
    # **无条件赋值**（不能只在 end 偏大时收缩）：英语的页眉只印单元号不印标题，
    # 锚点簇退化成单元扉页那一页，只收缩的话区间就永远停在扉页上——实测会把
    # "How tall are you?" 切成 p7-9。单元之间的内容归前一单元，这是教材的排法。
    nxt = hi
    for i in range(n - 1, -1, -1):
        end[i] = nxt
        if start[i] > end[i]:
            end[i] = start[i]
        nxt = start[i] - 1
    start[0] = max(start[0], lo)
    end[-1] = min(end[-1], hi)
    return {entries[i].get("lesson_id"): (start[i], end[i]) for i in range(n)}


def _page_offset(pages: list[dict], entries: list[dict], toc_pages) -> int | None:
    """印刷页码 → 页序 的偏移量（page_no = printed + offset）。

    教材正文的印刷页码与 PDF 页序通常只差一个常数（前面压着封面、编者页、
    目录）。优先从**已经识别出来**的页取中位数；整册一页都没识别出印刷页码
    时（科学有 9 册如此），改用目录起点对齐正文首页：目录里第一条的印刷页码
    就对应目录之后的第一页。
    """
    offs = sorted((p.get("page_no") - p.get("printed_no"))
                  for p in pages
                  if isinstance(p.get("printed_no"), int)
                  and isinstance(p.get("page_no"), int))
    if offs:
        return offs[len(offs) // 2]
    starts = [e.get("printed_start") for e in entries
              if isinstance(e.get("printed_start"), int)]
    if not starts:
        return None
    toc = [int(x) for x in (toc_pages or []) if isinstance(x, (int, float))]
    body_start = (max(toc) + 1) if toc else 0
    return body_start - min(starts)


def _page_no_keys(pages: list[dict], start: int, end: int, off: int) -> list[int]:
    """按偏移量把印刷页码区间换算成页序区间。"""
    return sorted(p.get("page_no") for p in pages
                  if isinstance(p.get("page_no"), int)
                  and start + off <= p.get("page_no") < end + off)


def build_book(book_id: str) -> list[dict]:
    meta, pages = ol.load_book(book_id)
    if not meta:
        return []
    path = os.path.join(config.OUTLINE_DIR, book_id + ".jsonl")
    if not os.path.exists(path):
        return []
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    head = rows[0]
    entries = [r for r in rows[1:] if r.get("type") != "meta"]
    if not entries:
        return []

    # 目录页只能取自**骨架产物**：parsed 的 meta 行里没有 toc_pages，
    # 取错会让"偏移兜底"少掉正文首页这个锚点，整册切不出来。
    toc_pages = set(head.get("toc_pages") or [])
    by = L.printed_index(pages, toc_pages)
    starts_all = [e.get("printed_start") for e in entries
                  if isinstance(e.get("printed_start"), int)]
    # 整册都没有印刷页码时（科学有 9 册如此）不能就此返回——后面还有按偏移
    # 换算页序的兜底，这里退场等于整册不切。
    last_printed = max(by) if by else (max(starts_all) if starts_all else 0)
    # 页眉单元名锚定：数学册的印刷页码抽不准（见 unit_anchor_spans 的说明），
    # 锚定成功时以它为准，否则退回页码方案。
    anchor = unit_anchor_spans(pages, entries, head.get("toc_pages")) or {}
    all_nos = sorted(p.get("page_no") for p in pages
                     if isinstance(p.get("page_no"), int))

    picked: list = []
    out: list = []
    for i, e in enumerate(entries):
        start = e.get("printed_start")
        if not isinstance(start, int):
            continue
        nxt = entries[i + 1].get("printed_start") if i + 1 < len(entries) else None
        end = nxt if isinstance(nxt, int) and nxt > start else last_printed + 1
        # 两条路各取一次，取覆盖页数更多的那条：只认印刷页码会在页码缺失的册
        # 里整节变空（数学一上"5以内数的认识"只落到 1 页、0 字）。
        nos_print = [by[k].get("page_no")
                     for k in sorted(k for k in by if start <= k < end)]
        off = _page_offset(pages, entries, head.get("toc_pages"))
        nos_off = _page_no_keys(pages, start, end, off) if off is not None else []
        nos = nos_print if len(nos_print) >= len(nos_off) else (nos_off or nos_print)
        sp = anchor.get(e.get("lesson_id"))
        nos_anchor = [n for n in all_nos if sp and sp[0] <= n <= sp[1]]
        # 锚定是内容级证据（页里确实印着这个单元名），不是退化成 1 页就以它为准
        if len(nos_anchor) > 1:
            nos = nos_anchor
        if not nos:
            continue
        picked.append((e, start, end, nos))

    # 目录顺序就是教材顺序：任两条目的页区间都不许重叠。三条路（页码/偏移/锚定）
    # 各有各的错法，锚点跨单元时尤其容易把邻单元的页一起吞掉，最后统一裁一刀。
    for i in range(len(picked) - 1, 0, -1):
        nxt = next((p[3][0] for p in picked[i:] if p[3]), None)
        if nxt is None:      # 后面全被裁空了，没有可参照的下界
            continue
        old = picked[i - 1][3]
        cur = [n for n in old if n < nxt]
        if not cur and old:
            # 裁空有两种：①一页上确实印着两个条目（音乐"春景"和"sol mi"同在 p17），
            # 起点没有越界 → 保留共享的那一页；②起点本身就跑到下一节之后去了，
            # 是噪声（目录顺序与页序矛盾）→ 丢掉，别留一段伸进下一节的区间。
            cur = [old[0]] if old[0] <= nxt else []
        picked[i - 1] = (picked[i - 1][0], picked[i - 1][1], picked[i - 1][2], cur)

    by_no = {p.get("page_no"): p for p in pages}
    out = []
    for e, start, end, nos in picked:
        if not nos:          # 被下一节整体盖住的噪声条目，见上面的裁剪
            continue
        per_page = [_clean(L.clean_page_lines((by_no.get(n) or {}).get("text") or ""))
                    for n in nos]
        lines = [ln for ls in per_page for ln in ls]
        text = "\n".join(lines)
        blks = _blocks(lines)
        out.append({
            "section_id": e.get("lesson_id"),
            "book_id": book_id,
            "subject": head.get("subject") or "",
            "grade": head.get("grade") or "",
            "term": head.get("term") or "",
            "unit_no": e.get("unit_no"),
            "unit_name": e.get("unit_name") or "",
            "title": e.get("title") or "",
            "printed_from": start,
            "printed_to": (end - 1) if end > start else start,
            "page_from": nos[0],
            "page_to": nos[-1],
            "n_pages": len(nos),
            "chars": len(text),
            "text": text,
            "blocks": blks,
            "n_examples": sum(1 for b in blks if b["kind"] == "例题"),
            "n_exercises": sum(1 for b in blks if b["kind"] == "练习"),
        })
    return out


def build_all(subject: str = "", verbose: bool = True) -> list[dict]:
    """按学科切分全部册；结果**全量覆盖**写入（骨架变了要跟着变）。"""
    if not os.path.isdir(config.OUTLINE_DIR):
        return []
    ids = sorted(f[:-6] for f in os.listdir(config.OUTLINE_DIR) if f.endswith(".jsonl"))
    keep, out = [], []
    for bid in ids:
        head_path = os.path.join(config.OUTLINE_DIR, bid + ".jsonl")
        head = json.loads(open(head_path, encoding="utf-8").readline())
        if subject and head.get("subject") != subject:
            continue
        rows = build_book(bid)
        if rows:
            keep.append(bid)
            out.extend(rows)
    # 只写本次学科的册：其余册的原产物保留，避免被清空
    if os.path.exists(SECTION_FILE):
        old = [json.loads(l) for l in open(SECTION_FILE, encoding="utf-8") if l.strip()]
        old = [r for r in old if r.get("book_id") not in keep]
    else:
        old = []
    os.makedirs(config.ATTRS_DIR, exist_ok=True)
    with open(SECTION_FILE, "w", encoding="utf-8") as f:
        for r in old + out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if verbose:
        print("小节切分：%d 册 / %d 节 → %s" % (len(keep), len(out), SECTION_FILE))
    return out
