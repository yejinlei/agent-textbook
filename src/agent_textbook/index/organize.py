# -*- coding: utf-8 -*-
"""构建期 LLM 整理层（四层里的第二层）：把切好的原文整理成可教的东西。

整理 = 人读一遍课文就能做的事，不涉及任何课外知识：
  * 结构：把段落归并成几个大段，各给一句话段意，再给一句全文大意；
  * 词语：解释原文里学生可能不懂的词（教材注释没覆盖的部分）。

前置条件：段落必须是干净的正文。这就是上一轮先把课后题、阅读链接、
生字条、图注从正文里分离出去的原因——带着它们做段意就是垃圾进垃圾出。

可校验性落在两处（越界即丢弃，不做修补）：
  * 结构：parts 的起止编号必须连续覆盖全部段落；
  * 词语：被解释的词必须真的在原文里出现，且不与教材已有注释重复。

产物 data/attrs/lesson_structure.jsonl、lesson_glossary.jsonl。
"""

import json
import os
import re
import time

from .. import config
from . import llm

STRUCT_FILE = os.path.join(config.ATTRS_DIR, "lesson_structure.jsonl")
GLOSS_FILE = os.path.join(config.ATTRS_DIR, "lesson_glossary.jsonl")

# 有课文结构可整理的体裁；习作/语文园地/识字/拼音/附录没有段落结构可言
STRUCT_GENRES = ("课文", "现代诗")
# 需要补词语解释的体裁：古诗/文言文的字词是教学重心
GLOSS_GENRES = ("古诗", "文言文")

PROMPT_STRUCT = (
    "你是小学语文教材分析助手。只根据下面给出的课文原文整理，"
    "不要凭记忆补充或改动课文内容。\n\n"
    "【课文】《{title}》（{grade}{term}）\n"
    "【正文段落】共 {n} 段，编号从 0 到 {last}\n"
    "{body}\n\n"
    "任务：\n"
    "1. 把段落归并成若干结构段，每段注明起止段落编号（from/to，含端点）；\n"
    "2. 每个结构段用一句话概括段意，不超过 40 字；\n"
    "3. 用一句话概括全文主要内容，不超过 60 字。\n\n"
    "严格要求：\n"
    "- 第一个结构段 from 必须是 0，最后一个 to 必须是 {last}；\n"
    "- 结构段之间连续不重叠（下一段 from = 上一段 to + 1），覆盖全部段落；\n"
    "- 段意与全文大意只能依据上面的原文；\n"
    "- 段意里**不要用引号**（书名用《》，强调的词语直接写），\n"
    "  引号会破坏 JSON，整条结果会被丢弃。\n\n"
    "只输出一行 JSON，不要任何解释：\n"
    '{{"parts":[{{"from":0,"to":2,"gist":"..."}}],"main_idea":"..."}}'
)

PROMPT_GLOSS = (
    "你是小学语文教材分析助手。下面是一首古诗（或文言文）的原文。\n\n"
    "【课文】《{title}》\n"
    "【原文】\n{text}\n\n"
    "{known}"
    "请解释原文里**学生可能读不懂**的字词。严格要求：\n"
    "1. 只解释原文中出现过的词，1~4 字，不得改写原文；\n"
    "2. 不要重复上面列出的教材已有注释；\n"
    "3. 释义简短，不超过 20 字，用现代汉语；\n"
    "4. 解释不超过 6 个词，挑最要紧的。\n\n"
    '只输出一行 JSON：{{"glossary":[{{"word":"…","sense":"…"}}]}}'
)


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


def _body_text(r: dict, max_chars: int = 4000) -> tuple[str, int]:
    """把段落拼成带编号的输入；返回（文本、段落数）。"""
    ps = r.get("paragraphs") or []
    out, used = [], 0
    for i, p in enumerate(ps):
        if used + len(p) > max_chars:
            break
        out.append("%d: %s" % (i, p))
        used += len(p)
    return "\n".join(out), len(out)


def check_parts(parts: list, n_paras: int) -> str:
    """结构段校验：必须连续覆盖全部段落。返回错误说明，通过返回空串。"""
    if not parts:
        return "结构段为空"
    if parts[0].get("from") != 0:
        return "首段 from=%s 不是 0" % parts[0].get("from")
    if parts[-1].get("to") != n_paras - 1:
        return "末段 to=%s 不是 %d" % (parts[-1].get("to"), n_paras - 1)
    for i, p in enumerate(parts):
        f, t = p.get("from"), p.get("to")
        if not isinstance(f, int) or not isinstance(t, int) or f > t:
            return "第 %d 段编号非法：%s" % (i, p)
        if not (p.get("gist") or "").strip():
            return "第 %d 段缺段意" % i
        if i and f != parts[i - 1].get("to") + 1:
            return "第 %d 段与上一不连续" % i
    return ""


def build_structure(limit: int = 0, force: bool = False,
                    verbose: bool = True) -> dict:
    """段落归并 + 段意 + 全文大意。"""
    metas = _load_meta()
    rows = _load_lessons()
    todo = [r for r in rows
            if (metas.get(r.get("lesson_id")) or {}).get("genre") in STRUCT_GENRES
            and len(r.get("paragraphs") or []) >= 2]
    if not force:
        done = llm.load_done(STRUCT_FILE, "lesson_id")
        todo = [r for r in todo if r.get("lesson_id") not in done]
    if limit:
        todo = todo[:limit]
    if verbose:
        print("待整理结构：%d 篇" % len(todo))
    if not todo:
        return {"ok": 0, "fail": 0, "reject": 0}

    ok = fail = reject = 0
    for i, r in enumerate(todo, 1):
        body, n = _body_text(r)
        if n < 2:
            fail += 1
            continue
        prompt = PROMPT_STRUCT.format(
            title=r.get("title") or "", grade=r.get("grade") or "",
            term=r.get("term") or "", n=n, last=n - 1, body=body)
        try:
            # 长课文（4000 字输入）推理开销大，2048 会让模型吐空
            res = llm.chat(prompt, max_tokens=4096)
            d = llm.parse_json(res.text)
            parts = d.get("parts") or []
            main_idea = (d.get("main_idea") or "").strip()
            err = check_parts(parts, n)
            if err:
                raise ValueError(err)
            if not main_idea:
                raise ValueError("缺全文大意")
            llm.append_jsonl(STRUCT_FILE, {
                "lesson_id": r.get("lesson_id"), "book_id": r.get("book_id"),
                "title": r.get("title"), "n_paragraphs": n,
                "parts": parts, "main_idea": main_idea,
                "model": res.model, "ts": int(time.time()),
            })
            ok += 1
            if verbose:
                print("  [%d/%d] %s → %d 段 / %s" % (
                    i, len(todo), r.get("title"), len(parts), main_idea[:30]))
        except Exception as e:
            # 校验失败与调用失败分开计：前者说明模型没按格式来，值得重试
            if "编号" in str(e) or "段" in str(e):
                reject += 1
            else:
                fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(todo), r.get("title"), e))
    if verbose:
        print("→ %s（成功 %d / 失败 %d / 校验丢弃 %d）"
              % (STRUCT_FILE, ok, fail, reject))
    return {"ok": ok, "fail": fail, "reject": reject}


def _poem_text(r: dict) -> str:
    """取诗句本身，不取粘在篇尾的课后题与注释碎片。

    篇的 text 末尾可能挂着课后题（`…说说《迢迢牵牛星》表达的情感。`）——
    它们与篇题混在同一行，清洗时为了保护篇题不能删。数据保留完整是对的，
    但喂给模型做词语解释时必须只给诗句：取前 8 个短句即可覆盖绝句与律诗，
    课后题那种长句子自然被长度筛掉。
    """
    sents = [s for s in (r.get("sentences") or []) if len(s) <= 30]
    if sents:
        return "".join(sents[:8])
    return (r.get("text") or "")[:600]


def _load_pieces() -> list[dict]:
    fp = os.path.join(config.ATTRS_DIR, "piece.jsonl")
    if not os.path.exists(fp):
        return []
    return [json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]


def build_glossary(limit: int = 0, force: bool = False,
                   verbose: bool = True) -> dict:
    """补教材注释没覆盖的字词解释。

    数据源是 **piece 而不是 lesson**：目录把《寒食》《迢迢牵牛星》也列成了
    条目，但它们 lesson 层的区间是整组诗（同一页），拿它去解释会把
    《迢迢牵牛星》的"迢迢、皎皎"安到《寒食》头上。只有 piece 层真正
    把每一首切开了。
    """
    todo = [p for p in _load_pieces()
            if p.get("kind") in GLOSS_GENRES and (p.get("text") or "").strip()]
    if not force:
        done = llm.load_done(GLOSS_FILE, "piece_id")
        todo = [p for p in todo if p.get("piece_id") not in done]
    if limit:
        todo = todo[:limit]
    if verbose:
        print("待整理词语：%d 篇" % len(todo))
    if not todo:
        return {"ok": 0, "fail": 0, "reject": 0}

    ok = fail = reject = 0
    for i, r in enumerate(todo, 1):
        text = _poem_text(r)
        notes = r.get("notes") or []
        known = ""
        if notes:
            known = "【教材已有注释】\n%s\n\n" % "\n".join(notes[:12])
        prompt = PROMPT_GLOSS.format(title=r.get("title") or "",
                                     text=text, known=known)
        try:
            res = llm.chat(prompt, max_tokens=2048)
            d = llm.parse_json(res.text)
            items = []
            for g in (d.get("glossary") or [])[:6]:
                w = (g.get("word") or "").strip()
                s = (g.get("sense") or "").strip()
                # 可校验：被解释的词必须真的在原文里
                if w and s and w in text and 1 <= len(w) <= 4:
                    items.append({"word": w, "sense": s})
            if not items:
                reject += 1
                if verbose:
                    print("  [%d/%d] %s 无词通过校验" % (i, len(todo), r.get("title")))
                continue
            llm.append_jsonl(GLOSS_FILE, {
                "piece_id": r.get("piece_id"), "lesson_id": r.get("lesson_id"),
                "book_id": r.get("book_id"), "title": r.get("title"),
                "glossary": items, "model": res.model, "ts": int(time.time()),
            })
            ok += 1
            if verbose:
                print("  [%d/%d] %s → %s" % (
                    i, len(todo), r.get("title"),
                    "、".join(x["word"] for x in items)))
        except Exception as e:
            fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(todo), r.get("title"), e))
    if verbose:
        print("→ %s（成功 %d / 失败 %d / 校验丢弃 %d）"
              % (GLOSS_FILE, ok, fail, reject))
    return {"ok": ok, "fail": fail, "reject": reject}
