# -*- coding: utf-8 -*-
"""数学公式属性层：把教材页的公式转成 LaTeX（看图通道）。

为什么必须看图
--------------
数学正文在 PDF 文本层里公式是坏的：分数被拆成上下两行（`1份是这箱矿泉水的3`
+ `1`），有的干脆整段丢失（`每份是这盒苹果的 ，`）。规则补不回来，所以公式
只能逐页渲染成图交给 VLM，产出可直接渲染/做动画的 LaTeX。

产物 data/attrs/section_formula.jsonl：一条公式一条，主键 formula_id
（= 小节:物理页:序号），靠 section_id 挂回小节，靠 (book_id, page_no) 挂回页。
"""

from __future__ import annotations

import json
import os
import time

from .. import config
from ..parse import vlm
from ..parse.online import find_book
from . import llm

ATTR_FILE = os.path.join(config.ATTRS_DIR, "section_formula.jsonl")

KINDS = ("定义", "性质", "法则", "例题", "练习", "计算过程")


def _parse_array(text: str) -> list[dict]:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()
    i = s.find("[")
    if i < 0:
        raise ValueError("回答里没有 JSON 数组")
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "[":
            depth += 1
        elif s[j] == "]":
            depth -= 1
            if depth == 0:
                return json.loads(s[i:j + 1])
    raise ValueError("JSON 数组没有闭合")


def _clean(row: dict) -> dict:
    latex = (str(row.get("latex") or "")).strip().strip("$").strip()
    kind = (str(row.get("kind") or "")).strip()
    if kind not in KINDS:
        kind = "例题" if latex else ""
    return {
        "latex": latex,
        "kind": kind,
        "note": (str(row.get("note") or row.get("desc") or "").strip())[:40],
        "vars": (str(row.get("vars") or "").strip())[:120],
    }


def retag(subject: str = "数学", verbose: bool = True) -> dict:
    """单元页区间修正后，把已抽出的公式重挂到正确的单元。

    公式是逐页看图抽的，latex 本身没错；错的是归属——早先按印刷页码切的小节
    区间是乱的，公式的 section_id/unit_name/title 跟着挂到了别的单元。
    按新的（页眉锚定的）区间重挂这三个字段即可，不必再付一遍 VLM 的成本。
    page_key 与 formula_id 保持不变，续跑时不会重复抽同一页。
    """
    src = os.path.join(config.ATTRS_DIR, "section_text.jsonl")
    if not os.path.exists(src) or not os.path.exists(ATTR_FILE):
        return {"n": 0, "fix": 0}
    secs = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    if subject:
        secs = [r for r in secs if r.get("subject") == subject]
    by_book: dict[str, list[dict]] = {}
    for r in secs:
        by_book.setdefault(r.get("book_id") or "", []).append(r)
    for v in by_book.values():
        v.sort(key=lambda r: r.get("page_from") or 0)

    rows = [json.loads(l) for l in open(ATTR_FILE, encoding="utf-8") if l.strip()]
    nfix = 0
    for r in rows:
        if subject and r.get("subject") != subject:
            continue
        cand = by_book.get(r.get("book_id") or "") or []
        pg = r.get("page_no")
        hit = next((s for s in cand
                    if isinstance(s.get("page_from"), int)
                    and isinstance(s.get("page_to"), int)
                    and isinstance(pg, int)
                    and s["page_from"] <= pg <= s["page_to"]), None)
        if hit is None:  # 落在单元之间（单元扉页）：归到紧邻的下一个单元
            hit = next((s for s in cand if isinstance(s.get("page_from"), int)
                        and isinstance(pg, int) and s["page_from"] > pg), None)
        if hit is None:
            hit = cand[-1] if cand else None
        if hit is None or hit.get("section_id") == r.get("section_id"):
            continue
        r.update(section_id=hit.get("section_id"),
                 unit_name=hit.get("unit_name"), title=hit.get("title"))
        nfix += 1
    with open(ATTR_FILE, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if verbose:
        print("→ %s（重挂 %d / %d 条公式）" % (ATTR_FILE, nfix, len(rows)))
    return {"n": len(rows), "fix": nfix}


def build(subject: str = "数学", limit: int = 0, force: bool = False,
          verbose: bool = True) -> dict:
    """逐页看图抽公式：按 (section_id, page_no) 续跑。"""
    src = os.path.join(config.ATTRS_DIR, "section_text.jsonl")
    if not os.path.exists(src):
        return {"ok": 0, "fail": 0, "n": 0}
    secs = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    if subject:
        secs = [r for r in secs if r.get("subject") == subject]
    secs = [r for r in secs if r.get("page_from") is not None]

    # 续跑键：小节+物理页。已抽过的页不再花钱（VLM 是这里唯一的成本大头）
    done = set() if force else llm.load_done(ATTR_FILE, "page_key")

    jobs = []
    for s in secs:
        pf, pt = int(s.get("page_from") or 0), int(s.get("page_to") or 0)
        for n in range(pf, pt + 1):
            key = "%s:%d" % (s.get("section_id"), n)
            if key in done:
                continue
            jobs.append((s, n, key))

    if limit:
        jobs = jobs[:limit]
    if verbose:
        print("待抽公式页：%d（小节 %d）" % (len(jobs), len(secs)))

    client = None
    ok = fail = nformula = 0
    for i, (s, n, key) in enumerate(jobs, 1):
        rec = find_book(s.get("book_id"))
        if not rec or not rec.get("_abs"):
            fail += 1
            continue
        if client is None:
            client = vlm.VLMClient()
        last = ""
        rows = None
        # 429/超时是平台侧限流，单次调用多等几轮（与 toc 同理）
        for attempt in range(4):
            try:
                r = vlm.extract_page_vlm(
                    rec["_abs"], n, client=client,
                    prompt=config.VLM_PROMPT_FORMULA,
                    dpi=vlm.dpi_for_attempt(attempt),
                )
                rows = [_clean(x) for x in _parse_array(r.text)]
                rows = [x for x in rows if x["latex"]]
                model = r.model
                break
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
                if attempt < 3 and vlm.needs_backoff(last):
                    time.sleep((10, 30, 60)[attempt])
        if rows is None:
            fail += 1
            if verbose:
                print("  [%d/%d] %s p%d 失败：%s" % (i, len(jobs), s.get("title"), n, last))
            continue

        # 整页没公式也要记一条空记录，否则每次重跑都会再花一次钱
        if not rows:
            llm.append_jsonl(ATTR_FILE, {
                "page_key": key, "formula_id": key + ":000",
                "section_id": s.get("section_id"), "book_id": s.get("book_id"),
                "subject": s.get("subject"), "grade": s.get("grade"),
                "term": s.get("term"), "unit_name": s.get("unit_name"),
                "title": s.get("title"), "page_no": n,
                "latex": "", "kind": "", "note": "", "vars": "",
                "model": model, "ts": int(time.time()),
            })
            ok += 1
            continue

        for k, x in enumerate(rows, 1):
            llm.append_jsonl(ATTR_FILE, {
                "page_key": key, "formula_id": "%s:%03d" % (key, k),
                "section_id": s.get("section_id"), "book_id": s.get("book_id"),
                "subject": s.get("subject"), "grade": s.get("grade"),
                "term": s.get("term"), "unit_name": s.get("unit_name"),
                "title": s.get("title"), "page_no": n,
                "latex": x["latex"], "kind": x["kind"], "note": x["note"],
                "vars": x["vars"], "model": model, "ts": int(time.time()),
            })
            nformula += 1
        ok += 1
        if verbose:
            print("  [%d/%d] %s p%d → %d 条" % (i, len(jobs), s.get("title"), n, len(rows)))

    if verbose:
        print("→ %s（页 %d / 失败 %d / 公式 %d 条）" % (ATTR_FILE, ok, fail, nformula))
    return {"ok": ok, "fail": fail, "n": nformula}
