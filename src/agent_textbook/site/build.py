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


def _unum(s):
    """Unit 2 / 第3单元 → 2，用于课本顺序排序。"""
    d = "".join(ch for ch in str(s or "") if ch.isdigit())
    return int(d) if d else 0


# ------------------------------------------------------------------ 数学
def build_math(con) -> dict:
    # unit_no 为空的是"整理复习/附录"之类，不算单元；text 是这一单元的教材正文
    units = _rows(con, """select section_id,grade,term,unit_no,title,
                          page_from,page_to,text from section_text
                          where subject='数学' and unit_no is not null""")
    kp = {r["section_id"]: r for r in _rows(
        con, "select section_id,points,summary from section_keypoint"
             " where subject='数学'")}
    # 公式与例题按 section_id 挂到单元（section_formula / example 都带 section_id）
    fm = {}
    for r in _rows(con, """select section_id,latex,kind,note,page_no
                           from section_formula"""):
        fm.setdefault(r["section_id"], []).append(r)
    ex = {}
    for r in _rows(con, """select section_id,name,stem,given,ask,steps,answer,
                           answer_latex,difficulty,page_hint
                           from example"""):
        ex.setdefault(r["section_id"], []).append(r)
    # 公式排序：先"是什么"（定义/法则/性质），再"怎么用"（例题/计算过程），最后练习
    KIND_ORDER = {"定义": 0, "法则": 1, "性质": 2, "例题": 3, "计算过程": 4, "练习": 5}

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
            "life": goals.math_life(u["title"], points),
            "points": points[:12],
            "page_from": u["page_from"], "page_to": u["page_to"],
            # 教材正文（这一单元课本上写的讲解与例题引子），按行切开，不截断
            "text": [ln.strip() for ln in (u.get("text") or "").split("\n")
                     if ln.strip()][:160],
        }
        if mp:
            nodes = _j(mp.get("nodes"))
            item["map"] = {"topic": mp.get("topic"), "summary": mp.get("summary"),
                           "nodes": [{"id": n.get("id"), "text": n.get("text"),
                                      "parent": n.get("parent")} for n in nodes],
                           "page": mp.get("page_from")}
        if ms:
            item["measures"] = _j(ms.get("units"))[:12]
        # 公式：同 latex 只留一条，按"定义→法则→性质→例题→计算过程→练习"排
        seen_latex, fl = set(), []
        for f in sorted(fm.get(u["section_id"]) or [],
                        key=lambda x: KIND_ORDER.get(x.get("kind"), 9)):
            lx = (f.get("latex") or "").strip()
            if not lx or lx in seen_latex:
                continue
            seen_latex.add(lx)
            fl.append({"latex": lx, "kind": f.get("kind"), "note": f.get("note"),
                       "page": f.get("page_no")})
        item["formulas"] = fl[:18]
        # 例题：题干 + 分步（每步可能带公式）+ 答案
        item["examples"] = [{
            "name": e.get("name"), "stem": e.get("stem"), "given": e.get("given"),
            "ask": e.get("ask"),
            "steps": [({"text": s.get("text"), "latex": s.get("latex")}
                       if isinstance(s, dict)
                       else {"text": str(s), "latex": ""})
                      for s in _j(e.get("steps"))],
            "answer": e.get("answer"), "answer_latex": e.get("answer_latex"),
            "difficulty": e.get("difficulty"), "page": e.get("page_hint"),
        } for e in (ex.get(u["section_id"]) or [])[:8]]
        out.append(item)

    out.sort(key=lambda x: (goals.key_of(x["grade"], x["term"]), _unum(x["unit_no"])))
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


# ------------------------------------------------------------------ 数学·解决问题
def build_problems(con) -> dict:
    """教材里的"解决问题"：已知 → 所求 → 分步 → 答案。

    教研里的共识：小学生解应用题，卡在**数量关系**——读不懂题、理不清关系、
    想得不灵活。所以这里不是题库，而是把每道题的数量关系与思考步骤摊开，
    并且默认把答案折起来：先自己想，再一步步对照。考点直接来自教材标注。
    """
    rows = _rows(con, """select grade,term,unit_name,name,type,stem,given,ask,steps,
                         answer,answer_latex,keypoint,difficulty,page_hint
                         from example
                         where subject='数学' and coalesce(given,'')<>''
                           and coalesce(ask,'')<>''""")
    out = []
    for r in rows:
        out.append({
            "grade": r.get("grade"), "term": r.get("term"), "book": _gt(r),
            "unit": r.get("unit_name"), "name": r.get("name"),
            "type": r.get("type"), "stem": r.get("stem"),
            "given": r.get("given"), "ask": r.get("ask"),
            "steps": [({"text": s.get("text"), "latex": s.get("latex")}
                       if isinstance(s, dict) else {"text": str(s), "latex": ""})
                      for s in _j(r.get("steps"))],
            "answer": r.get("answer"), "answer_latex": r.get("answer_latex"),
            "keypoint": (r.get("keypoint") or "").strip() or "其他",
            "difficulty": (r.get("difficulty") or "").strip() or "基础",
        })
    out.sort(key=lambda x: (goals.key_of(x["grade"], x["term"]), x["unit"] or ""))
    kp = {}
    for x in out:
        kp.setdefault(x["keypoint"], []).append(x["book"])
    # 考点上千个（多数只出现一两次），全列进下拉与分组反而找不到，
    # 只留题最多的前 400 个，其余在页面上归到"其他考点"。
    keypoints = sorted(
        [{"name": k, "n": len(v), "books": sorted({b for b in v if b})}
         for k, v in kp.items()], key=lambda x: (-x["n"], x["name"]))[:400]
    # 教材里单独标出来的"生活中的数学"：这些本来就是给孩子看"学了有什么用"的
    life = []
    for r in _rows(con, """select grade,term,unit_name,name,stem,given,ask,steps,answer,
                           keypoint from example
                           where subject='数学' and type='生活中的数学'"""):
        life.append({
            "book": _gt(r), "grade": r.get("grade"), "term": r.get("term"),
            "unit": r.get("unit_name"), "name": r.get("name"), "stem": r.get("stem"),
            "given": r.get("given"), "ask": r.get("ask"), "answer": r.get("answer"),
            "keypoint": (r.get("keypoint") or "").strip() or "其他",
            "steps": [({"text": s.get("text"), "latex": s.get("latex")}
                       if isinstance(s, dict) else {"text": str(s), "latex": ""})
                      for s in _j(r.get("steps"))],
        })
    return {"problems": out, "keypoints": keypoints, "life": life}


# ------------------------------------------------------------------ 语文
def build_chinese(con) -> dict:
    # 课文正文在 lesson_text：带段落、课后题、生字；体裁与作者从 lesson_meta 补
    meta = {r["lesson_id"]: r for r in _rows(
        con, "select lesson_id,genre,author,dynasty,source from lesson_meta")}
    texts = _rows(con, """select lesson_id,grade,term,unit_no,unit_name,section,
                          lesson_no,title,printed_start,page_from,page_to,chars,
                          paragraphs,tasks,newchars
                          from lesson_text""")
    # lesson_no 只有一半课文有值，缺的用 lessons 表里的 seq 兜底——
    # 课本顺序不能乱：按进度学时，第几单元第几课必须是书上那个次序。
    seqs = {r["lesson_id"]: r.get("seq") for r in _rows(
        con, "select lesson_id,seq from lessons")}

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
        no = _unum(r.get("lesson_no")) or _unum(seqs.get(r["lesson_id"]))
        out.append({
            "grade": r.get("grade"), "term": r.get("term"),
            "no": no,
            "book": "%s%s" % (r.get("grade") or "", r.get("term") or ""),
            "unit_no": r.get("unit_no"), "unit_name": r.get("unit_name"),
            "title": r.get("title"),
            "section": r.get("section") or "阅读",
            "domain": domain_of(r.get("section"), r.get("title")),
            "genre": m.get("genre"), "author": m.get("author"),
            "dynasty": m.get("dynasty"),
            "page": r.get("printed_start"), "chars": r.get("chars"),
            "paras": [p for p in _j(r.get("paragraphs")) if p],
            "tasks": [t for t in _j(r.get("tasks")) if t][:6],
            "newchars": _j(r.get("newchars"))[:30],
        })
    # 课本顺序：册次 → 单元 → 课次 → 起始印刷页码
    # （lesson_no 有缺有重，页码是最后的兜底，同一课次也按书上先后排）
    out.sort(key=lambda x: (goals.key_of(x["grade"], x["term"]),
                            _unum(x["unit_no"]), x["no"], x["page"] or 0))

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

    # 古诗文：原文 + 注释 + 译文（教材里印在课文下方，这里一并给出，不用翻书）
    gl = {}
    for r in _rows(con, "select title,glossary from lesson_glossary"):
        gl[r["title"]] = _j(r.get("glossary"))
    tr = {}
    for r in _rows(con, "select title,translation,literal from lesson_translation"):
        tr[r["title"]] = {"tr": r.get("translation"), "lit": _j(r.get("literal"))}
    pieces = []
    for r in _rows(con, """select grade,term,unit_no,unit_name,title,kind,dynasty,
                           author,text,notes from piece"""):
        t = r.get("title")
        pieces.append({
            "grade": r.get("grade"), "term": r.get("term"), "book": _gt(r),
            "unit_no": r.get("unit_no"), "title": t, "kind": r.get("kind"),
            "dynasty": r.get("dynasty"), "author": r.get("author"),
            "text": (r.get("text") or "")[:1200],
            "glossary": [g for g in (gl.get(t) or []) if isinstance(g, dict)][:20],
            "tr": (tr.get(t) or {}).get("tr") or "",
            "literal": [g for g in (tr.get(t) or {}).get("lit") or []
                        if isinstance(g, dict)][:20],
            "notes": r.get("notes"),
        })
    pieces.sort(key=lambda x: (goals.key_of(x["grade"], x["term"]), x["unit_no"] or 0))

    # 作者小传（课文中出现的作家）
    authors = {}
    for r in _rows(con, "select author,dynasty,intro,works from author_intro"):
        if r.get("author"):
            authors[r["author"]] = {"dynasty": r.get("dynasty"),
                                    "intro": r.get("intro"),
                                    "works": _j(r.get("works"))[:6]}

    return {
        "domains": [{"key": d["key"], "name": d["name"], "desc": d["desc"]}
                    for d in goals.CN_DOMAINS],
        "texts": out, "elements": elements, "words": bybook,
        "word_kinds": ["识字表", "写字表", "词语表"],
        "pieces": pieces, "authors": authors,
    }


def build_structures(con) -> dict:
    """课文骨架：一篇课文分几层、每层写什么、主旨是什么。

    一线最头疼的阅读坎是"读完了说不出写了什么"（概括）。教材只印课文，
    这里把**结构**摊开：全文分几层、每层要点、主旨是什么，
    并按体裁给不同的读法——说明文抓特征，记事抓六要素，诗歌抓意象。
    """
    txt = {r["lesson_id"]: r for r in _rows(
        con, """select lesson_id,grade,term,unit_no,unit_name,title,printed_start
                from lesson_text""")}
    genre = {r["lesson_id"]: r for r in _rows(
        con, "select lesson_id,genre_sub,reason from lesson_genre")}
    out = []
    for r in _rows(con, """select lesson_id,title,n_paragraphs,parts,main_idea
                           from lesson_structure"""):
        t = txt.get(r["lesson_id"]) or {}
        g = genre.get(r["lesson_id"]) or {}
        parts = [p for p in _j(r.get("parts")) if isinstance(p, dict)]
        out.append({
            "title": r.get("title") or t.get("title") or "",
            "book": "%s%s" % (t.get("grade") or "", t.get("term") or ""),
            "grade": t.get("grade"), "term": t.get("term"),
            "unit_no": t.get("unit_no"), "unit": t.get("unit_name"),
            "page": t.get("printed_start"),
            "n": _unum(r.get("n_paragraphs")),
            "parts": [{"from": _unum(p.get("from")), "to": _unum(p.get("to")),
                       "gist": p.get("gist") or ""} for p in parts],
            "main": r.get("main_idea") or "",
            "genre": g.get("genre_sub") or "", "why": g.get("reason") or "",
        })
    out.sort(key=lambda x: (goals.key_of(x["grade"], x["term"]),
                            _unum(x["unit_no"])))
    gs = {}
    for x in out:
        if x["genre"]:
            gs[x["genre"]] = gs.get(x["genre"], 0) + 1
    return {"structures": out,
            "genres": sorted(gs.items(), key=lambda x: (-x[1], x[0]))}


# ------------------------------------------------------------------ 英语
def build_english(con) -> dict:
    def pick(table, cols):
        return _rows(con, "select %s from %s where subject='英语'"
                     % (",".join(cols), table))

    vocab = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
              "unit": r.get("unit_no"), "word": r.get("word"),
              "phonetic": r.get("phonetic"), "meaning": r.get("meaning"),
              "topic": r.get("topic"), "example": r.get("example"),
              "theme": goals.en_theme(r.get("topic"))}
             for r in pick("en_vocab", ["grade", "term", "unit_no", "word",
                                        "phonetic", "meaning", "topic", "example"])]
    grammar = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
                "unit": r.get("unit_name"), "point": r.get("point"),
                "pattern": r.get("pattern"), "rule": r.get("rule"),
                "category": r.get("category"), "tense": r.get("tense"),
                "examples": _j(r.get("examples"))[:8]}
               for r in pick("en_grammar", ["grade", "term", "unit_name", "point",
                                            "pattern", "rule", "category", "tense",
                                            "examples"])]
    phonics = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
                "unit": r.get("unit_name"), "letters": r.get("letters"),
                "sound": r.get("sound"), "examples": _j(r.get("examples"))[:8],
                "chant": r.get("chant")}
               for r in pick("en_phonics", ["grade", "term", "unit_name", "letters",
                                            "sound", "examples", "chant"])]
    # 语篇即英语的"课文"：原文 + 译文 + 阅读理解题 + 重点词
    passages = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
                 "unit": r.get("unit_name"), "name": r.get("name"),
                 "genre": r.get("genre"), "source": r.get("source"),
                 "text": (r.get("text") or "")[:2000],
                 "zh": (r.get("zh") or "")[:2000],
                 "topic": r.get("topic"),
                 "words": _j(r.get("words"))[:20],
                 "comprehension": [c for c in _j(r.get("comprehension"))
                                   if isinstance(c, dict)][:8],
                 "keypoints": _j(r.get("keypoints"))[:8],
                 "writing": r.get("writing_task")}
                for r in pick("en_passage", ["grade", "term", "unit_name", "name",
                                             "genre", "source", "text", "zh", "topic",
                                             "words", "comprehension", "keypoints",
                                             "writing_task"])]
    dialogues = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
                  "unit": r.get("unit_name"), "scene": r.get("scene"),
                  "function": r.get("function"),
                  "patterns": _j(r.get("patterns"))[:6],
                  "turns": _j(r.get("turns"))[:12]}
                 for r in pick("en_dialogue", ["grade", "term", "unit_name", "scene",
                                               "function", "turns", "patterns"])]
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
    # 课本顺序：册次 → 单元（Unit 3 → 3）
    for lst in (vocab, grammar, phonics, passages, dialogues, songs, projects):
        lst.sort(key=lambda x: (goals.key_of(x["grade"], x["term"]),
                                _unum(x.get("unit"))))
    return {
        "domains": [{"key": d["key"], "name": d["name"], "desc": d["desc"]}
                    for d in goals.EN_DOMAINS],
        "vocab": vocab, "grammar": grammar, "phonics": phonics,
        "passages": passages, "dialogues": dialogues, "songs": songs,
        "projects": projects, "revisions": revisions,
        "themes": ["人与自我", "人与社会", "人与自然"],
    }


def build_speak(con) -> dict:
    """开口说：情境对话（分角色、逐句带中文）+ 常用表达 + 项目任务。

    "哑巴英语"的根子不是单词量，是没地方说。教材里每组对话本来就有角色、
    有场景、有功能，这里按角色摊开：可以一句一句推进，可以遮住中文自测，
    项目任务则给出"做出一样东西"的完整清单（用到哪句话、需要什么材料）。
    """
    dlg = []
    for r in _rows(con, """select grade,term,unit_name,title,scene,function,turns,
                           patterns from en_dialogue where subject='英语'"""):
        turns = [t for t in _j(r.get("turns")) if isinstance(t, dict)]
        if not turns:
            continue
        dlg.append({
            "book": _gt(r), "grade": r.get("grade"), "term": r.get("term"),
            "unit": r.get("unit_name"), "title": r.get("title"),
            "scene": r.get("scene"), "function": r.get("function"),
            "patterns": [str(p) for p in _j(r.get("patterns"))][:8],
            "turns": [{"s": t.get("speaker"), "speaker": t.get("speaker"),
                       "en": t.get("en"), "zh": t.get("zh")} for t in turns],
        })
    prj = []
    for r in _rows(con, """select grade,term,unit_name,name,type,goal,steps,language,
                           product,materials from en_project where subject='英语'"""):
        prj.append({
            "book": _gt(r), "grade": r.get("grade"), "term": r.get("term"),
            "unit": r.get("unit_name"), "name": r.get("name"),
            "type": r.get("type"), "goal": r.get("goal"),
            "steps": [str(s) for s in _j(r.get("steps"))][:8],
            "language": [str(s) for s in _j(r.get("language"))][:8],
            "product": r.get("product"),
            "materials": [str(s) for s in _j(r.get("materials"))][:8],
        })
    expr = []
    for r in _rows(con, """select grade,term,unit_no,en,zh from en_expr
                           where subject='英语'"""):
        if r.get("en"):
            expr.append({"book": _gt(r), "grade": r.get("grade"),
                         "unit": r.get("unit_no"), "en": r.get("en"),
                         "zh": r.get("zh")})
    for lst in (dlg, prj, expr):
        lst.sort(key=lambda x: (goals.key_of(x.get("grade"), x.get("term")),
                                _unum(x.get("unit"))))
    fs = {}
    for d in dlg:
        if d["function"]:
            fs[d["function"]] = fs.get(d["function"], 0) + 1
    return {"dialogues": dlg, "projects": prj, "exprs": expr,
            "functions": sorted(fs.items(), key=lambda x: (-x[1], x[0]))}


# ------------------------------------------------------------------ 页面
# 各科再分页：一页只做一件事——单页小、加载快、看得清
CN_PAGES = [
    ("index", "识字与写字", "literacy",
     "按册列出识字表、写字表、词语表，带拼音。字词靠查表，不靠讲解；点一个字看它的拼音。"),
    ("texts", "课文全文", "reading",
     "按册 → 单元 → 课文。单元头上印着这一单元的语文要素（读的时候练什么）；"
     "页首有课文目录，点目录直达课文，可按册筛选、按标题/作者/正文搜索，"
     "点「读全文」展开课文与课后题、本课生字。"),
    ("writing", "表达与交流", "writing",
     "习作要素就是习作量规：要求来自教材，写完可以逐条对着看。"),
    ("poetry", "古诗文", "poetry",
     "原文 + 注释 + 译文 + 逐句对译，教材印在课文下方的这里一并给出；"
     "古诗词与小古文分开排，可按主题字检索（飞花令）。"),
    ("structure", "课文骨架", "structure",
     "一篇课文分几层、每层写什么、主旨是什么。读之前先看骨架，读完拿主旨对照——"
     "“读完了说不出写了什么”这道坎，靠的是把结构看明白。不同体裁给不同的读法。"),
]
MATH_PAGES = [
    ("index", "全部单元", "all",
     "四大领域来自 2022 版课标。每个单元列出知识点、公式（真渲染）、例题（分步）"
     "与知识结构图。"),
    ("num", "数与代数", "num", "数的认识与运算、式与方程、比和比例。"),
    ("geo", "图形与几何", "geo", "图形的认识与测量、图形的位置与运动。"),
    ("stat", "统计与概率", "stat", "数据的收集与整理、统计图表、平均数、随机现象。"),
    ("prac", "综合与实践", "prac", "数学广角、主题活动与项目学习。"),
    ("problem", "解决问题", "problem",
     "教材里每一道“解决问题”：已知什么、求什么、分几步想、答案是什么。"
     "答案默认折起来——先自己想，再一步步对照。卡在数量关系上的，按考点找同类题练。"),
]
EN_PAGES = [
    ("index", "课文与语篇", "discourse",
     "教材里成篇的读与写：情景对话、短文。点“中文对照”切换译文——纸质书做不到。"),
    ("vocab", "词汇", "vocab",
     "按话题成串收录，带音标与例句；点单词才出中文（自测），另有听写练习。"),
    ("grammar", "语法汇总", "grammar",
     "按范畴汇总，附“哪一册学了什么时态”的时态线，句型里可替换处高亮。"),
    ("phonics", "语音拼读", "phonics", "字母与字母组合的发音：见词能读、听音能写。"),
    ("use", "综合运用", "use", "歌谣、项目任务与复习板块。"),
    ("speak", "开口说", "speak",
     "教材里每一组对话按角色摊开，一句一句推进；中文可遮住自测。"
     "另有项目任务：做出一样东西要说什么、要什么材料。敢开口，从有话可说开始。"),
]
SUBJECTS = [("chinese", "语文", CN_PAGES),
            ("math", "数学", MATH_PAGES),
            ("english", "英语", EN_PAGES)]

PAGE = """<!DOCTYPE html>
<html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 小学知识大全</title>
<link rel="stylesheet" href="{base}assets/app.css"></head>
<body data-page="{page}" data-base="{base}">
<header>
  <span class="seal">课本</span>
  <h1>小学知识大全</h1>
  <div class="sub">按教学目标编排 · 每条都来自教材，可核对到册次与页码</div>
</header>
<div class="wrap">
  <aside class="side">
    <p class="sidet">学科</p>
    <nav>{nav}</nav>
    {subnav}
  </aside>
  <main>
{body}
<div id="app"></div>
  </main>
</div>
<footer>由教材解析流水线生成 · 内容取自义务教育教科书（人教版）·
数据本地生成，不出本机</footer>
<script>window.DATA={data};</script>
<script src="{base}assets/app.js"></script>
</body></html>
"""


def _nav(cur, base=""):
    """主栏：总览 + 三科。"""
    a = ['<a href="%sindex.html"%s>总览</a>'
         % (base, ' class="on"' if cur == "index" else "")]
    for k, name, _ in SUBJECTS:
        a.append('<a href="%s%s/index.html"%s>%s</a>'
                 % (base, k, ' class="on"' if cur == k else "", name))
    return "".join(a)


def _subnav(cur, pages):
    """科内子页栏。"""
    return '<p class="sidet">专题</p><nav class="sub">' + "".join(
        '<a href="%s.html"%s>%s</a>' % (s, ' class="on"' if s == cur else "", t)
        for s, t, _, _ in pages) + "</nav>"


def _esc(s):
    """内联到 <script> 里的 JSON——顺手转义 </，免得教材正文提前闭合脚本。"""
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")


def _write(path, html):
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def _slice(key, kind, cn_d, math_d, en_d):
    """子页只拿自己那一份数据——页面小、打开快。"""
    if key == "chinese":
        books = sorted(cn_d["words"].keys())
        if kind == "literacy":
            return {"words": cn_d["words"], "word_kinds": cn_d["word_kinds"],
                    "books": books}
        if kind == "reading":
            return {"texts": [x for x in cn_d["texts"] if x["domain"] == "reading"],
                    "elements": cn_d["elements"], "authors": cn_d["authors"],
                    "books": books}
        if kind == "writing":
            return {"elements": cn_d["elements"], "authors": cn_d["authors"],
                    "texts": [x for x in cn_d["texts"] if x["domain"] == "writing"],
                    "books": books}
        if kind == "structure":
            return {"structures": cn_d["structures"], "genres": cn_d["genres"],
                    "books": books}
        return {"pieces": cn_d["pieces"], "books": books}
    if key == "math":
        books = sorted({u["book"] for u in math_d["units"]})
        units = math_d["units"] if kind == "all" else \
            [u for u in math_d["units"] if u["domain"] == kind]
        if kind == "problem":
            return {"problems": math_d["problems"], "keypoints": math_d["keypoints"],
                    "life": math_d["life"],
                    "books": sorted({p["book"] for p in math_d["problems"]})}
        d = {"domains": math_d["domains"], "units": units, "books": books}
        if kind == "all":
            d["measures"] = math_d["measures"]
        return d
    books = sorted({v["book"] for v in en_d["vocab"]})
    if kind == "speak":
        return {"dialogues": en_d["dialogues"], "projects": en_d["projects"],
                "exprs": en_d["exprs"], "functions": en_d["functions"],
                "books": sorted({d["book"] for d in en_d["dialogues"]})}
    keys = {"discourse": ["passages", "dialogues"], "vocab": ["vocab"],
            "grammar": ["grammar"], "phonics": ["phonics"],
            "use": ["songs", "projects", "revisions"]}
    d = {"books": books, "themes": en_d["themes"], "domains": en_d["domains"]}
    for k in keys.get(kind, []):
        d[k] = en_d[k]
    if kind != "vocab":
        d["vocab"] = en_d["vocab"]      # 册次/话题下拉与课文重点词用得上
    return d


def build_pages(out_dir: str = None, verbose: bool = True) -> dict:
    """生成整站。"""
    from . import anim      # 可选：Manim 动画（没渲染过就是空，不影响生成）

    out = out_dir or OUT_DIR
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    os.makedirs(os.path.join(out, "data"), exist_ok=True)
    if os.path.isdir(ASSETS_SRC):
        for fn in os.listdir(ASSETS_SRC):
            shutil.copy(os.path.join(ASSETS_SRC, fn), os.path.join(out, "assets", fn))

    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        math_d = build_math(con)
        math_d.update(build_problems(con))     # 解决问题（应用题）
        cn_d = build_chinese(con)
        cn_d.update(build_structures(con))     # 课文骨架
        en_d = build_english(con)
        en_d.update(build_speak(con))          # 开口说（对话/项目/常用表达）
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
<div class="card zh"><h3>语文</h3><p class="small">识字与写字、课文全文（带单元语文要素）、
表达与交流（习作要素）、古诗文（原文+注释+译文）。</p>
<a href="chinese/index.html">进入 →</a></div>
<div class="card ma"><h3>数学</h3><p class="small">按课标四大领域分页：数与代数、图形与几何、
统计与概率、综合与实践。每单元列出知识点、公式（真渲染）、例题（分步）与知识结构图。</p>
<a href="math/index.html">进入 →</a></div>
<div class="card en"><h3>英语</h3><p class="small">课文与语篇（中英对照可切换）、词汇（可自测）、
语法汇总（含时态线）、语音拼读、歌谣与项目任务。</p>
<a href="english/index.html">进入 →</a></div>
</div>""" % (
        stats["chinese"]["texts"], stats["chinese"]["elements"], stats["chinese"]["words"],
        stats["math"]["units"], stats["math"]["points"], stats["math"]["maps"],
        stats["english"]["vocab"], stats["english"]["grammar"],
        stats["english"]["phonics"], stats["english"]["songs"])

    _write(os.path.join(out, "index.html"), PAGE.format(
        title="总览", page="index", base="", subnav="", nav=_nav("index"),
        body=index_body, data=_esc({"stats": stats})))

    for key, name, pages in SUBJECTS:
        os.makedirs(os.path.join(out, key), exist_ok=True)
        for slug, title, kind, desc in pages:
            # 数学页额外挂 Manim 动画（渲染过才有，没渲染不影响页面）
            vids = anim.video_block(kind, out) if key == "math" else ""
            _write(os.path.join(out, key, slug + ".html"), PAGE.format(
                title="%s · %s" % (name, title), page="%s-%s" % (key, kind),
                base="../", nav=_nav(key, "../"), subnav=_subnav(slug, pages),
                body='<h2>%s · %s</h2><p class="lead">%s</p>%s'
                     % (name, title, desc, vids),
                data=_esc(_slice(key, kind, cn_d, math_d, en_d))))

    # 分页之前的单页文件不留，免得两套并存
    for f in ("chinese.html", "math.html", "english.html"):
        p = os.path.join(out, f)
        if os.path.exists(p):
            os.remove(p)

    if verbose:
        print("→ %s（总览 + 语文 %d 页 / 数学 %d 页 / 英语 %d 页）"
              % (out, len(CN_PAGES), len(MATH_PAGES), len(EN_PAGES)))
        print("   %s" % json.dumps(stats, ensure_ascii=False))
    return {"out": out, "stats": stats}
