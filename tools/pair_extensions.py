"""课外 Reading × 教材 Unit 挂载脚本（PairingV2）
对齐 data/readings/extension_roles.json 里定义的 7 种角色和打分公式。

输入：
  - data/readings/catalog.json           长文/短文/小说清单（含 facets）
  - data/readings/extension_roles.json   角色定义 + 打分公式
  - data/attrs/section_text.jsonl        教材单元权威源（subject=英语）
  - data/attrs/en_passage.jsonl          教材短文，提供 topic/words
输出：
  - data/readings/pairings.json          PairingV2 实例表
  - data/readings/catalog.json           回写 books[].pairs_with_unit + facets.text_role
"""
from __future__ import annotations
import json, re, math
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "data" / "readings"
ATTRS = ROOT / "data" / "attrs"

CATALOG_PATH = R / "catalog.json"
ROLES_PATH = R / "extension_roles.json"
SECTIONS_PATH = ATTRS / "section_text.jsonl"
PASSAGES_PATH = ATTRS / "en_passage.jsonl"
UNIT_GRAMMAR_PATH = ATTRS / "unit_grammar.json"
PAIRINGS_PATH = R / "pairings.json"


# ---------- 加载 ----------
def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def get_units() -> list[dict]:
    """教材英语单元，排除附录/复习/词汇表"""
    noise_kw = ("appendix", "词汇", "单词", "vocabulary", "words in",
                "复习", "revision", "recycle", "review")
    out = []
    for sec in load_jsonl(SECTIONS_PATH):
        if sec.get("subject") != "英语":
            continue
        unit_name = (sec.get("unit_name") or "")
        title = (sec.get("title") or "")
        if not unit_name.startswith("Unit"):
            continue
        blob = f"{unit_name} {title}".lower()
        if any(k.lower() in blob for k in noise_kw):
            continue
        out.append({
            "section_id": sec["section_id"],
            "book_id": sec["book_id"],
            "grade": sec.get("grade") or "",
            "term": sec.get("term") or "",
            "unit_no": sec.get("unit_no"),
            "unit_name": unit_name,
            "unit_title": title,
            "text": (sec.get("text") or "")[:5000],
        })
    return out


# ---------- 归一化 ----------
_STOP = set("""
a an the and or but of in on at to for with from by is are was were be been being
have has had do does did can could will would should may might must i you he she it
we they me him her us them my your his its our their this that these those what
which who whom whose where when how not no yes so if as than then here there only
also very much some any all other more most too one two get got go goes going been
""".split())
_WORD_RE = re.compile(r"[A-Za-z']+")


def tokens(text: str) -> set[str]:
    t = text.lower()
    t = re.sub(r"\b(\w+)'s\b", r"\1 ", t)
    return {w.strip("'") for w in _WORD_RE.findall(t)
            if w.strip("'") not in _STOP and len(w.strip("'")) > 2}


# 把教材 unit title 拆成关键词种子（用于主题匹配）
def unit_topic_seeds(unit: dict) -> set[str]:
    return tokens(f"{unit['unit_title']} {unit['text']}")


# ---------- 主题映射：extracurricular.primary_topic → 教材可能出现的英语关键词 ----------
_TOPIC_KEYWORDS = {
    # 动物/寓言
    "animal":          {"cat", "dog", "bird", "animal", "lion", "mouse", "rabbit",
                       "duck", "fox", "cow", "pig", "sheep", "elephant", "tiger"},
    "fable":           {"fable", "morality", "morale", "lesson", "wisdom", "aesop"},
    "nature":          {"nature", "tree", "forest", "river", "mountain", "ocean", "garden",
                       "flower", "plant", "seed", "season", "weather", "cloud", "rain"},
    "food":            {"food", "meal", "eat", "cook", "chocolate", "breakfast", "lunch", "dinner"},
    "science":         {"science", "experiment", "insect", "bug", "star", "planet", "space"},
    "space":           {"space", "planet", "star", "moon", "rocket", "galaxy"},
    "human_body":      {"body", "heart", "brain", "eye", "hand", "tooth", "finger", "ear"},
    "history":         {"history", "war", "king", "princess", "village", "castle", "ancient"},
    "cultural":        {"culture", "festival", "hawaii", "india", "africa", "chinese", "china"},
    "adventure":       {"adventure", "journey", "travel", "explore", "journey", "safari"},
    "friendship":      {"friend", "friendship", "kind", "kindness", "help", "care"},
    "family":          {"family", "father", "mother", "dad", "mum", "mom", "brother",
                       "sister", "grandpa", "grandma", "baby", "home"},
    "job":             {"job", "doctor", "teacher", "nurse", "worker", "farmer", "cook",
                       "officer", "office", "factory"},
    "community":       {"community", "neighbour", "neighbor", "town", "city", "village"},
    "technology":      {"computer", "robot", "machine", "digital", "phone"},
    "emotion":         {"happy", "sad", "angry", "fear", "afraid", "joy", "worried"},
    "social_justice":  {"fair", "equal", "justice", "oppression", "freedom"},
    "humor":           {"funny", "joke", "laugh", "playful"},
    "wisdom":          {"wisdom", "kindness", "generosity", "brave", "hero"},
    "identity":        {"self", "me", "name", "who am i", "personality"},
    "narrative.hero":  {"hero", "king", "queen", "princess", "dragon", "wizard", "knight"},
    "animal.fable":    {"lion", "mouse", "rabbit", "duck", "fox", "crow", "tortoise",
                       "hare", "frog", "wolf", "fox", "crow"},
    "family.pets":     {"pet", "dog", "cat", "bird", "fish", "goldfish", "rabbit", "hamster"},
    "nature.cosmic":   {"universe", "space", "galaxy", "star", "moon", "planet", "rocket", "mars"},
    "poverty":         {"poor", "poverty", "rich", "money", "wealth"},
    "monsters":        {"monster", "ghost", "vampire", "werewolf", "zombie", "villain"},
    "superheroes":     {"superhero", "hero", "power", "costume"},
    "pirates":         {"pirate", "ship", "sea", "treasure", "island", "ocean"},
    "diseases":        {"disease", "illness", "doctor", "nurse", "health"},
}


def topic_overlap(extracurricular_topics: list[str], unit_tokens: set[str]) -> tuple[float, list[str]]:
    """计算课外所有主题（primary + secondary）与教材单元 tokens 的重合比例"""
    all_tokens = set()
    hit = set()
    for t in extracurricular_topics:
        base = t.split(".", 1)[0]
        topic_kws = _TOPIC_KEYWORDS.get(t, set()) | _TOPIC_KEYWORDS.get(base, set())
        all_tokens |= topic_kws
        hit |= (topic_kws & unit_tokens)
    if not all_tokens:
        return 0.0, []
    # 分母固定 12：至少命中 3 个词才可能达到 0.25（门槛）
    denom = max(12, len(all_tokens))
    return min(len(hit) / denom, 1.0), sorted(hit)[:8]


# ---------- 技能映射 ----------
# 从教材的 section_text 里能提取的粗略信号：
#   - "Let's talk" 出现多 → speaking
#   - "Read and write" → reading_comprehension + writing
#   - "Let's spell" → phonics
#   - "Listen and ..." → listening
#   - "Self-check" 中 "I can read and spell" 等
_SKILL_KEYWORDS = {
    "reading_comprehension": ["read", "reading", "reading time"],
    "vocabulary_extension":  ["words", "vocabulary", "spell", "learn"],
    "storytelling":          ["story", "retell", "once upon"],
    "critical_thinking":     ["why", "think", "reason", "decide"],
    "writing":               ["write", "writing", "compose", "essay"],
    "discussion":            ["talk", "discuss", "conversation", "say"],
    "retelling":             ["retell", "story", "tell the story"],
    "roleplay":              ["roleplay", "act", "perform"],
    "listening":             ["listen"],
    "character_analysis":    ["character", "who is"],
    "plot_prediction":       ["next", "guess", "predict", "what happens"],
    "cultural_awareness":    ["culture", "festival", "chinese", "traditional"],
    "inference":             ["why", "reason", "guess", "predict"],
}


def skill_overlap(unit_text: str, extra_skills: list[str]) -> tuple[float, list[str]]:
    low = unit_text.lower()
    hits = []
    for sk in extra_skills:
        for kw in _SKILL_KEYWORDS.get(sk, [sk]):
            if kw in low:
                hits.append(sk)
                break
    if not hits:
        return 0.0, []
    return min(len(set(hits)) / max(1, len(extra_skills)) * 1.2, 1.0), sorted(set(hits))


# ---------- 词表覆盖 ----------
def word_coverage(unit_tokens: set[str], extra_words: list[str]) -> float:
    if not extra_words:
        return 0.0
    hit = [w for w in extra_words if w.lower().strip("'") in unit_tokens]
    return min(len(hit) / min(6, len(extra_words)), 1.0)


# ---------- 语法点 overlap ----------
# 按 role 分配不同权重：consolidation/writing_trigger 最看重语法重合；
# extension 稍看；pre_reading 几乎不看
_ROLE_GRAMMAR_EMPHASIS: dict[str, float] = {
    "pre_reading":      0.3,
    "bridge_text":      0.7,
    "consolidation":    1.0,
    "extension":        0.6,
    "compare_contrast": 0.4,
    "writing_trigger":  1.0,
    "culture_window":   0.3,
}

_STOP_GIDS = {"article.the", "conj.and_or_but", "article.a_an", "prep.common"}


def _jaccard_no_stop(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    sa -= _STOP_GIDS
    sb -= _STOP_GIDS
    if not sa and not sb:
        return 0.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def grammar_overlap(fp_unit: dict | None, fp_book: dict | None,
                    role: str, emphasis: float | None = None) -> float:
    """语法点重合度：Jaccard(top_ids 去掉普适语法) × role 权重。

    fp_unit: data/attrs/unit_grammar.json 中某个单元的条目（可能没有 top_ids）
    fp_book: book.facets.grammar_fingerprint 或 None
    """
    if not fp_unit or not fp_book:
        return 0.0
    ids_u = fp_unit.get("top_ids") or [g["id"] for g in fp_unit.get("grammar_points", [])]
    ids_b = fp_book.get("top_ids") or [g["id"] for g in fp_book.get("grammar_points", [])]
    if emphasis is None:
        emphasis = _ROLE_GRAMMAR_EMPHASIS.get(role, 0.6)
    return _jaccard_no_stop(ids_u, ids_b) * emphasis


# ---------- 写作特征 match ----------
# 每个 writing feature 的"接近度"权重
_WF_WEIGHTS: dict[str, float] = {
    "dialogue_heavy":      1.2,   # 对话式最强
    "short_sentence":      1.0,
    "list_like":           1.0,
    "rhyme":               0.8,
    "q_ratio":             0.6,
    "exclamation_ratio":   0.5,
    "sentence_variety":    0.5,
}


def writing_feature_match(wfs_unit: list[dict] | None,
                          wfs_book: list[dict] | None) -> float:
    """按 |v_unit - v_book| 计算"越接近越好"，0.3 以内 = 1.0。"""
    if not wfs_unit or not wfs_book:
        return 0.0
    u_map = {w["id"]: w["value"] for w in wfs_unit}
    b_map = {w["id"]: w["value"] for w in wfs_book}
    scores: list[float] = []
    for wid, w in _WF_WEIGHTS.items():
        if wid in u_map and wid in b_map:
            du = abs(u_map[wid] - b_map[wid])
            base = max(0.0, 1.0 - du / 0.3)
            scores.append(base * w)
    if not scores:
        return 0.0
    return min(sum(scores) / len(scores), 1.0)


# ---------- 加载教材 grammar 索引 ----------
def load_unit_grammar() -> dict[str, dict]:
    """data/attrs/unit_grammar.json：unit_key → entry（含 top_ids / writing_features）"""
    if not UNIT_GRAMMAR_PATH.exists():
        return {}
    return load_json(UNIT_GRAMMAR_PATH)


# ---------- Lexile 匹配（按 role） ----------
def lexile_score(lexile: dict | None, unit_grade: str, role: str) -> float:
    if not lexile:
        return 0.0
    target = {
        "pre_reading":       (-200, -50),
        "bridge_text":       (-100, 100),
        "consolidation":     (-100, 100),
        "extension":         (80, 300),
        "compare_contrast":  (-150, 200),
        "writing_trigger":   (-100, 150),
        "culture_window":    (-100, 200),
    }[role]
    # 估算教材 lexile 基线
    grade_lexile = {"一年级": 250, "二年级": 350, "三年级": 450, "四年级": 550,
                    "五年级": 700, "六年级": 850}
    base = 550  # 默认四年级
    for g, v in grade_lexile.items():
        if g in unit_grade:
            base = v
            break
    mean = lexile.get("mean") or (lexile.get("min", 400) + lexile.get("max", 400)) / 2
    delta = mean - base
    lo, hi = target
    if lo <= delta <= hi:
        return 1.0
    # 线性衰减
    dist = lo - delta if delta < lo else delta - hi
    return max(0.0, 1.0 - dist / 300)


# ---------- Role bonus ----------
def role_bonus(reading: dict, role: str, unit_grade: str) -> float:
    f = reading.get("facets", {})
    rules = {
        "pre_reading":        {"text_types": {"fable", "folktale", "fantasy"},
                               "buckets": {"very_short", "short"}},
        "bridge_text":        {"text_types": {"fable", "folktale", "realistic_fiction"},
                               "buckets": {"short", "medium"}},
        "consolidation":      {"text_types": None,  # None = 无偏好，给基础分
                               "buckets": {"short", "medium"}},
        "extension":          {"text_types": {"fantasy", "adventure", "realistic_fiction",
                                              "detective", "historical_fiction", "novel"},
                               "buckets": {"medium", "long"}},
        "compare_contrast":   {"text_types": {"realistic_fiction", "folktale", "satire"},
                               "buckets": {"short", "medium", "long"}},
        "writing_trigger":    {"text_types": {"fable", "folktale", "essay", "fantasy"},
                               "buckets": {"short", "medium"}},
        "culture_window":     {"text_types": {"folktale", "mythological", "satire"},
                               "buckets": {"short", "medium"}},
    }[role]
    score = 0.0
    if rules["text_types"] is None:
        score += 0.4  # 无偏好给中性基础分
    elif f.get("text_type") in rules["text_types"]:
        score += 0.6  # text_type 强匹配
    # bucket 加分
    if rules["buckets"] and f.get("word_count_bucket") in rules["buckets"]:
        score += 0.3
    # grade 交集加分
    grades = set(f.get("grade") or [])
    if unit_grade and any(g in unit_grade for g in grades):
        score += 0.2
    return min(score, 1.0)


# ---------- 教材文本 → 教材侧主题/技能（用于跨库比较） ----------
def unit_signals(unit: dict) -> dict:
    toks = tokens(unit["text"])
    # 教材主题：命中 _TOPIC_KEYWORDS 反向
    unit_topics_hit = []
    for topic_id, kws in _TOPIC_KEYWORDS.items():
        if toks & kws:
            unit_topics_hit.append(topic_id)
    return {"tokens": toks, "topics_hit": unit_topics_hit}


# ---------- 打分主体 ----------
def score_pair(reading: dict, unit: dict, role: str,
               unit_grammar: dict[str, dict] | None = None) -> dict | None:
    f = reading.get("facets", {})
    ext_topics = [reading.get("primary_topic")] + list(reading.get("secondary_topics") or [])
    ext_topics = [t for t in ext_topics if t]

    unit_toks = tokens(f"{unit['unit_title']} {unit['text']}")

    topic_score, topic_hit = topic_overlap(ext_topics, unit_toks)
    # 硬门禁：主题命中不足直接丢弃（topic_score=0.25 ≈ 3 个主题关键词）
    if topic_score < 0.25:
        return None

    skill_score, skill_hit = skill_overlap(unit["text"], f.get("target_skills") or [])

    covers = f.get("covers_words") or []
    w_score = word_coverage(unit_toks, covers) if covers else 0.0

    lexile = f.get("lexile")
    l_score = lexile_score(lexile, unit.get("grade") or "", role)
    rb = role_bonus(reading, role, unit.get("grade") or "")
    # role_bonus 硬门禁：至少 0.2（text_type 或 grade 或 bucket 三选一符合）
    if rb < 0.2:
        return None

    # 新增：语法点 overlap + 写作特征 match
    u_grammar = (unit_grammar or {}).get(unit["section_id"])
    b_fp = f.get("grammar_fingerprint")
    g_score = grammar_overlap(u_grammar, b_fp, role) if u_grammar else 0.0
    wf_score = writing_feature_match(
        (u_grammar or {}).get("writing_features"),
        (b_fp or {}).get("writing_features") if b_fp else None,
    )

    total = (0.28 * topic_score + 0.20 * skill_score + 0.10 * w_score
             + 0.10 * l_score + 0.05 * rb
             + 0.20 * g_score + 0.07 * wf_score)

    reasons = []
    if topic_hit:
        reasons.append(f"topic:{'/'.join(topic_hit[:2])}")
    if skill_hit:
        reasons.append(f"skill:{'/'.join(skill_hit[:2])}")
    if covers and w_score > 0:
        reasons.append(f"covers_words hit={w_score:.2f}")
    if l_score >= 0.9:
        reasons.append(f"lexile 落在 {role} 目标区间")
    elif l_score >= 0.5:
        reasons.append(f"lexile 边界")
    if rb >= 0.5:
        reasons.append(f"role_bonus={rb:.2f}")
    if g_score >= 0.25:
        reasons.append(f"grammar_overlap={g_score:.2f}")
    elif g_score >= 0.1:
        reasons.append(f"grammar 部分重合")
    if wf_score >= 0.5:
        reasons.append(f"writing_feature 接近={wf_score:.2f}")

    return {
        "reading_id": reading["id"],
        "reading_title": reading["title"],
        "section_id": unit["section_id"],
        "unit_name": unit["unit_name"],
        "unit_title": unit["unit_title"],
        "grade": unit["grade"],
        "term": unit["term"],
        "role": role,
        "match_score": round(total, 3),
        "match_breakdown": {
            "topic": round(topic_score, 3),
            "skill": round(skill_score, 3),
            "word":  round(w_score, 3),
            "lexile": round(l_score, 3),
            "role_bonus": round(rb, 3),
            "grammar": round(g_score, 3),
            "writing_feature": round(wf_score, 3),
        },
        "match_reasons": reasons,
        "source": "auto",
        "created_at": date.today().isoformat(),
    }


# ---------- 主流程 ----------
def main():
    catalog = load_json(CATALOG_PATH)
    roles_def = load_json(ROLES_PATH)
    units = get_units()
    books = catalog["books"]
    unit_grammar = load_unit_grammar()

    # 阈值
    min_score = roles_def["score_formula"]["thresholds"]["min_pair"]

    # 每 (reading, unit) 上跑所有 role，取 best role；同 unit 上多 role 分数都 >=min 时保留并列
    per_pair: dict[tuple[str, str], list[dict]] = {}
    for b in books:
        for u in units:
            for role in roles_def["roles"].keys():
                p = score_pair(b, u, role, unit_grammar=unit_grammar)
                if p is None or p["match_score"] < min_score:
                    continue
                per_pair.setdefault((b["id"], u["section_id"]), []).append(p)

    # 汇总
    pairings = []
    role_per_reading: dict[str, set[str]] = {}
    pairs_per_reading: dict[str, list[str]] = {}
    for (rid, sid), ps in per_pair.items():
        ps.sort(key=lambda x: -x["match_score"])
        best = ps[0]["match_score"]
        # 只保留最高 role；分差 >=0.10 才允许并列（避免同对多角色噪声）
        keep = [p for p in ps if best - p["match_score"] < 0.10]
        for p in keep:
            # 生成 id：包含 role 保证唯一
            p["id"] = f"{p['reading_id']}@{p['section_id']}#{p['role']}"
            pairings.append(p)
            role_per_reading.setdefault(rid, set()).add(p["role"])
            pairs_per_reading.setdefault(rid, []).append(p["section_id"])
    pairings.sort(key=lambda x: -x["match_score"])

    # 写 pairings.json
    out = {
        "_doc": "PairingV2：课外 Reading × 教材 Unit 挂载表。每条含 role / match_score / breakdown / reasons。",
        "_updated": date.today().isoformat(),
        "_formula_ref": "data/readings/extension_roles.json",
        "_threshold": {"min_pair": min_score, "keep_within_delta": 0.05},
        "_counts": {
            "units": len(units),
            "readings": len(books),
            "pairings": len(pairings),
            "by_role": {r: sum(1 for p in pairings if p["role"] == r)
                        for r in roles_def["roles"].keys()},
        },
        "pairings": pairings,
    }
    PAIRINGS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # 回写 catalog：每本 reading 的 facets.text_role 与顶层 pairs_with_unit
    for b in books:
        rid = b["id"]
        if rid in role_per_reading:
            b.setdefault("facets", {})["text_role"] = sorted(role_per_reading[rid])
        if rid in pairs_per_reading:
            b["pairs_with_unit"] = pairs_per_reading[rid]

    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    # 简报
    print(f"[pair_extensions] units={len(units)}  readings={len(books)}  pairings={len(pairings)}")
    print(f"[pair_extensions] by_role = {out['_counts']['by_role']}")
    print("--- top 12 pairings ---")
    for p in pairings[:12]:
        print(f"  score={p['match_score']:.2f}  [{p['role']:<16}] "
              f"{p['reading_id'][:28]:<28} → "
              f"{p['grade'] or '-'}{p['term'] or ''} {p['unit_name'] or ''}/{p['unit_title']}")
    print(f"[pair_extensions] 写出 → {PAIRINGS_PATH}")


if __name__ == "__main__":
    main()
