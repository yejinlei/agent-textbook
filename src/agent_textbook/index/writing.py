# -*- coding: utf-8 -*-
"""单元习作支架包：不给孩子范文，给孩子"写之前先做什么、写的时候看哪儿"。

为什么不做范文库：
  一、课标立场——2022 版要求"内容具体、感情真实"，反对套作、反对背范文。
     直接摆一篇优秀作文在面前，最可能发生的就是换个名字抄一遍，
     写出来的"扶老奶奶过马路"正是课标要治的假大空。
  二、版权——新概念作文选、在世作家作品整篇入库是有版权风险的。
     教材课文与教材自带例文不在这个问题上，而且它们**本来就与本单元
     写作要素对齐**（六下三单元"体会文章怎样表达情感"↔习作"让真情自然流露"），
     比外面找来的范文更贴题。

所以这里给的是支架，不是范文：
  写之前 → 观察卡（没素材是"写不出"最主要的病因，光讲技巧没用）
  写的时候 → 提纲支架 + 从本单元课文里摘的 3 处例证（学它"怎么把话说具体"）
  写完 → 量规自评 + 只改一处的修改清单

课文例证一律逐字校验：src 必须真的出现在本单元某篇课文正文里，
对不上就丢——宁可少一条，也不要一句编出来的"名言"。

产物 data/attrs/unit_writing.jsonl，按单元一条。
"""
import json
import os
import re
import time

from .. import config
from . import llm

OUT_FILE = os.path.join(config.ATTRS_DIR, "unit_writing.jsonl")
TEXT_FILE = os.path.join(config.ATTRS_DIR, "lesson_text.jsonl")
META_FILE = os.path.join(config.ATTRS_DIR, "lesson_meta.jsonl")
ELEM_FILE = os.path.join(config.ATTRS_DIR, "unit_element.jsonl")

RE_HAN = re.compile(r"[^一-鿿A-Za-z0-9]")

G_STAGE = {"一": "1-2", "二": "1-2", "三": "3-4",
           "四": "3-4", "五": "5-6", "六": "5-6"}

# 各学段的表达要求（课标原文口径）：写话 → 写清楚 → 内容具体、分段表述
EXP = {
    "1-2": "【写话】写自己想说的话，写想象中的事物；写出自己对周围事物的认识和感想",
    "3-4": "【习作】观察周围世界，能不拘形式地写下自己的见闻、感受和想象，"
           "注意把自己觉得新奇有趣或印象最深、最受感动的内容写清楚",
    "5-6": "【习作】养成留心观察周围事物的习惯，有意识地丰富自己的见闻，"
           "积累习作素材；能写简单的记实作文和想象作文，内容具体、感情真实，"
           "能分段表述，学写读书笔记与常见应用文",
}

RUBRIC_DOC = {
    "1-2": "2 条，用孩子听得懂的话（如“写出了谁在干什么”“句子读得通”）",
    "3-4": "3 条，围绕“写清楚了没有”（内容清楚、顺序清楚、语句通顺）",
    "5-6": "4 条，围绕“内容具体、感情真实、分段表述、语句通顺”",
}

PROMPT = (
    "你是小学语文教研员，给一个单元的习作设计**学习支架**。\n\n"
    "【单元】{grade}{term} 第{unit}单元\n"
    "【本单元写作要素】{focus}\n"
    "【课标要求】{exp}\n\n"
    "【教材习作页原文】\n{body}\n\n"
    "【本单元课文（可从中摘例证）】\n{lessons}\n\n"
    "任务：\n"
    "1. require：这个习作要写什么、写给谁看，只依据教材原文，不超过 80 字；\n"
    "2. observe：**写之前**一周可以做的观察或体验，3 条，每条不超过 25 字，"
    "要具体到能做（如“连续三天观察豆芽的变化”），不要“认真观察生活”这种空话；\n"
    "3. outline：动笔前的提纲支架，{outline_n} 步，每步不超过 25 字，"
    "是“想清楚写什么、重点写哪一段”，不要写成填空模板；\n"
    "4. evidence：从**本单元课文里**摘 {ev_n} 处值得学的写法，"
    "src 必须与课文原文**逐字一致**（含标点，不超过 40 字），"
    "lesson 写课文题目，learn 写“学它什么、我能怎么用”，不超过 30 字；\n"
    "   {ev_doc}\n"
    "5. rubric：写完怎么自评，{rubric_doc}；\n"
    "6. revise：修改清单，2-3 条，每条不超过 25 字，"
    "说清“先改什么”（如“把‘很高兴’换成当时的动作”），不要“认真修改”；\n"
    "7. micro：本单元每篇课文之后可以练的一个百字微写作，最多 3 个，"
    "每个不超过 30 字（如“写一段‘我很紧张’的具体表现”）。\n\n"
    "严格要求：\n"
    "- 不要写整篇范文、不要给万能开头结尾、不要给“好词好句”清单；\n"
    "- 不要用“通过……表达了……”这类成人化赏析腔；\n"
    "- 拿不准就留空，留白比编强。\n\n"
    "只输出一行 JSON，不要任何解释：\n"
    '{{"require":"","observe":[""],"outline":[""],'
    '"evidence":[{{"src":"","lesson":"","learn":""}}],'
    '"rubric":[""],"revise":[""],"micro":[""]}}'
)

EV_DOC = {
    "1-2": "   一二年级只摘“有意思的词和短句”，learn 说“可以照着说一句话”",
    "3-4": "   三四年级摘“把事物写具体的句子”（有颜色、动作、声音的），"
           "learn 说清它怎么做到具体；不要提修辞术语",
    "5-6": "   五六年级摘“写得具体或有顺序的句段”，"
           "learn 要说出它在课文里起了什么作用（让人看到什么、感受到什么），"
           "不要只贴“比喻”“拟人”这类标签——课标反对脱离实际运用讲概念",
}


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


def targets() -> list:
    """按单元归组：习作页 + 本单元课文（课文正文只取前 1200 字，够摘例证）。"""
    metas = {m.get("lesson_id"): m for m in _load(META_FILE)}
    texts = _load(TEXT_FILE)
    elems = {}
    for e in _load(ELEM_FILE):
        if str(e.get("subject") or "") != "语文":
            continue
        elems[(e.get("grade"), e.get("term"), str(e.get("unit_no")))] = e

    units = {}
    for t in texts:
        lid = t.get("lesson_id")
        genre = (metas.get(lid) or {}).get("genre") or ""
        key = (t.get("grade"), t.get("term"), str(t.get("unit_no")))
        if genre == "习作":
            u = units.setdefault(key, {"lessons": [], "writing": None})
            paras = [str(p).strip() for p in (t.get("paragraphs") or [])
                     if str(p).strip()]
            # 同一单元若有多篇习作，取正文最长的一页
            if u["writing"] is None or len("\n".join(paras)) > len(
                    "\n".join(u["writing"]["paras"])):
                u["writing"] = {"lesson_id": lid, "title": t.get("title") or "",
                                "paras": paras}
        elif genre in ("课文", "现代诗", "例文", "童话", "寓言"):
            u = units.setdefault(key, {"lessons": [], "writing": None})
            paras = [str(p).strip() for p in (t.get("paragraphs") or [])
                     if str(p).strip()]
            u["lessons"].append({"title": t.get("title") or "",
                                 "text": "\n".join(paras)[:1200],
                                 "paras": paras})
    out = []
    for (g, tm, un), u in units.items():
        if not u["writing"] or not u["writing"]["paras"]:
            continue
        g1 = str(g or "").strip()[:1]
        el = elems.get((g, tm, un)) or {}
        out.append({
            "unit_id": "%s-%s-%s" % (g, tm, un), "grade": g or "", "term": tm or "",
            "unit_no": un, "stage": G_STAGE.get(g1, "3-4"),
            "title": u["writing"]["title"],
            "focus": el.get("writing_focus") or "",
            "theme": el.get("theme") or "",
            "body": "\n".join(u["writing"]["paras"])[:2500],
            "lessons": u["lessons"],
        })
    return out


def _clean(u: dict, d: dict) -> dict:
    """清洗 + 校验。evidence 的 src 必须逐字出自本单元某篇课文，否则丢。"""
    stage = u["stage"]
    texts = {l["title"]: _han(l["text"]) for l in u["lessons"]}
    ev = []
    for e in (d.get("evidence") or [])[:4]:
        src = str(e.get("src") or "").strip()
        # 模型爱连书名号一起返回，页面上会变成《《北京的春节》》
        lesson = re.sub(r"[《》]", "", str(e.get("lesson") or "").strip())
        learn = str(e.get("learn") or "").strip()
        if not src or not learn:
            continue
        # 逐字校验：标点不计，但一个字都不许改
        if lesson in texts:
            if _han(src) not in texts[lesson]:
                continue
        elif not any(_han(src) in t for t in texts.values()):
            continue
        ev.append({"src": src[:60], "lesson": lesson,
                   "learn": learn[:40]})

    def arr(key, n, lim):
        return [str(x).strip()[:lim] for x in (d.get(key) or [])
                if str(x).strip()][:n]

    return {
        "require": str(d.get("require") or "").strip()[:120],
        "observe": arr("observe", 3, 40),
        "outline": arr("outline", 4 if stage != "1-2" else 2, 40),
        "evidence": ev[:3],
        "rubric": arr("rubric", 4 if stage == "5-6" else 3, 40),
        "revise": arr("revise", 3, 40),
        "micro": arr("micro", 3, 45),
    }


def _one(u: dict) -> dict:
    lessons = "\n\n".join("《%s》\n%s" % (l["title"], l["text"])
                          for l in u["lessons"][:4]) or "（本单元无课文）"
    prompt = PROMPT.format(
        grade=u["grade"], term=u["term"], unit=u["unit_no"],
        focus=u["focus"] or "（教材未单列）", exp=EXP[u["stage"]],
        body=u["body"], lessons=lessons,
        outline_n=4 if u["stage"] != "1-2" else 2,
        ev_n=3, ev_doc=EV_DOC[u["stage"]], rubric_doc=RUBRIC_DOC[u["stage"]])
    try:
        res = llm.chat(prompt, max_tokens=2048)
        got = _clean(u, llm.parse_json(res.text))
    except Exception as e:
        return {"unit_id": u["unit_id"], "ok": False, "why": str(e)}
    if not got["require"]:
        return {"unit_id": u["unit_id"], "ok": False, "why": "习作要求为空"}
    got.update({"unit_id": u["unit_id"], "grade": u["grade"], "term": u["term"],
                "unit_no": u["unit_no"], "stage": u["stage"],
                "title": u["title"], "writing_focus": u["focus"],
                "standard": EXP[u["stage"]], "ok": True, "ts": int(time.time())})
    return got


def build(limit: int = 0, force: bool = False, grade: str = "",
          verbose: bool = True) -> dict:
    todo = targets()
    if grade:
        key = str(grade).strip()[:1]
        todo = [u for u in todo if str(u["grade"]).strip()[:1] == key]
    if not force:
        done = llm.load_done(OUT_FILE, "unit_id")
        todo = [u for u in todo if u["unit_id"] not in done]
    todo = todo[:limit] if limit else todo
    if force and todo and os.path.exists(OUT_FILE):
        # 重跑的是其中一部分：先把这几个单元的旧行挑掉，再追加
        ids = {u["unit_id"] for u in todo}
        keep = []
        for line in open(OUT_FILE, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                if json.loads(line).get("unit_id") in ids:
                    continue
            except ValueError:
                pass
            keep.append(line)
        with open(OUT_FILE, "w", encoding="utf-8") as fh:
            fh.write("".join(l + "\n" for l in keep))
    if verbose:
        print("待生成习作支架：%d 个单元" % len(todo))
    ok = bad = 0
    with open(OUT_FILE, "a", encoding="utf-8") as fh:
        for i, u in enumerate(todo, 1):
            r = _one(u)
            if r.get("ok"):
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush()
                ok += 1
                if verbose:
                    print("  [%d/%d] %s %s第%s单元《%s》→ 观察%d/提纲%d/例证%d"
                          % (i, len(todo), r["grade"], r["term"], r["unit_no"],
                             r["title"][:14], len(r["observe"]),
                             len(r["outline"]), len(r["evidence"])))
            else:
                bad += 1
                if verbose:
                    print("  [%d/%d] %s 未生成：%s"
                          % (i, len(todo), u["title"][:14], r.get("why")))
    if verbose:
        print("→ %s（入库 %d / 未过 %d）" % (OUT_FILE, ok, bad))
    return {"ok": ok, "bad": bad, "n": len(todo)}


def stats() -> dict:
    rows = _load(OUT_FILE)
    if not rows:
        return {"n": 0}
    return {"n": len(rows),
            "有课文例证": sum(1 for r in rows if r.get("evidence")),
            "例证总数": sum(len(r.get("evidence") or []) for r in rows),
            "平均观察条数": round(sum(len(r.get("observe") or []) for r in rows)
                                  / len(rows), 1)}
