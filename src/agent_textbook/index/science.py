# -*- coding: utf-8 -*-
"""科学本体的两个深挖层：实验/探究 + 科学概念。

科学教材的本体不能照搬语文（篇/字词）或数学（公式/例题）：它的知识组织
单位是**探究活动**（提出问题—猜想—实验—现象—结论）和**科学概念**。
所以这里在通用小节层之上再抽两层：

    attrs/experiment.jsonl   一节里的实验/观察/制作/调查，含器材、步骤、
                             控制变量、现象、结论、安全提示
    attrs/concept.jsonl      科学概念：术语 + 定义 + 生活实例 + 常见迷思

只概括正文，**不添补外部知识**：教材没写的一律留空（避免把教参内容
当成教材内容混进来）。
"""

from __future__ import annotations

import json
import os
import time

from .. import config
from . import llm

EXP_FILE = os.path.join(config.ATTRS_DIR, "experiment.jsonl")
CONCEPT_FILE = os.path.join(config.ATTRS_DIR, "concept.jsonl")

EXP_KINDS = ("实验", "观察", "制作", "调查", "模拟", "种植养殖")

PROMPT_EXP = (
    "你是小学科学教材分析助手。只根据下面这段教材正文，把里面的"
    "**探究活动**（实验/观察/制作/调查/模拟）逐个抽出来。\n"
    "只输出 JSON：\n"
    '{{"experiments":[{{"name":"","kind":"实验","purpose":"","materials":[],'
    '"steps":[],"phenomenon":"","conclusion":"",'
    '"variables":{{"changed":"","measured":"","kept":[]}},'
    '"safety":[],"page_hint":""}}]}}\n'
    "要求：\n"
    "1. kind 只能是 实验/观察/制作/调查/模拟/种植养殖 之一。\n"
    "2. steps 是有序数组，每条一句话，照正文顺序，不要合并步骤。\n"
    "3. variables：changed=刻意改变的条件，measured=观察/测量的结果，\n"
    "   kept=保持不变的条件（数组）。正文没写对比实验就都填空。\n"
    "4. 正文里没有探究活动就输出 {{\"experiments\":[]}}。\n"
    "5. 不添补正文之外的知识；教材没写的一律留空。\n\n"
    "年级：{grade}{term}　单元：{unit}　小节：{title}\n\n"
    "正文：\n{body}"
)

PROMPT_CONCEPT = (
    "你是小学科学教材分析助手。只根据下面这段教材正文，抽出**科学概念**。\n"
    "只输出 JSON：\n"
    '{{"concepts":[{{"term":"","definition":"","example":"",'
    '"misconception":"","category":""}}]}}\n'
    "要求：\n"
    "1. term 是教材里出现的科学术语（如 蒸发、食物链、摩擦力、导体）。\n"
    "2. definition 用一句小学生能懂的话解释，照正文意思，不要扩写。\n"
    "3. example 写正文里给出的生活实例；没有就填空。\n"
    "4. misconception 写学生最常见的错误认识（如‘水开了才叫蒸发’），\n"
    "   只在正文有明显暗示时才写，否则填空，不要凭空编。\n"
    "5. category 只能是 物质科学/生命科学/地球与宇宙/技术与工程 之一。\n"
    "6. 一节最多 8 个概念，按正文出现顺序。\n\n"
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


def build_experiments(subject: str = "科学", limit: int = 0, force: bool = False,
                      verbose: bool = True) -> dict:
    rows = _load_sections(subject)
    if not force:
        done = llm.load_done(EXP_FILE, "section_id")
        rows = [r for r in rows if r.get("section_id") not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽探究活动：%d 节" % len(rows))
    ok = fail = nexp = 0
    for i, r in enumerate(rows, 1):
        prompt = PROMPT_EXP.format(
            grade=r.get("grade") or "", term=r.get("term") or "",
            unit=r.get("unit_name") or "", title=r.get("title") or "",
            body=(r.get("text") or "")[:6000])
        try:
            res = llm.chat(prompt, max_tokens=4000)
            data = llm.parse_json(res.text)
            exps = data.get("experiments") or []
            if not exps:
                # 记一条空壳，避免每次重跑都再花一次钱
                llm.append_jsonl(EXP_FILE, {
                    "exp_id": r["section_id"] + ":000",
                    "section_id": r.get("section_id"),
                    "book_id": r.get("book_id"), "subject": r.get("subject"),
                    "grade": r.get("grade"), "term": r.get("term"),
                    "unit_name": r.get("unit_name"), "title": r.get("title"),
                    "name": "", "kind": "", "purpose": "", "materials": [],
                    "steps": [], "phenomenon": "", "conclusion": "",
                    "variables": {}, "safety": [], "page_hint": "",
                    "model": res.model, "ts": int(time.time()),
                })
                ok += 1
                continue
            for k, e in enumerate(exps, 1):
                steps = [str(x).strip() for x in (e.get("steps") or []) if str(x).strip()]
                if not steps:
                    continue
                kind = (e.get("kind") or "").strip()
                llm.append_jsonl(EXP_FILE, {
                    "exp_id": "%s:%02d" % (r["section_id"], k),
                    "section_id": r.get("section_id"),
                    "book_id": r.get("book_id"), "subject": r.get("subject"),
                    "grade": r.get("grade"), "term": r.get("term"),
                    "unit_name": r.get("unit_name"), "title": r.get("title"),
                    "name": (e.get("name") or "").strip()[:60],
                    "kind": kind if kind in EXP_KINDS else "实验",
                    "purpose": (e.get("purpose") or "").strip()[:300],
                    "materials": [str(x).strip() for x in (e.get("materials") or [])][:20],
                    "steps": steps[:20],
                    "phenomenon": (e.get("phenomenon") or "").strip()[:300],
                    "conclusion": (e.get("conclusion") or "").strip()[:300],
                    "variables": e.get("variables") or {},
                    "safety": [str(x).strip() for x in (e.get("safety") or [])][:10],
                    "page_hint": (e.get("page_hint") or "").strip()[:20],
                    "model": res.model, "ts": int(time.time()),
                })
                nexp += 1
            ok += 1
            if verbose:
                print("  [%d/%d] %s → %d 个活动" % (i, len(rows), r.get("title"), len(exps)))
        except Exception as exc:
            fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(rows), r.get("title"), exc))
    if verbose:
        print("→ %s（节 %d / 失败 %d / 活动 %d）" % (EXP_FILE, ok, fail, nexp))
    return {"ok": ok, "fail": fail, "n": nexp}


def build_concepts(subject: str = "科学", limit: int = 0, force: bool = False,
                   verbose: bool = True) -> dict:
    rows = _load_sections(subject)
    if not force:
        done = llm.load_done(CONCEPT_FILE, "section_id")
        rows = [r for r in rows if r.get("section_id") not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽科学概念：%d 节" % len(rows))
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
                    "term": "", "definition": "", "example": "",
                    "misconception": "", "category": "",
                    "model": res.model, "ts": int(time.time()),
                })
                ok += 1
                continue
            for k, c in enumerate(cps, 1):
                term = (c.get("term") or "").strip()
                if not term:
                    continue
                llm.append_jsonl(CONCEPT_FILE, {
                    "concept_id": "%s:%02d" % (r["section_id"], k),
                    "section_id": r.get("section_id"),
                    "book_id": r.get("book_id"), "subject": r.get("subject"),
                    "grade": r.get("grade"), "term": r.get("term"),
                    "unit_name": r.get("unit_name"), "title": r.get("title"),
                    "term": term[:40],
                    "definition": (c.get("definition") or "").strip()[:300],
                    "example": (c.get("example") or "").strip()[:300],
                    "misconception": (c.get("misconception") or "").strip()[:300],
                    "category": (c.get("category") or "").strip()[:20],
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
