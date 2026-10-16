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
import re
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


def _book_sort_key(book: str):
    """册次字符串 → 排序键：一年级上册 < 一年级下册 < 二年级上册 ……"""
    m = re.match(r"^(.*年级)(上册|下册)$", book or "")
    if m:
        return goals.key_of(m.group(1), m.group(2))
    return (99, 99)


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
            "sid": u["section_id"],
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
    # 数学每单元本体（LLM 补的算理/算法/易错/思想/联系）：挂上去，默认不显示
    mkb_path = os.path.join(config.ATTRS_DIR, "math_kb.jsonl")
    mkeep = ("stage", "topic", "standard", "why", "how", "traps", "ideas",
             "links")
    mkb = {}
    if os.path.exists(mkb_path):
        for line in open(mkb_path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("section_id"):
                mkb[r["section_id"]] = {k: r[k] for k in mkeep if r.get(k)}
    for u in out:
        if u.get("sid") and u["sid"] in mkb:
            u["kb"] = mkb[u["sid"]]
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
                          paragraphs,tasks,newchars,notes
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
            "id": r.get("lesson_id"),
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
            # 教材脚注（"①本文选自……"、"①作者……"），原样放在正文下面
            "notes": [n for n in _j(r.get("notes")) if n][:8],
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

    # 每课本体（LLM 补的外延知识）：挂上去，页面默认不显示，家长勾选才出来。
    # 教材里已有的（课文、课后题、生字、段意、中心）不重复带，只带补出来的部分。
    kb_path = os.path.join(config.ATTRS_DIR, "lesson_kb.jsonl")
    keep = ("stage", "standard", "recite", "words", "sentences", "methods",
            "questions", "polyphone", "notes", "background", "center", "exam",
            "traps", "accumulate", "extend", "transfer")
    kb = {}
    if os.path.exists(kb_path):
        for line in open(kb_path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("lesson_id"):
                kb[r["lesson_id"]] = {k: r[k] for k in keep if r.get(k)}
    for x in out:
        if x.get("id") and x["id"] in kb:
            x["kb"] = kb[x["id"]]

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
# unit_name 只是占位的 "Unit 3"，真实单元名（My friends）在该单元 section 的
# title 上；附录（Appendix/Revision/Recycle）没有 unit_no，单独归一类。
# 所以单元主键取 (book_id, unit_no)，单元号再回填给只带 unit_name 的子表。
RE_EN_PH = re.compile(r"^unit\s*\d+$", re.I)          # 占位名 Unit 3
RE_EN_APPENDIX = re.compile(r"^(appendix|revision|recycle)\b", re.I)


def _en_real_name(r):
    """单元真名：unit_name 若已是真名（Making friends）就用它，否则取 title。

    低年级两本书的 unit_name 就是真名，而 title 是单元核心问句
    （How do we make friends?），拿来当单元名会误导。
    """
    nm = (r.get("unit_name") or "").strip()
    tt = (r.get("title") or "").strip()
    for v in (nm, tt):
        if v and not RE_EN_PH.match(v) and not RE_EN_APPENDIX.match(v):
            return v
    return ""


def _en_unit_index(con):
    """英语单元规范表。

    返回 (by_section, names)：
      by_section[section_id] = (unit_no, 单元真名 / 附录栏目名)
      names[(book_id, unit_no)] = 单元真名
    """
    rows = _rows(con, """select section_id,book_id,unit_no,unit_name,title,page_from
                         from section_text where subject='英语'""")
    cand = {}
    for r in rows:
        if r.get("unit_no") is None:
            continue
        key = (r.get("book_id"), int(r["unit_no"]))
        nm = _en_real_name(r)
        old = cand.get(key)
        pg = r.get("page_from") or 0
        if nm and (not old or pg < old[0]):
            cand[key] = (pg, nm)
    names = {k: v[1] for k, v in cand.items()}
    by_sec = {}
    for r in rows:
        if not r.get("section_id"):
            continue
        if r.get("unit_no") is None:
            # 附录/复习没有单元号，用它的栏目名当标签（Songs、Words in each unit…）
            by_sec[r["section_id"]] = (None, _en_real_name(r) or
                                       (r.get("unit_name") or ""))
            continue
        key = (r.get("book_id"), int(r["unit_no"]))
        by_sec[r["section_id"]] = (int(r["unit_no"]),
                                   names.get(key) or (r.get("unit_name") or ""))
    return by_sec, names


def _en_unit_resolver(con):
    """把任意一行英语数据归范成 (unit_no, 单元真名)。"""
    by_sec, names = _en_unit_index(con)

    def resolve(r):
        info = by_sec.get(r.get("section_id") or "")
        if info:
            return info
        try:                              # en_song 的 unit_no 是字符串
            no = int(r.get("unit_no"))
        except (TypeError, ValueError):
            return (None, r.get("unit_name") or "")
        if not no:
            return (None, r.get("unit_name") or "")
        return (no, names.get((r.get("book_id"), no)) or ("Unit %d" % no))

    return resolve


def build_english(con) -> dict:
    resolve = _en_unit_resolver(con)

    def pick(table, cols):
        # unit_no / 单元真名要从母表反查，能取到的关联列都一并取出（附录表没有 section_id）
        have = {r[0] for r in con.execute(
            "select column_name from information_schema.columns where table_name='%s'"
            % table).fetchall()}
        c = [x for x in list(dict.fromkeys(
            list(cols) + ["section_id", "book_id"])) if x in have]
        return _rows(con, "select %s from %s where subject='英语'"
                     % (",".join(c), table))

    def base(r):
        no, nm = resolve(r)
        return {"grade": r["grade"], "term": r["term"], "book": _gt(r),
                "unit_no": no, "unit": nm}

    # 逐单元词表走 unit_no；书末字母序总表（source=vocab）没有单元，单列一类
    vocab = []
    for r in pick("en_vocab", ["grade", "term", "unit_no", "source", "word",
                               "phonetic", "meaning", "topic", "example"]):
        v = dict(base(r), word=r.get("word"), phonetic=r.get("phonetic"),
                 meaning=r.get("meaning"), topic=r.get("topic"),
                 example=r.get("example"), theme=goals.en_theme(r.get("topic")))
        if not v["unit_no"]:
            v["unit"] = "词汇总表" if r.get("source") == "vocab" else "（未标单元）"
        vocab.append(v)
    grammar = [dict(base(r), point=r.get("point"), pattern=r.get("pattern"),
                    rule=r.get("rule"), category=r.get("category"),
                    tense=r.get("tense"), examples=_j(r.get("examples"))[:8])
               for r in pick("en_grammar", ["grade", "term", "unit_name", "point",
                                            "pattern", "rule", "category", "tense",
                                            "examples"])]
    phonics = [dict(base(r), letters=r.get("letters"), sound=r.get("sound"),
                    examples=_j(r.get("examples"))[:8], chant=r.get("chant"))
               for r in pick("en_phonics", ["grade", "term", "unit_name", "letters",
                                            "sound", "examples", "chant"])]
    # 语篇即英语的"课文"：原文 + 译文 + 阅读理解题 + 重点词
    passages = [dict(base(r), name=r.get("name"), genre=r.get("genre"),
                     source=r.get("source"), text=(r.get("text") or "")[:2000],
                     zh=(r.get("zh") or "")[:2000], topic=r.get("topic"),
                     words=_j(r.get("words"))[:20],
                     comprehension=[c for c in _j(r.get("comprehension"))
                                    if isinstance(c, dict)][:8],
                     keypoints=_j(r.get("keypoints"))[:8],
                     writing=r.get("writing_task"))
                for r in pick("en_passage", ["grade", "term", "unit_name", "name",
                                             "genre", "source", "text", "zh", "topic",
                                             "words", "comprehension", "keypoints",
                                             "writing_task"])]
    dialogues = [dict(base(r), scene=r.get("scene"), function=r.get("function"),
                      patterns=_j(r.get("patterns"))[:6],
                      turns=_j(r.get("turns"))[:12])
                 for r in pick("en_dialogue", ["grade", "term", "unit_name", "scene",
                                               "function", "turns", "patterns"])]
    songs = [dict(base(r), name=r.get("song_title"),
                  lyrics=_j(r.get("lyrics"))[:30], topic=r.get("topic"))
             for r in pick("en_song", ["grade", "term", "unit_no", "song_title",
                                       "lyrics", "topic"])]
    projects = [dict(base(r), name=r.get("name"), type=r.get("type"),
                     goal=r.get("goal"), product=r.get("product"))
                for r in pick("en_project", ["grade", "term", "unit_name", "name",
                                             "type", "goal", "product"])]
    revisions = [{"grade": r["grade"], "term": r["term"], "book": _gt(r),
                  "unit": "复习", "theme": r.get("theme"),
                  "tasks": _j(r.get("tasks"))[:10], "outcome": r.get("outcome")}
                 for r in pick("en_revision", ["grade", "term", "theme", "tasks",
                                               "outcome"])]

    # 同一单元里的词汇、对话、短文、歌曲应共享 topic。先攒出单元 → topic 映射，
    # 再把对话/歌曲/项目/复习里缺失 topic 的补上——否则“按话题”筛选时，
    # 对话因为没有 topic 会被全部过滤掉，页面显示 0 课。
    unit_topic = {}
    for x in vocab + passages + dialogues + songs + projects + revisions:
        t = x.get("topic") or x.get("theme")
        if t:
            unit_topic[(x["grade"], x["term"], x.get("unit_no") or 0)] = t
    for x in dialogues + songs + projects + revisions:
        if x.get("topic") or x.get("theme"):
            continue
        t = unit_topic.get((x["grade"], x["term"], x.get("unit_no") or 0))
        if t:
            x["topic"] = t
            x["theme"] = goals.en_theme(t)

    # 课本顺序：册次 → 单元号（无单元号的附录/复习排在册末）
    def _ord(x):
        no = x.get("unit_no")
        return (goals.key_of(x["grade"], x["term"]), 0 if no else 1, no or 0,
                str(x.get("unit") or ""))

    for lst in (vocab, grammar, phonics, passages, dialogues, songs, projects,
                revisions):
        lst.sort(key=_ord)
    return {
        "domains": [{"key": d["key"], "name": d["name"], "desc": d["desc"]}
                    for d in goals.EN_DOMAINS],
        "vocab": vocab, "grammar": grammar, "phonics": phonics,
        "passages": passages, "dialogues": dialogues, "songs": songs,
        "projects": projects, "revisions": revisions,
        "themes": ["人与自我", "人与社会", "人与自然"],
    }


def _clean_reading_text(raw, limit=8000):
    """清洗 Gutenberg 纯文本：取 *** START / *** END 之间的正文。"""
    import re
    # 如果原始文件是 404 网页，直接返回空
    if re.search(r"404|Page Not Found|Not Found", raw[:500], re.I) and "<html" in raw[:500].lower():
        return ""
    # 优先找 *** START OF ... *** 和 *** END OF ... *** 标记
    start_pat = re.compile(r"\*\*\* *START OF.*?\*\*\*", re.I)
    end_pat = re.compile(r"\*\*\* *(END|FINIS).*?\*\*\*", re.I)
    m_start = start_pat.search(raw)
    m_end = end_pat.search(raw, m_start.end() if m_start else 0)
    if m_start:
        body = raw[m_start.end():]
        if m_end:
            body = body[:m_end.start() - m_start.end()]
    else:
        # 无标记：逐行跳过 # 元数据行、=== 分隔行、头部信息
        lines = raw.split("\n")
        out = []
        for line in lines:
            s = line.strip()
            if s.startswith("#") or s.startswith("==="):
                continue
            if s.startswith("Title:") or s.startswith("Author:"):
                continue
            if s.startswith("Release Date") or s.startswith("Language:"):
                continue
            out.append(line)
        body = "\n".join(out)
    # 如果正文是 HTML 网页（404 等），提取纯文本
    if re.search(r"<!DOCTYPE|<html|<body", body, re.I):
        # 去掉 <script> 和 <style> 块
        body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.I | re.S)
        body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.I | re.S)
        # 去掉所有 HTML 标签
        body = re.sub(r"<[^>]+>", "", body)
    # 折叠多余空行，去掉 BOM
    body = body.replace("\ufeff", "").strip()
    # 去掉正文开头的制作信息（第一个段落块如果含制作关键词则跳过）
    first_para = re.match(r"(.*?)(?:\n\n|\Z)", body, re.S)
    if first_para and re.search(r"(Produced by|Proofreading|Internet Archive|Transcriber|gutenberg|pgdp\.net)", first_para.group(1), re.I):
        body = body[first_para.end():].strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body[:limit] if len(body) > limit else body


def _load_readings():
    """长文库 catalog.json → 精简后供课外拓展页展示。"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "data", "readings", "catalog.json")
    if not os.path.exists(path):
        return []
    raw = json.load(open(path, encoding="utf-8"))
    texts_dir = os.path.join(os.path.dirname(path), "texts")
    out = []
    for b in raw.get("books", []):
        f = b.get("facets", {})
        bid = b.get("id", "")
        # 加载全文：清洗 Gutenberg 头尾元数据，截前 8000 字符
        text = ""
        tp = os.path.join(texts_dir, bid + ".txt")
        if os.path.exists(tp):
            with open(tp, encoding="utf-8", errors="replace") as fh:
                raw_txt = fh.read()
            text = _clean_reading_text(raw_txt, 8000)
        out.append({
            "id": bid, "title": b.get("title", ""),
            "author": b.get("author", ""),
            "primary_topic": b.get("primary_topic", ""),
            "secondary_topics": b.get("secondary_topics", []),
            "text": text,
            "facets": {
                "grade": f.get("grade", []), "grade_band": f.get("grade_band", ""),
                "text_type": f.get("text_type", ""),
                "themes": f.get("themes", []), "settings": f.get("settings", []),
                "word_count_bucket": f.get("word_count_bucket", ""),
                "lexile": f.get("lexile", {}),
                "cultural_origin": f.get("cultural_origin", ""),
                "time_period": f.get("time_period", ""),
                "target_skills": f.get("target_skills", []),
                "text_role": f.get("text_role", []),
            },
            "pairs_with_unit": b.get("pairs_with_unit", []),
        })
    return out


def _load_pairings():
    """data/readings/pairings.json → 精简双向挂载表（供卡片与反向入口共用）。"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "data", "readings", "pairings.json")
    if not os.path.exists(path):
        return []
    raw = json.load(open(path, encoding="utf-8"))
    out = []
    for p in raw.get("pairings", []):
        out.append({
            "reading_id": p.get("reading_id", ""),
            "reading_title": p.get("reading_title", ""),
            "section_id": p.get("section_id", ""),
            "unit_name": p.get("unit_name", ""),
            "unit_title": p.get("unit_title", ""),
            "grade": p.get("grade", ""),
            "term": p.get("term", ""),
            "role": p.get("role", ""),
            "match_score": p.get("match_score", 0),
            "reasons": (p.get("match_reasons") or [])[:3],
        })
    return out


def _load_unit_index():
    """data/outline/*.jsonl → {outline lesson_id: 单元定位信息}。

    单元数据存在 outline 的 meta + lesson 行里，教材前端（enText）用
    「册名 # 第N单元」做主键，而 pairings / catalog 用 outline 的 lesson_id
    （<book_id>:<seq>）。这里做一次对照，让课外拓展卡片能跳到正确单元。
    """
    import os, re
    od = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                      "data", "outline")
    if not os.path.isdir(od):
        return {}
    GRADENUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
                "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}
    def grnum(g):
        m = re.match(r"([一二三四五六])年级", g or "")
        return GRADENUM.get(m.group(1), 0) if m else 0
    idx = {}
    for fn in sorted(os.listdir(od)):
        if not fn.endswith(".jsonl"):
            continue
        path = os.path.join(od, fn)
        recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        meta = next((r for r in recs if r.get("type") == "meta"), None)
        if not meta:
            continue
        stage = meta.get("stage") or ""
        grade = meta.get("grade") or ""
        term = meta.get("term") or ""
        # 教材册名 = 年级 + 学期（如 三年级上册），与 vocab/passages 的 book 字段一致
        book = grade + term if (grade and term) else (meta.get("book_id") or "")[:8]
        for r in recs:
            if r.get("type") == "meta":
                continue
            nid = r.get("lesson_id") or ""
            if not nid:
                continue
            un = r.get("unit_no")
            idx[nid] = {
                "book": book,
                "unit_no": un,
                "unit_name": r.get("unit_name") or ("Unit " + str(un) if un else ""),
                "unit_title": r.get("title") or "",
                "grade": grade,
                "term": term,
                "printed_start": r.get("printed_start"),
                "gr": grnum(grade),
                "tt": 1 if "上" in term else (2 if "下" in term else 0),
                "vid": (meta.get("version") or "").replace("（", "("),
            }
    return idx


def _enrich_readings(readings, pairings, unit_index):
    """给每本课外书补 units（带教材单元定位信息）+ 反向索引。

    catalog 的 pairs_with_unit 与 pairings 的 section_id 合并去重，
    再用 outline 索引解析出年级/册名/单元名，让前端能显示与跳转。
    """
    pair_of = {}
    for p in pairings:
        pair_of.setdefault(p.get("section_id") or "", []).append(p)
    read_of = {}
    for p in pairings:
        read_of.setdefault(p.get("reading_id") or "", []).append(p)
    reverse = {}
    for b in readings:
        ids = []
        for sid in (b.get("pairs_with_unit") or []):
            if sid not in ids:
                ids.append(sid)
        for p in read_of.get(b.get("id") or "", []):
            sid = p.get("section_id") or ""
            if sid and sid not in ids:
                ids.append(sid)
        units = []
        seen = set()
        for sid in ids:
            u = dict(unit_index.get(sid) or {})
            pl = pair_of.get(sid, [])
            if pl:
                p0 = pl[0]
                u.setdefault("unit_title", p0.get("unit_title") or "")
                u.setdefault("unit_name", p0.get("unit_name") or "")
                u.setdefault("grade", p0.get("grade") or "")
                u.setdefault("term", p0.get("term") or "")
                u["role"] = p0.get("role") or ""
                u["match_score"] = p0.get("match_score") or 0
                u["reasons"] = (p0.get("match_reasons") or [])[:2]
            # 同一「册名#单元号」只留一条（一本书可能横跨同单元的多个 lesson_id）
            key = (u.get("book") or sid, u.get("unit_no"), u.get("unit_name"))
            if key in seen:
                continue
            seen.add(key)
            units.append(u)
        units.sort(key=lambda u: (u.get("gr") or 0, u.get("tt") or 0,
                                  u.get("unit_no") or 0))
        b["units"] = units
        b["pairs_with_unit"] = ids
        if units:
            reverse[b.get("id") or ""] = {
                "id": b.get("id") or "", "title": b.get("title") or "",
                "author": b.get("author") or "",
                "topic": b.get("primary_topic") or "",
            }
    by_unit = {}
    for rid, meta in reverse.items():
        for u in [x for x in readings if x.get("id") == rid][0]["units"]:
            if not u.get("book"):
                continue
            k = u["book"] + "#U" + str(u.get("unit_no") or 0)
            lst = by_unit.setdefault(k, [])
            # 同一单元下同一本书只挂一次（一本书可能横跨同单元的多个 lesson_id）
            if not any(m.get("id") == meta.get("id") for m in lst):
                lst.append(meta)
    for k in by_unit:
        by_unit[k].sort(key=lambda m: m.get("title") or "")
    return by_unit, reverse


def _load_picturebooks():
    """绘本 books.json → 精简后供课外拓展页展示。"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "data", "picturebooks", "books.json")
    if not os.path.exists(path):
        return []
    raw = json.load(open(path, encoding="utf-8"))
    out = []
    for b in raw.get("books", []):
        f = b.get("facets", {})
        pages = b.get("pages", [])
        out.append({
            "id": b.get("id", ""), "title": b.get("title", ""),
            "author": b.get("author", ""), "level": b.get("level", ""),
            "primary_topic": b.get("primary_topic", ""),
            "secondary_topics": b.get("secondary_topics", []),
            "word_count": b.get("word_count", 0),
            "reading_time_min": b.get("reading_time_min", 0),
            "facets": {
                "grade": f.get("grade", []), "grade_band": f.get("grade_band", ""),
                "text_type": f.get("text_type", ""),
                "themes": f.get("themes", []), "settings": f.get("settings", []),
                "word_count_bucket": f.get("word_count_bucket", ""),
                "lexile": f.get("lexile", {}),
                "cultural_origin": f.get("cultural_origin", ""),
                "time_period": f.get("time_period", ""),
                "target_skills": f.get("target_skills", []),
                "text_role": f.get("text_role", []),
            },
            "pages": [{"n": p.get("n"), "text": p.get("text", "")}
                      for p in pages[:20]],
        })
    return out


def _writing_data():
    """英语写作教学数据：流程/六要素/文体/句型/连接词/检查表/练习。"""
    return {
        "process": [
            {"step": 1, "en": "Prewriting", "zh": "构思",
             "desc": "想清楚写什么、给谁看。用思维导图、关键词、提问列出想法。",
             "tips": ["Who/What/When/Where/Why", "画思维导图", "列关键词"]},
            {"step": 2, "en": "Drafting", "zh": "起草",
             "desc": "先把想法写下来，不停笔修改。先求完整，不求完美。",
             "tips": ["不停顿写完第一稿", "不会的词先空着或用中文", "写够字数再改"]},
            {"step": 3, "en": "Revising", "zh": "修改",
             "desc": "看内容与结构：顺序对不对？有没有多余的句子？开头结尾好不好？",
             "tips": ["朗读自己的文章", "删掉重复的句子", "加连接词让更流畅"]},
            {"step": 4, "en": "Editing", "zh": "校对",
             "desc": "检查拼写、标点、大小写、语法。逐句检查，不放过小错误。",
             "tips": ["检查大小写与句号", "拼写逐词核对", "时态是否一致"]},
            {"step": 5, "en": "Publishing", "zh": "发表",
             "desc": "工整誊抄或打字排版，加上标题，分享给同学或家人。",
             "tips": ["标题居中加粗", "段落缩进", "分享给家人读"]}
        ],
        "traits": [
            {"en": "Ideas", "zh": "思路", "icon": "💡",
             "desc": "文章有没有一个明确的主意？细节是否支撑主旨？",
             "check": ["我知道我要写什么", "每个段落都围绕主旨"]},
            {"en": "Organization", "zh": "结构", "icon": "🏗",
             "desc": "开头吸引人吗？中间有条理吗？结尾有总结吗？",
             "check": ["开头引人入胜", "段落有逻辑顺序", "结尾呼应开头"]},
            {"en": "Voice", "zh": "语气", "icon": "🎭",
             "desc": "读起来像谁在说话？正式还是活泼？适合读者吗？",
             "check": ["语气适合读者", "能感觉到作者的情感"]},
            {"en": "Word Choice", "zh": "选词", "icon": "✏",
             "desc": "用词准确吗？有没有重复？能不能换更好的词？",
             "check": ["不用太多very/good/nice", "动词具体", "形容词生动"]},
            {"en": "Sentence Fluency", "zh": "句子流畅", "icon": "🌊",
             "desc": "句子长短搭配吗？读起来顺口吗？有没有太多流水句？",
             "check": ["长短句搭配", "没有Run-on句", "开头不总是I/The"]},
            {"en": "Conventions", "zh": "规范", "icon": "✓",
             "desc": "拼写、标点、大小写、语法是否正确？",
             "check": ["拼写正确", "标点用对", "主谓一致"]},
            {"en": "Presentation", "zh": "呈现", "icon": "🎨",
             "desc": "文章的版面和样子：标题、分段、字迹、插图、排版是否美观清楚？",
             "check": ["有醒目的标题", "段落有缩进", "字迹/排版整齐", "有需要时配插图"]}
        ],
        "genres": [
            {"en": "Narrative", "zh": "叙事", "icon": "📖",
             "structure": ["开头：交代时间、地点、人物", "中间：发生了什么（按顺序）", "结尾：结果或感受"],
             "frames": ["One day, ...", "Suddenly, ...", "Finally, ...", "In the end, ..."],
             "example": "Last Sunday, I went to the park with my family. We played games and had a picnic. I felt very happy.",
             "sample": "A Lucky Day on the Way to School\nLast Monday, I walked to school with my friend Ben. On the way, we saw a little dog sitting under a tree. It looked sad and hungry. We shared our bread with it and it ate quickly. Then the dog followed us to school. The teacher was surprised, but she smiled. We named the dog Lucky. At the end of the day, a kind lady came and took Lucky home. Ben and I were happy that we could help. That day, we learned that helping others makes us happy."},
            {"en": "Descriptive", "zh": "描写", "icon": "🎨",
             "structure": ["整体印象", "细节描写（看/听/闻/触）", "感受总结"],
             "frames": ["It looks like ...", "I can see ...", "It smells like ...", "It makes me feel ..."],
             "example": "My bedroom is small but cozy. The walls are light blue. There is a big window near my bed. I can hear birds singing every morning.",
             "sample": "My Kitchen Garden\nAt the back of our house, there is a small kitchen garden. It is green and full of life. In the morning, I can see sunflowers turning their heads to the sun. I can hear bees buzzing around the flowers. When I touch the grass, it is soft and wet with dew. The tomatoes smell fresh and sweet. Sitting there, I feel calm and happy. This little garden is my favourite place at home."},
            {"en": "Expository", "zh": "说明", "icon": "📋",
             "structure": ["主题句：说明什么", "事实/步骤/原因", "总结句"],
             "frames": ["First, ...", "Second, ...", "Also, ...", "In conclusion, ..."],
             "example": "There are three things I do every morning. First, I brush my teeth. Second, I eat breakfast. Also, I read a book for ten minutes.",
             "sample": "How to Keep My Desk Clean\nKeeping my desk clean is easy if I follow three steps. First, I put my books back on the shelf after I read them. Second, I put the pencils and erasers into my pencil case every evening. Also, I use a small box for my toys so they do not cover the desk. In conclusion, a clean desk helps me study better and find things quickly."},
            {"en": "Persuasive", "zh": "议论", "icon": "💬",
             "structure": ["观点：我认为……", "理由1 + 例子", "理由2 + 例子", "号召行动"],
             "frames": ["I think ... because ...", "For example, ...", "Another reason is ...", "You should ..."],
             "example": "I think students should have more PE classes. First, exercise keeps us healthy. Second, sports help us make friends. You should play sports every day!",
             "sample": "We Should Read More Books\nI think every student should read more books. First, reading helps us learn new words and make our sentences better. For example, I learned many new words from a storybook. Second, reading is a fun way to rest after playing. Another reason is that a book can take us to faraway places without leaving home. You should try reading ten minutes every day!"},
            {"en": "Letter/Email", "zh": "书信", "icon": "✉",
             "structure": ["称呼 (Dear ...)", "正文：写什么事", "结尾问候 (Best wishes,)", "署名"],
             "frames": ["Dear ...,", "How are you?", "I am writing to ...", "Best wishes,", "Yours, ..."],
             "example": "Dear Tom,\nHow are you? I am writing to invite you to my birthday party. It is on Saturday at 3 pm. I hope you can come!\nBest wishes,\nLi Ming",
             "sample": "A Thank-you Letter\nDear Grandma,\nThank you for the red gloves you sent me. They are warm and beautiful, and I wear them every day to school. The weather is getting cold here, so your gloves really help. I also love the drawings on them. I am writing to say thank you from my heart. Please come to visit us soon!\nLove,\nAmy"}
        ],
        "transitions": [
            {"cat": "顺序", "zh": "Sequence", "words": ["first", "then", "next", "after that", "finally", "in the end"]},
            {"cat": "补充", "zh": "Addition", "words": ["also", "too", "and", "besides", "what's more", "in addition"]},
            {"cat": "对比", "zh": "Contrast", "words": ["but", "however", "although", "on the other hand", "while", "whereas"]},
            {"cat": "因果", "zh": "Cause & Effect", "words": ["because", "so", "therefore", "as a result", "since", "due to"]},
            {"cat": "举例", "zh": "Example", "words": ["for example", "for instance", "such as", "like", "namely"]},
            {"cat": "总结", "zh": "Conclusion", "words": ["in conclusion", "to sum up", "in short", "all in all", "overall"]}
        ],
        "conventions": [
            {"topic": "大写", "icon": "🔠",
             "rules": ["句子开头第一个字母要大写", "专有名词要大写（人名、地名、星期、月份）", "人称代词 I 永远大写", "书名/标题的重要单词首字母大写"],
             "example": "✓ My name is Lily.   ✗ my name is lily."},
            {"topic": "标点", "icon": "❓",
             "rules": ["陈述句结尾用 .", "疑问句结尾用 ?", "表达强烈情感用 !", "人名/地名字用逗号隔开（Dear Tom,）"],
             "example": "✓ Are you ready?   ✗ Are you ready."},
            {"topic": "拼写", "icon": "🔤",
             "rules": ["先写完整再改拼写，别为修改打断思路", "写完逐词核对，用词典或朗读检查", "注意易混词：there / their / they're", "名词变复数别漏 s 或 es"],
             "example": "✓ there is a book   ✗ their is a book"},
            {"topic": "时态一致", "icon": "⏰",
             "rules": ["同一件事不要一会儿现在时一会儿过去时", "现在经常发生用一般现在时", "上星期做的用一般过去时", "将来打算用 be going to / will"],
             "example": "✓ Yesterday I went to the park.   ✗ Yesterday I go to the park."},
            {"topic": "句子完整", "icon": "🧩",
             "rules": ["每个句子都要有主语和谓语", "不要写半边句子（Fragment）", "不要一句话没写完就换行", "学会用 and / but / so 连接",
              "例：把 I like dogs. They are cute. 连成 I like dogs because they are cute."],
             "example": "✓ I like dogs because they are cute.   ✗ Dogs. Because cute."}
        ],
        "grade_guide": [
            {"grade": "一二年级", "icon": "🌱",
             "goal": "能写 3-5 个单词组成的简单句子", "length": "20-30 词",
             "tips": ["会用 I like ... / I can ... 开头", "大写和句号正确", "看图写 1 句话", "抄写并工整誊写"],
             "focus": "句子 → 简单书写"},
            {"grade": "三年级", "icon": "🌿",
             "goal": "能写 2-3 句连贯的简单句", "length": "30-50 词",
             "tips": ["会给句子加 and / but", "按时间顺序写小事件", "学会问答式写作", "会写贺卡和简单信件"],
             "focus": "段落雏形 → 书信"},
            {"grade": "四年级", "icon": "🌲",
             "goal": "能写 3-5 句的小段落", "length": "50-80 词",
             "tips": ["有主题句和结尾", "按 First/Second 写步骤", "描写用感官词", "用连接词使句子连贯"],
             "focus": "完整段落 → 说明"},
            {"grade": "五年级", "icon": "🌳",
             "goal": "能写多段落短文", "length": "80-120 词",
             "tips": ["段落有结构（开头-中间-结尾）", "学会议论：观点+理由", "会写叙事故事", "检查表自查"],
             "focus": "多段落 → 叙事/议论"},
            {"grade": "六年级", "icon": "🏆",
             "goal": "能写审题清晰、结构完整的短文", "length": "120-160 词",
             "tips": ["审题：看清要求再写", "综合运用连接词与句型", "会用 there be / 比较级", "发表前做 Presentation 呈现"],
             "focus": "审题立意 → 完整写作"}
        ],
        "sentence_frames": [
            {"level": "简单句", "en": "Simple", "color": "#e8f5e9",
             "frames": ["I like ___.", "He is ___.", "She can ___.", "They have ___.", "We went to ___."]},
            {"level": "并列句", "en": "Compound", "color": "#e3f2fd",
             "frames": ["I like ___, and he likes ___.", "She is tired, but she keeps going.", "We can go now, or we can wait.", "I was hungry, so I ate an apple."]},
            {"level": "复合句", "en": "Complex", "color": "#fff3e0",
             "frames": ["When I ___, I ___.", "Because ___, ___.", "If ___, ___.", "Although ___, ___."]}
        ],
        "checklist": [
            {"item": "我的文章有标题", "cat": "结构"},
            {"item": "每个段落只有一个主题", "cat": "结构"},
            {"item": "开头能吸引读者", "cat": "结构"},
            {"item": "结尾有总结或感受", "cat": "结构"},
            {"item": "用了连接词让句子更流畅", "cat": "流畅"},
            {"item": "没有太多重复的词", "cat": "选词"},
            {"item": "动词用了具体词", "cat": "选词"},
            {"item": "句子长短搭配", "cat": "流畅"},
            {"item": "拼写都正确", "cat": "规范"},
            {"item": "标点符号用对了", "cat": "规范"},
            {"item": "大小写正确", "cat": "规范"},
            {"item": "时态前后一致", "cat": "规范"}
        ],
        "prompts": [
            {"type": "看图写话", "en": "Picture Description", "zh": "看图写 5 句话，描述你在图中看到了什么。", "min_words": 30},
            {"type": "续写", "en": "Story Continuation", "zh": "It was a rainy day. Suddenly, I heard a strange sound... 续写这个故事。", "min_words": 50},
            {"type": "仿写", "en": "Imitation", "zh": "仿写一篇 My Family 短文，介绍你的家庭（参照课文体裁）。", "min_words": 40},
            {"type": "书信", "en": "Letter", "zh": "给你的好朋友写一封信，邀请他/她来你家玩。", "min_words": 50},
            {"type": "议论", "en": "Opinion", "zh": "你认为小学生应该有作业吗？写出你的观点和理由。", "min_words": 40},
            {"type": "描写", "en": "Description", "zh": "描写你最喜欢的地方（教室、公园、房间……），至少用 3 个感官词。", "min_words": 40},
            {"type": "自由写作", "en": "Free Writing", "zh": "写任何你想写的话题，写满 5 分钟不停笔。", "min_words": 60}
        ],
        "creative": [
            {"cat": "创意写作工坊", "icon": "🎭",
             "items": [
                 {"name": "看图写话", "en": "Picture Story", "desc": "看图先说出 5 个看到的名词，再加动作词，连成一个小故事。",
                  "frames": ["I can see ___.", "There is a ___.", "The ___ is ___-ing.", "Suddenly, ___.", "In the end, ___."],
                  "example": "I can see a boy and a dog. The dog is running. Suddenly, it stops and looks at me. In the end, we play together."},
                 {"name": "故事续写", "en": "Story Extension", "desc": "给你一个开头，接着往下编，加入新角色和转折。",
                  "frames": ["Then ___.", "After that, ___.", "But suddenly, ___.", "Finally, ___."],
                  "example": "It was raining. Then the door opened. A tiny fox walked in. But suddenly, it spoke: 'Help me!' Finally, we became friends."},
                 {"name": "五感描写", "en": "Five Senses", "desc": "用看/听/闻/尝/触摸五种感觉写同一个地方。",
                  "frames": ["I can see ___.", "I can hear ___.", "It smells like ___.", "It tastes like ___.", "It feels ___-ing."],
                  "example": "I can see a market. I can hear people talking. It smells like fresh bread. The juice tastes sweet. The fruit feels smooth."},
                 {"name": "广告海报", "en": "Poster Ad", "desc": "为一样东西写一小段广告，把它的好处说得让人心动。",
                  "frames": ["Come and try ___.", "It is ___.", "You will love it because ___.", "Don't miss it!", "Price: ___"],
                   "example": "Come and try my magic eraser! It is small and cheap. You will love it because it cleans anything. Don't miss it!"},
                 {"name": "漫画对话", "en": "Comic Talk", "desc": "写两人对话，句子短、带情绪，读起来像漫画。",
                  "frames": ["\"Hi!\" said ___.", "\"Let's ___.\"", "\"Oh no! ___\"", "\"Haha, good idea!\""],
                  "example": "\"Hi!\" said Tom. \"Let's fly a kite!\" \"Oh no! The kite is stuck!\" \"Don't worry. I have a ladder.\" \"Haha, good idea!\""}
             ]},
            {"cat": "写作小游戏", "icon": "🎲",
             "items": [
                 {"name": "故事接龙", "en": "Story Chain", "desc": "几个人轮流每人加一句，故事会越编越离奇。",
                  "frames": ["Once ___.", "Then ___.", "But ___.", "And then ___.", "At last ___."],
                  "example": "Once a cat wore shoes. Then it rode a bike. But it fell into a pond. And then a fish helped it up. At last they became friends."},
                 {"name": "骰子造句", "en": "Dice Sentences", "desc": "掷骰子选 谁/在哪里/做什么，拼出一个滑稽句子。",
                  "frames": ["___ (谁) ___ (在哪里) ___ (做什么).", "Suddenly, ___ (谁) ___ (做什么)."],
                  "example": "A penguin in the kitchen sings a song. Suddenly, the penguin dances on the table."},
                 {"name": "词云成篇", "en": "Word Cloud", "desc": "先圈 6-8 个词，再用一句话把它们全部用进去。",
                  "frames": ["Today, I saw ___, ___, and ___ at ___.", "___ made me feel ___, so I ___."],
                  "example": "Today, I saw a kite, an apple, and a dragonfly at the park. The dragonfly made me feel happy, so I ran after it."},
                 {"name": "换头换尾", "en": "Swap Ending", "desc": "给一个老故事换一个新结尾，或者把主角换成动物。",
                  "frames": ["Long ago, ___ was the hero.", "But this time, the ending was different: ___."],
                  "example": "Long ago, a rabbit was the hero. But this time, the ending was different: the rabbit became a king!"}
             ]},
            {"cat": "诗歌与押韵", "icon": "🎵",
             "items": [
                 {"name": "押韵小诗", "en": "Rhyming Poem", "desc": "选一组押韵词（cat/bat、moon/soon）写 2-4 行小诗。",
                  "frames": ["___ at ___", "And the ___ goes ___", "___ in the ___, / ___ and ___", "The ___ / makes us ___"],
                  "example": "The cat sat on the mat. It chased a bat with a hat. The bat flew high, away to the sky. The cat said bye bye."},
                 {"name": "俳句", "en": "Haiku", "desc": "日本短诗：三行，音节 5-7-5，写一处自然画面。",
                  "frames": ["Line1 (5): ___ ___ ___ ___ ___", "Line2 (7): ___ ___ ___ ___ ___ ___ ___", "Line3 (5): ___ ___ ___ ___ ___"],
                  "example": "Spring rain falls softly (5) / On the green leaves of the tree (7) / A bird starts to sing (5)."},
                 {"name": "藏头诗", "en": "Acrostic", "desc": "把名字竖着写，每行以字母开头写一句。",
                  "frames": ["S: ___", "U: ___", "N: ___", "..."],
                  "example": "S: Summer brings sunshine. U: Under the trees we play. N: Night comes, we say goodbye."},
                 {"name": "声音词诗", "en": "Onomatopoeia", "desc": "多用哗啦/叮咚/汪汪这类声音词，让诗「响」起来。",
                  "frames": ["___ sounds ___", "___ goes ___", "All day, ___ and ___"],
                  "example": "The rain goes drip drip. The bell goes ding dong. The dog says woof woof. All day we sing a noisy song."}
             ]},
            {"cat": "分话题创意提示库", "icon": "💡",
             "items": [
                 {"name": "旅行奇遇", "en": "Travel", "desc": "想象出发去一个没去过的地方。",
                  "frames": ["I packed my bag with ___ and ___.", "When I arrived, I saw ___.", "The best part was ___."],
                  "example": "I packed my bag with cookies and a map. When I arrived at the moon, I saw a green rabbit. The best part was hopping over craters."},
                 {"name": "如果动物会说话", "en": "Talking Animals", "desc": "选一个你喜欢的小动物，写它第一天上学的故事。",
                  "frames": ["I am a ___.", "On my first day, I met ___.", "We learned to ___."],
                  "example": "I am a little duck. On my first day, I met a shy turtle. We learned to quack and swim together."},
                 {"name": "梦想的职业", "en": "Dream Job", "desc": "写长大后想做什么，为什么，会怎样帮助别人。",
                  "frames": ["When I grow up, I want to ___.", "Because ___.", "I will help ___."],
                  "example": "When I grow up, I want to be a doctor. Because I can make sick kids feel better. I will help every child smile again."},
                 {"name": "我的秘密基地", "en": "Secret Base", "desc": "写一个只有你知道的秘密角落，说清它长什么样。",
                  "frames": ["My secret base is ___.", "It looks like ___.", "Only __ knows it.", "I go there when ___."],
                  "example": "My secret base is under the big oak tree. It looks like a tent made of leaves. Only my cat knows it. I go there when I want to read."}
             ]}
        ]
    }


def _load_taxonomy():
    """taxonomy.json 的分面定义 → 供 UI 渲染筛选项标签。"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "data", "readings", "taxonomy.json")
    if not os.path.exists(path):
        return {}
    raw = json.load(open(path, encoding="utf-8"))
    dims = raw.get("dimensions", {})
    # 精简：只保留 UI 需要的 label 映射
    out = {}
    for k, v in dims.items():
        if v.get("type") == "single_enum" and isinstance(v.get("values"), dict):
            out[k] = {"label": v.get("description", k),
                      "values": {kk: vv for kk, vv in v["values"].items()}}
        elif v.get("type") == "single_enum" and isinstance(v.get("values"), list):
            out[k] = {"label": v.get("description", k), "values": v["values"]}
        elif v.get("type") == "multi_enum" and isinstance(v.get("values"), dict):
            out[k] = {"label": v.get("description", k),
                      "values": {kk: vv for kk, vv in v["values"].items()}}
        elif v.get("type") == "multi_enum" and isinstance(v.get("values"), list):
            out[k] = {"label": v.get("description", k), "values": v["values"]}
        elif v.get("type") == "range" and "bands" in v:
            out[k] = {"label": v.get("description", k),
                      "values": {kk: vv.get("grade_hint", kk)
                                 for kk, vv in v["bands"].items()}}
    return out


def build_speak(con) -> dict:
    """开口说：情境对话（分角色、逐句带中文）+ 常用表达 + 项目任务。

    "哑巴英语"的根子不是单词量，是没地方说。教材里每组对话本来就有角色、
    有场景、有功能，这里按角色摊开：可以一句一句推进，可以遮住中文自测，
    项目任务则给出"做出一样东西"的完整清单（用到哪句话、需要什么材料）。
    """
    # 单元号与真名同样走规范表：这条路径的 dialogues 才是站点实际用的那份
    resolve = _en_unit_resolver(con)
    dlg = []
    for r in _rows(con, """select grade,term,unit_name,title,scene,function,turns,
                           patterns,section_id,book_id from en_dialogue
                           where subject='英语'"""):
        turns = [t for t in _j(r.get("turns")) if isinstance(t, dict)]
        if not turns:
            continue
        no, unit = resolve(r)
        dlg.append({
            "book": _gt(r), "grade": r.get("grade"), "term": r.get("term"),
            "unit_no": no, "unit": unit, "title": r.get("title"),
            "scene": r.get("scene"), "function": r.get("function"),
            "patterns": [str(p) for p in _j(r.get("patterns"))][:8],
            "turns": [{"s": t.get("speaker"), "speaker": t.get("speaker"),
                       "en": t.get("en"), "zh": t.get("zh")} for t in turns],
        })
    prj = []
    for r in _rows(con, """select grade,term,unit_name,name,type,goal,steps,language,
                           product,materials,section_id,book_id from en_project
                           where subject='英语'"""):
        no, unit = resolve(r)
        prj.append({
            "book": _gt(r), "grade": r.get("grade"), "term": r.get("term"),
            "unit_no": no, "unit": unit, "name": r.get("name"),
            "type": r.get("type"), "goal": r.get("goal"),
            "steps": [str(s) for s in _j(r.get("steps"))][:8],
            "language": [str(s) for s in _j(r.get("language"))][:8],
            "product": r.get("product"),
            "materials": [str(s) for s in _j(r.get("materials"))][:8],
        })
    expr = []
    for r in _rows(con, """select grade,term,unit_no,en,zh,book_id from en_expr
                           where subject='英语'"""):
        if r.get("en"):
            no, unit = resolve(r)
            expr.append({"book": _gt(r), "grade": r.get("grade"),
                         "term": r.get("term"), "unit_no": no, "unit": unit,
                         "en": r.get("en"), "zh": r.get("zh")})

    # 给开口说里的对话补上单元 topic：站点最终用的是这份 dialogues，
    # 如果不补 topic，英语“课文与语篇”页按话题筛选时对话会全丢。
    unit_topic = {}
    for r in _rows(con, "select grade,term,unit_no,topic from en_vocab "
                     "where subject='英语' and topic is not null"):
        unit_topic[(r["grade"], r["term"], r.get("unit_no") or 0)] = r["topic"]
    for r in _rows(con, "select grade,term,unit_name,topic from en_passage "
                     "where subject='英语' and topic is not null"):
        no, _ = resolve(r)
        unit_topic[(r["grade"], r["term"], no or 0)] = r["topic"]
    for r in _rows(con, "select grade,term,unit_no,topic from en_song "
                     "where subject='英语' and topic is not null"):
        unit_topic[(r["grade"], r["term"], r.get("unit_no") or 0)] = r["topic"]
    for d in dlg:
        if d.get("topic") or not d.get("unit_no"):
            continue
        t = unit_topic.get((d["grade"], d["term"], d["unit_no"]))
        if t:
            d["topic"] = t
            d["theme"] = goals.en_theme(t)

    # 课本顺序：册次 → 单元号（无单元号的附录/复习排在册末）
    def _ord(x):
        no = x.get("unit_no")
        return (goals.key_of(x.get("grade"), x.get("term")), 0 if no else 1,
                no or 0, str(x.get("unit") or ""))

    for lst in (dlg, prj, expr):
        lst.sort(key=_ord)
    fs = {}
    for d in dlg:
        if d["function"]:
            fs[d["function"]] = fs.get(d["function"], 0) + 1
    return {"dialogues": dlg, "projects": prj, "exprs": expr,
            "functions": sorted(fs.items(), key=lambda x: (-x[1], x[0]))}


# ------------------------------------------------------------------ 页面
# 各科再分页：一页只做一件事——单页小、加载快、看得清
CN_PAGES = [
    ("index", "课文全文", "reading",
     "这一页可以当课本用：按册 → 单元 → 课，教材顺序一条不落。"
     "每一课保留教材原有内容——课文正文、本课生字、课后题、作者与注释；"
     "单元头上印着这一单元的语文要素（读的时候练什么）。"
     "页首有课文目录，点目录直达课文，可按册筛选、按标题/作者/正文搜索，"
     "点「读全文」展开课文与课后题、本课生字。"),
    ("literacy", "识字与写字", "literacy",
     "按册列出识字表、写字表、词语表，带拼音。字词靠查表，不靠讲解；点一个字看它的拼音。"),
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
    ("index", "课本单元", "all",
     "这一页可以当课本用：按册 → 单元，教材顺序排下来。每个单元保留教材原有内容——"
     "课本原文、例题（题干 → 分步 → 答案）、公式（真渲染）、知识点与知识结构图；"
     "领域页签来自 2022 版课标四大领域。"),
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
     "每一课都是一个学习中心：课文默认折叠，点开就是预习、音标、自然拼读、语法、"
     "练习、小游戏、复习自评与课外拓展。情景对话逐句分行（角色、原文、中文可遮住自测），"
     "短文原文 + 译文 + 重点词 + 理解题一并给出；点右上角“中文对照”切换译文。"),
    ("vocab", "词汇", "vocab",
     "按话题成串收录，带音标与例句；点单词才出中文（自测），另有听写练习。"),
    ("grammar", "语法汇总", "grammar",
     "按范畴汇总，附“哪一册学了什么时态”的时态线，句型里可替换处高亮。"),
    ("phonics", "语音拼读", "phonics", "字母与字母组合的发音：见词能读、听音能写。"),
    ("use", "综合运用", "use", "歌谣、项目任务与复习板块。"),
    ("speak", "开口说", "speak",
     "教材里每一组对话按角色摊开，一句一句推进；中文可遮住自测。"
     "另有项目任务：做出一样东西要说什么、要什么材料。敢开口，从有话可说开始。"),
    ("dictation", "听写练习", "dictation",
     "三种模式：拼写听写（看中文/音标听发音拼写）、句子听写（听整句照听打下来）、"
     "短文填空（读短文听发音填关键词）。支持按册次/单元/话题/难度筛选，10 题一组，"
     "错题保留在右侧错题本，方便回头重做。"),
    ("extra", "课外拓展", "extra",
     "教材之外的同主题阅读：按话题串起来，短文配译文与朗读，"
     "对话配情景与功能。想多读几篇同一个话题的，来这里。"),
    ("writing", "英语写作", "writing",
     "从构思到发表的完整写作流程：六要素（思路/结构/语气/选词/句子/规范）、"
     "文体类型（叙事/描写/说明/议论/书信）、句型支架与连接词、教材范文拆解、"
     "看图写话与仿写练习。配合写作检查表，一步步把想法变成文章。"),
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


def build_lesson_hubs(en_d):
    """课文与语篇页的「每课学习中心」单元级配套数据。

    按 (book#U{unit_no}) 聚合：
      grammar  —— 本单元语法条目（句型/规则/例句，瘦字段）
      phonics  —— 本单元自然拼读（字母组合/发音/例词）
      projects —— 本单元项目任务（课外拓展用）
    按册聚合：
      songs    —— 歌谣大多只标到册（unit="Songs"），挂到同册每个单元
    前端键与 app.js 的 slot() 主键保持一致：book + "#" + ("U"+unit_no or unit)。
    """
    def ukey(x):
        return (x.get("book") or "") + "#" + (
            "U" + str(x["unit_no"]) if x.get("unit_no") else (x.get("unit") or ""))

    # 入库时部分单元被重复导入过（同一 (letters,sound) / point 出现 2~3 份），
    # 展示层按内容指纹去重，学习中心才不至于一屏翻三遍同一页。
    units = {}
    seen = {}
    def slot(k):
        return units.setdefault(k, {"grammar": [], "phonics": [], "projects": []})

    for g in en_d.get("grammar", []):
        if not g.get("unit_no"):
            continue
        fingerprint = (g.get("point") or "").strip().lower()
        if not fingerprint:
            continue
        key = (ukey(g), fingerprint)
        if seen.get(key):
            continue
        seen[key] = 1
        slot(ukey(g))["grammar"].append({
            "point": g.get("point") or "",
            "pattern": g.get("pattern") or "",
            "rule": g.get("rule") or "",
            "examples": [{"en": e.get("en") or "", "zh": e.get("zh") or ""}
                         for e in (g.get("examples") or [])[:3]],
        })
    for p in en_d.get("phonics", []):
        if not p.get("unit_no"):
            continue
        fingerprint = ((p.get("letters") or "").strip() + "|" +
                       (p.get("sound") or "").strip()).lower()
        key = (ukey(p), fingerprint)
        if seen.get(key):
            continue
        seen[key] = 1
        slot(ukey(p))["phonics"].append({
            "letters": p.get("letters") or "",
            "sound": p.get("sound") or "",
            "examples": [w for w in dict.fromkeys(p.get("examples") or [])][:8],
            "chant": p.get("chant") or "",
        })
    for p in en_d.get("projects", []):
        if not p.get("unit_no"):
            continue
        fingerprint = (p.get("name") or "").strip().lower()
        if not fingerprint:
            continue
        key = (ukey(p), fingerprint)
        if seen.get(key):
            continue
        seen[key] = 1
        slot(ukey(p))["projects"].append({
            "name": p.get("name") or "",
            "type": p.get("type") or "",
            "goal": p.get("goal") or "",
            "steps": (p.get("steps") or [])[:6],
            "language": (p.get("language") or [])[:8],
            "product": p.get("product") or "",
        })

    songs = {}
    for s in en_d.get("songs", []):
        book = s.get("book") or ""
        if not book:
            continue
        songs.setdefault(book, []).append({
            "name": s.get("name") or "",
            "lyrics": (s.get("lyrics") or [])[:12],
            "topic": s.get("topic") or "",
        })
    return {"units": units, "songs": songs}


def _slice(key, kind, cn_d, math_d, en_d):
    """子页只拿自己那一份数据——页面小、打开快。"""
    if key == "chinese":
        books = sorted(cn_d["words"].keys(), key=_book_sort_key)
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
        books = sorted({u["book"] for u in math_d["units"]}, key=_book_sort_key)
        units = math_d["units"] if kind == "all" else \
            [u for u in math_d["units"] if u["domain"] == kind]
        if kind == "problem":
            return {"problems": math_d["problems"], "keypoints": math_d["keypoints"],
                    "life": math_d["life"],
                    "books": sorted({p["book"] for p in math_d["problems"]}, key=_book_sort_key)}
        d = {"domains": math_d["domains"], "units": units, "books": books}
        if kind == "all":
            d["measures"] = math_d["measures"]
        return d
    books = sorted({v["book"] for v in en_d["vocab"]}, key=_book_sort_key)
    if kind == "speak":
        return {"dialogues": en_d["dialogues"], "projects": en_d["projects"],
                "exprs": en_d["exprs"], "functions": en_d["functions"],
                "books": sorted({d["book"] for d in en_d["dialogues"]}, key=_book_sort_key)}
    if kind == "dictation":
        # 拼写/句子/短文三种模式分别需要 vocab / dialogues+passages / passages
        return {"vocab": en_d["vocab"], "passages": en_d["passages"],
                "dialogues": en_d["dialogues"], "exprs": en_d.get("exprs", []),
                "themes": en_d["themes"], "books": books}
    keys = {"discourse": ["passages", "dialogues"], "vocab": ["vocab"],
            "grammar": ["grammar"], "phonics": ["phonics"],
            "use": ["songs", "projects", "revisions"],
            "extra": ["passages", "dialogues"],
            "writing": ["passages", "dialogues", "vocab", "grammar"]}
    d = {"books": books, "themes": en_d["themes"], "domains": en_d["domains"]}
    for k in keys.get(kind, []):
        d[k] = en_d[k]
    if kind == "discourse":
        # 每课学习中心的单元级配套 + 本单元配套的课外书（反向入口）
        hubs = build_lesson_hubs(en_d)
        extra_by_unit, _ = _enrich_readings(_load_readings(),
                                            _load_pairings(),
                                            _load_unit_index())
        hubs["extra"] = extra_by_unit
        d["hubs"] = hubs
    if kind == "extra":
        # 本体论课外拓展：加载长文库 + 绘本 + 分类标准
        readings = _load_readings()
        _enrich_readings(readings, _load_pairings(), _load_unit_index())
        d["readings"] = readings
        d["picturebooks"] = _load_picturebooks()
        d["taxonomy"] = _load_taxonomy()
    if kind == "writing":
        d["writing"] = _writing_data()
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

    # 英语点读音频：把 data/tts/ 合并进 pages/tts/（含 index.json 与 4 个音色子目录）
    # 注意：pages/tts 可能已经有构建时未覆盖的批量生成音频（如 fa5563f4 的 6318x4 音色），
    # 这里必须用增量合并，不能 rmtree —— 否则 pages/tts 会被 data/tts（只有 1500 多份）
    # 反向覆盖，把已有的 25k+ MP3 删光。
    from . import tts as _tts
    if os.path.isdir(_tts.TTS_DIR):
        tts_out = os.path.join(out, "tts")
        os.makedirs(tts_out, exist_ok=True)
        shutil.copytree(_tts.TTS_DIR, tts_out, dirs_exist_ok=True)
        n_mp3 = sum(len([f for f in os.listdir(os.path.join(tts_out, v))
                         if f.endswith(".mp3")])
                    for v in os.listdir(tts_out)
                    if os.path.isdir(os.path.join(tts_out, v)))
        if verbose:
            print(f"→ TTS: {n_mp3} MP3 已同步到 {tts_out}")

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
<div class="card cn"><h3>语文</h3><p class="small">课文全文（按册→单元→课，含生字与课后题，可当课本）、
识字与写字、表达与交流（习作要素）、古诗文（原文+注释+译文）。</p>
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
