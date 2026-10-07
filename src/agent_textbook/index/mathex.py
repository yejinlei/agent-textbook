# -*- coding: utf-8 -*-
"""数学本体的两个深挖层：例题（含解题步骤） + 数学概念。

数学的知识组织单位是**例题**：教材靠"例 1 / 做一做 / 练习"把概念落成可操作
的过程。要做公式动画，光有 LaTeX 不够——必须知道这条公式出现在哪道题的哪
一步、用来干什么。所以本模块抽：

    attrs/example.jsonl    例题：题面、已知、要求、分步解法、答案、题型，
                           并把本节已抽出的 LaTeX 公式按页挂到 formula_refs
    attrs/concept.jsonl    数学概念：术语 + 定义 + 符号表示 + 性质 + 易错点
                           （与科学概念同表，用 subject/category 区分）

为什么例题用文本层而不是看图
----------------------------
数学正文文本层里公式是坏的（分数被拆成两行），但**题面叙述是完整的**
（"小华身高1米3分米。只用'米'作单位怎样表示？"）。所以结构用文本层抽（便宜、
快），公式由 formula 层补齐（那层是逐页看图抽的，LAteX 准确），两者用
(section_id, page_no) 对齐。
"""

from __future__ import annotations

import json
import os
import time

from .. import config
from . import llm

EXAMPLE_FILE = os.path.join(config.ATTRS_DIR, "example.jsonl")
CONCEPT_FILE = os.path.join(config.ATTRS_DIR, "concept.jsonl")
FORMULA_FILE = os.path.join(config.ATTRS_DIR, "section_formula.jsonl")

EX_TYPES = ("例题", "做一做", "练习", "思考题", "复习题", "生活中的数学")

# 数学概念的四大领域，与科学概念的 category（物质科学等）互不冲突
CONCEPT_CATS = ("数与代数", "图形与几何", "统计与概率", "综合与实践")

PROMPT_EXAMPLE = (
    "你是小学数学教材分析助手。只根据下面这段教材正文，把里面的**题目**"
    "（例题、做一做、练习题、思考题）逐个抽出来。\n"
    "只输出 JSON：\n"
    '{{"examples":[{{"title":"","type":"例题","stem":"","given":"","ask":"",'
    '"steps":[{{"text":"","latex":""}}],"latex":[],"answer":"",'
    '"answer_latex":"","keypoint":"","difficulty":"","page_hint":""}}]}}\n'
    "要求：\n"
    "1. type 只能是 例题/做一做/练习/思考题/复习题/生活中的数学 之一；"
    "教材印着'例1'的是例题，'做一做'单独算一条。\n"
    "2. stem 是完整的题目原文（含数字和条件），不要改写。\n"
    "3. given/ask 分别填已知条件和所求；没有就填空。\n"
    "4. steps 是有序数组，一步一个元素：text 写这一步在算什么（如'把1米平均"
    "分成10份，每份是1分米'），latex 写这一步对应的算式（如 1\\\\div 10=0.1）；"
    "不要合并步骤，也不要跳步。\n"
    "5. latex 数组写这道题里出现的算式/公式，按出现顺序"
    "（如 \\\\frac{{1}}{{2}}、24\\\\div 6=4、S=a\\\\times b）。\n"
    "6. answer 写最终答案（含单位）；answer_latex 写答案对应的 LaTeX，"
    "没有公式就填空。\n"
    "7. keypoint 写这道题考的知识点（如'分母是10的分数改写为小数'），10字内。\n"
    "8. difficulty 只能是 基础/提高/拓展 之一，按教材中的位置判断。\n"
    "9. page_hint 写题目在教材里的位置（页码或栏目名，如'练习二'）；拿不准就填空。\n"
    "10. 正文里只有讲解没有题目就输出 {{\"examples\":[]}}；"
    "一节最多 10 道题，按出现顺序。\n"
    "11. 不添补正文之外的题目；正文里竖排分数被拆坏看不清时，latex 留空，不要猜。\n\n"
    "年级：{grade}{term}　单元：{unit}　小节：{title}\n\n"
    "正文：\n{body}"
)

PROMPT_CONCEPT = (
    "你是小学数学教材分析助手。只根据下面这段教材正文，抽出**数学概念**。\n"
    "只输出 JSON：\n"
    '{{"concepts":[{{"term":"","definition":"","symbol":"",'
    '"property":"","example":"","misconception":"","category":""}}]}}\n'
    "要求：\n"
    "1. term 是教材里出现的数学概念/术语（如 小数、面积、平行、平均数、方程）。\n"
    "2. definition 用一句小学生能懂的话解释，照正文意思，不要扩写。\n"
    "3. symbol 写这个概念在教材里的数学表示：数字、字母表达式或 LaTeX"
    "（如 0.1、S=a×b、\\\\frac{{1}}{{10}}）；没有就填空。\n"
    "4. property 写性质/法则/注意点（如'小数末尾添上0或去掉0，小数的大小不变'）。\n"
    "5. example 写正文给出的例子；没有就填空。\n"
    "6. misconception 写最常见的错误认识（如'小数都比1小'），"
    "只在正文有明显暗示时才写，否则填空，不要凭空编。\n"
    "7. category 只能是 数与代数/图形与几何/统计与概率/综合与实践 之一。\n"
    "8. 一节最多 8 个概念，按正文出现顺序。\n\n"
    "年级：{grade}{term}　单元：{unit}　小节：{title}\n\n"
    "正文：\n{body}"
)


def _load_sections(subject: str) -> list[dict]:
    src = os.path.join(config.ATTRS_DIR, "section_text.jsonl")
    if not os.path.exists(src):
        return []
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    if subject:
        rows = [r for r in rows if r.get("subject") == subject]
    return [r for r in rows if (r.get("text") or "").strip()]


def _formula_index() -> dict[str, list[str]]:
    """section_id → 本节已抽出的 LaTeX 列表（按页、按序号排好）。

    例题本身拿不到 LaTeX（文本层里公式是坏的），用这层把公式挂回来，
    动画才有东西可渲染。
    """
    idx: dict[str, list[str]] = {}
    if not os.path.exists(FORMULA_FILE):
        return idx
    for l in open(FORMULA_FILE, encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        tex = (r.get("latex") or "").strip()
        if not tex:
            continue
        idx.setdefault(r.get("section_id") or "", []).append(tex)
    return idx


def build_examples(subject: str = "数学", limit: int = 0, force: bool = False,
                   verbose: bool = True) -> dict:
    rows = _load_sections(subject)
    if not force:
        done = llm.load_done(EXAMPLE_FILE, "section_id")
        rows = [r for r in rows if r.get("section_id") not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽例题：%d 节" % len(rows))
    fidx = _formula_index()
    ok = fail = nexp = 0
    for i, r in enumerate(rows, 1):
        prompt = PROMPT_EXAMPLE.format(
            grade=r.get("grade") or "", term=r.get("term") or "",
            unit=r.get("unit_name") or "", title=r.get("title") or "",
            body=(r.get("text") or "")[:6000])
        try:
            res = llm.chat(prompt, max_tokens=4000)
            data = llm.parse_json(res.text)
            exs = data.get("examples") or []
            refs = fidx.get(r.get("section_id"), [])[:12]
            if not exs:
                llm.append_jsonl(EXAMPLE_FILE, {
                    "example_id": r["section_id"] + ":000",
                    "section_id": r.get("section_id"),
                    "book_id": r.get("book_id"), "subject": r.get("subject"),
                    "grade": r.get("grade"), "term": r.get("term"),
                    "unit_name": r.get("unit_name"), "title": r.get("title"),
                    "name": "", "type": "", "stem": "", "given": "", "ask": "",
                    "steps": [], "latex": [], "answer": "", "answer_latex": "",
                    "keypoint": "", "difficulty": "", "page_hint": "",
                    "formula_refs": refs,
                    "model": res.model, "ts": int(time.time()),
                })
                ok += 1
                continue
            for k, e in enumerate(exs, 1):
                stem = (e.get("stem") or "").strip()
                if not stem:
                    continue
                # 步骤允许两种写法：纯字符串，或 {text, latex}（后者带算式，动画用）
                steps = []
                for s in (e.get("steps") or []):
                    if isinstance(s, dict):
                        t = (s.get("text") or "").strip()
                        lx = (s.get("latex") or "").strip()
                    else:
                        t, lx = str(s).strip(), ""
                    if t:
                        steps.append({"text": t[:200], "latex": lx[:200]})
                typ = (e.get("type") or "").strip()
                llm.append_jsonl(EXAMPLE_FILE, {
                    "example_id": "%s:%02d" % (r["section_id"], k),
                    "section_id": r.get("section_id"),
                    "book_id": r.get("book_id"), "subject": r.get("subject"),
                    "grade": r.get("grade"), "term": r.get("term"),
                    "unit_name": r.get("unit_name"), "title": r.get("title"),
                    "name": (e.get("title") or "").strip()[:60],
                    "type": typ if typ in EX_TYPES else "例题",
                    "stem": stem[:600],
                    "given": (e.get("given") or "").strip()[:300],
                    "ask": (e.get("ask") or "").strip()[:300],
                    "steps": steps[:20],
                    "latex": [str(x).strip()[:200] for x in (e.get("latex") or [])][:12],
                    "answer": (e.get("answer") or "").strip()[:200],
                    "answer_latex": (e.get("answer_latex") or "").strip()[:200],
                    "keypoint": (e.get("keypoint") or "").strip()[:40],
                    "difficulty": (e.get("difficulty") or "").strip()[:10],
                    "page_hint": (e.get("page_hint") or "").strip()[:20],
                    "formula_refs": refs,
                    "model": res.model, "ts": int(time.time()),
                })
                nexp += 1
            ok += 1
            if verbose:
                print("  [%d/%d] %s → %d 题" % (i, len(rows), r.get("title"), len(exs)))
        except Exception as exc:
            fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(rows), r.get("title"), exc))
    if verbose:
        print("→ %s（节 %d / 失败 %d / 例题 %d）" % (EXAMPLE_FILE, ok, fail, nexp))
    return {"ok": ok, "fail": fail, "n": nexp}


def build_concepts(subject: str = "数学", limit: int = 0, force: bool = False,
                   verbose: bool = True) -> dict:
    """数学概念：与科学概念共用 concept.jsonl，靠 subject/category 区分。"""
    rows = _load_sections(subject)
    if not force:
        done = llm.load_done(CONCEPT_FILE, "section_id")
        rows = [r for r in rows if r.get("section_id") not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽数学概念：%d 节" % len(rows))
    ok = fail = ncp = 0
    for i, r in enumerate(rows, 1):
        prompt = PROMPT_CONCEPT.format(
            grade=r.get("grade") or "", term=r.get("term") or "",
            unit=r.get("unit_name") or "", title=r.get("title") or "",
            body=(r.get("text") or "")[:6000])
        try:
            res = llm.chat(prompt, max_tokens=4000)
            data = llm.parse_json(res.text)
            cps = data.get("concepts") or []
            if not cps:
                llm.append_jsonl(CONCEPT_FILE, {
                    "concept_id": r["section_id"] + ":000",
                    "section_id": r.get("section_id"),
                    "book_id": r.get("book_id"), "subject": r.get("subject"),
                    "grade": r.get("grade"), "term": r.get("term"),
                    "unit_name": r.get("unit_name"), "title": r.get("title"),
                    "term_name": "", "definition": "", "symbol": "",
                    "property": "", "example": "", "misconception": "",
                    "category": "", "model": res.model, "ts": int(time.time()),
                })
                ok += 1
                continue
            for k, c in enumerate(cps, 1):
                term = (c.get("term") or "").strip()
                if not term:
                    continue
                cat = (c.get("category") or "").strip()
                llm.append_jsonl(CONCEPT_FILE, {
                    "concept_id": "%s:%02d" % (r["section_id"], k),
                    "section_id": r.get("section_id"),
                    "book_id": r.get("book_id"), "subject": r.get("subject"),
                    "grade": r.get("grade"), "term": r.get("term"),
                    "unit_name": r.get("unit_name"), "title": r.get("title"),
                    "term_name": term[:40],
                    "definition": (c.get("definition") or "").strip()[:300],
                    "symbol": (c.get("symbol") or "").strip()[:200],
                    "property": (c.get("property") or "").strip()[:300],
                    "example": (c.get("example") or "").strip()[:300],
                    "misconception": (c.get("misconception") or "").strip()[:300],
                    "category": cat if cat in CONCEPT_CATS else "",
                    "model": res.model, "ts": int(time.time()),
                })
                ncp += 1
            ok += 1
            if verbose:
                print("  [%d/%d] %s → %d 个概念" % (i, len(rows), r.get("title"), len(cps)))
        except Exception as exc:
            fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(rows), r.get("title"), exc))
    if verbose:
        print("→ %s（节 %d / 失败 %d / 概念 %d）" % (CONCEPT_FILE, ok, fail, ncp))
    return {"ok": ok, "fail": fail, "n": ncp}
