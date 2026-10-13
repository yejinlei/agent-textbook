"""绘本挂教材单元：Pairing 匹配脚本
输入：
  - data/picturebooks/books.json      （绘本库）
  - data/picturebooks/topics.json     （绘本话题关键词）
  - data/attrs/section_text.jsonl     （英语教材单元权威源）
  - data/attrs/en_passage.jsonl       （英语短文，提供更细的 topic/words）
输出：
  - data/picturebooks/pairings.json   （Pairing 实例表，含 match_score/reason）
  - data/picturebooks/books.json      （回写 pairs_with_unit + extends_activity）
"""
from __future__ import annotations
import json, re
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
PB_DIR = ROOT / "data" / "picturebooks"
ATTRS = ROOT / "data" / "attrs"

BOOKS_PATH = PB_DIR / "books.json"
TOPICS_PATH = PB_DIR / "topics.json"
SECTIONS_PATH = ATTRS / "section_text.jsonl"
PASSAGES_PATH = ATTRS / "en_passage.jsonl"
UNIT_GRAMMAR_PATH = ATTRS / "unit_grammar.json"
PAIRINGS_PATH = PB_DIR / "pairings.json"


# -------- 数据加载 --------
def load_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def get_units() -> list[dict]:
    """把 section_text 转成轻量 unit 索引（仅英语，只保留正课 Unit，排除附录/词汇表）"""
    units = []
    for sec in load_jsonl(SECTIONS_PATH):
        if sec.get("subject") != "英语":
            continue
        title = (sec.get("title") or "").strip()
        unit_name = (sec.get("unit_name") or "").strip()
        # 排除附录、词汇表、总复习、phonics 汇总表等
        noise_kw = ("appendix", "词汇", "单词", "vocabulary", "words in",
                     "复习", "revision", "recycle", "review")
        if any(k.lower() in title.lower() or k.lower() in unit_name.lower() for k in noise_kw):
            continue
        if not unit_name.startswith("Unit"):
            continue
        text = (sec.get("text") or "")[:4000]
        units.append({
            "section_id": sec["section_id"],
            "book_id": sec["book_id"],
            "grade": sec.get("grade"),
            "term": sec.get("term"),
            "unit_no": sec.get("unit_no"),
            "unit_name": sec.get("unit_name"),
            "title": sec.get("title"),
            "text_head": text,
            "text_len": len(text),
        })
    return units


def get_passage_by_section(section_id: str) -> list[dict]:
    """按 section_id 索引 en_passage 的 topic / words"""
    return [p for p in load_jsonl(PASSAGES_PATH)
            if p.get("section_id") == section_id]


# -------- 特征提取 --------
_STOP = set("""
a an the and or but of in on at to for with from by is are was were be been being
have has had do does did can could will would should may might must i you he she it
we they me him her us them my your his its our their this that these those what
which who whom whose where when how not no yes so if as than then here there only
also very much some any all other more most too one two get got go goes going been
""".split())

_WORD_RE = re.compile(r"[A-Za-z]+")


def tokens(text: str) -> list[str]:
    # 先把 's / 'll / 're / 've / 'n't / 't 拆开，方便 father's → father
    t = re.sub(r"\b(\w+)'s\b", lambda m: " " + m.group(1) + " ", text.lower())
    t = re.sub(r"\b(\w+)'(?:ll|re|ve|n't|t)\b", lambda m: " " + m.group(1) + " ", t)
    return [w for w in _WORD_RE.findall(t) if w not in _STOP and len(w) > 2]


def unique_tokens(text: str) -> set[str]:
    return set(tokens(text))


def keyword_hits(text_tokens: set[str], keywords: list[str]) -> int:
    """keywords 里可能包含多词短语，逐条比对"""
    text = " " + " ".join(text_tokens) + " "
    hits = 0
    for kw in keywords:
        kw = kw.lower().strip()
        if not kw:
            continue
        if " " in kw:
            if kw in text:
                hits += 1
        else:
            if kw in text_tokens:
                hits += 1
    return hits


# -------- 评分 --------
# 策略：
#   1. topic 关键词命中（primary + secondary）——主权重
#   2. covers_words 命中——中权重
#   3. 教材单元文本里出现的绘本词（覆盖词汇）——低权重
# 只有 (1) 命中 >= 1 才允许建立 Pairing；否则丢弃（避免"任何书都能挂任何东西"）。

_W_TOPIC = 30     # 每命中一个 topic 关键词加 30 分
_W_COVER = 20     # 每命中一个 covers_word 加 20 分
_W_SKILL = 15     # 语法/技能维度命中
_GRADE_PENALTY = 10  # 年级不匹配扣分

# PB 级别 → 合适年级范围（大致对应）
PB_GRADE_FIT = {
    "PB1": {"一", "二", "三"},
    "PB2": {"三", "四", "五"},
    "PB3": {"四", "五", "六"},
}

# 拓展任务生成模板（按 primary_topic 给一句可执行的活动名）
_ACTIVITY_TEMPLATES = {
    "animal":        "用绘本里的动物角色复述故事（Retell with characters）",
    "family.pets":   "对比绘本的宠物与教材里的家庭角色，写一段描述",
    "nature.cosmic": "围绕自然现象写一段 Why/How 说明文",
    "food":          "用绘本出现的食材造句，扩展教材里的食物词汇",
    "identity":      "介绍自己 vs. 教材里的自我介绍句型，做角色对比",
    "narrative.hero":"续写绘本结局并朗读 3 遍",
    "friendship":    "用绘本情节展开教材 Friendship 单元的角色扮演",
    "job":           "调查家庭职业，套用教材里的 What's your... job 句型",
    "money":         "在教材职业/家庭语境中引入价格与交易扩展句",
    "poverty":       "讨论资源公平，写一段 4-5 句的观点表达",
    "animal.fable":  "总结寓言寓意，套用教材观点表达句型",
}


def grade_fit(pb_level: str, grade: str) -> bool:
    if not grade:
        return True
    fit = PB_GRADE_FIT.get(pb_level, set())
    return any(g in grade for g in fit)


def score_pairing(book: dict, unit: dict, passages: list[dict], topics_data: dict) -> dict | None:
    text_tokens_unit = unique_tokens(unit["text_head"])
    unit_passage_words = set()
    unit_passage_topics = []
    unit_passage_keywords = set()
    for p in passages:
        for w in (p.get("words") or []):
            unit_passage_words.add(w.lower())
            unit_passage_keywords.update(_WORD_RE.findall(w.lower()))
        unit_passage_topics.append(p.get("topic") or "")
    unit_passage_keywords -= _STOP

    # 1) topic 关键词命中
    topic_hits_detail = []
    for topic_id in [book.get("primary_topic"), *(book.get("secondary_topics") or [])]:
        if not topic_id:
            continue
        node = next((t for t in topics_data["topics"] if t["id"] == topic_id), None)
        if not node:
            continue
        hits = keyword_hits(text_tokens_unit, node.get("keywords_en", []))
        if hits:
            topic_hits_detail.append((topic_id, node["label"], hits))

    if not topic_hits_detail:
        return None  # 硬性门禁：至少一个话题命中

    score = sum(_W_TOPIC * h for _, _, h in topic_hits_detail)

    # 2) covers_words 命中（在单元正文 + 短文 words 里）
    covers = book.get("covers_words") or []
    cover_hit_list = [w for w in covers
                      if w.lower() in text_tokens_unit or w.lower() in unit_passage_keywords]
    score += _W_COVER * len(cover_hit_list)

    # 3) 语法点：新指纹体系——按 book.supports_grammar 与 unit_grammar.top_ids 求 overlap
    #    同时兼容老 supports_grammar（grammar.tense 等），转成等价的新 id 集合
    book_grammar_ids = set(book.get("supports_grammar") or [])
    # 老→新 id 展开
    _LEGACY = {
        "grammar.tense":      {"tense.present_simple", "tense.present_progressive",
                               "tense.past_simple", "tense.future_going_to", "be.was_were"},
        "grammar.there_be":   {"there.be"},
        "grammar.modal":      {"modal.can_could"},
        "grammar.be_verb":    {"be.am_is_are", "be.was_were", "be.contraction"},
        "grammar.pronouns":   {"pron.possessive", "pron.possessive_noun"},
        "grammar.plurals":    {"noun.plural_s"},
        "grammar.comparatives": {"comparative"},
        "grammar.questions":  {"question.wh_words", "question.be_verb_invert",
                               "question.do_verb_invert"},
        "grammar.negation":   {"negation"},
        "grammar.prepositions": {"prep.common"},
        "grammar.articles":   {"article.a_an", "article.the"},
        "grammar.conjunctions": {"conj.and_or_but"},
        "grammar.exclamations": {"exclamation"},
        "grammar.imperative": {"imperative"},
    }
    for legacy, ids in _LEGACY.items():
        if legacy in book_grammar_ids:
            book_grammar_ids |= ids
    # 拿 unit_grammar（从 unit_grammar.json 加载，如果没加载用 unit 内嵌 top_ids）
    u_top = set(unit.get("grammar_top_ids") or [])
    # 去掉普适 grammar（article/conj/prep）
    _STOP_GIDS = {"article.the", "conj.and_or_but", "article.a_an", "prep.common"}
    book_grammar_ids -= _STOP_GIDS
    u_top -= _STOP_GIDS
    if u_top and book_grammar_ids:
        overlap = book_grammar_ids & u_top
        if overlap:
            grammar_hits = sorted(overlap)[:5]
            score += _W_SKILL * len(overlap)
        else:
            grammar_hits = []
    else:
        grammar_hits = []

    # 4) 年级不匹配轻扣
    if not grade_fit(book.get("level", ""), unit.get("grade") or ""):
        score -= _GRADE_PENALTY

    # 生成拓展任务
    ext = _ACTIVITY_TEMPLATES.get(book.get("primary_topic", ""), None)

    reason_parts = []
    if topic_hits_detail:
        top_topic = max(topic_hits_detail, key=lambda x: x[2])
        reason_parts.append(f"话题命中:{top_topic[1]}({top_topic[2]})")
    if cover_hit_list:
        reason_parts.append(f"覆盖词:{','.join(cover_hit_list[:4])}")
    if grammar_hits:
        reason_parts.append(f"语法:{'/'.join(grammar_hits)}")

    return {
        "book_id": book["id"],
        "section_id": unit["section_id"],
        "section_book_id": unit["book_id"],
        "subject": "英语",
        "grade": unit.get("grade"),
        "term": unit.get("term"),
        "unit_no": unit.get("unit_no"),
        "unit_name": unit.get("unit_name"),
        "title": unit.get("title"),
        "match_score": max(score, 1),
        "matched_by": "topic+cover+grammar",
        "reason": "；".join(reason_parts),
        "extended_activity": ext,
    }


def main():
    books = json.loads(BOOKS_PATH.read_text(encoding="utf-8"))["books"]
    topics_data = json.loads(TOPICS_PATH.read_text(encoding="utf-8"))
    units = get_units()

    # 加载 unit_grammar：把 top_ids 挂到 unit 上，供 score_pairing 使用
    unit_grammar: dict[str, dict] = {}
    if UNIT_GRAMMAR_PATH.exists():
        ug = json.loads(UNIT_GRAMMAR_PATH.read_text(encoding="utf-8"))
        for uid, entry in ug.items():
            unit_grammar[uid] = entry
        for u in units:
            e = unit_grammar.get(u["section_id"])
            if e:
                u["grammar_top_ids"] = e.get("top_ids") or []

    # 建立 section → passages 索引
    passages_all = load_jsonl(PASSAGES_PATH)
    sec_to_passages: dict[str, list[dict]] = {}
    for p in passages_all:
        sid = p.get("section_id")
        if sid:
            sec_to_passages.setdefault(sid, []).append(p)

    pairings = []
    # 只为 pages 非空的绘本挂（避免占位符）
    for book in books:
        if not book.get("pages"):
            continue
        scored = []
        for unit in units:
            p = score_pairing(book, unit, sec_to_passages.get(unit["section_id"], []), topics_data)
            if p:
                scored.append(p)
        # 每本书最多保留 top-3 挂载
        scored.sort(key=lambda x: -x["match_score"])
        pairings.extend(scored[:3])

    # 全库排序
    pairings.sort(key=lambda x: -x["match_score"])

    out = {
        "_doc": "绘本↔教材单元挂载表。每条 Pairing 表示一本书挂到某个英语课本单元，并给出 match_score / reason / 拓展任务名。",
        "_updated": "2026-10-13",
        "_threshold": {"min_topic_hits": 1, "min_score": 30},
        "pairings": pairings,
    }
    PAIRINGS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # 回写 books.json 的 pairs_with_unit 和 extends_activity
    by_book: dict[str, list[dict]] = {}
    for p in pairings:
        by_book.setdefault(p["book_id"], []).append({
            "section_id": p["section_id"],
            "unit_name": p["unit_name"],
            "title": p["title"],
            "grade": p["grade"],
            "term": p["term"],
            "match_score": p["match_score"],
        })

    # 需要读整个 store 才保留顶层字段
    store = json.loads(BOOKS_PATH.read_text(encoding="utf-8"))
    for book in store["books"]:
        ps = by_book.get(book["id"], [])
        if ps:
            book["pairs_with_unit"] = [x["section_id"] for x in ps]
            acts = set()
            for p in pairings:
                if p["book_id"] == book["id"] and p.get("extended_activity"):
                    acts.add(p["extended_activity"])
            book["extends_activity"] = sorted(acts)
    BOOKS_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

    # 输出简报
    print(f"[pair_units] units={len(units)}  books_with_pages={sum(1 for b in books if b.get('pages'))}")
    print(f"[pair_units] pairings 总数 = {len(pairings)}")
    for p in pairings[:12]:
        print(f"  score={p['match_score']:>3}  {p['book_id'][:32]:<32} → "
              f"{p['grade'] or '-'}{p['term'] or ''} {p['unit_name'] or ''} / {p['title']}")
    print(f"[pair_units] 写出 → {PAIRINGS_PATH.name}")


if __name__ == "__main__":
    main()
