# -*- coding: utf-8 -*-
"""数学每单元本体：这一单元要掌握什么（按课标学段，不超纲）。

两条铁律，和语文那套一样：

一、**教材里已经写着的，一律不重抽**——
  单元正文在 section_text，知识点在 section_keypoint，公式法则是 latex，
  例题分步在 example，生活场景是 goals 按单元匹配的。
  LLM 只补教材印不下、上课却真要讲的东西：算理、算法步骤、易错点、
  用到的数学思想、这个单元在知识链上的前后位置。

二、**不超纲，也不生造**——
  数学思想（转化、数形结合、模型、极限……）按学段开闸，低年级只给
  "分类、对应、数形结合"这种他真能体会的；易错点同理。
  所有术语走白名单，模型自己造的词一律丢。

依据是 2022 版数学课标的"三会"（会用数学的眼光观察、会用数学的思维
思考、会用数学的语言表达）与各学段的核心素养表现，页面上会写明依据哪一条。
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import config
from . import llm
from .lessonkb import _load, stage_of

KB_FILE = os.path.join(config.ATTRS_DIR, "math_kb.jsonl")
TEXT_FILE = os.path.join(config.ATTRS_DIR, "section_text.jsonl")
KP_FILE = os.path.join(config.ATTRS_DIR, "section_keypoints.jsonl")
FM_FILE = os.path.join(config.ATTRS_DIR, "section_formula.jsonl")
EX_FILE = os.path.join(config.ATTRS_DIR, "example.jsonl")

# ============================================================ 主题（按单元标题判）
TOPICS = [
    ("数与运算", ["数的认识", "以内", "加减", "加、减", "乘", "除", "运算",
                  "口算", "笔算", "估算", "分数", "小数", "百分数", "因数",
                  "倍数", "四则", "混合运算", "凑整", "分与合", "比多少"]),
    ("量与计量", ["厘米", "米", "千米", "克", "千克", "吨", "时、分", "秒",
                  "面积单位", "体积单位", "人民币", "元、角", "质量", "长度单位",
                  "认识钟表", "容积"]),
    ("图形与几何", ["图形", "角", "三角形", "四边形", "圆", "周长", "面积",
                    "体积", "表面积", "位置", "方向", "平移", "旋转", "轴对称",
                    "观察物体", "长方体", "正方体", "平行", "垂直", "线和角",
                    "扇形"]),
    ("比和比例", ["比", "比例", "正比例", "反比例", "比例尺"]),
    ("统计与概率", ["统计", "条形", "折线", "扇形统计图", "平均数", "可能性",
                    "概率", "数据", "分类与整理"]),
    ("代数初步", ["用字母表示数", "方程", "解方程", "代数式", "等量关系"]),
    ("数学广角", ["鸡兔同笼", "找次品", "鸽巢", "植树", "优化", "烙饼",
                  "数学广角", "推理", "数与形", "编码", "数字编码", "对策"]),
    ("综合与实践", ["综合与实践", "生活中的数学", "体育中的数学", "1亿有多大",
                    "量一量", "旅游计划", "掷一掷", "营养午餐"]),
]

# 课标锚点：每个字段对应哪一条（2022 版数学课标）
M_STANDARD = {
    "why": "【三会·数学思维】理解算理：知道“为什么这样算”，而不只是会算",
    "how": "【运算能力】能正确、合理、简洁地进行运算，说得出每一步在做什么",
    "traps": "【运算能力·推理意识】辨析易错处，能说出道理",
    "ideas": "【核心素养表现】数学思想：转化、数形结合、分类、模型等",
    "links": "【知识的结构化】体会知识间的联系，知道从哪来、往哪去",
    "life": "【应用意识】从真实情境中发现和提出问题（三会·数学眼光）",
}

# 易错点类型：按学段开，低年级不谈"单位换算""公式混淆"这类
TRAP_TYPES = {
    "1-2": ("算理", "算法", "审题", "书写", "进位退位", "数位", "单位"),
    "3-4": ("算理", "算法", "审题", "书写", "进位退位", "数位", "单位",
            "单位换算", "概念", "图形特征", "公式混淆"),
    "5-6": ("算理", "算法", "审题", "书写", "进位退位", "数位", "单位",
            "单位换算", "概念", "图形特征", "公式混淆", "小数点", "符号",
            "约分通分", "比例关系"),
}

# 数学思想：低年级只给他真能体会的那几个
IDEAS = {
    "1-2": ("分类", "对应", "一一对应", "数形结合", "有序思考"),
    "3-4": ("转化", "数形结合", "分类", "对应", "一一对应", "符号化", "归纳",
            "类比", "有序思考", "变中有不变"),
    "5-6": ("转化", "数形结合", "分类", "对应", "符号化", "模型", "推理",
            "归纳", "类比", "抽象", "极限", "优化", "方程思想", "函数思想",
            "集合", "变中有不变", "有序思考"),
}

PROMPT = (
    "你是小学数学教研员。下面是教材里的一个单元，请按“这一单元要掌握什么”\n"
    "整理笔记，给家长对着课本看，别写成教案。\n\n"
    "【单元】《{title}》（{book}，第{unit}单元 · {topic}主题）\n"
    "【学段】{stage} 年级（这是课标学段，要求不能拔高也不能降低）\n"
    "【教材正文（节选）】\n{text}\n"
    "【知识点】{points}\n"
    "【公式与法则】{latex}\n"
    "【例题】{examples}\n\n"
    "任务：\n"
    "1. why：这一单元“为什么这样算／为什么这样想”（算理），\n"
    "   用孩子能懂的话说，不超过 80 字。\n"
    "2. how：算法或解题步骤，最多 5 步。s 写这一步做什么（不超过 24 字），\n"
    "   note 写这一步为什么要做（不超过 20 字）。\n"
    "3. traps：易错点，最多 4 条。type 只能从下面挑：{traps}\n"
    "   text 写清错在哪、正确的是什么，不超过 30 字。\n"
    "4. ideas：这一单元用到的数学思想，只能从下面挑，最多 3 个：{ideas}\n"
    "5. links：before 写“要会这个，前面得先会什么”，\n"
    "   after 写“这个学会后，接着要学什么”，各不超过 30 字。\n\n"
    "严格要求：\n"
    "- 不要写解释，只输出一行 JSON；不要使用英文双引号以外的引号；\n"
    "- **不许编**：算理、算法都要对着上面的教材正文与例题来；\n"
    "- 拿不准的字段留空数组或空串，留白比写错强。\n\n"
    "只输出一行 JSON：\n"
    "{{\"why\":\"\",\"how\":[{{\"s\":\"\",\"note\":\"\"}}],"
    "\"traps\":[{{\"type\":\"\",\"text\":\"\"}}],\"ideas\":[],"
    "\"links\":{{\"before\":\"\",\"after\":\"\"}}}}"
)


def topic_of(title: str, text: str) -> str:
    """按单元标题（正文作补充）判主题；认不出就归到数与运算。"""
    s = (title or "") + " " + (text or "")[:200]
    for name, kws in TOPICS:
        for k in kws:
            if k in s:
                return name
    return "数与运算"


def _targets() -> list:
    """待处理的单元：按册次 → 单元排序。"""
    from ..site import goals

    kp = {r.get("section_id"): r for r in _load(KP_FILE) if r.get("section_id")}
    fm = {}
    for r in _load(FM_FILE):
        fm.setdefault(r.get("section_id"), []).append(r)
    ex = {}
    for r in _load(EX_FILE):
        ex.setdefault(r.get("section_id"), []).append(r)

    out = []
    for r in _load(TEXT_FILE):
        if str(r.get("subject") or "") != "数学":
            continue
        if not r.get("unit_no"):
            continue      # 整理复习、附录之类不算单元
        text = (r.get("text") or "").strip()
        sid = r.get("section_id")
        k = kp.get(sid) or {}
        try:
            points = json.loads(k.get("points") or "[]")
        except Exception:
            points = []
        latex = [(f.get("latex") or "").strip() for f in fm.get(sid) or []]
        latex = [x for x in latex if x][:12]
        examples = []
        for e in (ex.get(sid) or [])[:3]:
            examples.append("%s（答案：%s）" % (e.get("stem") or e.get("name") or "",
                                             e.get("answer") or ""))
        out.append({
            "section_id": sid, "grade": r.get("grade"), "term": r.get("term"),
            "unit_no": r.get("unit_no"), "title": r.get("title") or "",
            "stage": stage_of(r.get("grade")), "text": text,
            "topic": topic_of(r.get("title"), text),
            "points": [str(p) for p in points][:12], "latex": latex,
            "examples": examples, "page": r.get("page_from"),
        })
    out.sort(key=lambda x: (goals.key_of(x["grade"], x["term"]),
                            str(x["unit_no"] or 0).zfill(3)))
    return out


def _prompt(t: dict) -> str:
    return PROMPT.format(
        title=t["title"], book="%s%s" % (t["grade"], t["term"]),
        unit=t["unit_no"] or "?", topic=t["topic"], stage=t["stage"],
        text=(t["text"] or "（教材未抽到正文）")[:1500],
        points="、".join(t["points"])[:300] or "（暂无）",
        latex="；".join(t["latex"])[:400] or "（暂无）",
        examples=" / ".join(t["examples"])[:500] or "（暂无）",
        traps="、".join(TRAP_TYPES.get(t["stage"], TRAP_TYPES["3-4"])),
        ideas="、".join(IDEAS.get(t["stage"], IDEAS["3-4"])))


def _pick(d: dict, key: str, n: int) -> list:
    v = d.get(key) or []
    return [x for x in v if isinstance(x, dict)][:n]


def _check(t: dict, d: dict) -> tuple:
    stage = t["stage"]
    dropped = []

    why = str(d.get("why") or "").strip()[:120]

    how = []
    for h in _pick(d, "how", 5):
        s = str(h.get("s") or "").strip()
        if s:
            how.append({"s": s[:40], "note": str(h.get("note") or "").strip()[:30]})

    trap_ok = TRAP_TYPES.get(stage, TRAP_TYPES["3-4"])
    traps = []
    for x in _pick(d, "traps", 4):
        tp = str(x.get("type") or "").strip()
        if tp in trap_ok:
            traps.append({"type": tp,
                          "text": str(x.get("text") or "").strip()[:40]})
        else:
            dropped.append("trap:" + tp)

    idea_ok = IDEAS.get(stage, IDEAS["3-4"])
    ideas = []
    for m in (d.get("ideas") or []):
        s = str(m).strip()
        if s in idea_ok:
            ideas.append(s)
        else:
            dropped.append("idea:" + s)
    ideas = ideas[:3]

    lk = d.get("links") or {}
    links = {"before": str(lk.get("before") or "").strip()[:40],
             "after": str(lk.get("after") or "").strip()[:40]}

    got = {"why": why, "how": how, "traps": traps, "ideas": ideas, "links": links}
    return got, dropped


def build(limit: int = 0, force: bool = False, workers: int = 4,
          verbose: bool = True) -> dict:
    todo = _targets()
    if not force:
        done = llm.load_done(KB_FILE, "section_id")
        todo = [t for t in todo if t.get("section_id") not in done]
    if limit:
        todo = todo[:limit]
    if verbose:
        print("待生成数学本体：%d 个单元" % len(todo))
    if not todo:
        return {"ok": 0, "fail": 0}

    ok = fail = 0

    def one(t: dict) -> tuple:
        try:
            res = llm.chat(_prompt(t), max_tokens=1536)
            d = llm.parse_json(res.text)
            if not isinstance(d, dict):
                raise ValueError("返回的不是对象")
            got, dropped = _check(t, d)
            if verbose and dropped:
                print("  丢弃 %s：%s" % (t["title"], "、".join(dropped)[:80]))
            row = {"section_id": t["section_id"], "grade": t["grade"],
                   "term": t["term"], "unit_no": t["unit_no"],
                   "title": t["title"], "stage": t["stage"],
                   "topic": t["topic"], "page": t["page"],
                   "standard": M_STANDARD, "model": res.model,
                   "ts": int(time.time())}
            row.update(got)
            return row, None
        except Exception as e:
            return None, "%s：%s" % (t["title"], e)

    rows_new = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(one, t) for t in todo]
        for i, f in enumerate(as_completed(futs), 1):
            row, err = f.result()
            if err:
                fail += 1
                if verbose:
                    print("  [%d/%d] 失败 %s" % (i, len(todo), err))
                continue
            rows_new.append(row)
            ok += 1
            if verbose:
                print("  [%d/%d] %s(%s·%s) → 算理%d字 步骤%d 易错%d 思想%d"
                      % (i, len(todo), row["title"], row["stage"], row["topic"],
                         len(row["why"]), len(row["how"]), len(row["traps"]),
                         len(row["ideas"])))

    # 重跑的单元覆盖旧记录，直接追加会留两条
    from ..site import goals
    ids = {r["section_id"] for r in rows_new}
    rows = [r for r in _load(KB_FILE) if r.get("section_id") not in ids]
    rows += rows_new
    rows.sort(key=lambda r: (goals.key_of(r["grade"], r["term"]),
                             str(r["unit_no"] or 0).zfill(3)))
    with open(KB_FILE, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if verbose:
        print("→ %s（成功 %d / 失败 %d）" % (KB_FILE, ok, fail))
    return {"ok": ok, "fail": fail}


def stats() -> dict:
    rows = _load(KB_FILE)
    tp = {}
    for r in rows:
        tp[r.get("topic") or "?"] = tp.get(r.get("topic") or "?", 0) + 1
    return {"units": len(rows), "by_topic": tp,
            "traps": sum(len(r.get("traps") or []) for r in rows),
            "ideas": sum(len(r.get("ideas") or []) for r in rows),
            "steps": sum(len(r.get("how") or []) for r in rows)}
