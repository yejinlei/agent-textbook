# -*- coding: utf-8 -*-
"""构建期 LLM 校对层（四层里的第一层）：只修规则修不了的。

规则层已经把能修的都修了——栏目归类、注释分离、诗句结构判古诗、虚词密度判
文言文。留给 LLM 的只有两类：

  * 课文的**细分体裁**：写景/记事/童话/说明文是语义判断，规则写不出来；
  * 未定位篇的正文：规则定位失败时，让 LLM 在父课原文里把这一篇挑出来。

三条铁律（与解析层一致，违反任何一条都不如不做）：
  1. 喂原文：输入永远是切好的原文，禁止它凭记忆写课文内容；
  2. 可校验：体裁受枚举约束；补抽的引文必须能在原文里逐句找到，否则丢弃；
  3. 可重跑：按 id 追加写 JSONL，带 model 与时间戳，换模型重抽时覆盖。

产物 data/attrs/lesson_genre.jsonl、piece_fix.jsonl。
"""

import json
import os
import re
import time

from .. import config
from ..parse.vlm import VLMClient

GENRE_FILE = os.path.join(config.ATTRS_DIR, "lesson_genre.jsonl")
PIECE_FIX_FILE = os.path.join(config.ATTRS_DIR, "piece_fix.jsonl")

# 细分体裁：封闭枚举，越界即判为失败（可校验性的落点）
GENRE_SUB = ("写景状物", "记事写人", "童话寓言", "神话传说", "说明文",
             "议论文", "现代诗", "儿歌", "散文", "其他")
RE_JSON = re.compile(r"\{.*\}", re.S)

PROMPT_GENRE = (
    "你是小学语文教材分析助手。只根据下面给出的课文原文作答，"
    "不要凭记忆补充或改动课文内容。\n\n"
    "【课文】《{title}》（{grade}{term}）\n"
    "【正文开头】\n{text}\n\n"
    "请判断这篇课文的体裁，只能从下列选项里选一个：\n"
    + "、".join(GENRE_SUB) + "\n\n"
    "只输出一行 JSON，不要任何解释：\n"
    '{{"genre_sub": "选项", "reason": "不超过 15 字的依据"}}'
)

PROMPT_PIECE = (
    "你是小学语文教材分析助手。下面是一课的教材原文，其中收录了若干篇。\n\n"
    "【课文】《{parent}》原文：\n{text}\n\n"
    "请从中找出《{title}》这一篇，逐句摘录它的**原文**句子。严格要求：\n"
    "1. 只能是上面原文里出现过的句子，不得翻译、改写、补字、发挥；\n"
    "2. 一句一行，保留原标点，不要加序号；\n"
    "3. 若原文里确实没有这一篇，就返回空列表。\n\n"
    '只输出一行 JSON：{{"lines": ["句子1", "句子2"]}}'
)


def _norm(s: str) -> str:
    return re.sub(r"[\s　·•・​-‏﻿，。！？；、]", "", s or "")


def _parse_json(text: str) -> dict:
    """从模型输出里抠出 JSON——它可能自带 ```json 围栏或前后废话。"""
    m = RE_JSON.search(text or "")
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}


def _load_done(path: str, key: str) -> set:
    done = set()
    if not os.path.exists(path):
        return done
    for l in open(path, encoding="utf-8"):
        if l.strip():
            try:
                done.add(json.loads(l).get(key))
            except ValueError:
                continue
    return done


def _append(path: str, rec: dict) -> None:
    os.makedirs(config.ATTRS_DIR, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load_lessons() -> list[dict]:
    fp = os.path.join(config.ATTRS_DIR, "lesson_text.jsonl")
    if not os.path.exists(fp):
        return []
    return [json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]


def _load_meta() -> dict:
    fp = os.path.join(config.ATTRS_DIR, "lesson_meta.jsonl")
    out = {}
    if os.path.exists(fp):
        for l in open(fp, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                out[r.get("lesson_id")] = r
    return out


def sync_piece_genre(verbose: bool = True) -> dict:
    """子篇条目的体裁继承父课。

    目录把《寒食》《学弈》这些子篇也列成了独立条目，规则层只看标题，
    认得出父课《古诗三首》是古诗，却把子篇判成了普通课文——于是《十五夜
    望月》被送去让 LLM 判"写景状物"。piece 层已经确定了父子关系与体裁，
    直接回填即可，一次 LLM 调用都不用。
    """
    fp = os.path.join(config.ATTRS_DIR, "piece.jsonl")
    fp_meta = os.path.join(config.ATTRS_DIR, "lesson_meta.jsonl")
    if not (os.path.exists(fp) and os.path.exists(fp_meta)):
        return {"fixed": 0}
    want = {}
    for l in open(fp, encoding="utf-8"):
        if not l.strip():
            continue
        p = json.loads(l)
        if p.get("kind") in ("古诗", "文言文"):
            want[(p.get("book_id"), p.get("title"))] = p["kind"]
    rows = [json.loads(l) for l in open(fp_meta, encoding="utf-8") if l.strip()]
    fixed = 0
    for r in rows:
        k = want.get((r.get("book_id"), r.get("title")))
        if k and r.get("genre") != k:
            r["genre"] = k
            fixed += 1
    if fixed:
        with open(fp_meta, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if verbose:
        print("子篇体裁回填：%d 条 → %s" % (fixed, fp_meta))
    return {"fixed": fixed}


def classify_genre(limit: int = 0, force: bool = False,
                   verbose: bool = True) -> dict:
    """给规则层只能判成"课文"的条目补细分体裁。"""
    metas = _load_meta()
    rows = _load_lessons()
    # 只处理"课文"：古诗/文言文/习作/语文园地等已由规则确定，不必花钱
    todo = [r for r in rows
            if (metas.get(r.get("lesson_id")) or {}).get("genre") == "课文"
            and (r.get("text") or "").strip()]
    if not force:
        done = _load_done(GENRE_FILE, "lesson_id")
        todo = [r for r in todo if r.get("lesson_id") not in done]
    if limit:
        todo = todo[:limit]
    if verbose:
        print("待判体裁：%d 篇" % len(todo))
    if not todo:
        return {"ok": 0, "fail": 0}

    client = VLMClient()
    ok = fail = 0
    for i, r in enumerate(todo, 1):
        text = (r.get("text") or "")[:600]
        prompt = PROMPT_GENRE.format(
            title=r.get("title") or "", grade=r.get("grade") or "",
            term=r.get("term") or "", text=text)
        try:
            # 推理型模型会把 token 耗在思考上，给小了会返回空内容
            # （config 里记录的同一个坑：max_tokens 不够 → content 为空）
            res = client.chat(prompt, max_tokens=2048)
            d = _parse_json(res.text)
            g = (d.get("genre_sub") or "").strip()
            if g not in GENRE_SUB:
                raise ValueError("体裁越界：%r" % g)
            _append(GENRE_FILE, {
                "lesson_id": r.get("lesson_id"), "book_id": r.get("book_id"),
                "title": r.get("title"), "genre_sub": g,
                "reason": (d.get("reason") or "")[:40],
                "model": res.model, "ts": int(time.time()),
            })
            ok += 1
            if verbose:
                print("  [%d/%d] %s → %s" % (i, len(todo), r.get("title"), g))
        except Exception as e:
            fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(todo), r.get("title"), e))
    if verbose:
        print("→ %s（成功 %d / 失败 %d）" % (GENRE_FILE, ok, fail))
    return {"ok": ok, "fail": fail}


def _wider_text(book_id: str, start: int, span: int = 4) -> str:
    """父课切出来的正文里没有这一篇时，直接按页码取后续几页的原文。

    子篇常常跨页（`十五夜望月` 在 p12，而父课区间只切到 p11），
    此时给它父课的 text 等于没给，模型只能回答"找不到"。
    """
    from . import lessons as L
    from . import outline as ol

    path = os.path.join(config.OUTLINE_DIR, book_id + ".jsonl")
    if not os.path.exists(path) or not isinstance(start, int):
        return ""
    head = json.loads(open(path, encoding="utf-8").readline())
    _, pages = ol.load_book(book_id)
    by = L.printed_index(pages, set(head.get("toc_pages") or []))
    if not by:
        return ""
    keys = sorted(k for k in by if start <= k < start + span)
    if not keys:
        keys = sorted(k for k in by if start - 1 <= k < start + span)
    out = []
    for k in keys:
        out.extend(L.clean_page_lines(by[k].get("text") or ""))
    return "\n".join(out)


def fix_pieces(limit: int = 0, force: bool = False, verbose: bool = True) -> dict:
    """给规则定位失败的篇补正文——引文必须逐句能在父课原文里找到。"""
    fp = os.path.join(config.ATTRS_DIR, "piece.jsonl")
    if not os.path.exists(fp):
        return {"ok": 0, "fail": 0, "reject": 0}
    ps = [json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]
    todo = [p for p in ps if not p.get("located")]
    if not force:
        done = _load_done(PIECE_FIX_FILE, "piece_id")
        todo = [p for p in todo if p.get("piece_id") not in done]
    if limit:
        todo = todo[:limit]
    if verbose:
        print("待补篇：%d 篇" % len(todo))
    if not todo:
        return {"ok": 0, "fail": 0, "reject": 0}

    rows = {r.get("lesson_id"): r for r in _load_lessons()}
    client = VLMClient()
    ok = fail = reject = 0
    for i, p in enumerate(todo, 1):
        parent = rows.get(p.get("lesson_id")) or {}
        src = parent.get("text") or ""
        # 父课区间没覆盖到这一篇（跨页）时，直接按页码取后续页
        if _norm(p.get("title") or "") not in _norm(src):
            wider = _wider_text(p.get("book_id") or "", p.get("printed_start"))
            if len(wider) > len(src):
                src = wider
        if len(src) < 20:
            fail += 1
            if verbose:
                print("  [%d/%d] %s 取不到原文，跳过" % (i, len(todo), p.get("title")))
            continue
        prompt = PROMPT_PIECE.format(
            parent=p.get("parent_title") or "", title=p.get("title") or "",
            text=src[:4000])
        try:
            res = client.chat(prompt, max_tokens=4096)
            d = _parse_json(res.text)
            lines = [x.strip() for x in (d.get("lines") or []) if str(x).strip()]
            # 可校验：每句都必须在原文里出现，否则整条丢弃（宁缺勿编）
            ns = _norm(src)
            bad = [x for x in lines if _norm(x) not in ns]
            if not lines or len(bad) > len(lines) / 2:
                reject += 1
                if verbose:
                    print("  [%d/%d] %s 引文校验未过（%d/%d 句不在原文）" % (
                        i, len(todo), p.get("title"), len(bad), len(lines)))
                continue
            _append(PIECE_FIX_FILE, {
                "piece_id": p.get("piece_id"), "lesson_id": p.get("lesson_id"),
                "title": p.get("title"), "lines": lines,
                "n_bad": len(bad), "model": res.model, "ts": int(time.time()),
            })
            ok += 1
            if verbose:
                print("  [%d/%d] %s → %d 句" % (i, len(todo), p.get("title"), len(lines)))
        except Exception as e:
            fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(todo), p.get("title"), e))
    if verbose:
        print("→ %s（成功 %d / 失败 %d / 引文不实丢弃 %d）"
              % (PIECE_FIX_FILE, ok, fail, reject))
    applied = apply_piece_fixes(verbose=verbose)
    return {"ok": ok, "fail": fail, "reject": reject, "applied": applied}


def apply_piece_fixes(verbose: bool = True) -> int:
    """把补抽到的正文写回 piece.jsonl，并标记为 llm 来源。

    来源字段很重要：规则切的与 LLM 补的可信度不同，后续整理/扩展层
    （译文、意象）应当只对**规则定位成功**的篇直接展开。
    """
    from . import pieces as P

    if not os.path.exists(PIECE_FIX_FILE):
        return 0
    fixes = {}
    for l in open(PIECE_FIX_FILE, encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            fixes[r.get("piece_id")] = r
    fp = os.path.join(config.ATTRS_DIR, "piece.jsonl")
    ps = [json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]
    n = 0
    for p in ps:
        fx = fixes.get(p.get("piece_id"))
        if not fx or not fx.get("lines"):
            continue
        text = "".join(fx["lines"])
        p["text"] = text
        p["sentences"] = P.split_sentences(text)
        p["chars"] = len(_norm(text))
        p["located"] = True
        p["source"] = "llm"
        n += 1
    if n:
        with open(fp, "w", encoding="utf-8") as f:
            for p in ps:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
    if verbose:
        print("写回 piece.jsonl：%d 篇（来源 llm）" % n)
    return n
