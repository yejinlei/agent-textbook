# -*- coding: utf-8 -*-
"""数学/科学的知识点层：一节讲什么、有哪些概念与公式。

语文的补充层（字词/译文/作者）是**往原文里添外部知识**，风险在编造；
这一层正好相反——它是**概括已有正文**，模型不该往外想，只该往下压。
所以校验的重点也不同：

  * 摘要必须能在正文里找到依据（不凭记忆写"本册还学过…"这类跨节内容）；
  * 公式必须是正文里出现过的符号式（含 = ＋ － × ÷ 或字母），否则宁可空；
  * 术语解释只收正文里确实出现的词，收不准就少收。

产物 data/attrs/section_keypoints.jsonl，一节一条，主键 section_id。
"""

from __future__ import annotations

import json
import os
import re
import time

from .. import config
from . import llm

KP_FILE = os.path.join(config.ATTRS_DIR, "section_keypoints.jsonl")

RE_HEDGE = re.compile(r"可能|也许|大概|应该是|不确定|估计")
RE_FORMULA = re.compile(r"[=＝]|[\d\+\-×÷]\s*[a-zA-Z]|[a-zA-Z]\s*[=＝]|[＋－]")

PROMPT_KP = (
    "你是小学教材分析助手。只读下面**一节教材的正文**，概括这一节的学习内容。\n\n"
    "教材：{grade}{term}{subject}\n"
    "单元：{unit}\n"
    "小节：{title}\n\n"
    "正文（可能含插图描述，形式为 [图N] 描述：…）：\n"
    "{body}\n\n"
    "严格要求：\n"
    "1. 只概括**这一节正文里写了**的内容，不要凭你自己的知识补充，"
    "不要出现正文里没有的知识点。\n"
    "2. summary：一句话说明这一节学什么（不超过 50 字）。\n"
    "3. points：3~6 条知识点，每条不超过 30 字，按正文出现顺序写。\n"
    "4. formulas：正文里出现过的**算式或数量关系**（如 `长方形面积=长×宽`、"
    "`路程=速度×时间`）。必须用正文里的符号写法；正文里没有就返回空数组。\n"
    "5. terms：正文里出现且需要解释的**关键术语**，最多 5 个，每个一句话解释；"
    "没有就返回空数组。\n"
    "6. 拿不准的宁可不写，不要编。\n\n"
    '只输出一行 JSON：{{"summary":"...","points":["..."],'
    '"formulas":["..."],"terms":[{{"term":"...","gloss":"..."}}]}}'
)


def _body(r: dict, limit: int = 2200) -> str:
    """取正文：开头 + 例题/实验块的开头。

    一节正文动辄三五千字，全塞进去既费 token 又容易让模型抓不住重点；
    但也不能只取开头——例题才是这节的骨架。故开头与例题块各留一段。
    """
    text = r.get("text") or ""
    if len(text) <= limit:
        return text
    head = text[:int(limit * 0.6)]
    blocks = r.get("blocks") or []
    extra = ""
    for b in blocks:
        if b.get("kind") in ("例题", "实验", "探究"):
            extra = b.get("text") or ""
            break
    if not extra:
        for b in blocks:
            if b.get("kind") not in ("正文",):
                extra = b.get("text") or ""
                break
    return (head + "\n…\n" + extra[:int(limit * 0.4)]).strip()


def build(limit: int = 0, force: bool = False, subject: str = "",
          verbose: bool = True) -> dict:
    from . import sections as S

    rows = [json.loads(l) for l in open(S.SECTION_FILE, encoding="utf-8") if l.strip()]
    if subject:
        rows = [r for r in rows if r.get("subject") == subject]
    # 正文太短的不抽（多半是复习页或切残的），抽了也抽不出东西
    rows = [r for r in rows if (r.get("chars") or 0) >= 200]
    if not force:
        done = llm.load_done(KP_FILE, "section_id")
        rows = [r for r in rows if r.get("section_id") not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽知识点：%d 节" % len(rows))
    if not rows:
        return {"ok": 0, "fail": 0, "reject": 0}

    ok = fail = reject = 0
    for i, r in enumerate(rows, 1):
        prompt = PROMPT_KP.format(
            grade=r.get("grade") or "", term=r.get("term") or "",
            subject=r.get("subject") or "", unit=r.get("unit_name") or "",
            title=r.get("title") or "", body=_body(r))
        try:
            res = llm.chat(prompt, max_tokens=2048)
            d = llm.parse_json(res.text)
            summary = (d.get("summary") or "").strip()
            points = [str(x).strip() for x in (d.get("points") or []) if str(x).strip()]
            formulas = [str(x).strip() for x in (d.get("formulas") or []) if str(x).strip()]
            terms = []
            for t in (d.get("terms") or []):
                if isinstance(t, dict) and t.get("term"):
                    terms.append({"term": str(t["term"]).strip(),
                                  "gloss": str(t.get("gloss") or "").strip()})
            if not summary or len(summary) > 60:
                raise ValueError("摘要缺失或过长：%s" % summary[:20])
            if not points:
                raise ValueError("没有知识点")
            if RE_HEDGE.search(summary) or any(RE_HEDGE.search(p) for p in points):
                raise ValueError("含不确定措辞")
            # 公式必须是正文里出现过的符号式，凭空写的直接丢
            body = _body(r)
            formulas = [f for f in formulas
                        if RE_FORMULA.search(f) and (f[:8] in body or f in body)]
            llm.append_jsonl(KP_FILE, {
                "section_id": r.get("section_id"), "book_id": r.get("book_id"),
                "subject": r.get("subject"), "grade": r.get("grade"),
                "term": r.get("term"), "unit_name": r.get("unit_name"),
                "title": r.get("title"), "summary": summary, "points": points,
                "formulas": formulas, "terms": terms,
                "model": res.model, "ts": int(time.time()),
            })
            ok += 1
            if verbose:
                print("  [%d/%d] %s → %s" % (i, len(rows), r.get("title"), summary[:36]))
        except Exception as e:
            if "摘要" in str(e) or "知识点" in str(e) or "不确定" in str(e):
                reject += 1
            else:
                fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(rows), r.get("title"), e))
    if verbose:
        print("→ %s（成功 %d / 失败 %d / 校验丢弃 %d）" % (KP_FILE, ok, fail, reject))
    return {"ok": ok, "fail": fail, "reject": reject}
