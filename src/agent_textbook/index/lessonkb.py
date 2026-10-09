# -*- coding: utf-8 -*-
"""每课本体论：一堂语文课要掌握什么。

两条铁律：

一、**教材里已经写着的，一律不重抽**——
  分段段意与中心思想来自 lesson_structure，课后题原文来自 lesson_text.tasks，
  会认/会写字来自 words（教材字表），按"字确实出现在这篇课文里"归到本课。
  LLM 只补教材写不下、上课却真要用的东西。

二、**不超纲**。课标把小学分成三个学段（1-2 / 3-4 / 5-6），各学段该抓什么
  是写死的：比如"初步领悟文章的基本表达方法"是第三学段（5-6 年级）的事，
  拿去要求三年级就是拔高。故本体按学段启用字段（STAGE_FIELDS），
  每个字段都挂一条课标锚点（STANDARD），页面上能看见"这条依据哪一条"。

补的每一条还要过校验才入库：句子不在正文里、写法是自己造的词、课后题不是
教材原题——一律丢掉。宁可少一条，不要错一条：这是给孩子看的，编出来的比空着糟。
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import config
from . import llm

KB_FILE = os.path.join(config.ATTRS_DIR, "lesson_kb.jsonl")
TEXT_FILE = os.path.join(config.ATTRS_DIR, "lesson_text.jsonl")
STRUCT_FILE = os.path.join(config.ATTRS_DIR, "lesson_structure.jsonl")
WORDS_FILE = os.path.join(config.ATTRS_DIR, "words.jsonl")
ELEM_FILE = os.path.join(config.ATTRS_DIR, "unit_element.jsonl")
GENRE_FILE = os.path.join(config.ATTRS_DIR, "lesson_genre.jsonl")
META_FILE = os.path.join(config.ATTRS_DIR, "lesson_meta.jsonl")

# ============================================================ 课标锚点
# 依据《义务教育语文课程标准（2022 年版）》学段要求（1-2 / 3-4 / 5-6 三个学段）

G_STAGE = {"一": "1-2", "二": "1-2", "三": "3-4",
           "四": "3-4", "五": "5-6", "六": "5-6"}

# 各学段抓哪些字段：超纲的一律不抓
STAGE_FIELDS = {
    "1-2": ["chars", "read", "words", "idea", "notes", "background", "center",
            "exam", "traps", "accumulate", "transfer", "extend"],
    "3-4": ["chars", "read", "recite", "words", "parts", "idea",
            "sentences", "questions", "notes", "background", "center", "exam",
            "traps", "accumulate", "transfer", "extend"],
    "5-6": ["chars", "read", "recite", "words", "parts", "idea",
            "sentences", "methods", "questions", "polyphone", "notes",
            "background", "center", "exam", "traps", "accumulate", "transfer",
            "extend"],
}

STANDARD = {
    "chars": "【识字与写字】主动识字、有独立识字能力；书写规范、端正、整洁",
    "read": "【阅读】用普通话正确、流利、有感情地朗读课文",
    "recite": "【阅读】诵读优秀诗文，体验情感、展开想象，领悟诗文大意",
    "words": "【阅读】联系上下文和生活积累，理解词句的意思",
    "parts": "【阅读】初步把握文章的内容，复述叙事性作品的大意",
    "idea": "【阅读】体会文章表达的思想感情",
    "sentences": "【阅读·第二学段起】体会课文中关键词句表达情意的作用",
    "methods": "【阅读·第三学段】了解表达顺序，初步领悟基本的表达方法"
               "（课标要求随文学习，不做系统讲授与死记硬背）",
    "polyphone": "【识字与写字】读准字音，分辨多音字在不同语境中的读法",
    "notes": "【阅读】感受作品中生动的形象和优美的语言（第二学段）；"
             "简单描述印象最深的场景、人物、细节（第三学段）",
    "questions": "【阅读】对课文中不理解的地方提出疑问；敢于提出看法、作出判断",
    "background": "【阅读】借助作者、出处与背景资料理解课文"
                  "（第三学段：能借助相关资料理解含义深刻的句子）",
    "center": "【阅读】体会文章表达的思想感情；说出对人物与事件的感受",
    "exam": "【学业质量】识字写字、阅读与表达的学段学业质量要求",
    "traps": "【识字与写字】读准字音、认清字形；"
             "第三学段：辨别词语的感情色彩、体会标点用法",
    "accumulate": "【阅读】积累课文中的优美词语、精彩句段（第二学段起）",
    "extend": "【拓展】课外阅读与跨学科学习（课标：整本书阅读、跨学科学习）",
    "transfer": "【表达】%s",
}

# 各学段的"表达"要求：一年级写话，三四年级写清楚，五六年级分段表述
EXP = {
    "1-2": "【写话】写自己想说的话，写想象中的事物",
    "3-4": "【习作】不拘形式写下见闻与感受，把印象最深的内容写清楚",
    "5-6": "【习作】内容具体、感情真实，分段表述；学写读书笔记与常见应用文",
}

# 修辞与写法术语白名单：模型爱生造（"多感官描写""情景交融式结构"），
# 只认教材里讲过的；且只有第三学段才启用（低年级只认最基础的修辞）
RHETORIC = ("比喻", "拟人", "排比", "夸张", "设问", "反问")

# 段内标签：描写 / 观察角度 / 说明方法 / 诗文
DEPICT = ("外貌描写", "语言描写", "动作描写", "神态描写", "心理描写",
          "环境描写", "场面描写", "细节描写", "侧面描写")
ANGLE = ("多感官", "由远及近", "由近及远", "动静结合", "点面结合",
         "时间顺序", "事情发展顺序", "游览顺序", "总分总", "首尾呼应")
EXPLAIN = ("列数字", "作比较", "举例子", "打比方", "分类别", "下定义")
POEM = ("意象", "炼字", "典故", "对仗", "押韵")
OTHER = ("对比", "衬托", "反复", "对偶", "引用", "想象", "联想",
         "借景抒情", "借物抒情", "连续观察")
METHODS = RHETORIC + DEPICT + ANGLE + EXPLAIN + POEM + OTHER

# 各学段允许出现的段内标签（守住课标：低年级不谈写法术语）
TAGS = {
    "1-2": (),
    "3-4": RHETORIC[:4] + ("动作描写", "语言描写", "神态描写", "心理描写",
                           "外貌描写", "环境描写", "细节描写", "多感官",
                           "对比", "想象"),
    "5-6": METHODS,
}

# 段内批注的大类：低年级不谈"写法"
NOTE_KINDS = ("段意", "字词", "朗读", "提问", "写法", "积累", "背诵")
NOTE_STAGE = {"1-2": ("段意", "字词", "朗读", "提问", "积累"),
              "3-4": NOTE_KINDS, "5-6": NOTE_KINDS}

# 考点白名单：模型最爱编"常考xxx"，只认这些，且按学段开
EXAM_POINTS = {
    "1-2": ("识字写字", "字音", "笔顺", "朗读背诵", "词语理解", "看图说话"),
    "3-4": ("识字写字", "多音字", "词语理解", "近反义词", "句子理解",
            "段落大意", "中心思想", "背诵默写", "人物品质", "修改病句",
            "想象画面", "写作顺序", "仿写句子"),
    "5-6": ("识字写字", "多音字", "词语理解", "感情色彩", "句子理解",
            "段落大意", "中心思想", "背诵默写", "人物品质", "修辞手法",
            "说明方法", "表达顺序", "句段作用", "标点用法", "开放问答",
            "小练笔"),
}

# 易错点白名单：形近同音三四年级起，感情色彩与标点五六年级才谈
TRAP_TYPES = {
    "1-2": ("字音", "字形", "笔顺"),
    "3-4": ("字音", "字形", "笔顺", "多音字", "形近字", "同音字",
            "词语搭配", "量词"),
    "5-6": ("字音", "字形", "笔顺", "多音字", "形近字", "同音字",
            "词语搭配", "量词", "感情色彩", "标点", "修辞误用"),
}

PROMPT = (
    "你是小学语文教研员。下面是教材里的一篇课文，请按“一堂课要掌握什么”\n"
    "整理结构化笔记，供家长和孩子对着课文看。\n\n"
    "【课文】《{title}》（{book}，第{unit}单元）\n"
    "【学段】{stage} 年级（这是课标学段，要求不能拔高也不能降低）\n"
    "【正文】\n{text}\n"
    "【教材已有的分段段意】\n{parts}\n"
    "【教材里的课后题】\n{tasks}\n"
    "【作者与出处（教材已给，不要重复生成，也不要改）】{author}\n"
    "【本课生字（教材字表）】{chars}\n\n"
    "{tasks_doc}\n"
    "严格要求：\n"
    "- 不要用引号（书名用《》），引号会破坏 JSON；不要写任何解释；\n"
    "- **不许编**：课后题照抄教材原文，背诵要求只从课后题里摘，课后题没写就留空；\n"
    "- 拿不准的字段留空数组或空串，留白比写错强；\n"
    "- **不做“好词好句摘抄”**：要的是“课文里读不懂就读不通的词”，不是华丽的词；\n"
    "- **不做修辞术语填空、不背答题模板**：低年级连术语都不提，\n"
    "  五六年级谈表达方法也只讲“这样写在课文里起了什么作用”。\n\n"
    "只输出一行 JSON：\n"
    "{{\"read\":{{\"text\":\"\",\"recite\":\"\"}},\"polyphone\":[{{\"zi\":\"\","
    "\"items\":[{{\"py\":\"\",\"ci\":\"\"}}]}}],\"words\":[{{\"w\":\"\","
    "\"mean\":\"\"}}],\"sentences\":[{{\"src\":\"\",\"why\":\"\"}}],"
    "\"methods\":[],\"questions\":[{{\"q\":\"\",\"hint\":\"\"}}],"
    "\"transfer\":\"\",\"notes\":[{{\"para\":0,\"kind\":\"\",\"tags\":[],"
    "\"text\":\"\"}}],\"background\":\"\",\"center\":{{\"idea\":\"\","
    "\"virtue\":\"\"}},\"exam\":[{{\"point\":\"\",\"how\":\"\"}}],"
    "\"traps\":[{{\"type\":\"\",\"text\":\"\"}}],\"accumulate\":[{{\"t\":\"\","
    "\"why\":\"\"}}],\"extend\":{{\"life\":\"\",\"links\":[]}}}}"
)

# 学段 → 给模型的任务清单（字段与要求随学段变，不超纲）
TASKS_DOC = {
    "1-2": (
        "任务（本学段只抓下面 5 项，不要分析写法与表达方法）：\n"
        "1. read：朗读要求，只从课后题原文摘（如“朗读课文”），没写就留空。\n"
        "2. words：读了课文要理解的词，最多 6 个，**必须出现在正文或生字里**，\n"
        "   解释要联系上下文和生活实际、一年级孩子听得懂，不超过 20 字。\n"
        "   注意：要的是“课文里这个词是什么意思”，不是“优美华丽的词”。\n"
        "3. idea：这篇课文说了什么、让人觉得怎样，一句话，不超过 40 字。\n"
        "4. transfer：读了之后可以说/写的一句话（写话），不超过 40 字。\n"
        "5. notes：逐段提示，最多 4 条，para 从 0 开始，\n"
        "   kind 只能是 段意／字词／朗读／提问／积累，tags 留空，text 不超过 30 字。\n"
        "   段内可以点：人物什么心情、读到这想到什么画面、可以问问孩子什么。\n"
        "6. background：与课文有关的常识（作者是谁、故事从哪来、图上是什么），\n"
        "   一两句话，不超过 60 字；没有确切把握就留空，不要编。\n"
        "7. center：virtue 写这篇课文让人明白的道理，一句话不超过 30 字。\n"
        "8. exam：本课考点，最多 3 条。point 只能从下面挑：{exam}\n"
        "   how 写“怎么考、怎么答”，不超过 30 字。\n"
        "9. traps：容易读错写错的字，最多 4 条。type 只能从下面挑：{traps}\n"
        "   text 写清错在哪、正确的是什么，不超过 30 字。\n"
        "10. accumulate：课文里要积累的词或短句，最多 3 条，\n"
        "    t 必须与正文逐字一致，why 写可以怎么用，不超过 20 字。\n"
        "11. extend：life 写读了之后能做的一件小事（观察/做手工/问家人），\n"
        "    不超过 40 字。\n"
    ),
    "3-4": (
        "任务（本学段抓下面 8 项；不要求分析“表达方法”，那是五六年级的事）：\n"
        "1. read：朗读与背诵要求，只从课后题原文摘（如“背诵第3、4自然段”），\n"
        "   课后题没写就返回空。\n"
        "2. words：联系上下文要理解的词，最多 8 个，**必须出现在正文或生字里**，\n"
        "   解释不超过 30 字。不要挑“好词”，要挑“不懂就读不通这句话的词”。\n"
        "3. sentences：读到这里值得停一下的句子，最多 3 句。src 必须与正文\n"
        "   **逐字一致**（含标点）；why 用孩子听得懂的话说：读到这句，眼前出现\n"
        "   什么画面、心里什么感觉——**不要写“比喻”“拟人”这类术语**，不超过 40 字。\n"
        "4. questions：课后题的答题思路。q 必须**照抄上面课后题的原文**，\n"
        "   hint 是“怎么想、从课文哪儿找”，不超过 60 字；没课后题就留空。\n"
        "5. transfer：从课文到生活的表达运用（说一段话／小练笔），不超过 60 字。\n"
        "6. notes：逐段批注，最多 6 条，para 从 0 开始。\n"
        "   kind 只能是 段意／字词／朗读／提问／写法／积累／背诵；\n"
        "   tags 写这一段用了什么描写或修辞，只能从下面挑，最多 2 个：\n"
        "   {tags}\n"
        "   text 不超过 40 字，说清这一段要孩子看什么（可以是一个提问）。\n"
        "7. background：作者、出处、写作背景或与课文有关的历史/科学常识，\n"
        "   不超过 80 字；不确定就留空。\n"
        "8. center：idea 一句话概括中心（教材已给的就照抄教材），\n"
        "   virtue 写人物品质或明白的道理，各不超过 40 字。\n"
        "9. exam：本课考点，最多 4 条。point 只能从下面挑：{exam}\n"
        "   how 写“常怎么考、答题时从课文哪儿找”，不超过 40 字。\n"
        "10. traps：易错点，最多 5 条。type 只能从下面挑：{traps}\n"
        "    text 写清错在哪、正确的是什么，不超过 30 字。\n"
        "11. accumulate：课文里值得积累的词句，最多 3 条，\n"
        "    t 必须与正文逐字一致，why 写可以怎么用，不超过 20 字。\n"
        "12. extend：life 写读了之后能做的事，不超过 40 字；\n"
        "    links 写可以一起读的同类文章或跨学科联系（如“看看地图上的庐山”），\n"
        "    最多 2 条，每条不超过 30 字。\n"
    ),
    "5-6": (
        "任务（本学段抓下面 10 项，可以谈表达顺序与表达方法）：\n"
        "1. read：朗读与背诵要求，只从课后题原文摘；课后题没写就留空。\n"
        "2. polyphone：本课多音字，最多 4 个，每个举一个常见词。\n"
        "3. words：联系上下文和积累要理解的词，最多 8 个，\n"
        "   **必须出现在正文或生字里**，解释不超过 30 字。\n"
        "4. sentences：值得停下来读的句子，最多 3 句。src 必须与正文**逐字一致**，\n"
        "   why 说它在课文里起了什么作用（写出什么画面、什么心情），不超过 40 字。\n"
        "5. methods：本课的表达顺序与表达方法，只写课文里确实看得出来的，\n"
        "   最多 4 个，只能从下面清单里挑：\n"
        "   {methods}\n"
        "6. questions：课后题的答题思路。q 必须**照抄课后题原文**，\n"
        "   hint 是“怎么想、从课文哪儿找”，不超过 60 字。\n"
        "7. transfer：从课文到生活的表达运用（小练笔／常见应用文），不超过 60 字。\n"
        "8. notes：逐段批注，最多 6 条，para 从 0 开始。\n"
        "   kind 只能是 段意／字词／朗读／提问／写法／积累／背诵；\n"
        "   tags 是这段的描写角度／修辞／说明方法，只能从下面挑，最多 2 个：\n"
        "   {methods}\n"
        "   text 不超过 40 字，落到“这段写了什么形象、什么细节、为什么这么写”。\n"
        "9. background：作者、出处、写作背景、典故出处，不超过 100 字；\n"
        "   不确定就留空。\n"
        "10. center：idea 中心思想，virtue 人物品质或道理启示，各不超过 40 字。\n"
        "11. exam：本课考点，最多 5 条。point 只能从下面挑：{exam}\n"
        "    how 写“常怎么考、怎么答”，不超过 40 字。\n"
        "12. traps：易错点（含词语感情色彩、标点用法），最多 5 条。\n"
        "    type 只能从下面挑：{traps}，text 不超过 30 字。\n"
        "13. accumulate：课文里值得积累的词句、名言或诗句，最多 3 条，\n"
        "    t 必须与正文逐字一致，why 写可以怎么用，不超过 20 字。\n"
        "14. extend：life 写读了之后能做的事，不超过 40 字；\n"
        "    links 写同类文章或跨学科联系，最多 2 条，每条不超过 30 字。\n"
    ),
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


def _norm(s: str) -> str:
    """只留汉字与字母数字，用于判断某句/某词是否真出自原文。"""
    return re.sub(r"[^一-鿿A-Za-z0-9]", "", s or "")


def _paras(r: dict) -> list:
    ps = r.get("paragraphs") or []
    if isinstance(ps, str):
        try:
            ps = json.loads(ps)
        except Exception:
            ps = [p for p in ps.split("\n") if p.strip()]
    return [str(p).strip() for p in ps if str(p).strip()]


def stage_of(grade: str) -> str:
    """年级 → 课标学段。认不出就按第二学段（3-4）处理。"""
    return G_STAGE.get(str(grade or "").strip()[:1], "3-4")


def standard_of(stage: str) -> dict:
    """这一课各字段对应的课标要求（页面要显示"依据哪一条"）。"""
    on = STAGE_FIELDS.get(stage, STAGE_FIELDS["3-4"])
    out = {}
    for k in on:
        if k == "chars":
            out["chars"] = STANDARD["chars"]
        elif k == "transfer":
            out["transfer"] = STANDARD["transfer"] % EXP.get(stage, EXP["3-4"])
        elif k in STANDARD:
            out[k] = STANDARD[k]
    return out


def _book_words(rows: list) -> dict:
    """按册归集教材字表：会认 / 会写 / 词语。

    字表里 lesson_no 一半是空的，按它归课会漏；反过来做——先把整册的字攒起来，
    再按“这个字确实出现在这篇课文里”归到本课，不依赖 lesson_no。
    """
    books = {}
    for r in rows:
        b = r.get("book_id") or ""
        kind = str(r.get("kind") or "")
        val = str(r.get("value") or "").strip()
        if not b or not val:
            continue
        d = books.setdefault(b, {"ren": set(), "xie": set(), "ci": set()})
        if "写字" in kind:
            d["xie"].add(val)
        elif "词语" in kind:
            d["ci"].add(val)
        else:
            d["ren"].add(val)
    return books


def _targets() -> list:
    """待处理的课文：正文非空才算一课（语文园地等没正文的不做）。"""
    texts = _load(TEXT_FILE)
    structs = {s.get("lesson_id"): s for s in _load(STRUCT_FILE)}
    words = _book_words(_load(WORDS_FILE))
    genres = {g.get("lesson_id"): (g.get("genre") or "") for g in _load(GENRE_FILE)}
    # 作者与出处教材已给：挂上去给模型看，免得它编一个
    metas = {m.get("lesson_id"): m for m in _load(META_FILE) if m.get("lesson_id")}
    elems = {}
    for e in _load(ELEM_FILE):
        if str(e.get("subject") or "") != "语文":
            continue
        elems[(e.get("grade"), e.get("term"), str(e.get("unit_no")))] = e

    out = []
    for r in texts:
        ps = _paras(r)
        if not ps:
            continue
        b = r.get("book_id") or ""
        body = "\n".join(ps)
        w = words.get(b, {"ren": set(), "xie": set(), "ci": set()})
        ren = sorted([c for c in w["ren"] if c and c in body])
        xie = sorted([c for c in w["xie"] if c and c in body])
        st = structs.get(r.get("lesson_id")) or {}
        el = elems.get((r.get("grade"), r.get("term"), str(r.get("unit_no")))) or {}
        stage = stage_of(r.get("grade"))
        out.append({
            "lesson_id": r.get("lesson_id"), "book_id": b,
            "title": r.get("title") or "", "grade": r.get("grade") or "",
            "term": r.get("term") or "", "stage": stage,
            "unit_no": r.get("unit_no"), "lesson_no": r.get("lesson_no"),
            "page": r.get("page"),
            "genre": genres.get(r.get("lesson_id")) or "",
            "author": (metas.get(r.get("lesson_id")) or {}).get("author") or "",
            "source": (metas.get(r.get("lesson_id")) or {}).get("source") or "",
            "element": el.get("reading_focus") or el.get("theme") or "",
            "paras": ps, "body": body, "ren": ren, "xie": xie,
            "parts": st.get("parts") or [], "idea": st.get("main_idea") or "",
            "tasks": [t for t in (r.get("tasks") or []) if t],
        })
    return out


def _prompt(t: dict) -> str:
    stage = t["stage"]
    head = "\n".join(t["paras"])[:3000]
    parts = "\n".join(
        "第%d-%d段：%s" % (p.get("from", 0), p.get("to", 0), p.get("gist") or "")
        for p in (t["parts"] or [])[:14]) or "（暂无）"
    tasks = "\n".join("- " + str(x) for x in (t["tasks"] or [])[:6]) or "（教材未给）"
    doc = TASKS_DOC.get(stage, TASKS_DOC["3-4"]).format(
        tags="、".join(TAGS.get(stage, ())), methods="、".join(METHODS),
        exam="、".join(EXAM_POINTS.get(stage, ())),
        traps="、".join(TRAP_TYPES.get(stage, ())))
    return PROMPT.format(
        title=t["title"], book="%s%s" % (t["grade"], t["term"]),
        author=t.get("author") or "（教材未标）", unit=t["unit_no"] or "?", stage=stage, text=head, parts=parts,
        tasks=tasks,
        chars="、".join((t["xie"] or []) + (t["ren"] or []))[:120] or "（暂无）",
        tasks_doc=doc)


def _pick(d: dict, key: str, n: int) -> list:
    v = d.get(key) or []
    return [x for x in v if isinstance(x, dict)][:n]


def _check(t: dict, d: dict) -> tuple:
    """校验并清洗。返回（清洗后的片段, 被丢弃的说明）。

    学段不要求的字段一律清空——三年级抽不出"表达方法"不是失败，
    是课标本来就不要求。
    """
    stage = t["stage"]
    on = STAGE_FIELDS.get(stage, STAGE_FIELDS["3-4"])
    body_n = _norm(t["body"])
    chars = set(t["ren"]) | set(t["xie"])
    tasks_n = [_norm(str(x)) for x in (t["tasks"] or [])]
    dropped = []

    read = d.get("read") or {}
    recite = str(read.get("recite") or "").strip()
    if recite and not any(recite and _norm(recite) in tn for tn in tasks_n):
        dropped.append("recite")
        recite = ""

    words = []
    for w in _pick(d, "words", 8):
        s = str(w.get("w") or "").strip()
        if s and (_norm(s) in body_n or s in chars):
            words.append({"w": s, "mean": str(w.get("mean") or "").strip()[:40]})
        else:
            dropped.append("word:" + s)

    sents = []
    for s in _pick(d, "sentences", 3 if "sentences" in on else 0):
        src = str(s.get("src") or "").strip()
        # 半截句子（没断在标点上）看着别扭，宁可不要
        whole = len(src) >= 16 or (src and src[-1:] in "。！？…”）”》】")
        if src and _norm(src) in body_n and whole:
            sents.append({"src": src, "why": str(s.get("why") or "").strip()[:60]})
        else:
            dropped.append("sent")

    # 低年级只认最基础的修辞；表达方法（顺序、点面结合等）是第三学段才抓
    pool = METHODS if stage == "5-6" else RHETORIC
    methods = [str(m).strip() for m in (d.get("methods") or [])
               if str(m).strip() in pool][:4]
    if "methods" not in on:
        methods = []

    qs = []
    for q in _pick(d, "questions", 6):
        text = str(q.get("q") or "").strip()
        if not text:
            continue
        n = _norm(text)
        if any(n and (n in tn or tn in n) for tn in tasks_n):
            qs.append({"q": text, "hint": str(q.get("hint") or "").strip()[:80]})
        else:
            dropped.append("q")

    poly = []
    for p in _pick(d, "polyphone", 4 if "polyphone" in on else 0):
        zi = str(p.get("zi") or "").strip()
        if zi and _norm(zi) and _norm(zi) in body_n:
            items = [{"py": str(i.get("py") or "").strip(),
                      "ci": str(i.get("ci") or "").strip()}
                     for i in (p.get("items") or []) if isinstance(i, dict)][:3]
            if items:
                poly.append({"zi": zi, "items": items})
        else:
            dropped.append("poly:" + zi)

    kinds_ok = NOTE_STAGE.get(stage, NOTE_KINDS)
    tags_ok = TAGS.get(stage, ())
    notes = []
    for n in _pick(d, "notes", 6):
        try:
            i = int(n.get("para"))
        except Exception:
            continue
        kind = str(n.get("kind") or "").strip()
        if not (0 <= i < len(t["paras"])) or kind not in kinds_ok:
            continue
        # 自己造的标签一律丢：宁可没标签，也不要"多感官交融式描写"这种词
        tags = [str(x).strip() for x in (n.get("tags") or [])
                if str(x).strip() in tags_ok][:2]
        notes.append({"para": i, "kind": kind, "tags": tags,
                      "text": str(n.get("text") or "").strip()[:60]})

    # 背景资料：允许外部知识，没法逐字核验，只限长度，靠"不确定就留空"约束
    background = str(d.get("background") or "").strip()[:160]

    # 中心：教材已给的优先（页面用教材的），LLM 只补教材没给的
    c = d.get("center") or {}
    center = {"idea": str(c.get("idea") or "").strip()[:80],
              "virtue": str(c.get("virtue") or "").strip()[:40]}

    # 考点：point 必须落在白名单，模型编的"常考xxx"一律丢
    exam_ok = EXAM_POINTS.get(stage, ())
    exam = []
    for x in _pick(d, "exam", 5):
        p = str(x.get("point") or "").strip()
        if p in exam_ok:
            exam.append({"point": p, "how": str(x.get("how") or "").strip()[:50]})
        else:
            dropped.append("exam:" + p)

    # 易错点：type 走白名单（低年级不给"感情色彩""标点"）
    trap_ok = TRAP_TYPES.get(stage, ())
    traps = []
    for x in _pick(d, "traps", 5):
        tp = str(x.get("type") or "").strip()
        if tp in trap_ok:
            traps.append({"type": tp,
                          "text": str(x.get("text") or "").strip()[:40]})
        else:
            dropped.append("trap:" + tp)

    # 积累：必须逐字出自正文，编不出来就别要
    acc = []
    for a in _pick(d, "accumulate", 3):
        s = str(a.get("t") or "").strip()
        if s and _norm(s) in body_n:
            acc.append({"t": s, "why": str(a.get("why") or "").strip()[:30]})
        else:
            dropped.append("acc:" + s[:6])

    ext = d.get("extend") or {}
    extend = {"life": str(ext.get("life") or "").strip()[:60],
              "links": [str(x).strip()[:30] for x in (ext.get("links") or [])
                        if str(x).strip()][:2]}

    # 模型爱留空壳（"我读了《》，最喜欢……"），这种占位句不如不要
    transfer = str(d.get("transfer") or "").strip()[:100]
    if "《》" in transfer or "（）" in transfer:
        dropped.append("transfer")
        transfer = ""

    got = {"recite": recite, "words": words, "sentences": sents,
           "methods": methods, "questions": qs, "polyphone": poly,
           "notes": notes, "background": background, "center": center,
           "exam": exam, "traps": traps, "accumulate": acc,
           "extend": extend, "transfer": transfer}
    # 本学段不要求的字段一律清空：三年级没有"表达方法"不是失败，是课标不要求
    for k in list(got):
        if k in on or k == "notes":
            continue
        got[k] = {} if isinstance(got[k], dict) else (
            [] if isinstance(got[k], list) else "")
    return got, dropped


def build(limit: int = 0, force: bool = False, workers: int = 4,
          grade: str = "", verbose: bool = True) -> dict:
    """生成每课本体。已处理过的跳过（--force 重跑）。

    grade 用来按年级跑（"三"/"三年级"都认），便于分学段抽查质量。
    """
    from ..site import goals      # 册次顺序得用它，汉字字符串排序是错的

    todo = _targets()
    if grade:
        key = str(grade).strip()[:1]
        todo = [t for t in todo if str(t.get("grade") or "").strip()[:1] == key]
    if not force:
        done = llm.load_done(KB_FILE, "lesson_id")
        todo = [t for t in todo if t.get("lesson_id") not in done]
    todo.sort(key=lambda x: (goals.key_of(x["grade"], x["term"]),
                             str(x["unit_no"] or 0).zfill(3),
                             str(x["lesson_no"] or 0).zfill(3)))
    if limit:
        todo = todo[:limit]
    if verbose:
        print("待生成本体：%d 课" % len(todo))
    if not todo:
        return {"ok": 0, "fail": 0, "empty": 0}

    ok = fail = empty = 0

    def one(t: dict) -> tuple:
        try:
            res = llm.chat(_prompt(t), max_tokens=2048)
            d = llm.parse_json(res.text)
            if not isinstance(d, dict):
                raise ValueError("返回的不是对象")
            got, dropped = _check(t, d)
            if verbose and dropped:
                print("  丢弃 %s：%s" % (t["title"], "、".join(dropped)[:80]))
            if not any(got.values()):
                empty += 1
            row = {
                "lesson_id": t["lesson_id"], "book_id": t["book_id"],
                "title": t["title"], "grade": t["grade"], "term": t["term"],
                "stage": t["stage"], "unit_no": t["unit_no"],
                "lesson_no": t["lesson_no"], "page": t["page"],
                "genre": t["genre"], "element": t["element"],
                "standard": standard_of(t["stage"]),
                "ren": t["ren"], "xie": t["xie"],
                "parts": t["parts"], "idea": t["idea"], "tasks": t["tasks"],
                "model": res.model, "ts": int(time.time()),
            }
            row.update(got)
            return row, None
        except Exception as e:
            return None, "%s：%s" % (t["title"], e)

    done_rows = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(one, t) for t in todo]
        for i, f in enumerate(as_completed(futs), 1):
            row, err = f.result()
            if err:
                fail += 1
                if verbose:
                    print("  [%d/%d] 失败 %s" % (i, len(todo), err))
                continue
            done_rows.append(row)
            ok += 1
            if verbose:
                print("  [%d/%d] %s(%s) → 词%d 句%d 写法%d 批注%d"
                      % (i, len(todo), row["title"], row["stage"],
                         len(row["words"]), len(row["sentences"]),
                         len(row["methods"]), len(row["notes"])))

    done_rows.sort(key=lambda r: (goals.key_of(r["grade"], r["term"]),
                                  str(r["unit_no"] or 0).zfill(3),
                                  str(r["lesson_no"] or 0).zfill(3)))
    # 重跑的课要覆盖旧记录（直接追加会留两条），所以整体重写一次
    new_ids = {r["lesson_id"] for r in done_rows}
    rows = [r for r in _load(KB_FILE) if r.get("lesson_id") not in new_ids]
    rows += done_rows
    rows.sort(key=lambda r: (goals.key_of(r["grade"], r["term"]),
                             str(r["unit_no"] or 0).zfill(3),
                             str(r["lesson_no"] or 0).zfill(3)))
    with open(KB_FILE, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if verbose:
        print("→ %s（成功 %d / 失败 %d / 无内容 %d）" % (KB_FILE, ok, fail, empty))
    return {"ok": ok, "fail": fail, "empty": empty}


def stats() -> dict:
    rows = _load(KB_FILE)
    by_stage = {}
    for r in rows:
        by_stage[r.get("stage") or "?"] = by_stage.get(r.get("stage") or "?", 0) + 1
    return {"lessons": len(rows), "by_stage": by_stage,
            "words": sum(len(r.get("words") or []) for r in rows),
            "sentences": sum(len(r.get("sentences") or []) for r in rows),
            "methods": sum(len(r.get("methods") or []) for r in rows),
            "questions": sum(len(r.get("questions") or []) for r in rows),
            "notes": sum(len(r.get("notes") or []) for r in rows)}
