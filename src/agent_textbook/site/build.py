# -*- coding: utf-8 -*-
"""静态站点"小学知识大全"：按教学目标组织的静态页面。

与 Agent 交互无关的那部分知识（教材里抽出来的字词、知识点、句型、歌谣…）
本来就应该是**可翻阅的静态页面**，不必每次问模型。这里从知识库取数，
按课标的教学目标骨架（`goals.py`）组织，生成不依赖后端的 HTML。

产出：pages/{index,math,chinese,english}.html + assets/ + data/*.json
所有数据内联进 HTML，双击即可打开（file:// 下也能用）。
"""
import json
import os
import shutil

import duckdb

from .. import config
from . import goals

OUT_DIR = os.path.join(config.ROOT, "pages")
ASSETS_SRC = os.path.join(os.path.dirname(__file__), "assets")
DB_PATH = os.path.join(config.DATA_DIR, "kb.duckdb")

# lessons 表没写 book_id（全空），真实册号藏在 lesson_id 的前 36 位
BOOK_OF = "substr(lesson_id,1,36)"


def _rows(con, sql):
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _j(s, default=None):
    """JSON 字段（存的时候是字符串）。"""
    if not s:
        return default if default is not None else []
    if isinstance(s, (list, dict)):
        return s
    try:
        return json.loads(s)
    except Exception:
        return default if default is not None else []


def _gt(r):
    """册次名：四年级上册。"""
    return "%s%s" % (r.get("grade") or "", r.get("term") or "")


# ------------------------------------------------------------------ 数学
def build_math(con) -> dict:
    units = _rows(con, """select section_id,grade,term,unit_no,title,
                          page_from,page_to from section_text
                          where subject='数学' and unit_no is not null""")
    kp = {r["section_id"]: r for r in _rows(
        con, "select section_id,points,summary from section_keypoint"
             " where subject='数学'")}
    maps = {}
    for r in _rows(con, """select grade,term,unit_name,topic,summary,nodes,
                           n_nodes,page_from from unit_map"""):
        maps[(r["grade"], r["term"], r["unit_name"])] = r
    measures = {}
    for r in _rows(con, """select grade,term,unit_name,units,symbols
                           from math_unit"""):
        measures[(r["grade"], r["term"], r["unit_name"])] = r

    out = []
    for u in units:
        points = [str(x).strip() for x in _j((kp.get(u["section_id"]) or {}).get("points"))]
        dom = goals.math_domain(u["title"])
        mp = maps.get((u["grade"], u["term"], u["title"]))
        ms = measures.get((u["grade"], u["term"], u["title"]))
        item = {
            "grade": u["grade"], "term": u["term"], "book": _gt(u),
            "unit_no": u["unit_no"], "title": u["title"], "domain": dom,
            "literacy": goals.math_literacy(u["title"], points),
            "points": points[:12],
            "page_from": u["page_from"], "page_to": u["page_to"],
        }
        if mp:
            nodes = _j(mp.get("nodes"))
            item["map"] = {"topic": mp.get("topic"), "summary": mp.get("summary"),
                           "nodes": [{"id": n.get("id"), "text": n.get("text"),
                                      "parent": n.get("parent")} for n in nodes],
                           "page": mp.get("page_from")}
        if ms:
            item["measures"] = _j(ms.get("units"))[:12]
        out.append(item)

    out.sort(key=lambda x: (goals.key_of(x["grade"], x["term"]), x["unit_no"] or 0))
    all_measures = []
    for (g, t, un), r in measures.items():
        for m in _j(r.get("units")):
            if isinstance(m, dict) and m.get("name"):
                all_measures.append({"name": m.get("name"), "rate": m.get("rate"),
                                     "dim": m.get("dimension"), "book": "%s%s" % (g, t),
                                     "unit": un})
    return {
        "domains": [{"key": d["key"], "name": d["name"], "desc": d["desc"]}
                    for d in goals.MATH_DOMAINS],
        "units": out, "measures": all_measures,
        "n_maps": len(maps),
    }


# ------------------------------------------------------------------ 语文
def build_chinese(con) -> dict:
    cn = "'语文'"
    # lessons 表没有 grade/term，从 books 关联出来
    texts = _rows(con, """select l.lesson_id,l.unit_no,l.unit_name,l.section,
                          l.title,l.printed_start,b.grade,b.term
                          from lessons l
                          join books b on b.book_id=%s
                          where b.subject=%s""" % (BOOK_OF, cn))
    meta = {r["lesson_id"]: r for r in _rows(
        con, "select lesson_id,genre,author,dynasty from lesson_meta")}

    def domain_of(sec, title):
        s = (sec or "") + (title or "")
        if "习作" in s or "口语交际" in s or "例文" in s:
            return "writing"
        if "识字" in s or "汉语拼音" in s or "写字" in s:
            return "literacy"
        if "综合性学习" in s or "快乐读书吧" in s or "语文园地" in s:
            return "inquiry"
        return "reading"

    out = []
    for r in texts:
        m = meta.get(r["lesson_id"]) or {}
        out.append({
            "grade": r.get("grade"), "term": r.get("term"),
            "book": "%s%s" % (r.get("grade") or "", r.get("term") or ""),
            "unit_no": r.get("unit_no"), "title": r.get("title"),
            "section": r.get("section") or "阅读",
            "domain": domain_of(r.get("section"), r.get("title")),
            "genre": m.get("genre"), "author": m.get("author"),
            "page": r.get("printed_start"),
        })
    out.sort(key=lambda x: (goals.key_of(x["grade"], x["term"]), x["unit_no"] or 0))

    elements = []
    for r in _rows(con, """select grade,term,unit_no,unit_name,unit_title,theme,
                           reading_focus,writing_focus,points,page_no
                           from unit_element where subject='语文'"""):
        elements.append({
            "grade": r["grade"], "term": r["term"], "book": _gt(r),
            "unit_no": r["unit_no"], "unit_title": r.get("unit_title"),
            "theme": r.get("theme"), "reading": r.get("reading_focus"),
            "writing": r.get("writing_focus"),
            "points": _j(r.get("points"))[:8], "page": r.get("page_no"),
        })
    elements.sort(key=lambda x: (goals.key_of(x["grade"], x["term"]), x["unit_no"] or 0))

    words = _rows(con, """select w.grade,w.term,w.kind,w.value,w.pinyin,w.page_no
                          from words w join books b on b.book_id=w.book_id
                          where b.subject='语文'""")
    bybook = {}
    for r in words:
        b = "%s%s" % (r["grade"] or "", r["term"] or "")
        bybook.setdefault(b, {}).setdefault(r["kind"] or "词语表", []).append(
            [r["value"] or "", r["pinyin"] or ""])
    # 同一个字会在多课重复出现（识字表里"一"既在第 1 课也在词语里），
    # 按字去重，拼音取先出现那条的非空值。
    for b in bybook:
        for k in bybook[b]:
            seen, uniq = {}, []
            for v, p in bybook[b][k]:
                if v in seen:
                    if p and not seen[v][1]:
                        seen[v][1] = p
                    continue
                seen[v] = [v, p]
                uniq.append(seen[v])
            bybook[b][k] = sorted(uniq, key=lambda x: x[0])

    return {
        "domains": [{"key": d["key"], "name": d["name"], "desc": d["desc"]}
                    for d in goals.CN_DOMAINS],
        "texts": out, "elements": elements, "words": bybook,
        "word_kinds": ["识字表", "写字表", "词语表"],
    }


# ------------------------------------------------------------------ 英语
def build_english(con) -> dict:
    def pick(table, cols):
        return _rows(con, "select %s from %s where subject='英语'"
                     % (",".join(cols), table))

    vocab = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
              "unit": r.get("unit_no"), "word": r.get("word"),
              "phonetic": r.get("phonetic"), "meaning": r.get("meaning"),
              "topic": r.get("topic"), "theme": goals.en_theme(r.get("topic"))}
             for r in pick("en_vocab", ["grade", "term", "unit_no", "word",
                                        "phonetic", "meaning", "topic"])]
    grammar = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
                "unit": r.get("unit_name"), "point": r.get("point"),
                "pattern": r.get("pattern"), "rule": r.get("rule"),
                "category": r.get("category")}
               for r in pick("en_grammar", ["grade", "term", "unit_name", "point",
                                            "pattern", "rule", "category"])]
    phonics = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
                "unit": r.get("unit_name"), "letters": r.get("letters"),
                "sound": r.get("sound"), "examples": _j(r.get("examples"))[:8],
                "chant": r.get("chant")}
               for r in pick("en_phonics", ["grade", "term", "unit_name", "letters",
                                            "sound", "examples", "chant"])]
    passages = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
                 "unit": r.get("unit_name"), "name": r.get("name"),
                 "genre": r.get("genre"), "source": r.get("source"),
                 "text": (r.get("text") or "")[:600], "topic": r.get("topic")}
                for r in pick("en_passage", ["grade", "term", "unit_name", "name",
                                             "genre", "source", "text", "topic"])]
    dialogues = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
                  "unit": r.get("unit_name"), "scene": r.get("scene"),
                  "function": r.get("function"),
                  "turns": _j(r.get("turns"))[:8]}
                 for r in pick("en_dialogue", ["grade", "term", "unit_name", "scene",
                                               "function", "turns"])]
    songs = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
              "unit": r.get("unit_no"), "name": r.get("song_title"),
              "lyrics": _j(r.get("lyrics"))[:30], "topic": r.get("topic")}
             for r in pick("en_song", ["grade", "term", "unit_no", "song_title",
                                       "lyrics", "topic"])]
    projects = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
                 "unit": r.get("unit_name"), "name": r.get("name"),
                 "type": r.get("type"), "goal": r.get("goal"),
                 "product": r.get("product")}
                for r in pick("en_project", ["grade", "term", "unit_name", "name",
                                             "type", "goal", "product"])]
    revisions = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
                  "theme": r.get("theme"), "tasks": _j(r.get("tasks"))[:10],
                  "outcome": r.get("outcome")}
                 for r in pick("en_revision", ["grade", "term", "theme", "tasks",
                                               "outcome"])]
    for lst in (vocab, grammar, phonics, passages, dialogues, songs, projects):
        lst.sort(key=lambda x: goals.key_of(x["grade"], x["term"]))
    return {
        "domains": [{"key": d["key"], "name": d["name"], "desc": d["desc"]}
                    for d in goals.EN_DOMAINS],
        "vocab": vocab, "grammar": grammar, "phonics": phonics,
        "passages": passages, "dialogues": dialogues, "songs": songs,
        "projects": projects, "revisions": revisions,
        "themes": ["人与自我", "人与社会", "人与自然"],
    }


# ------------------------------------------------------------------ 页面
NAV = [("index.html", "总览"), ("chinese.html", "语文"),
       ("math.html", "数学"), ("english.html", "英语")]

PAGE = """<!DOCTYPE html>
<html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 小学知识大全</title>
<link rel="stylesheet" href="assets/app.css"></head>
<body data-page="{page}">
<header>
  <span class="seal">课本</span>
  <h1>小学知识大全</h1>
  <div class="sub">按教学目标编排 · 每条都来自教材，可核对到册次与页码</div>
  <nav>{nav}</nav>
</header>
<main>
{body}
<div id="app"></div>
</main>
<footer>由教材解析流水线生成 · 内容取自义务教育教科书（人教版）·
数据本地生成，不出本机</footer>
<script>window.DATA={data};</script>
<script src="assets/app.js"></script>
</body></html>
"""


def _nav(cur):
    return "".join('<a href="%s"%s>%s</a>' % (h, ' class="on"' if h == cur else "", t)
                   for h, t in NAV)


def _esc(s):
    """内联到 <script> 里的 JSON——顺手转义 </，免得教材正文提前闭合脚本。"""
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")


def _write(path, html):
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def build_pages(out_dir: str = None, verbose: bool = True) -> dict:
    """生成整站。"""
    out = out_dir or OUT_DIR
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    os.makedirs(os.path.join(out, "data"), exist_ok=True)
    if os.path.isdir(ASSETS_SRC):
        for fn in os.listdir(ASSETS_SRC):
            shutil.copy(os.path.join(ASSETS_SRC, fn), os.path.join(out, "assets", fn))

    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        math_d = build_math(con)
        cn_d = build_chinese(con)
        en_d = build_english(con)
    finally:
        con.close()

    stats = {
        "math": {"units": len(math_d["units"]),
                 "points": sum(len(u["points"]) for u in math_d["units"]),
                 "maps": math_d["n_maps"],
                 "measures": len(math_d["measures"])},
        "chinese": {"texts": len(cn_d["texts"]), "elements": len(cn_d["elements"]),
                    "words": sum(len(v) for b in cn_d["words"].values()
                                 for v in b.values())},
        "english": {"vocab": len(en_d["vocab"]), "grammar": len(en_d["grammar"]),
                    "phonics": len(en_d["phonics"]), "passages": len(en_d["passages"]),
                    "songs": len(en_d["songs"])},
    }

    def dump(name, data):
        with open(os.path.join(out, "data", name + ".json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    dump("math", math_d)
    dump("chinese", cn_d)
    dump("english", en_d)

    index_body = """<div class="hero">
  <div class="verse">按学科 · 按教学目标 · 一条一条都对得上课本</div>
  <div class="rule"></div>
  <p class="lead">这里是不需要问 Agent 也能查的那部分知识：字词表、单元语文要素、
  数学知识点与知识结构图、英语词汇句型与歌谣……<b>全部从教材里抽出来</b>，
  每条都能核对到哪一册、哪一单元、第几页。<b>没有一条是模型编的。</b></p>
</div>
<h2>规模</h2>
<div class="grid">
<div class="card">语文 课文 <big>%d</big> 篇 · 单元要素 <big>%d</big> 条 · 字词 <big>%d</big> 条</div>
<div class="card">数学 单元 <big>%d</big> 个 · 知识点 <big>%d</big> 条 · 结构图 <big>%d</big> 张</div>
<div class="card">英语 词汇 <big>%d</big> · 句型 <big>%d</big> · 拼读 <big>%d</big> · 歌谣 <big>%d</big></div>
</div>
<h2>入口</h2>
<div class="grid">
<div class="card zh"><h3>语文</h3><p class="small">识字与写字（识字表/写字表/词语表）、
阅读与鉴赏（单元语文要素 + 课文）、表达与交流（习作要素 + 口语交际）、梳理与探究。</p>
<a href="chinese.html">进入 →</a></div>
<div class="card ma"><h3>数学</h3><p class="small">按课标四大领域编排：数与代数、图形与几何、
统计与概率、综合与实践。每单元列出知识点，附整理复习的知识结构图与计量单位进率。</p>
<a href="math.html">进入 →</a></div>
<div class="card en"><h3>英语</h3><p class="small">语音拼读、词汇、语法句型、语篇对话，
以及歌谣、项目任务与复习板块；词汇按三大主题范畴归类。</p>
<a href="english.html">进入 →</a></div>
</div>""" % (
        stats["chinese"]["texts"], stats["chinese"]["elements"], stats["chinese"]["words"],
        stats["math"]["units"], stats["math"]["points"], stats["math"]["maps"],
        stats["english"]["vocab"], stats["english"]["grammar"],
        stats["english"]["phonics"], stats["english"]["songs"])

    _write(os.path.join(out, "index.html"), PAGE.format(
        title="总览", page="index", nav=_nav("index.html"), body=index_body,
        data=_esc({"stats": stats})))

    _write(os.path.join(out, "math.html"), PAGE.format(
        title="数学", page="math", nav=_nav("math.html"),
        body='<h2>数学 · 按教学目标编排</h2>'
             '<p class="lead">四大领域来自 2022 版课标；每个单元标注它主要练的'
             '核心素养表现（数感、量感、推理意识…）。知识点是从教材正文抽的，'
             '不是概括。</p>',
        data=_esc(math_d)))

    _write(os.path.join(out, "chinese.html"), PAGE.format(
        title="语文", page="chinese", nav=_nav("chinese.html"),
        body='<h2>语文 · 按教学目标编排</h2>'
             '<p class="lead">四大语文实践活动来自 2022 版课标。'
             '单元语文要素是教材印在单元导语页上的原话——它就是这一单元的纲：'
             '阅读要素说明"读的时候练什么"，习作要素就是习作的要求（写完可逐条对照）。'
             '低年级（一、二年级）教材不印单元要素，所以这里从三年级起才列得出来。</p>',
        data=_esc(cn_d)))

    _write(os.path.join(out, "english.html"), PAGE.format(
        title="英语", page="english", nav=_nav("english.html"),
        body='<h2>英语 · 按教学目标编排</h2>'
             '<p class="lead">按语言知识与语言技能分五块；词汇另按课标三大主题范畴'
             '（人与自我 / 人与社会 / 人与自然）归类。</p>',
        data=_esc(en_d)))

    if verbose:
        print("→ %s（index + 语文 + 数学 + 英语）" % out)
        print("   %s" % json.dumps(stats, ensure_ascii=False))
    return {"out": out, "stats": stats}
