# -*- coding: utf-8 -*-
"""语文专家组：段意与中心的**复核**，不是重写。

先说清楚为什么还需要这一步：lesson_structure 的覆盖率已经是 100%
（259/259 篇课文都有段意与全文大意），所以要补的不是"有没有"，而是
"敢不敢信"——抽查里像"表达了……的主题""赞美其美妙动听"这类句子，
形式上完全合规，但可能只是套了个模板。

多 agent 在这里的价值**不是投票**。同一个 prompt 问三次然后少数服从多数，
对"概括段意"这种确定性任务帮助极小：模型犯的是**同源错误**（都套模板、
都漏掉最后两段），三个人会一起错，还会把错的一致性当成正确。
真正有用的是把**生成**和**核查**拆给不同的角色，而且核查必须能算：

  一稿（整理者）：写段意 + 每段交一句 evidence（"凭什么这么说"）
  判官（程序）：  不看模型脸色，只做三件可计算的事——
                  ① evidence 是不是逐字出自对应段落；
                  ② 全文大意覆盖了多少个结构段（关键词命中）；
                  ③ 是不是只剩套话、有没有超纲说法。
  二稿（复查者）：只有判官没通过才登场，且**带着一稿的错因**重做
                  （"第 2 段 evidence 不是原文"），不是重问一遍同样的话。

判不过又不肯改的，标 needs_review 存着但页面不显示——留白比错强。

产物 data/attrs/lesson_panel.jsonl：结构段（含 evidence）、主要内容、
中心/启示、审核结果。不改动既有 lesson_structure.jsonl。
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import config
from . import llm

PANEL_FILE = os.path.join(config.ATTRS_DIR, "lesson_panel.jsonl")
TEXT_FILE = os.path.join(config.ATTRS_DIR, "lesson_text.jsonl")
STRUCT_FILE = os.path.join(config.ATTRS_DIR, "lesson_structure.jsonl")
META_FILE = os.path.join(config.ATTRS_DIR, "lesson_meta.jsonl")

STRUCT_GENRES = ("课文", "现代诗")

# 只留汉字与字母数字：判断 evidence 是否逐字出自原文时，标点差异不算数
RE_HAN = re.compile(r"[^一-鿿A-Za-z0-9]")

# 混进正文的生字条：一长串连续的汉字、中间一个标点都没有
# （"蚱啃樱蚌割嘟倭拴啰逛"）。8 字起步是为了不误伤诗句——
# 古诗最长七言，八言以上的无标点纯汉字串在课文里基本只有字表。
RE_ZITIAO = re.compile(r"^[一-鿿]{8,}$")

# 套话：这些尾巴本身不算错（《猫》确实是"喜爱之情"），
# 但整句只剩这类词、前面没有具体内容时，就是没信息量的模板
RE_CLICHE = re.compile(
    r"表达了?作者?[^，。]{0,10}(思想感情|感情|赞美|热爱|喜爱|怀念)|"
    r"(赞美|赞扬|歌颂)了?[^，。]{0,12}(精神|品质|情感)|"
    r"告诉我们(一个)?[^，。]{0,8}道理|"
    r"[^，。]{0,10}的(主题|中心思想)$")

# 第一学段不许出现的说法：课标 1-2 年级只要求"感受语言文字的美"，
# 谈"中心思想/表达了作者"是拔高
RE_OVER_12 = re.compile(r"中心思想|表达了作者|揭示了|讽刺了|批判了")

# 判定"有没有具体内容"时忽略的虚词（不然"课文写了猫"也能算命中）
STOP = re.compile(r"[的地得，。！？、；：""''《》（）]|课文|本文|全诗|这篇|通过|主要|内容|写了|讲了|描写|介绍|表现|说明|一个|我们|可以|什么|怎样|如何")

CENTER_DOC = {
    "1-2": "这一项**留空**（第一学段不谈中心思想，只要求说出读后的感受）",
    "3-4": "读了这篇课文，能说出人物怎么样、或明白了一件什么事，"
           "不超过 40 字；不要写“表达了作者……”这种套话",
    "5-6": "中心思想与启示，不超过 50 字；先说写了什么，再说要告诉我们什么",
}

PROMPT_DRAFT = (
    "你是小学语文教研员（{stage} 学段）。下面是课文原文，以及一份别人整理好的"
    "段落段意，请你复核。\n\n"
    "【课文】《{title}》（{book}）\n"
    "【正文段落】共 {n} 段，编号 0 到 {last}\n{body}\n\n"
    "【待复核的段意】\n{parts}\n"
    "【待复核的全文大意】{idea}\n\n"
    "任务：\n"
    "1. 逐段复核：段意有没有说错、说空、漏掉关键内容？错了就重写，不超过 40 字；\n"
    "2. 每一段补一句 evidence：从**该段原文里逐字照抄**一句最能支撑这条段意的"
    "话（不超过 30 字，一个字都不要改，包括标点）；\n"
    "3. main_idea：一句话说清全文**写了什么**，不超过 60 字，"
    "不要写“表达了什么感情”；\n"
    "4. center：{center_doc}\n"
    "5. 结构段必须连续覆盖全部段落（首段 from=0，末段 to={last}），"
    "段数不要超过 {maxparts} 个。\n\n"
    "只输出一行 JSON，不要任何解释：\n"
    '{{"parts":[{{"from":0,"to":1,"gist":"","evidence":""}}],'
    '"main_idea":"","center":""}}'
)

PROMPT_RECHECK = (
    "你是另一位语文教研员。上一位整理的内容没通过机器核查，"
    "问题在下面，请**只看课文原文**重做一遍，别照抄上一份：\n"
    "【错因】{why}\n\n"
    "【课文】《{title}》（{book}）\n"
    "【正文段落】共 {n} 段，编号 0 到 {last}\n{body}\n\n"
    "任务：\n"
    "1. 把段落归并成若干结构段，每段一句话段意，不超过 40 字；\n"
    "2. 每段附 evidence：从该段原文里**逐字照抄**一句（不超过 30 字）；\n"
    "3. main_idea：一句话说清全文写了什么，不超过 60 字；\n"
    "   要能覆盖多数段落，别只说开头两段；\n"
    "4. center：{center_doc}\n"
    "5. 结构段连续覆盖全部段落（首段 from=0，末段 to={last}）。\n\n"
    "只输出一行 JSON，不要任何解释：\n"
    '{{"parts":[{{"from":0,"to":1,"gist":"","evidence":""}}],'
    '"main_idea":"","center":""}}'
)


def _load(path: str) -> list:
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _han(s: str) -> str:
    return RE_HAN.sub("", s or "")


def _bigrams(s: str) -> set:
    """把句子切成二字词，用于算"大意覆盖了多少段"。"""
    s = STOP.sub("", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1) if len(s[i:i + 2]) == 2}


def _seg_text(paras: list, f: int, t: int) -> str:
    return "".join(paras[f:t + 1])


def audit(t: dict, parts: list, idea: str, center: str) -> dict:
    """判官：只做能算的核查，不评价文采。返回（错因列表, 明细）。

    三道关：
      ① evidence 必须逐字出自它所属的那几段（抄错段落也算错）；
      ② 全文大意要覆盖多数结构段（只概括开头两段的最常见）；
      ③ 套话与超纲：只剩"表达了……感情"这种没内容的，或一二年级谈中心思想。
    """
    paras = t["paras"]
    why, checks = [], {}
    if not parts:
        return {"ok": False, "why": ["没有结构段"], "checks": {}}

    # ① evidence 逐字校验
    bad_ev = []
    for p in parts:
        try:
            f, tt = int(p.get("from")), int(p.get("to"))
        except Exception:
            why.append("结构段编号不是整数")
            continue
        if not (0 <= f <= tt < len(paras)):
            why.append("结构段 %d-%d 越界" % (f, tt))
            continue
        ev = str(p.get("evidence") or "").strip()
        if not ev:
            bad_ev.append("第%d段" % f)
            continue
        if _han(ev) not in _han(_seg_text(paras, f, tt)):
            bad_ev.append("第%d段" % f)
    if bad_ev:
        why.append("evidence 不是原文原句（%s）" % "、".join(bad_ev[:3]))
    checks["evidence"] = 1.0 - len(bad_ev) / max(1, len(parts))

    # ② 大意覆盖面
    bg = _bigrams(idea)
    hit = 0
    for p in parts:
        try:
            f, tt = int(p.get("from")), int(p.get("to"))
        except Exception:
            continue
        seg = _han(_seg_text(paras, f, tt))
        if any(b in seg for b in bg):
            hit += 1
    cover = hit / max(1, len(parts))
    checks["coverage"] = round(cover, 2)
    if cover < 0.5:
        why.append("全文大意只覆盖了 %.0f%% 的段落，可能漏了后半篇" % (cover * 100))

    # ③ 套话与超纲
    hollow = [str(p.get("gist") or "") for p in parts
              if RE_CLICHE.search(str(p.get("gist") or ""))]
    if RE_CLICHE.search(idea or "") and len(_han(idea)) < 40:
        why.append("全文大意只剩套话，没有具体内容")
    checks["cliche"] = len(hollow)
    if t["stage"] == "1-2" and (RE_OVER_12.search(center or "")
                                or RE_OVER_12.search(idea or "")):
        why.append("第一学段不谈中心思想/表达了作者（超纲）")
    return {"ok": not why, "why": why, "checks": checks}


def _targets() -> list:
    """待复核的课文：以 lesson_structure 已有的稿子为一稿底本。"""
    texts = _load(TEXT_FILE)
    structs = {s.get("lesson_id"): s for s in _load(STRUCT_FILE)}
    metas = {m.get("lesson_id"): m for m in _load(META_FILE)}
    out = []
    for r in texts:
        lid = r.get("lesson_id")
        genre = (metas.get(lid) or {}).get("genre") or ""
        if genre not in STRUCT_GENRES:
            continue
        raw = [str(p).strip() for p in (r.get("paragraphs") or []) if str(p).strip()]
        # 生字条被当成一段，段意就会写出"生字表"这种废话，先剔掉
        ps = [p for p in raw if not RE_ZITIAO.match(p)]
        if len(ps) < 2:
            continue
        st = structs.get(lid) or {}
        g = str(r.get("grade") or "").strip()[:1]
        stage = {"一": "1-2", "二": "1-2", "三": "3-4",
                 "四": "3-4", "五": "5-6", "六": "5-6"}.get(g, "3-4")
        out.append({
            "lesson_id": lid, "title": r.get("title") or "", "grade": g,
            "stage": stage, "paras": ps,
            # 段落编号变了，旧稿的 from/to 已经错位，别再拿它当底本
            "base_parts": (st.get("parts") or []) if len(ps) == len(raw) else [],
            "base_idea": st.get("main_idea") or "",
        })
    return out


def _fmt_parts(parts: list) -> str:
    if not parts:
        return "（还没有，请你自己归并）"
    return "\n".join("第%d-%d段：%s" % (p.get("from", 0), p.get("to", 0),
                                        p.get("gist") or "")
                     for p in parts[:12])


def _clean(t: dict, d: dict) -> tuple:
    parts, n = [], len(t["paras"])
    for p in (d.get("parts") or [])[:10]:
        try:
            f, tt = int(p.get("from")), int(p.get("to"))
        except Exception:
            continue
        if not (0 <= f <= tt < n):
            continue
        parts.append({"from": f, "to": tt,
                      "gist": str(p.get("gist") or "").strip()[:60],
                      "evidence": str(p.get("evidence") or "").strip()[:40]})
    # 连续覆盖是硬要求：断一截就是漏了内容，不做修补
    ok = bool(parts) and parts[0]["from"] == 0 and parts[-1]["to"] == n - 1
    for i, p in enumerate(parts):
        if i and p["from"] != parts[i - 1]["to"] + 1:
            ok = False
    if not ok:
        return [], "", ""
    center = "" if t["stage"] == "1-2" else str(d.get("center") or "").strip()[:60]
    return parts, str(d.get("main_idea") or "").strip()[:80], center


def _one(t: dict) -> dict:
    body = "\n".join("%d: %s" % (i, p) for i, p in enumerate(t["paras"]))[:4000]
    n = len(t["paras"])
    maxparts = 6 if n > 8 else 4
    base = {
        "title": t["title"], "book": t["grade"] or "",
        "stage": t["stage"], "n": n, "last": n - 1, "body": body,
        "center_doc": CENTER_DOC[t["stage"]], "maxparts": maxparts,
    }
    try:
        res = llm.chat(PROMPT_DRAFT.format(
            parts=_fmt_parts(t["base_parts"]),
            idea=t["base_idea"] or "（还没有）", **base), max_tokens=3072)
        parts, idea, center = _clean(t, llm.parse_json(res.text))
    except Exception as e:
        return {"lesson_id": t["lesson_id"], "ok": False,
                "why": ["调用失败：%s" % e], "round": 0}
    if not parts:
        return {"lesson_id": t["lesson_id"], "ok": False,
                "why": ["结构段没有连续覆盖全部段落"], "round": 1}

    a = audit(t, parts, idea, center)
    round_no = 1
    if not a["ok"]:
        # 二稿：换一个角色，并且**带着错因**重做——这是多 agent 唯一真正有用的地方
        try:
            res2 = llm.chat(PROMPT_RECHECK.format(
                why="；".join(a["why"][:3]), **base), max_tokens=3072)
            p2, i2, c2 = _clean(t, llm.parse_json(res2.text))
            if p2:
                a2 = audit(t, p2, i2, c2)
                if a2["ok"] or len(a2["why"]) < len(a["why"]):
                    parts, idea, center, a, round_no = p2, i2, c2, a2, 2
        except Exception:
            pass
    return {"lesson_id": t["lesson_id"], "book_id": t.get("book_id") or "",
            "title": t["title"], "grade": t["grade"], "stage": t["stage"],
            "parts": parts, "main_idea": idea, "center": center,
            "n_paragraphs": n, "round": round_no,
            "audit": {"ok": a["ok"], "why": a["why"], "checks": a["checks"]},
            "ts": int(time.time())}


def build(limit: int = 0, force: bool = False, workers: int = 4,
          grade: str = "", verbose: bool = True) -> dict:
    todo = _targets()
    if grade:
        key = str(grade).strip()[:1]
        todo = [t for t in todo if t["grade"] == key]
    if not force:
        done = llm.load_done(PANEL_FILE, "lesson_id")
        todo = [t for t in todo if t["lesson_id"] not in done]
    todo = todo[:limit] if limit else todo
    if force and todo and os.path.exists(PANEL_FILE):
        # 重跑的是其中一部分：先把这几篇的旧结果挑掉，再追加，免得同课两行
        ids = {t["lesson_id"] for t in todo}
        keep = []
        for line in open(PANEL_FILE, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                if json.loads(line).get("lesson_id") in ids:
                    continue
            except ValueError:
                pass
            keep.append(line)
        with open(PANEL_FILE, "w", encoding="utf-8") as fh:
            fh.write("".join(l + "\n" for l in keep))
    if verbose:
        print("待复核：%d 篇" % len(todo))
    ok = bad = 0
    with open(PANEL_FILE, "a", encoding="utf-8") as fh:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = {ex.submit(_one, t): t for t in todo}
            for i, fu in enumerate(as_completed(futs), 1):
                r = fu.result()
                if r.get("parts"):
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    fh.flush()
                    ok += 1
                    if verbose:
                        print("  [%d/%d] %s → %d 段｜通过 %s｜第 %d 稿" % (
                            i, len(todo), r["title"], len(r["parts"]),
                            r["audit"]["ok"], r["round"]))
                else:
                    bad += 1
                    if verbose:
                        print("  [%d/%d] %s 未通过：%s" % (
                            i, len(todo), futs[fu]["title"],
                            "；".join(r.get("why") or [])))
    if verbose:
        print("→ %s（入库 %d / 未过 %d）" % (PANEL_FILE, ok, bad))
    return {"ok": ok, "bad": bad, "n": len(todo)}


def stats() -> dict:
    rows = _load(PANEL_FILE)
    if not rows:
        return {"n": 0}
    passed = [r for r in rows if r.get("audit", {}).get("ok")]
    return {
        "n": len(rows), "通过": len(passed),
        "二稿才通过": sum(1 for r in passed if r.get("round") == 2),
        "证据完整率": round(sum(r["audit"]["checks"].get("evidence", 0)
                                for r in rows) / len(rows), 3),
        "大意覆盖率": round(sum(r["audit"]["checks"].get("coverage", 0)
                                for r in rows) / len(rows), 3),
        "套话段数": sum(r["audit"]["checks"].get("cliche", 0) for r in rows),
    }
