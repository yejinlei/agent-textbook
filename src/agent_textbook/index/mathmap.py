# -*- coding: utf-8 -*-
"""数学的两个补充槽位：整理与复习的知识结构图、单位与符号表。

为什么单独开一个模块
--------------------
这两个东西都不在"正文"里，靠正文章节那条流水线抽不出来：

  * **知识结构图**是印在"整理和复习"页上的一张**图**（中心写单元主题、
    分支写学了哪些知识）。290 个课时里有 52 个是整理复习课时，它们的正文
    几乎全是复习题，图才是本体。好在插图层（page_figure）已经把图面描述
    写成了文字——树状图的分支关系就写在里面，所以这里读描述就能还原结构，
    不必再渲染一遍页面。

  * **单位与符号**是教材零星散着教的（长度单位在某一单元、面积单位在另一
    单元），没有独立栏目。规则只能抓到"1千米=1000米"这类写法，实测全库只
    有 19 条去重进率，漏得厉害；单位符号（S、V、π、∠）更是没有固定写法。
    所以按单元问一遍模型，再按册聚合。

产物 data/attrs/unit_map.jsonl（一课时一条）、math_unit.jsonl（一单元一条）。
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from .. import config
from . import llm

MAP_FILE = os.path.join(config.ATTRS_DIR, "unit_map.jsonl")
UNIT_FILE = os.path.join(config.ATTRS_DIR, "math_unit.jsonl")

# 整理复习课时的标题特征：教材写法不统一（"整理和复习"/"整理与复习"/
# "复习与关联"/"总复习"），按关键字认，不按全名认。
MAP_TITLE_KEYS = ("整理", "复习")

PROMPT_MAP = (
    "你是小学数学教材分析助手。下面是教材**整理与复习**栏目里插图的文字描述。\n"
    "有些单元在这一页印着一张**知识结构图**（树状/网状图：中心写本单元主题，"
    "分支写这一单元学了哪些知识）。\n"
    "只输出 JSON：\n"
    '{{"has_map":false,"topic":"","nodes":[],"summary":""}}\n'
    "要求：\n"
    "1. 下面两种都算结构图，has_map=true：\n"
    "   ①树状/网状图——看到'结构图''树状图''分支''思维导图'，"
    "或能看出中心主题向外分叉；\n"
    "   ②知识点梳理框——矩形框里罗列'本单元学习的主要知识点''我们学了什么'"
    "之类（教材常用这种，不一定画成树）。\n"
    "   若全是人物插画、题目配图、算理示意图或算式罗列，才 has_map=false。\n"
    "2. 罗列式的梳理框没有层级：把单元主题作为根节点，知识点都挂在它下面。\n"
    "3. nodes 用**扁平数组 + parent** 表示层级：根节点 parent 填 0，"
    "其余填父节点的 id；id 从 1 开始；最多 30 个节点。\n"
    "4. nodes 每项：{{'id':1,'text':'','parent':0}}，text 抄结构图里的原文，"
    "不要改写、不要补图外的知识。\n"
    "5. topic 填结构图的中心主题（如'确定位置'）；summary 一句话概括这张图，20 字内。\n"
    "6. 描述里读不出内容就不要硬编，has_map=false。\n\n"
    "年级：{grade}{term}　单元：{unit}　栏目：{title}\n\n"
    "插图描述：\n{body}"
)

PROMPT_UNIT = (
    "你是小学数学教材分析助手。下面是教材某个单元的正文。\n"
    "抽出这个单元里出现的**计量单位**和**数学符号**。\n"
    "只输出 JSON：\n"
    '{{"units":[{{"name":"","category":"","symbol":"","rates":[],"example":""}}],'
    '"symbols":[{{"symbol":"","name":"","meaning":"","latex":"","example":""}}]}}\n'
    "要求：\n"
    "1. units：教材里真正教的单位（如 千米、米、平方厘米、升、吨、时、元、度）。\n"
    "   category 只能是 长度/面积/体积与容积/质量/时间/货币/角度/其他 之一。\n"
    "   symbol 写单位的字母表示（km、m、cm²、L、t、kg、°），没有就填空。\n"
    "2. rates：单位换算，如正文写'1千米=1000米'，就填 "
    "{{'from':'千米','to':'米','factor':'1000'}}；正文没给进率就空数组，不要自己推。\n"
    "3. symbols：数学符号（如 ×、÷、=、＜、＞、π、%、∠、⊥、∥、≈）"
    "以及用字母表示的量（如 S 表示面积、V 表示体积、a 表示边长）；\n"
    "   meaning 写它在教材里的含义，latex 写对应 LaTeX（\\times、\\div、"
    "\\pi、\\angle 等），没有就填空。\n"
    "4. example 抄正文原句（20 字内）；没有填空。\n"
    "5. 只收**正文里出现过**的单位和符号，不要编、不要凭常识补；"
    "一个单元最多 12 个单位、12 个符号。\n\n"
    "年级：{grade}{term}　单元：{unit}\n\n"
    "正文：\n{body}"
)


def _load_subsections(subject: str = "数学") -> list[dict]:
    src = os.path.join(config.ATTRS_DIR, "subsection.jsonl")
    if not os.path.exists(src):
        return []
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if (r.get("subject") or "") == subject]
    return [r for r in rows
            if any(k in (r.get("title") or "") for k in MAP_TITLE_KEYS)]


def _load_sections(subject: str = "数学") -> list[dict]:
    src = os.path.join(config.ATTRS_DIR, "section_text.jsonl")
    if not os.path.exists(src):
        return []
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    return [r for r in rows if (r.get("subject") or "") == subject
            and (r.get("text") or "").strip()]


def _figure_text(book_id: str, page_from, page_to) -> str:
    """把一课时的页区间里已有的插图描述拼起来。

    描述是插图层（page_figure）看图写好的文字，结构图的分支关系就在里面；
    读现成的比重新渲染页面省一整轮 VLM。
    """
    if not isinstance(page_from, int):
        return ""
    pt = page_to if isinstance(page_to, int) else page_from
    out = []
    for n in range(page_from, min(pt, page_from + 12) + 1):
        fp = os.path.join(config.FIGURES_DIR, str(book_id), "%04d.md" % n)
        if os.path.exists(fp):
            out.append("第%d页：%s" % (n, open(fp, encoding="utf-8").read().strip()))
    return "\n\n".join(out)


def build_maps(subject: str = "数学", limit: int = 0, force: bool = False,
               verbose: bool = True, workers: int = 6) -> dict:
    """整理与复习页上的知识结构图 → 扁平节点 + parent，可直接画成树。"""
    rows = _load_subsections(subject)
    key = "subsection_id"
    if not force:
        done = llm.load_done(MAP_FILE, key)
        rows = [r for r in rows if r.get(key) not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽知识结构图：%d 个整理复习课时" % len(rows))
    if not rows:
        return {"ok": 0, "nomap": 0, "fail": 0}

    jobs = [(r, _figure_text(r.get("book_id"), r.get("page_from"), r.get("page_to")))
            for r in rows]
    results: list = [None] * len(jobs)

    def _ask(i_j: tuple) -> None:
        i, (r, body) = i_j
        if len(body) < 30:
            results[i] = ("skip", None, None, "")
            return
        prompt = PROMPT_MAP.format(grade=r.get("grade") or "", term=r.get("term") or "",
                                   unit=r.get("unit_name") or "",
                                   title=r.get("title") or "", body=body[:6000])
        try:
            res = llm.chat(prompt, max_tokens=2500)
            results[i] = ("ok", llm.parse_json(res.text), res, "")
        except Exception as exc:
            results[i] = ("err", None, None, str(exc))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(_ask, list(enumerate(jobs))))

    ok = nomap = fail = 0
    for i, (r, body) in enumerate(jobs):
        state, data, res, err = results[i]
        if state != "ok":
            if state == "err":
                fail += 1
                if verbose:
                    print("  [%d/%d] %s 失败：%s"
                          % (i + 1, len(jobs), r.get("title"), err))
            else:
                nomap += 1
            continue
        nodes = []
        for nd in (data.get("nodes") or [])[:30]:
            t = str(nd.get("text") or "").strip()
            if not t:
                continue
            try:
                pid = int(nd.get("id") or 0)
                par = int(nd.get("parent") or 0)
            except (TypeError, ValueError):
                continue
            nodes.append({"id": pid, "text": t[:60], "parent": par})
        if not data.get("has_map") or not nodes:
            nomap += 1
            continue
        llm.append_jsonl(MAP_FILE, {
            "map_id": r.get("subsection_id"), "section_id": r.get("section_id"),
            "subsection_id": r.get("subsection_id"), "book_id": r.get("book_id"),
            "subject": subject, "grade": r.get("grade") or "",
            "term": r.get("term") or "", "unit_no": r.get("unit_no"),
            "unit_name": r.get("unit_name") or "", "title": r.get("title") or "",
            "topic": (data.get("topic") or "").strip()[:40],
            "summary": (data.get("summary") or "").strip()[:60],
            "nodes": nodes, "n_nodes": len(nodes),
            "page_from": r.get("page_from"), "page_to": r.get("page_to"),
            "model": res.model, "ts": int(time.time()),
        })
        ok += 1
        if verbose:
            print("  [%d/%d] %s%s %s → %d 节点（%s）"
                  % (i + 1, len(jobs), r.get("grade"), r.get("term"),
                     r.get("unit_name"), len(nodes),
                     (data.get("topic") or "")[:20]))
    if verbose:
        print("→ %s（结构图 %d / 无结构图 %d / 失败 %d）"
              % (MAP_FILE, ok, nomap, fail))
    return {"ok": ok, "nomap": nomap, "fail": fail}


def build_units(subject: str = "数学", limit: int = 0, force: bool = False,
                verbose: bool = True, workers: int = 6) -> dict:
    """按单元抽计量单位（含进率）与数学符号。"""
    rows = _load_sections(subject)
    key = "section_id"
    if not force:
        done = llm.load_done(UNIT_FILE, key)
        rows = [r for r in rows if r.get(key) not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽单位与符号：%d 个单元" % len(rows))
    if not rows:
        return {"ok": 0, "nunit": 0, "nsym": 0, "fail": 0}

    results: list = [None] * len(rows)

    def _ask(i_r: tuple) -> None:
        i, r = i_r
        prompt = PROMPT_UNIT.format(grade=r.get("grade") or "", term=r.get("term") or "",
                                    unit=r.get("unit_name") or "",
                                    body=(r.get("text") or "")[:6000])
        try:
            res = llm.chat(prompt, max_tokens=2500)
            results[i] = (llm.parse_json(res.text), res, "")
        except Exception as exc:
            results[i] = (None, None, str(exc))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(_ask, list(enumerate(rows))))

    ok = fail = nunit = nsym = 0
    for i, r in enumerate(rows, 1):
        data, res, err = results[i - 1]
        if data is None:
            fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(rows), r.get("unit_name"), err))
            continue
        try:
            units = []
            for u in (data.get("units") or [])[:12]:
                name = (u.get("name") or "").strip()
                if not name:
                    continue
                rates = []
                for rt in (u.get("rates") or [])[:6]:
                    if not isinstance(rt, dict):
                        continue
                    a = str(rt.get("from") or "").strip()
                    b = str(rt.get("to") or "").strip()
                    if a and b:
                        rates.append({"from": a[:12], "to": b[:12],
                                      "factor": str(rt.get("factor") or "")[:20]})
                units.append({"name": name[:20],
                              "category": (u.get("category") or "").strip()[:10],
                              "symbol": (u.get("symbol") or "").strip()[:12],
                              "rates": rates,
                              "example": (u.get("example") or "").strip()[:60]})
            syms = []
            for s in (data.get("symbols") or [])[:12]:
                sym = (s.get("symbol") or "").strip()
                if not sym:
                    continue
                syms.append({"symbol": sym[:12],
                             "name": (s.get("name") or "").strip()[:20],
                             "meaning": (s.get("meaning") or "").strip()[:60],
                             "latex": (s.get("latex") or "").strip()[:30],
                             "example": (s.get("example") or "").strip()[:60]})
            llm.append_jsonl(UNIT_FILE, {
                "item_id": r.get("section_id"), "section_id": r.get("section_id"),
                "book_id": r.get("book_id"), "subject": subject,
                "grade": r.get("grade") or "", "term": r.get("term") or "",
                "unit_no": r.get("unit_no"), "unit_name": r.get("unit_name") or "",
                "units": units, "symbols": syms,
                "n_units": len(units), "n_symbols": len(syms),
                "model": res.model, "ts": int(time.time()),
            })
            nunit += len(units)
            nsym += len(syms)
            ok += 1
            if verbose:
                print("  [%d/%d] %s%s %s → %d 单位 / %d 符号"
                      % (i, len(rows), r.get("grade"), r.get("term"),
                         r.get("unit_name"), len(units), len(syms)))
        except Exception as exc:
            fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(rows), r.get("unit_name"), exc))
    if verbose:
        print("→ %s（单元 %d / 失败 %d / 单位 %d / 符号 %d）"
              % (UNIT_FILE, ok, fail, nunit, nsym))
    return {"ok": ok, "fail": fail, "nunit": nunit, "nsym": nsym}
