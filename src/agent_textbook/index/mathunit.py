# -*- coding: utf-8 -*-
"""数学课级切分：把"单元级"小节再拆成教材真实的课时。

为什么需要这一层
----------------
数学骨架只能抽到**单元**（每册 7~11 条）——教材目录本来就只列单元，看图重抽
也一样（实测仍是 9 条）。于是单元级小节里塞了整个单元的页：例题归不到"课"，
公式也只能挂到单元，做动画时无法说清"这道题是哪一课的"。

课时不在目录里，但在版面上有迹可循：人教版数学每一课都从新的一页开始，页顶
是一行短标题（"在校园里找一找""6的乘法口诀"）。规则只能筛出候选（噪声多：
"=" "4×5" "辆车" 也会被当成标题），所以规则筛候选 + LLM 一次判定整册，兼顾
成本与准确率。

产物 data/attrs/subsection.jsonl：主键 subsection_id（= 单元级 section_id + 序号），
带 page_from/page_to，公式层可按页挂回课时。
"""

from __future__ import annotations

import json
import os
import re
import time

from .. import config
from ..parse import vlm
from ..parse.online import find_book
from . import llm
from . import lessons as L
from . import outline as ol
from . import sections as S

SUBSEC_FILE = os.path.join(config.ATTRS_DIR, "subsection.jsonl")

# 候选页首行：短、有汉字、不是页码或算式碎片
RE_CJK = re.compile(r"[\u4e00-\u9fff]")
RE_BAD_HEAD = re.compile(r"^[\d\s=×÷＋+\-－*/、.．○●△□（）()]+$")
# 标题里基本不会出现句中逗号/冒号/问号——出现就是正文片段（"运动场的跑道，通常"）
RE_TAIL_PUNCT = re.compile(r"[。！？，、；：）,:：?？]")

PROMPT = (
    "你是小学数学教材分析助手。下面是某册教材正文里，按版面规则筛出的"
    "「可能是一节课开头」的页面清单。请**对每一页**判断它是不是新一节（课时）"
    "的开始。\n"
    "只输出 JSON：\n"
    '{{"pages":[{{"page":12,"is_start":true,"title":"在教室里玩一玩",'
    '"unit":"数学游戏"}}]}}\n'
    "输入格式：页码 | 该页开头文字\n\n"
    "{cands}\n\n"
    "要求：\n"
    "1. 输入的每一页都要给出一条，is_start 为 true/false，不要漏页、不要新增。\n"
    "2. is_start=true 的条件：这一页是**新一课的第一页**，页顶那行就是课标题。\n"
    "3. title 必须是教材印的课标题：3~16 字的短语，不含逗号、句号、问号、冒号，"
    "也不可以是算式、数字或正文句子片段。\n"
    "   反例（这些都判 false）：'运动场的跑道，通常'、'59千克'、"
    "'想一想：200×3='、'对折次数'、'2. 分数的简单计算'里的题号部分。\n"
    "   正例：'毫米、分米的认识'、'曹冲称象的故事'、'分数的初步认识'、"
    "'数学广角：搭配问题'。\n"
    "4. 上一课的续页、纯练习页、单元扉页的续页都判 false。\n"
    "5. unit 填所属单元名（页眉或上下文判断），判断不出就填空。\n"
    "6. 一课通常占 2~8 页，本册正文约 {npages} 页；若你判出的课之间隔了十几页，"
    "说明中间漏判了，请复查。\n"
)


PROMPT_VLM = (
    "看这一页小学数学教材。判断它是不是**新一课（课时）的第一页**。\n"
    "只输出 JSON，不要解释：\n"
    '{"is_start": true, "title": "课标题", "unit": "单元名"}\n'
    "或\n"
    '{"is_start": false}\n'
    "要求：\n"
    "1. is_start=true 的条件：这一页是一节新课的开始，页面顶部印着课标题。\n"
    "2. title 照抄页面顶部印的课标题，是 3~16 字的短语"
    "（如 毫米、分米的认识 / 曹冲称象的故事 / 数学广角：搭配问题），"
    "不要自己概括，也不要把题目、句子、算式当成标题。\n"
    "3. 上一课的续页、纯练习页、单元扉页的续页、目录和附录都判 false。\n"
    "4. unit 填页眉上的单元名，看不清就填空。\n"
)


def _json_obj(text: str) -> dict:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("回答里没有 JSON 对象")
    return json.loads(s[i:j + 1])


def _candidates(pages: list[dict], toc_pages: set) -> list[tuple[int, str, str]]:
    """规则筛候选：正文区里首行像标题的页。返回 (page_no, 首行, 开头文字)。"""
    out = []
    for p in pages:
        no = p.get("page_no")
        if not isinstance(no, int) or no in toc_pages:
            continue
        lines = [x.strip() for x in (p.get("text") or "").split("\n") if x.strip()]
        if not lines:
            continue
        head = lines[0]
        # 只挡掉明显不是标题的页（纯算式/纯数字行），其余全部交给 VLM：
        # 课起始页的页顶常常先出现插图说明文字，按"首行像标题"筛会漏掉近半的课
        if RE_BAD_HEAD.match(head):
            continue
        if len(re.findall(r"\d", head)) > len(head) / 2:
            continue
        out.append((no, head, " ".join(lines[:6])[:120]))
    return out


def _text_of(pages: list[dict], start: int, end: int) -> tuple[str, list[dict], int]:
    """拼 [start,end] 页的正文，复用切分层的清洗与分块。"""
    by_no = {p.get("page_no"): p for p in pages}
    nos = [n for n in sorted(by_no) if start <= n <= end]
    lines = []
    for n in nos:
        raw = (by_no.get(n) or {}).get("text") or ""
        lines.extend(S._clean(L.clean_page_lines(raw)))
    text = "\n".join(lines)
    return text, S._blocks(lines), len(nos)


def _toc_of(book_id: str) -> set:
    path = os.path.join(config.OUTLINE_DIR, book_id + ".jsonl")
    if not os.path.exists(path):
        return set()
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    return set((rows[0].get("toc_pages") or [])) if rows else set()


def _section_of(secs: list[dict], page: int):
    """按页定位所属单元；页落在单元之间的空档（单元扉页）时归到最近的下一个。

    教材的单元区间是按页眉锚定切的，单元扉页常常落在上一个单元的区间之外，
    硬判"落在区间内"会把整单元的课丢掉（实测三上"观察物体"整单元消失）。
    """
    hit = None
    for r in secs:
        pf, pt = r.get("page_from"), r.get("page_to")
        if isinstance(pf, int) and isinstance(pt, int) and pf <= page <= pt:
            hit = r
            break
    if hit is not None:
        return hit
    nxt = next((r for r in secs if isinstance(r.get("page_from"), int)
                and r.get("page_from") > page), None)
    if nxt is not None:
        return nxt
    return next((r for r in secs if isinstance(r.get("page_to"), int)
                 and r.get("page_to") < page), None)


def _sections_of(subject: str) -> dict[str, list[dict]]:
    sec_path = os.path.join(config.ATTRS_DIR, "section_text.jsonl")
    if not os.path.exists(sec_path):
        return {}
    secs = [json.loads(l) for l in open(sec_path, encoding="utf-8") if l.strip()]
    if subject:
        secs = [r for r in secs if r.get("subject") == subject]
    out: dict[str, list[dict]] = {}
    for r in secs:
        out.setdefault(r.get("book_id"), []).append(r)
    return out


def build(subject: str = "数学", limit: int = 0, force: bool = False,
          verbose: bool = True) -> dict:
    """逐册切课时：规则筛候选 → LLM 判定 → 落到单元级小节下。"""
    sec_path = os.path.join(config.ATTRS_DIR, "section_text.jsonl")
    if not os.path.exists(sec_path):
        return {"ok": 0, "fail": 0, "n": 0}
    secs = [json.loads(l) for l in open(sec_path, encoding="utf-8") if l.strip()]
    if subject:
        secs = [r for r in secs if r.get("subject") == subject]
    books: dict[str, list[dict]] = {}
    for r in secs:
        books.setdefault(r.get("book_id"), []).append(r)

    done = set() if force else llm.load_done(SUBSEC_FILE, "book_id")
    book_ids = [b for b in books if b not in done]
    if limit:
        book_ids = book_ids[:limit]
    if force and book_ids and os.path.exists(SUBSEC_FILE):
        # 重跑的册要先清掉旧记录，否则新旧课时在同一页区间上重叠
        keep = [json.loads(l) for l in open(SUBSEC_FILE, encoding="utf-8")
                if l.strip()]
        keep = [r for r in keep if r.get("book_id") not in set(book_ids)]
        with open(SUBSEC_FILE, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if verbose:
        print("待切课时：%d 册" % len(book_ids))

    ok = fail = nsub = 0
    for i, bid in enumerate(book_ids, 1):
        meta, pages = ol.load_book(bid)
        if not meta or not pages:
            fail += 1
            continue
        head_path = os.path.join(config.OUTLINE_DIR, bid + ".jsonl")
        toc_pages = set()
        if os.path.exists(head_path):
            rows = [json.loads(l) for l in open(head_path, encoding="utf-8") if l.strip()]
            if rows:
                toc_pages = set(rows[0].get("toc_pages") or [])
        cands = _candidates(pages, toc_pages)
        if not cands:
            llm.append_jsonl(SUBSEC_FILE, {
                "book_id": bid, "subject": meta.get("subject") or "",
                "grade": meta.get("grade") or "", "term": meta.get("term") or "",
                "subsection_id": bid + ":000", "section_id": "", "unit_name": "",
                "title": "", "seq": 0, "printed_start": None,
                "page_from": None, "page_to": None, "n_pages": 0, "chars": 0,
                "text": "", "blocks": [], "model": "", "ts": int(time.time()),
            })
            ok += 1
            continue

        # 课标题在文本层里和正文混在一起，规则+文本 LLM 都判不准（recall 太低），
        # 只能逐页看图。候选页每册约 30~40 页，成本可控。
        rec = find_book(bid)
        if not rec or not rec.get("_abs"):
            fail += 1
            continue
        client = vlm.VLMClient()
        seen: dict[int, dict] = {}
        model = ""
        for no, head, ctx in cands:
            last = ""
            for attempt in range(3):
                try:
                    r = vlm.extract_page_vlm(
                        rec["_abs"], no, client=client,
                        prompt=PROMPT_VLM, dpi=110,
                    )
                    obj = _json_obj(r.text)
                    model = r.model
                    if obj.get("is_start") and (obj.get("title") or "").strip():
                        seen[no] = {"page": no,
                                    "title": str(obj.get("title")).strip()[:60],
                                    "unit": str(obj.get("unit") or "").strip()[:40]}
                    break
                except Exception as exc:
                    last = f"{type(exc).__name__}: {exc}"
                    if attempt < 2 and vlm.needs_backoff(last):
                        time.sleep((10, 30)[attempt])
            if verbose and no % 10 == 0:
                print("    候选 p%d 已判 %d 课" % (no, len(seen)))
        lessons = [seen[k] for k in sorted(seen)]

        mine = sorted(books[bid], key=lambda r: r.get("page_from") or 0)
        recs = []
        for k, ls in enumerate(lessons, 1):
            pg = ls["page"]
            sec = _section_of(mine, pg)
            if sec is None:
                continue
            nxt = next((x["page"] for x in lessons[k:] if x["page"] > pg), None)
            end = (nxt - 1) if nxt else (sec.get("page_to") or pg)
            if end > (sec.get("page_to") or pg):
                end = sec.get("page_to") or pg
            text, blks, npages = _text_of(pages, pg, end)
            recs.append({
                "subsection_id": "%s:%02d" % (sec.get("section_id"), k),
                "section_id": sec.get("section_id"),
                "book_id": bid, "subject": meta.get("subject") or "",
                "grade": meta.get("grade") or "", "term": meta.get("term") or "",
                # 单元名只认目录：VLM 填的 unit 有时是"第2单元"甚至课名本身
                "unit_name": (sec.get("title") or "").strip()[:40],
                "title": (ls.get("title") or "").strip()[:60],
                "seq": k, "printed_start": None,
                "page_from": pg, "page_to": end, "n_pages": npages,
                "chars": len(text), "text": text, "blocks": blks,
                "model": model, "ts": int(time.time()),
            })
            nsub += 1
        # 单元扉页（只有单元名、几十字的那页）常被判成一课，并入紧邻的下一课
        merged = []
        for idx, r in enumerate(recs):
            nxt = recs[idx + 1] if idx + 1 < len(recs) else None
            if ((r.get("chars") or 0) < 200 and nxt is not None
                    and (nxt.get("page_from") or 0) <= (r.get("page_to") or 0) + 1):
                nxt["page_from"] = r.get("page_from")
                nxt["text"], nxt["blocks"], nxt["n_pages"] = _text_of(
                    pages, nxt["page_from"], nxt["page_to"])
                nxt["chars"] = len(nxt["text"])
                continue
            merged.append(r)
        recs = merged
        for r in recs:
            llm.append_jsonl(SUBSEC_FILE, r)

        if not recs:
            llm.append_jsonl(SUBSEC_FILE, {
                "book_id": bid, "subject": meta.get("subject") or "",
                "grade": meta.get("grade") or "", "term": meta.get("term") or "",
                "subsection_id": bid + ":000", "section_id": "", "unit_name": "",
                "title": "", "seq": 0, "printed_start": None,
                "page_from": None, "page_to": None, "n_pages": 0, "chars": 0,
                "text": "", "blocks": [], "model": model, "ts": int(time.time()),
            })
        ok += 1
        if verbose:
            print("  [%d/%d] %s → %d 课（候选 %d 页）"
                  % (i, len(book_ids), meta.get("title"), len(recs), len(cands)))
    if verbose:
        print("→ %s（册 %d / 失败 %d / 课时 %d）" % (SUBSEC_FILE, ok, fail, nsub))
    return {"ok": ok, "fail": fail, "n": nsub}


def retag(subject: str = "数学", verbose: bool = True) -> dict:
    """单元区间修好后，把已切出的课时重新挂回正确的单元下。

    sections 早先按印刷页码切区间，而数学册的 printed_no 是乱的（取到的是版面
    题号），课时归属跟着错：单元名填成"第2单元"、甚至整单元的课被丢掉。区间
    改成页眉锚定之后重挂一次即可，不必再付一遍 VLM 判页的成本。
    """
    books = _sections_of(subject)
    if not books or not os.path.exists(SUBSEC_FILE):
        return {"ok": 0, "n": 0}
    old = [json.loads(l) for l in open(SUBSEC_FILE, encoding="utf-8") if l.strip()]
    subs: dict[str, list[dict]] = {}
    for r in old:
        if r.get("title") and r.get("book_id") in books:
            subs.setdefault(r.get("book_id"), []).append(r)

    new: list[dict] = []
    for bid, rows in subs.items():
        meta, pages = ol.load_book(bid)
        if not pages:
            continue
        mine = sorted(books[bid], key=lambda r: r.get("page_from") or 0)
        for r in rows:
            r["_sec"] = _section_of(mine, r.get("page_from") or 0)
        groups: dict[str, list[dict]] = {}
        for r in rows:
            sec = r.get("_sec")
            if sec is None:
                continue
            groups.setdefault(sec.get("section_id") or "", []).append(r)
        for sid, grp in groups.items():
            grp.sort(key=lambda r: r.get("page_from") or 0)
            sec = grp[0]["_sec"]
            for k, r in enumerate(grp, 1):
                pf = r.get("page_from")
                nxt = grp[k].get("page_from") if k < len(grp) else None
                pt = (nxt - 1) if isinstance(nxt, int) else (sec.get("page_to") or pf)
                hi = sec.get("page_to")
                if isinstance(hi, int) and (pt > hi or not isinstance(pt, int)):
                    pt = hi
                text, blks, npages = _text_of(pages, pf, pt)
                r.update(section_id=sec.get("section_id"),
                         subsection_id="%s:%02d" % (sec.get("section_id"), k),
                         unit_name=(sec.get("title") or "")[:40], seq=k,
                         # 年级学期只认目录：parsed 的 meta 里这两项是空的
                         grade=sec.get("grade") or r.get("grade") or "",
                         term=sec.get("term") or r.get("term") or "",
                         page_to=pt, n_pages=npages, chars=len(text),
                         text=text, blocks=blks)
                r.pop("_sec", None)
                new.append(r)
        if verbose:
            print("  %s%s → %d 课" % (meta.get("grade") or "", meta.get("term") or "",
                                      len([x for x in new if x.get("book_id") == bid])))
    done = set(id(r) for r in new)
    keep = [r for r in old if id(r) in done or not (
        r.get("title") and r.get("book_id") in books)]
    with open(SUBSEC_FILE, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if verbose:
        print("→ %s（重挂 %d 课）" % (SUBSEC_FILE, len(new)))
    return {"ok": len(subs), "n": len(new)}


PROMPT_GAP = (
    "看这一页小学数学教材。它位于前后两节课之间的空档里，上一轮没有判成新课。\n"
    "请判断这一页是不是某一节课（含复习课、实践活动课、整理与复习）的**第一页**。\n"
    "只输出 JSON，不要解释：\n"
    '{"is_start": true, "title": "课标题", "unit": "单元名"}\n'
    "或\n"
    '{"is_start": false}\n'
    "要求：\n"
    "1. 页面顶部印有课标题（3~16 字短语）就判 true，title 照抄标题。\n"
    "2. 上一课的续页、练习页、单元扉页续页、目录附录都判 false。\n"
    "3. 拿不准就判 false。\n"
)


def fill_gaps(subject: str = "数学", min_gap: int = 2, inner_span: int = 5,
              dpi: int = 150, limit: int = 0, verbose: bool = True) -> dict:
    """补漏：漏判的课起始页再判一次。

    查两类页：
      1. 课时之间没被任何课覆盖的空档页（连续段短于 min_gap 的跳过）；
      2. **跨度大的课的内部页** —— 课数偏少的主因不是覆盖不足，而是相邻几课
         被并成了一课（实测空档只有 9 页/册，但课跨十几页）。所以页数超过
         inner_span 的课，除首页外一律复查。
    只看这两类页，页数少，可以提高 dpi 换准确率。
    """
    books = _sections_of(subject)
    if not books or not os.path.exists(SUBSEC_FILE):
        return {"ok": 0, "fail": 0, "n": 0}
    subs: dict[str, list[dict]] = {}
    for l in open(SUBSEC_FILE, encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get("title"):
            subs.setdefault(r.get("book_id"), []).append(r)
    book_ids = [b for b in books if b in subs]
    if limit:
        book_ids = book_ids[:limit]
    if verbose:
        print("待补漏：%d 册" % len(book_ids))

    ok = fail = nnew = 0
    for i, bid in enumerate(book_ids, 1):
        meta, pages = ol.load_book(bid)
        if not meta or not pages:
            fail += 1
            continue
        rec = find_book(bid)
        if not rec or not rec.get("_abs"):
            fail += 1
            continue
        toc = _toc_of(bid)
        mine = sorted(books[bid], key=lambda r: r.get("page_from") or 0)
        lo = min((r.get("page_from") for r in mine
                  if isinstance(r.get("page_from"), int)), default=None)
        hi = max((r.get("page_to") for r in mine
                  if isinstance(r.get("page_to"), int)), default=None)
        if lo is None or hi is None:
            ok += 1
            continue
        covered = set()
        inner: set = set()
        for r in subs[bid]:
            pf, pt = r.get("page_from"), r.get("page_to")
            if not (isinstance(pf, int) and isinstance(pt, int)):
                continue
            covered |= set(range(pf, pt + 1))
            # 跨度过长的课：内部很可能藏着没判出来的课起始页
            if pt - pf + 1 >= inner_span:
                inner |= set(range(pf + 1, pt))
        gap = sorted({n for n in range(lo, hi + 1)
                      if n not in covered and n not in toc} | inner)
        # 空档切成连续段，太短的（1 页）通常是上节课的尾巴，跳过
        segs, cur = [], []
        for n in gap:
            if cur and n == cur[-1] + 1:
                cur.append(n)
            else:
                if len(cur) >= min_gap or (cur and cur[0] in inner):
                    segs.append(cur)
                cur = [n]
        if len(cur) >= min_gap or (cur and cur[0] in inner):
            segs.append(cur)
        if not segs:
            ok += 1
            continue

        client = vlm.VLMClient()
        found: dict[int, dict] = {}
        model = ""
        for seg in segs:
            for n in seg:
                for attempt in range(3):
                    try:
                        r = vlm.extract_page_vlm(rec["_abs"], n, client=client,
                                                 prompt=PROMPT_GAP, dpi=dpi)
                        obj = _json_obj(r.text)
                        model = r.model
                        if obj.get("is_start") and (obj.get("title") or "").strip():
                            found[n] = {"page": n,
                                        "title": str(obj.get("title")).strip()[:60],
                                        "unit": str(obj.get("unit") or "").strip()[:40]}
                        break
                    except Exception as exc:
                        if attempt < 2 and vlm.needs_backoff(
                                f"{type(exc).__name__}: {exc}"):
                            time.sleep((10, 30)[attempt])
        if not found:
            ok += 1
            if verbose:
                print("  [%d/%d] %s 空档 %d 页 → 无新课"
                      % (i, len(book_ids), meta.get("title"), len(gap)))
            continue

        # 旧课 + 新课一起重排：page_to 一律改到下一课首页的前一页
        lessons = [{"page": r.get("page_from"), "title": r.get("title"),
                    "unit": r.get("unit_name")} for r in subs[bid]]
        lessons.extend(found.values())
        lessons.sort(key=lambda x: x["page"])
        recs = []
        for k, ls in enumerate(lessons, 1):
            pg = ls["page"]
            sec = _section_of(mine, pg)
            if sec is None:
                continue
            nxt = next((x["page"] for x in lessons[k:] if x["page"] > pg), None)
            end = (nxt - 1) if nxt else (sec.get("page_to") or pg)
            if end > (sec.get("page_to") or pg):
                end = sec.get("page_to") or pg
            text, blks, npages = _text_of(pages, pg, end)
            recs.append({
                "subsection_id": "%s:%02d" % (sec.get("section_id"), k),
                "section_id": sec.get("section_id"), "book_id": bid,
                "subject": meta.get("subject") or "",
                "grade": meta.get("grade") or "", "term": meta.get("term") or "",
                "unit_name": (sec.get("title") or "")[:40],
                "title": (ls.get("title") or "")[:60], "seq": k,
                "printed_start": None, "page_from": pg, "page_to": end,
                "n_pages": npages, "chars": len(text), "text": text,
                "blocks": blks, "model": model, "ts": int(time.time()),
            })
        merged = []
        for idx, r in enumerate(recs):
            nxt = recs[idx + 1] if idx + 1 < len(recs) else None
            if ((r.get("chars") or 0) < 200 and nxt is not None
                    and (nxt.get("page_from") or 0) <= (r.get("page_to") or 0) + 1):
                nxt["page_from"] = r.get("page_from")
                nxt["text"], nxt["blocks"], nxt["n_pages"] = _text_of(
                    pages, nxt["page_from"], nxt["page_to"])
                nxt["chars"] = len(nxt["text"])
                continue
            merged.append(r)
        recs = merged

        keep = [json.loads(l) for l in open(SUBSEC_FILE, encoding="utf-8")
                if l.strip()]
        keep = [r for r in keep if r.get("book_id") != bid]
        keep.extend(recs)
        with open(SUBSEC_FILE, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        nnew += len(found)
        ok += 1
        if verbose:
            print("  [%d/%d] %s 空档 %d 页 → 补 %d 课，共 %d 课"
                  % (i, len(book_ids), meta.get("title"), len(gap),
                     len(found), len(recs)))
    if verbose:
        print("→ %s（册 %d / 失败 %d / 补 %d 课）" % (SUBSEC_FILE, ok, fail, nnew))
    return {"ok": ok, "fail": fail, "n": nnew}
