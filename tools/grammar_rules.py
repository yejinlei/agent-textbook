# -*- coding: utf-8 -*-
"""英语语法点 + 写作特征 检测规则表（教材侧 / 课外侧共用）。

设计要点：
  1. 每个 grammar point 是一个 id + 一组正则表达式 + 中英文名。
  2. 每个 writing feature 是一个 id + 一个纯函数(text)→bool。
  3. 检测函数返回 fingerprint dict：{grammar_points, writing_features}。
  4. 正则都是 case-insensitive、词边界安全；对教材里出现的短命令（chant/song）也能命中。

用法：
    from tools.grammar_rules import detect
    fp = detect(text)
    fp == {"grammar_points": [{"id": "be.am_is_are", "count": 4, "evidence": "I am happy"}, ...],
            "writing_features": [{"id": "dialogue_heavy", "ratio": 0.4}, ...]}
"""
from __future__ import annotations
import re
from typing import Callable

# ---------------------------------------------------------------------------
# 语法点（grammar points）
# ---------------------------------------------------------------------------
# 每个 entry: (id, label_zh, label_en, [pattern, ...])
# pattern 可以是 str（自动 compile, IGNORECASE）或 (str, flags)
GRAMMAR_PATTERNS: list[tuple[str, str, str, list[str]]] = [
    # be 动词家族
    ("be.am_is_are",   "be 动词 am/is/are",   "be verb (am/is/are)",
        [r"\b(?:I\s+)?am\b", r"\b(?:he|she|it)\s+is\b", r"\b(?:they|you|we)\s+are\b"]),
    ("be.was_were",    "be 动词 was/were",    "be verb (was/were)",
        [r"\b(?:I|he|she|it)\s+was\b", r"\b(?:they|you|we)\s+were\b"]),
    ("be.contraction", "be 动词缩写 I'm/He's/They're",  "be verb contractions",
        [r"\bI'?m\b", r"\b(?:He|She|It)'?s\b", r"\b(?:You|We|They)'?re\b"]),

    # Pronouns / Possessives
    ("pron.possessive", "形容词性物主代词 my/your/his/her",  "possessive adjectives",
        [r"\b(?:my|your|his|her|its|our|their)\s+[A-Za-z]+"]),
    ("pron.possessive_noun", "'s 所有格", "'s possessive",
        [r"\b(?:cat|dog|fox|crow|bird|horse|baby|mother|father|grandma|grandpa|sister|brother|girl|boy|man|woman|child|teacher|friend)'s\b"]),
    ("pron.these_those", "these/those 指示代词",  "demonstratives",
        [r"\b(?:these|those)\b"]),

    # there be
    ("there.be",       "there is/are",       "there be",
        [r"\bthere\s+(?:is|are|'s)\b"]),

    # Tenses
    ("tense.present_simple",  "一般现在时 (第三人称单数 -s)",  "present simple (3rd sg -s)",
        [r"\b(?:has|likes|wants|needs|loves|sees|knows|makes|takes|gets|comes|plays|reads|writes|says|does|works|looks|lives|gives|brings|has|have)\b",
         r"\b(?:he|she|it)\s+\w{2,}(?:s|es)\b(?!['‘’\w])"]),
    ("tense.present_progressive",  "现在进行时 is/are -ing",  "present progressive",
        [r"\b(?:am|is|are)\s+\w+ing\b"]),
    ("tense.future_going_to",      "一般将来时 will / going to",  "future (will / going to)",
        [r"\bwill\s+\w+", r"\b(?:is|are|am|was|were)\s+going\s+to\b"]),
    ("tense.past_simple",          "一般过去时 -ed",  "past simple",
        [r"\b(?:was|were|had|did|went|saw|made|took|got|came|played|wanted)\b"]),

    # Modal verbs
    ("modal.can_could",  "情态动词 can/could",  "modal can/could",
        [r"\b(?:can|can't|cannot|could)\b"]),
    ("modal.should_must",  "should / must",     "modal should / must",
        [r"\b(?:should|must)\b"]),

    # Imperative
    ("imperative",       "祈使句（动词开头）",  "imperative sentences",
        [r"^[A-Z]?[a-z]+\s+(?:your|the|me|us|him|her|them|it|my|our)\b",
         r"\b(?:open|close|put|take|show|tell|say|make|go|come|listen|look|share|help|sing|play|draw|read|write|wave|smile)\s+(?:your|the|me|us|him|her|them|it|my|our|his|her|a|an)\b"]),

    # Interrogatives
    ("question.wh_words",  "疑问词 What/Where/Who/Why/How/When/Which",  "wh-questions",
        [r"\b(?:What|Where|Who|Whose|Why|How|When|Which|Whom)\s+\w+"]),
    ("question.be_verb_invert",  "be 动词疑问句 Are you...",  "be-verb questions",
        [r"\b(?:Are|Is|Am)\s+(?:you|I|he|she|it|we|they)\b"]),
    ("question.do_verb_invert",  "do/does 疑问句",  "do/does questions",
        [r"\b(?:Do|Does)\s+(you|I|he|she|it|we|they)\b"]),

    # Comparatives & superlatives
    ("comparative",  "比较级 -er / more ... than",  "comparatives",
        [r"\b\w+er\s+than\b", r"\bmore\s+\w+\s+than\b",
         r"\b(?:taller|shorter|bigger|smaller|older|younger|better|worse|more|less)\b"]),

    # Plurals
    ("noun.plural_s",  "名词复数 -s/-es",  "noun plurals",
        # 白名单：常见教材复数名词（含 Unit 1-4 出现的 animals/fruit/people 等）
        [r"\b(?:cats|dogs|bears|monkeys|apples|oranges|bananas|grapes|broccoli|tomatoes|potatoes|carrots|eggs|boxes|boxes|books|pens|pencils|rulers|erasers|rubbers|crayons|dolls|bags|pencases|schoolbags|pandas|lions|tigers|elephants|rabbits|hamsters|parrots|fish|men|women|children|friends|teachers|parents|sisters|brothers|grandparents|friends|brothers|sisters|people|boys|girls|kids|babies|cows|sheep|horses|chickens|ducks|pigs|foxes|lions|tigers|bears|monkeys|pandas|birds)\b",
         r"\b(?:there\s+are\s+(?:some|any)\s+\w+s)"]
    ),

    # Prepositions
    ("prep.common",  "介词 in/on/at/under/behind/next to",  "common prepositions",
        [r"\b(?:in|on|at|under|over|behind|in\s+front\s+of|next\s+to|between)\b"]),

    # Negation
    ("negation",  "否定 not/don't/can't",  "negation",
        [r"\b(?:not|no|never|don't|doesn't|didn't|isn't|aren't|wasn't|weren't|can't|couldn't|won't|wouldn't)\b"]),

    # Articles
    ("article.a_an",  "不定冠词 a/an",  "indefinite article a/an",
        [r"\b(?:a|an)\s+\w+"]),
    ("article.the",   "定冠词 the",    "definite article the",
        [r"\bthe\s+\w+"]),

    # Conjunctions
    ("conj.and_or_but",  "and / or / but",  "coordinating conjunctions",
        [r"\b(?:and|or|but)\b"]),

    # Interjections / Exclamations
    ("exclamation",  "感叹词 Oh / Hey / Wow / Bye",  "interjections",
        [r"\b(?:Oh|Hey|Wow|Bye|Hi|Hello)\b[!?,.]"]),
]


# ---------------------------------------------------------------------------
# 写作特征（writing features）
# ---------------------------------------------------------------------------
# 每个 entry: (id, label_zh, label_en, ratio_func(text) -> float|None)
#   - 返回 [0,1] 的比例值，或 None（不适合此文本，如长度不足）
def _ratio(hit: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(hit / total, 3)


def _sentences(text: str) -> list[str]:
    # 简易分句：句末标点 + 换行
    parts = re.split(r"[.!?]+(?:\s+|$)|\n+", text)
    return [s.strip() for s in parts if s.strip() and len(s.strip()) > 2]


def _feat_question_ratio(text: str):
    sents = _sentences(text)
    if len(sents) < 3:
        return None
    q = sum(1 for s in sents if s.lstrip().startswith(("What", "Where", "Who", "Why", "How", "When", "Which", "Do", "Does", "Are", "Is", "Am", "Can", "Should", "Must")))
    return _ratio(q, len(sents))


def _feat_exclamation_ratio(text: str):
    sents = _sentences(text)
    if len(sents) < 3:
        return None
    e = sum(1 for s in sents if "!" in s)
    return _ratio(e, len(sents))


def _feat_short_sentence_ratio(text: str):
    sents = [s for s in _sentences(text) if not s.startswith("<")]
    if len(sents) < 5:
        return None
    short = sum(1 for s in sents if len(s.split()) <= 6)
    return _ratio(short, len(sents))


def _feat_dialogue_ratio(text: str):
    """按行判定"对话式"：短行 + 名字/称呼起手。"""
    lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 1]
    if len(lines) < 6:
        return None
    dial_pat = re.compile(r"^(?:[A-Z][a-z]+|[A-Z][a-z]+s?)\s*:|^(?:Hello|Hi|Hey|Bye|OK|Okay|Yes|No|Thank|Thanks|Nice|What|Where|Who|Why|How|When|Which|Are|Is|Am|Can|Should)\b|^[\"“].*[\"”]$")
    dial = sum(1 for l in lines if len(l) <= 40 and dial_pat.match(l))
    return _ratio(dial, len(lines))


def _feat_rhyme_presence(text: str):
    """押韵检测：取每行末尾单词的最后 3 字母（去掉静音 e），出现 >=2 次相同。"""
    lines = [l.strip().rstrip(".!?,\"“”") for l in text.splitlines() if l.strip()]
    if len(lines) < 4:
        return None
    endings: dict[str, int] = {}
    for l in lines:
        # 取最后单词
        m = re.search(r"([A-Za-z]+)\s*$", l)
        if not m:
            continue
        w = m.group(1).lower()
        if len(w) < 3:
            continue
        # 去静音 e（如 "me"→"m"，"tree"→"treeno"）——保留 3 字母
        ending = re.sub(r"[aeiou]", "", w[-3:]).strip()
        if len(ending) >= 2:
            endings[ending] = endings.get(ending, 0) + 1
    if not endings:
        return 0.0
    rhyme_hits = sum(1 for v in endings.values() if v >= 2)
    return min(rhyme_hits / 2, 1.0)


def _feat_sentence_variety(text: str):
    """句式多样性：不同疑问类型 + 感叹 + 陈述 + 祈使 的覆盖度。"""
    sents = [s.strip() for s in _sentences(text) if len(s.strip()) > 2]
    if len(sents) < 6:
        return None
    kinds = set()
    for s in sents:
        head = s.lstrip()
        if head.endswith("?"):
            kinds.add("question")
        if head.endswith("!"):
            kinds.add("exclamation")
        if re.match(r"^[A-Z][a-z]+\s+(?:the|your|me|us|him|her|them)\b", head):
            kinds.add("imperative")
        else:
            kinds.add("statement")
    return _ratio(len(kinds), 4)  # 4 类齐全=1.0


def _feat_list_structure(text: str):
    """列表式（chant / 词汇表）：多行同长度短词。"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 5:
        return 0.0
    short_lines = [l for l in lines if len(l.split()) <= 3]
    return min(len(short_lines) / len(lines), 1.0)


WRITING_FEATURES: list[tuple[str, str, str, Callable[[str], float | None]]] = [
    ("q_ratio",           "疑问句比例",    "question sentence ratio",   _feat_question_ratio),
    ("exclamation_ratio", "感叹句比例",    "exclamation sentence ratio", _feat_exclamation_ratio),
    ("short_sentence",    "短句比例（<=6 词）", "short sentence ratio", _feat_short_sentence_ratio),
    ("dialogue_heavy",    "对话式行文",    "dialogue-heavy structure", _feat_dialogue_ratio),
    ("rhyme",             "押韵",          "rhyme in chant/song",      _feat_rhyme_presence),
    ("sentence_variety",  "句式多样性",    "sentence variety",         _feat_sentence_variety),
    ("list_like",         "列表/chant 结构", "list-like (chant) structure", _feat_list_structure),
]


# ---------------------------------------------------------------------------
# 主检测入口
# ---------------------------------------------------------------------------
_COMPILED = [
    (gid, gzh, gen, [re.compile(p, re.IGNORECASE) for p in patterns])
    for gid, gzh, gen, patterns in GRAMMAR_PATTERNS
]


def detect(text: str) -> dict:
    """输入一段英文文本，返回 grammar_points + writing_features 指纹。"""
    text = text or ""
    # grammar
    gpts: list[dict] = []
    for gid, gzh, gen, rx_list in _COMPILED:
        total_hits = 0
        evidence = ""
        for rx in rx_list:
            m = rx.search(text)
            if m:
                evidence = m.group(0)[:40]
                # 用 findall 数出现次数
                total_hits += len(rx.findall(text))
        if total_hits > 0:
            gpts.append({
                "id": gid,
                "label_zh": gzh,
                "label_en": gen,
                "count": total_hits,
                "evidence": evidence,
            })
    # writing features
    wfs: list[dict] = []
    for wid, wzh, wen, fn in WRITING_FEATURES:
        try:
            v = fn(text)
        except Exception:
            v = None
        if v is not None:
            wfs.append({
                "id": wid,
                "label_zh": wzh,
                "label_en": wen,
                "value": round(v, 3) if isinstance(v, float) else v,
            })
    return {
        "grammar_points": gpts,
        "writing_features": wfs,
    }


def ids_of(fp: dict) -> tuple[list[str], list[str]]:
    """从指纹里抽出 (grammar ids, writing feature ids) 两个集合，用于 overlap 计算。"""
    gids = [g["id"] for g in fp.get("grammar_points", [])]
    wids = [w["id"] for w in fp.get("writing_features", [])]
    return gids, wids
