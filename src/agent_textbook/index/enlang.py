# -*- coding: utf-8 -*-
"""英语本体的五个深挖层：情景对话 / 句型语法 / 拼读 / 语篇 / 项目。

英语教材的知识组织单位不是"小节"而是**交际功能 + 句型**：一个 Unit 里
Let's talk 给情景对话、Let's learn 给目标句型、Letters and sounds 给拼读规则。
所以英语在词汇表（enwords.py 规则抽附录）之外再抽五层：

    attrs/en_dialogue.jsonl  情景对话：场景、交际功能、逐句话轮（含中译）、
                             本节可套用的句型
    attrs/en_grammar.jsonl   句型/语法：结构式、规则、时态或词法归类、例句
    attrs/en_phonics.jsonl   拼读：字母或字母组合、发音、例词、歌谣原文
    attrs/en_passage.jsonl   语篇：Read and write / Start to read / Story time
                             的成篇原文、体裁、阅读理解题、配套写作任务
    attrs/en_project.jsonl   项目：Project / Make a 的任务目标、步骤、产出、
                             做这件事要用的语言

前三层是"怎么说"，后两层是"怎么读、怎么写、怎么用"——教材里 Read and write
与 Project 占了 62 / 63 节，不抽这两层，"阅读理解"和"做中学"两个课标维度在
库里就是空的，只剩词汇和句型。

只概括正文出现的对话与句型，**不补充课外语法**（教材没写的不写），
避免把教参体系当成教材内容。
"""

from __future__ import annotations

import json
import os
import re
import time

from .. import config
from . import llm

DIALOGUE_FILE = os.path.join(config.ATTRS_DIR, "en_dialogue.jsonl")
GRAMMAR_FILE = os.path.join(config.ATTRS_DIR, "en_grammar.jsonl")
PHONICS_FILE = os.path.join(config.ATTRS_DIR, "en_phonics.jsonl")
PASSAGE_FILE = os.path.join(config.ATTRS_DIR, "en_passage.jsonl")
PROJECT_FILE = os.path.join(config.ATTRS_DIR, "en_project.jsonl")

FUNCS = ("问候与介绍", "询问信息", "请求与应答", "描述事物", "表达喜好",
         "邀请与建议", "购物与价格", "时间与日程", "方位与路线",
         "能力与他人", "感受与情绪", "其他")

G_CATS = ("句型", "时态", "名词", "代词", "介词", "形容词副词", "疑问句",
          "情态动词", "There be", "其他")

# 语篇体裁：教材里成篇出现的文体就这几种，别的归入"其他"
P_GENRES = ("短文", "对话", "书信", "邮件", "日记", "故事", "剧本", "歌谣",
            "通知", "说明", "图表说明", "谜语", "诗歌", "其他")
P_SOURCES = ("Read and write", "Start to read", "Story time", "Short plays",
             "Let's read", "Reading", "其他")
# 项目类型：Project / Make a 栏目的常见形态
PJ_TYPES = ("手工制作", "调查采访", "角色表演", "海报展板", "游戏活动",
            "展示介绍", "写作创作", "其他")

# 只在这两类栏目出现的节才值得调用模型：正文里没有对应板块就跳过，
# 省掉约一半的调用（137 节里语篇约 80 节、项目约 70 节）。
RE_HAS_PASSAGE = re.compile(
    r"Read and write|Start to read|Story time|Short plays|Let\u2019s read|Reading",
    re.I)
RE_HAS_PROJECT = re.compile(r"Project|Make a|Let\u2019s make|Make and", re.I)

PROMPT_DIALOGUE = (
    "你是小学英语教材分析助手。只根据下面这段教材正文，把里面的**对话**逐个"
    "抽出来（教材里的 Let's talk、Listen and chant、Listen and sing、"
    "Role-play、Story time 都算）。\n"
    "只输出 JSON：\n"
    '{{"dialogues":[{{"scene":"","function":"问候与介绍","turns":['
    '{{"speaker":"","en":"","zh":""}}],"patterns":[],"page_hint":""}}]}}\n'
    "要求：\n"
    "1. 一段对话一条：同一个情景里连续的话轮算一段，中间换场景就另起一条。\n"
    "2. turns 按原文顺序，一句一个元素；speaker 写说话人（教材里没写名字就"
    "用 A/B），en 写英文原句，zh 写这一句的中文意思（正文没给就按字面译）。\n"
    "3. function 只能是 问候与介绍/询问信息/请求与应答/描述事物/表达喜好/"
    "邀请与建议/购物与价格/时间与日程/方位与路线/能力与他人/感受与情绪/其他 之一。\n"
    "4. patterns 写这段对话里可套用的句型（如 Where are you from? I'm from ...），"
    "最多 4 条，必须是正文里出现过的。\n"
    "5. 歌谣/chant 也算对话，speaker 写 Chant。\n"
    "6. 正文里没有对话就输出 {{\"dialogues\":[]}}；一节最多 6 段。\n\n"
    "年级：{grade}{term}　单元：{unit}　小节：{title}\n\n"
    "正文：\n{body}"
)

PROMPT_GRAMMAR = (
    "你是小学英语教材分析助手。只根据下面这段教材正文，抽出**句型与语法点**。\n"
    "只输出 JSON：\n"
    '{{"grammar":[{{"point":"","pattern":"","rule":"","category":"句型",'
    '"tense":"","examples":[{{"en":"","zh":""}}],"page_hint":""}}]}}\n'
    "要求：\n"
    "1. point 写这个语法点的名字（如 询问国籍、there be 句型、一般现在时）。\n"
    "2. pattern 写结构式，可替换的部分用 ... 或占位（如 Where are you from? "
    "I'm from ...；There is/are ...）。\n"
    "3. rule 用一句小学生能懂的话说明用法或构成，照正文意思，不要扩写成语法书。\n"
    "4. category 只能是 句型/时态/名词/代词/介词/形容词副词/疑问句/情态动词/"
    "There be/其他 之一。\n"
    "5. tense 只在涉及时态时填（一般现在时/一般过去时/一般将来时/现在进行时/"
    "be going to），否则填空。\n"
    "6. examples 写正文里出现过的例句（英文 + 中文），最多 4 条。\n"
    "7. 正文里没有明确的句型/语法板块就输出 {{\"grammar\":[]}}；一节最多 6 条。\n\n"
    "年级：{grade}{term}　单元：{unit}　小节：{title}\n\n"
    "正文：\n{body}"
)

PROMPT_PHONICS = (
    "你是小学英语教材分析助手。只根据下面这段教材正文，抽出**自然拼读 / 语音**"
    "板块（Letters and sounds、Let's spell、Listen and repeat 等）。\n"
    "只输出 JSON：\n"
    '{{"phonics":[{{"letters":"","sound":"","examples":[],"chant":"",'
    '"page_hint":""}}]}}\n'
    "要求：\n"
    "1. letters 写字母或字母组合（如 a、ea、sh、a-e）。\n"
    "2. sound 写发音（音标或教材标注的读法，如 /æ/）。\n"
    "3. examples 写正文给出的例词（纯英文单词，最多 10 个）。\n"
    "4. chant 写配套的歌谣/句子原文（如 The cat is fat.）；没有就填空。\n"
    "5. 正文里没有拼读板块就输出 {{\"phonics\":[]}}。\n\n"
    "年级：{grade}{term}　单元：{unit}　小节：{title}\n\n"
    "正文：\n{body}"
)


PROMPT_PASSAGE = (
    "你是小学英语教材分析助手。只根据下面这段教材正文，把里面的**成篇语篇**"
    "（Read and write、Start to read、Story time、Short plays、邮件/日记/故事等"
    "连续成篇的内容）逐个抽出来。\n"
    "只输出 JSON：\n"
    '{{"passages":[{{"name":"","genre":"短文","source":"Read and write",'
    '"text":"","zh":"","topic":"","words":[],"comprehension":['
    '{{"q":"","options":[],"answer":""}}],"writing_task":"","keypoints":[]}}]}}\n'
    "要求：\n"
    "1. 一段成篇内容一条。**只抽** Read and write、Start to read、Story time、"
    "Short plays、Let's read 这些栏目里的成篇内容（含它们附的短文、邮件、日记、"
    "故事、剧本）。\n"
    "   以下**都不算语篇**，抽了就是错的：Let's talk 的对话、Let's learn 的单词和"
    "句型、Let's chant / Let's sing 的歌谣（歌谣归拼读层）、Let's check 的听力题、"
    "单词表与附录。\n"
    "2. text 是**原文**，按教材顺序写，句子之间用换行分隔；不要改写、不要补写。\n"
    "3. genre 只能是 短文/对话/书信/邮件/日记/故事/剧本/歌谣/通知/说明/图表说明/"
    "谜语/诗歌/其他 之一。\n"
    "4. source 填它所在的栏目名，只能是 Read and write / Start to read / "
    "Story time / Short plays / Let's read / Reading 之一；判断不出就填 其他"
    "（不要留空）。\n"
    "5. zh 写这段的中文意思（按正文意思译，不要添加正文没有的内容）。\n"
    "6. words 写这段里的目标词或词组（英文，最多 10 个）。\n"
    "7. comprehension 写教材附的阅读理解题（填空题、判断题、选择题都写）："
    "q 是题干，options 是选项（没有选项就空数组），answer 填教材给出的答案；"
    "教材没给答案就填空，不要猜。\n"
    "8. writing_task 写配套的写作/仿写要求原文（如 Write about your friend.）；"
    "没有就填空。\n"
    "9. keypoints 写这段涉及的语言点（最多 4 条，如 there be、一般现在时第三人称）。\n"
    "10. 正文里没有成篇内容就输出 {{\"passages\":[]}}；一节最多 3 段。\n\n"
    "年级：{grade}{term}　单元：{unit}　小节：{title}\n\n"
    "正文：\n{body}"
)

PROMPT_PROJECT = (
    "你是小学英语教材分析助手。只根据下面这段教材正文，把里面的**项目/动手任务**"
    "（Project、Make a ...、Let's make、Make and say 等要学生做出成果的任务）"
    "逐个抽出来。\n"
    "只输出 JSON：\n"
    '{{"projects":[{{"name":"","type":"手工制作","goal":"","steps":[],'
    '"language":[],"product":"","materials":[]}}]}}\n'
    "要求：\n"
    "1. 一个任务一条；纯练习题、对话、单词表不算项目。\n"
    "2. name 写教材印的任务名（如 Make a family tree、Make a poster）。\n"
    "3. type 只能是 手工制作/调查采访/角色表演/海报展板/游戏活动/展示介绍/"
    "写作创作/其他 之一。\n"
    "4. goal 用一句话说清这个任务要做什么、做成什么。\n"
    "5. steps 按教材给的顺序写步骤（一条一步，最多 8 步）；教材没写步骤就填空数组。\n"
    "6. language 写完成这个任务要用到的句型或表达（英文，最多 6 条，必须是正文"
    "里出现过的，如 This is my ... / I can ...）。\n"
    "7. product 写最终产出物（如 一张家庭树海报）；materials 写所需材料"
    "（正文没提就填空数组）。\n"
    "8. 正文里没有项目/动手任务就输出 {{\"projects\":[]}}；一节最多 3 个。\n\n"
    "年级：{grade}{term}　单元：{unit}　小节：{title}\n\n"
    "正文：\n{body}"
)


def _load_sections(subject: str = "英语") -> list[dict]:
    src = os.path.join(config.ATTRS_DIR, "section_text.jsonl")
    if not os.path.exists(src):
        return []
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    if subject:
        rows = [r for r in rows if r.get("subject") == subject]
    return [r for r in rows if (r.get("text") or "").strip()]


def _base(r: dict, sid: str) -> dict:
    return {
        "section_id": r.get("section_id"), "book_id": r.get("book_id"),
        "subject": r.get("subject"), "grade": r.get("grade"),
        "term": r.get("term"), "unit_name": r.get("unit_name"),
        "title": r.get("title"),
    }


def _run(rows: list[dict], path: str, prompt_tpl: str, key: str, id_key: str,
         build_row, empty_row, verbose: bool, label: str) -> dict:
    ok = fail = n = 0
    for i, r in enumerate(rows, 1):
        prompt = prompt_tpl.format(
            grade=r.get("grade") or "", term=r.get("term") or "",
            unit=r.get("unit_name") or "", title=r.get("title") or "",
            body=(r.get("text") or "")[:6000])
        try:
            res = llm.chat(prompt, max_tokens=4000)
            data = llm.parse_json(res.text)
            items = data.get(key) or []
            if not items:
                row = _base(r, "")
                row.update(empty_row())
                row[id_key] = r["section_id"] + ":000"
                row["model"] = res.model
                row["ts"] = int(time.time())
                llm.append_jsonl(path, row)
                ok += 1
                continue
            for k, it in enumerate(items, 1):
                row = build_row(r, it)
                if not row:
                    continue
                row.update(_base(r, ""))
                row[id_key] = "%s:%02d" % (r["section_id"], k)
                row["model"] = res.model
                row["ts"] = int(time.time())
                llm.append_jsonl(path, row)
                n += 1
            ok += 1
            if verbose:
                print("  [%d/%d] %s → %d %s" % (i, len(rows), r.get("title"), len(items), label))
        except Exception as exc:
            fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(rows), r.get("title"), exc))
    if verbose:
        print("→ %s（节 %d / 失败 %d / %s %d）" % (path, ok, fail, label, n))
    return {"ok": ok, "fail": fail, "n": n}


def build_dialogues(subject: str = "英语", limit: int = 0, force: bool = False,
                    verbose: bool = True) -> dict:
    rows = _load_sections(subject)
    if not force:
        done = llm.load_done(DIALOGUE_FILE, "section_id")
        rows = [r for r in rows if r.get("section_id") not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽情景对话：%d 节" % len(rows))

    def build(r, d):
        turns = []
        for t in (d.get("turns") or []):
            en = (t.get("en") or "").strip()
            if not en:
                continue
            turns.append({"speaker": (t.get("speaker") or "").strip()[:20],
                          "en": en[:200], "zh": (t.get("zh") or "").strip()[:200]})
        if not turns:
            return None
        fn = (d.get("function") or "").strip()
        return {"scene": (d.get("scene") or "").strip()[:100],
                "function": fn if fn in FUNCS else "其他",
                "turns": turns[:40],
                "patterns": [str(x).strip()[:120] for x in (d.get("patterns") or [])][:4],
                "page_hint": (d.get("page_hint") or "").strip()[:20]}

    return _run(rows, DIALOGUE_FILE, PROMPT_DIALOGUE, "dialogues",
                "dialogue_id", build,
                lambda: {"scene": "", "function": "", "turns": [], "patterns": [],
                         "page_hint": ""},
                verbose, "段对话")


def build_grammar(subject: str = "英语", limit: int = 0, force: bool = False,
                  verbose: bool = True) -> dict:
    rows = _load_sections(subject)
    if not force:
        done = llm.load_done(GRAMMAR_FILE, "section_id")
        rows = [r for r in rows if r.get("section_id") not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽句型语法：%d 节" % len(rows))

    def build(r, g):
        point = (g.get("point") or "").strip()
        if not point:
            return None
        exs = []
        for e in (g.get("examples") or []):
            en = (e.get("en") or "").strip() if isinstance(e, dict) else str(e).strip()
            if not en:
                continue
            zh = (e.get("zh") or "").strip() if isinstance(e, dict) else ""
            exs.append({"en": en[:200], "zh": zh[:200]})
        cat = (g.get("category") or "").strip()
        return {"point": point[:60],
                "pattern": (g.get("pattern") or "").strip()[:200],
                "rule": (g.get("rule") or "").strip()[:300],
                "category": cat if cat in G_CATS else "其他",
                "tense": (g.get("tense") or "").strip()[:20],
                "examples": exs[:4],
                "page_hint": (g.get("page_hint") or "").strip()[:20]}

    return _run(rows, GRAMMAR_FILE, PROMPT_GRAMMAR, "grammar",
                "grammar_id", build,
                lambda: {"point": "", "pattern": "", "rule": "", "category": "",
                         "tense": "", "examples": [], "page_hint": ""},
                verbose, "条语法")


def _passage_ok(p: dict) -> bool:
    """语篇层只留"成篇的读与写"，别把别的层的内容搬过来。

    模型会把 Let's chant 的歌谣（拼读层已有 chant）和说不清栏目的对话（多是
    Let's talk，对话层已有）也算成语篇，两层撞车；还有把听力题干当作正文的。
    """
    g, s = (p.get("genre") or "").strip(), (p.get("source") or "").strip()
    if g == "歌谣":
        return False
    if g == "对话" and s == "其他":
        return False
    text = (p.get("text") or "").strip()
    if len(text) < 120 and re.match(r"^(Listen|Look|Read) and\b", text):
        return False
    return True


def build_passages(subject: str = "英语", limit: int = 0, force: bool = False,
                   verbose: bool = True) -> dict:
    """语篇层：成篇的读与写（Read and write / Start to read / Story time）。

    只调用正文里真有语篇栏目的节——137 节里约一半没有，跳过能省一半调用。
    """
    rows = _load_sections(subject)
    rows = [r for r in rows if RE_HAS_PASSAGE.search(r.get("text") or "")]
    if not force:
        done = llm.load_done(PASSAGE_FILE, "section_id")
        rows = [r for r in rows if r.get("section_id") not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽语篇：%d 节" % len(rows))

    def build(r, p):
        text = (p.get("text") or "").strip()
        if not text or not _passage_ok(p):
            return None
        comp = []
        for c in (p.get("comprehension") or [])[:8]:
            q = (c.get("q") or "").strip() if isinstance(c, dict) else str(c).strip()
            if not q:
                continue
            comp.append({
                "q": q[:300],
                "options": [str(x).strip()[:80] for x in
                            (c.get("options") or [])][:6] if isinstance(c, dict) else [],
                "answer": (c.get("answer") or "").strip()[:120] if isinstance(c, dict) else "",
            })
        g = (p.get("genre") or "").strip()
        s = (p.get("source") or "").strip()
        return {"name": (p.get("name") or "").strip()[:80],
                "genre": g if g in P_GENRES else "其他",
                "source": s if s in P_SOURCES else "其他",
                "text": text[:4000],
                "zh": (p.get("zh") or "").strip()[:2000],
                "topic": (p.get("topic") or "").strip()[:60],
                "words": [str(x).strip()[:40] for x in (p.get("words") or [])][:10],
                "comprehension": comp,
                "writing_task": (p.get("writing_task") or "").strip()[:400],
                "keypoints": [str(x).strip()[:60] for x in
                              (p.get("keypoints") or [])][:4]}

    return _run(rows, PASSAGE_FILE, PROMPT_PASSAGE, "passages", "passage_id", build,
                lambda: {"name": "", "genre": "", "source": "", "text": "", "zh": "",
                         "topic": "", "words": [], "comprehension": [],
                         "writing_task": "", "keypoints": []},
                verbose, "段语篇")


def build_projects(subject: str = "英语", limit: int = 0, force: bool = False,
                   verbose: bool = True) -> dict:
    """项目层：Project / Make a ... —— 课标的"做中学"维度。"""
    rows = _load_sections(subject)
    rows = [r for r in rows if RE_HAS_PROJECT.search(r.get("text") or "")]
    if not force:
        done = llm.load_done(PROJECT_FILE, "section_id")
        rows = [r for r in rows if r.get("section_id") not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽项目：%d 节" % len(rows))

    def build(r, p):
        name = (p.get("name") or "").strip()
        if not name:
            return None
        t = (p.get("type") or "").strip()
        return {"name": name[:80],
                "type": t if t in PJ_TYPES else "其他",
                "goal": (p.get("goal") or "").strip()[:300],
                "steps": [str(x).strip()[:200] for x in (p.get("steps") or [])][:8],
                "language": [str(x).strip()[:120] for x in (p.get("language") or [])][:6],
                "product": (p.get("product") or "").strip()[:120],
                "materials": [str(x).strip()[:40] for x in
                              (p.get("materials") or [])][:8]}

    return _run(rows, PROJECT_FILE, PROMPT_PROJECT, "projects", "project_id", build,
                lambda: {"name": "", "type": "", "goal": "", "steps": [],
                         "language": [], "product": "", "materials": []},
                verbose, "个项目")


def build_phonics(subject: str = "英语", limit: int = 0, force: bool = False,
                  verbose: bool = True) -> dict:
    rows = _load_sections(subject)
    if not force:
        done = llm.load_done(PHONICS_FILE, "section_id")
        rows = [r for r in rows if r.get("section_id") not in done]
    if limit:
        rows = rows[:limit]
    if verbose:
        print("待抽拼读：%d 节" % len(rows))

    def build(r, p):
        letters = (p.get("letters") or "").strip()
        if not letters:
            return None
        return {"letters": letters[:30],
                "sound": (p.get("sound") or "").strip()[:40],
                "examples": [str(x).strip()[:40] for x in (p.get("examples") or [])][:10],
                "chant": (p.get("chant") or "").strip()[:300],
                "page_hint": (p.get("page_hint") or "").strip()[:20]}

    return _run(rows, PHONICS_FILE, PROMPT_PHONICS, "phonics",
                "phonics_id", build,
                lambda: {"letters": "", "sound": "", "examples": [], "chant": "",
                         "page_hint": ""},
                verbose, "条拼读")
