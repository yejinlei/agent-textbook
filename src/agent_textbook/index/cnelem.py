# -*- coding: utf-8 -*-
"""语文单元要素：单元导语页上印着的读写要素。

为什么单独抽这一层
------------------
统编语文教材的每个单元，都在**单元导语页**用 ◎ 列出本单元要掌握的语文要素
（阅读要素 + 习作要素），这是教材编者最明确的"这一单元教什么"的表达。可它
不在任何一篇课文里——课文正文、单元目录条目都拿不到，只有单元首页那一页有
（实测 84 个单元，文本层就能读出来，不必看图）。

有了它，"这一单元训练什么能力""这篇课文承载哪个要素"才有据可依，而不是
靠模型从课文里猜。

产物 data/attrs/unit_element.jsonl，一单元一条。
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from .. import config
from ..parse.online import read_book
from . import llm

ELEM_FILE = os.path.join(config.ATTRS_DIR, "unit_element.jsonl")

PROMPT_ELEM = (
    "你是小学语文教材分析助手。下面是教材某个**单元导语页**的正文。\n"
    "统编教材每个单元在导语页上用 ◎ 列出本单元的语文要素（阅读要素、习作要素）。\n"
    "只输出 JSON：\n"
    '{{"reading_focus":"","writing_focus":"","theme":"","points":[],'
    '"unit_title":""}}\n'
    "要求：\n"
    "1. reading_focus 填**阅读/听说类**要素原文"
    "（如'分清内容的主次，体会作者是如何详写主要部分的'）；没有就填空。\n"
    "2. writing_focus 填**习作/表达类**要素原文"
    "（如'习作时注意抓住重点，写出特点'）；没有就填空。\n"
    "3. theme 填单元的人文主题（导语页上方那句话，"
    "如'百里不同风，千里不同俗'）；没有就填空。\n"
    "4. points 数组：导语页上每一条 ◎ 要素的原文，按出现顺序，最多 6 条。\n"
    "5. unit_title 填单元名（如'第一单元'）；拿不准填空。\n"
    "6. **只照抄教材原文**，不要改写、不要扩写、不要自己总结；"
    "页面里没有的就填空，不要编。\n"
    "7. 若正文里同时出现 ◎ 标记和'第X单元'字样，它**一定**是单元导语页，"
    "必须抽、不要 skip；只有确实看不到 ◎ 要素（低年级没有单元导语，"
    "常见的是普通课文页或目录页）才输出 {{\"skip\":true}}。\n\n"
    "年级：{grade}{term}\n\n"
    "单元导语页正文：\n{body}"
)


def _units(subject: str = "语文") -> list[dict]:
    """按 (book_id, unit_no) 归并出每个单元的起始页。

    单元导语页印在单元第一课的**前一页**，所以取该单元最小 page_from 再往前
    推一页；往前两页也备着，有的册在导语页前还夹了半页目录尾巴。
    """
    src = os.path.join(config.ATTRS_DIR, "section_text.jsonl")
    if not os.path.exists(src):
        return []
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if (r.get("subject") or "") == subject]
    best: dict = {}
    for r in rows:
        uno = r.get("unit_no")
        pf = r.get("page_from")
        if not isinstance(pf, int):
            continue
        k = (r.get("book_id"), uno)
        cur = best.get(k)
        if cur is None or pf < cur["page_from"]:
            best[k] = {"page_from": pf, "grade": r.get("grade") or "",
                       "term": r.get("term") or "", "unit_name": r.get("unit_name") or ""}
    out = []
    for (bid, uno), v in best.items():
        out.append({"book_id": bid, "unit_no": uno, **v})
    out.sort(key=lambda r: (r["book_id"], r["unit_no"] if isinstance(r["unit_no"], int) else 0))
    return out


def _page_texts(book_id: str) -> dict[int, str]:
    _, pages = read_book(book_id)
    return {p.get("page_no"): (p.get("text") or "")
            for p in pages if isinstance(p.get("page_no"), int)}


def build(subject: str = "语文", limit: int = 0, force: bool = False,
          verbose: bool = True, workers: int = 6) -> dict:
    units = _units(subject)
    if not force:
        done = llm.load_done(ELEM_FILE, "unit_id")
        units = [u for u in units
                 if "%s:%02d" % (u["book_id"], u["unit_no"] or 0) not in done]
    if limit:
        units = units[:limit]
    if verbose:
        print("待抽单元要素：%d 个单元" % len(units))
    if not units:
        return {"ok": 0, "skip": 0, "fail": 0}

    cache: dict[str, dict[int, str]] = {}
    for u in units:
        cache.setdefault(u["book_id"], _page_texts(u["book_id"]))

    jobs = []
    for u in units:
        texts = cache.get(u["book_id"]) or {}
        # 往前看三页取最像导语页的那页：导语页上必有 ◎ 要素标记和"第X单元"。
        # 只盯 page_from-1 会抓到上一课的尾巴（二年级"我爱阅读"就是这么混进来的）。
        pf = u["page_from"]
        cands = [(n, (texts.get(n) or "").strip()) for n in (pf - 1, pf - 2, pf - 3)]
        cands = [(n, t) for n, t in cands if t]
        if not cands:
            jobs.append((u, "", pf))
            continue
        page, body = max(cands, key=lambda nt: (nt[1].count("◎") * 2
                                                + (1 if "单元" in nt[1] else 0),
                                                len(nt[1])))
        jobs.append((u, body, page))

    results: list = [None] * len(jobs)

    def _ask(i_j: tuple) -> None:
        i, (u, body, page) = i_j
        if len(body) < 20:
            results[i] = ("skip", None, None, "")
            return
        prompt = PROMPT_ELEM.format(grade=u.get("grade") or "",
                                    term=u.get("term") or "", body=body[:1500])
        try:
            res = llm.chat(prompt, max_tokens=1200)
            results[i] = ("ok", llm.parse_json(res.text), res, "")
        except Exception as exc:
            results[i] = ("err", None, None, str(exc))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(_ask, list(enumerate(jobs))))

    ok = skip = fail = 0
    for i, (u, body, page) in enumerate(jobs):
        state, data, res, err = results[i]
        if state != "ok":
            if state == "err":
                fail += 1
                if verbose:
                    print("  [%d/%d] 单元%s 失败：%s"
                          % (i + 1, len(jobs), u.get("unit_no"), err))
            else:
                skip += 1
            continue
        if data.get("skip"):
            skip += 1
            continue
        pts = [str(x).strip()[:120] for x in (data.get("points") or []) if str(x).strip()]
        llm.append_jsonl(ELEM_FILE, {
            "unit_id": "%s:%02d" % (u["book_id"], u["unit_no"] or 0),
            "book_id": u["book_id"], "subject": subject,
            "grade": u.get("grade") or "", "term": u.get("term") or "",
            "unit_no": u["unit_no"], "unit_name": u.get("unit_name") or "",
            "unit_title": (data.get("unit_title") or "").strip()[:40],
            "theme": (data.get("theme") or "").strip()[:80],
            "reading_focus": (data.get("reading_focus") or "").strip()[:160],
            "writing_focus": (data.get("writing_focus") or "").strip()[:160],
            "points": pts[:6],
            "page_no": page,
            "model": res.model, "ts": int(time.time()),
        })
        ok += 1
        if verbose:
            print("  [%d/%d] %s%s 单元%s → 读：%s"
                  % (i + 1, len(jobs), u.get("grade"), u.get("term"), u.get("unit_no"),
                     (data.get("reading_focus") or "(无)")[:40]))
    if verbose:
        print("→ %s（单元 %d / 非导语页 %d / 失败 %d）" % (ELEM_FILE, ok, skip, fail))
    return {"ok": ok, "skip": skip, "fail": fail}
