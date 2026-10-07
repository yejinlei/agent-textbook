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
            sec = None
            for r in mine:
                pf, pt = r.get("page_from"), r.get("page_to")
                if isinstance(pf, int) and isinstance(pt, int) and pf <= pg <= pt:
                    sec = r
                    break
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
                "unit_name": (ls.get("unit") or sec.get("unit_name") or "").strip()[:40],
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
