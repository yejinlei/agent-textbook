# -*- coding: utf-8 -*-
"""英语本体的三个深挖层：情景对话 / 句型语法 / 拼读。

英语教材的知识组织单位不是"小节"而是**交际功能 + 句型**：一个 Unit 里
Let's talk 给情景对话、Let's learn 给目标句型、Letters and sounds 给拼读规则。
所以英语在词汇表（enwords.py 规则抽附录）之外再抽三层：

    attrs/en_dialogue.jsonl  情景对话：场景、交际功能、逐句话轮（含中译）、
                             本节可套用的句型
    attrs/en_grammar.jsonl   句型/语法：结构式、规则、时态或词法归类、例句
    attrs/en_phonics.jsonl   拼读：字母或字母组合、发音、例词、歌谣原文

只概括正文出现的对话与句型，**不补充课外语法**（教材没写的不写），
避免把教参体系当成教材内容。
"""

from __future__ import annotations

import json
import os
import time

from .. import config
from . import llm

DIALOGUE_FILE = os.path.join(config.ATTRS_DIR, "en_dialogue.jsonl")
GRAMMAR_FILE = os.path.join(config.ATTRS_DIR, "en_grammar.jsonl")
PHONICS_FILE = os.path.join(config.ATTRS_DIR, "en_phonics.jsonl")

FUNCS = ("问候与介绍", "询问信息", "请求与应答", "描述事物", "表达喜好",
         "邀请与建议", "购物与价格", "时间与日程", "方位与路线",
         "能力与他人", "感受与情绪", "其他")

G_CATS = ("句型", "时态", "名词", "代词", "介词", "形容词副词", "疑问句",
          "情态动词", "There be", "其他")

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
