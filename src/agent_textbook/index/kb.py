# -*- coding: utf-8 -*-
"""知识库存储（L3）：DuckDB 建库、导入与查询。

设计要点：
  * 主表只放稳定字段；新增属性一律**新建表**再 JOIN，主表一行不改。
  * JSONL 是 source of truth，整库可秒级重建（数据量只有几千条）。
  * lessons.lesson_id 是稳定主键（册 id + 目录内序号），属性表靠它挂载。
"""

import glob
import json
import os

import duckdb

from .. import config
from . import outline as ol

DB_PATH = os.path.join(config.DATA_DIR, "kb.duckdb")
WORDS_FILE = os.path.join(config.ATTRS_DIR, "words.jsonl")
LESSON_TEXT_FILE = os.path.join(config.ATTRS_DIR, "lesson_text.jsonl")
LESSON_META_FILE = os.path.join(config.ATTRS_DIR, "lesson_meta.jsonl")
PIECE_FILE = os.path.join(config.ATTRS_DIR, "piece.jsonl")
GENRE_FILE = os.path.join(config.ATTRS_DIR, "lesson_genre.jsonl")
STRUCT_FILE = os.path.join(config.ATTRS_DIR, "lesson_structure.jsonl")
GLOSS_FILE = os.path.join(config.ATTRS_DIR, "lesson_glossary.jsonl")
TRANS_FILE = os.path.join(config.ATTRS_DIR, "lesson_translation.jsonl")
AUTHOR_FILE = os.path.join(config.ATTRS_DIR, "lesson_author.jsonl")
INTRO_FILE = os.path.join(config.ATTRS_DIR, "author_intro.jsonl")
SECTION_FILE = os.path.join(config.ATTRS_DIR, "section_text.jsonl")
KP_FILE = os.path.join(config.ATTRS_DIR, "section_keypoints.jsonl")
# 英语本体：词与常用表达（附录规则层，见 index/enwords.py）
EN_VOCAB_FILE = os.path.join(config.ATTRS_DIR, "en_vocab.jsonl")
EN_EXPR_FILE = os.path.join(config.ATTRS_DIR, "en_expr.jsonl")
# 数学本体：公式 LaTeX（看图，见 index/formula.py）
FORMULA_FILE = os.path.join(config.ATTRS_DIR, "section_formula.jsonl")
# 科学本体：探究活动 + 科学概念（见 index/science.py）
EXP_FILE = os.path.join(config.ATTRS_DIR, "experiment.jsonl")
CONCEPT_FILE = os.path.join(config.ATTRS_DIR, "concept.jsonl")
# 数学本体：例题（含解题步骤），公式的"用武之地"（见 index/mathex.py）
EXAMPLE_FILE = os.path.join(config.ATTRS_DIR, "example.jsonl")
# 数学课时（见 index/mathunit.py）：单元级小节拆出来的课
SUBSEC_FILE = os.path.join(config.ATTRS_DIR, "subsection.jsonl")
# 英语本体：情景对话 / 句型语法 / 拼读（见 index/enlang.py）
EN_DIALOGUE_FILE = os.path.join(config.ATTRS_DIR, "en_dialogue.jsonl")
EN_GRAMMAR_FILE = os.path.join(config.ATTRS_DIR, "en_grammar.jsonl")
EN_PHONICS_FILE = os.path.join(config.ATTRS_DIR, "en_phonics.jsonl")
# 英语语篇与项目（见 index/enlang.py）：阅读/写作/做中学三个维度的落点
EN_PASSAGE_FILE = os.path.join(config.ATTRS_DIR, "en_passage.jsonl")
EN_PROJECT_FILE = os.path.join(config.ATTRS_DIR, "en_project.jsonl")
# 语文单元要素（见 index/cnelem.py）：单元导语页上印的读写要素
ELEM_FILE = os.path.join(config.ATTRS_DIR, "unit_element.jsonl")
# 数学补充槽位（见 index/mathmap.py）：整理复习页的知识结构图、单位与符号表
MAP_FILE = os.path.join(config.ATTRS_DIR, "unit_map.jsonl")
MATH_UNIT_FILE = os.path.join(config.ATTRS_DIR, "math_unit.jsonl")

# 用 OR REPLACE 而不是 IF NOT EXISTS：表结构演进（如给 lesson_text 加 notes 列）
# 时，IF NOT EXISTS 会静默沿用旧表，导入的列数对不上才暴露，排查成本高。
# 属性表全部由 JSONL 重建，整表替换没有任何损失。
SCHEMA = [
    """CREATE OR REPLACE TABLE books(
        book_id VARCHAR PRIMARY KEY, stage VARCHAR, subject VARCHAR,
        version VARCHAR, grade VARCHAR, term VARCHAR, title VARCHAR,
        total_pages INTEGER, toc_pages VARCHAR)""",
    """CREATE OR REPLACE TABLE lessons(
        lesson_id VARCHAR PRIMARY KEY, book_id VARCHAR, seq INTEGER,
        unit_no INTEGER, unit_name VARCHAR, unit_tag VARCHAR, section VARCHAR,
        lesson_no VARCHAR, title VARCHAR, printed_start INTEGER,
        elective BOOLEAN)""",
    """CREATE OR REPLACE TABLE words(
        book_id VARCHAR, grade VARCHAR, term VARCHAR, kind VARCHAR,
        lesson_no VARCHAR, value VARCHAR, pinyin VARCHAR, page_no INTEGER)""",
    # 课文正文（切分产物）：paragraphs/tasks/exercises/notes/newchars 存 JSON 串
    """CREATE OR REPLACE TABLE lesson_text(
        lesson_id VARCHAR PRIMARY KEY, book_id VARCHAR, grade VARCHAR, term VARCHAR,
        unit_no INTEGER, unit_name VARCHAR, section VARCHAR, lesson_no VARCHAR,
        title VARCHAR, printed_start INTEGER, printed_end INTEGER,
        page_from INTEGER, page_to INTEGER, n_pages INTEGER, chars INTEGER,
        text VARCHAR, text_plain VARCHAR,
        paragraphs VARCHAR, tasks VARCHAR, exercises VARCHAR, notes VARCHAR,
        reading_links VARCHAR, newchars VARCHAR)""",
    # 课文元数据：体裁/作者/朝代/出处，只记原文里写明的
    """CREATE OR REPLACE TABLE lesson_meta(
        lesson_id VARCHAR PRIMARY KEY, book_id VARCHAR, title VARCHAR,
        genre VARCHAR, author VARCHAR, dynasty VARCHAR, source VARCHAR)""",
    # 篇（piece）：一课多篇的展开，piece_id 由父 lesson_id + 序号构成
    """CREATE OR REPLACE TABLE piece(
        piece_id VARCHAR PRIMARY KEY, lesson_id VARCHAR, book_id VARCHAR,
        grade VARCHAR, term VARCHAR, unit_no INTEGER, unit_name VARCHAR,
        lesson_no VARCHAR, parent_title VARCHAR, seq INTEGER, title VARCHAR,
        kind VARCHAR, printed_start INTEGER, printed_end INTEGER,
        dynasty VARCHAR, author VARCHAR, located BOOLEAN, chars INTEGER,
        text VARCHAR, sentences VARCHAR, notes VARCHAR)""",
    # 细分体裁（LLM 校对层）：与 lesson_meta.genre 分开存——
    # genre 是规则判的大类（课文/古诗/习作…），genre_sub 是语义细分（写景/记事…），
    # 分开才能看出"哪一条是模型给的"，换模型重抽时只覆盖这张表。
    """CREATE OR REPLACE TABLE lesson_genre(
        lesson_id VARCHAR PRIMARY KEY, book_id VARCHAR, title VARCHAR,
        genre_sub VARCHAR, reason VARCHAR, model VARCHAR, ts BIGINT)""",
    # 课文结构（LLM 整理层）：段落归并成结构段 + 段意 + 全文大意。
    # parts 存 JSON 串，段数是可校验的（结构段必须连续覆盖全部段落），
    # 换模型重抽时整表替换即可。
    """CREATE OR REPLACE TABLE lesson_structure(
        lesson_id VARCHAR PRIMARY KEY, book_id VARCHAR, title VARCHAR,
        n_paragraphs INTEGER, parts VARCHAR, main_idea VARCHAR,
        model VARCHAR, ts BIGINT)""",
    # 词语解释（LLM 整理层）：补教材注释没覆盖的字词。
    # 挂在 **piece** 上而不是 lesson——一课多首古诗时，lesson 层是整组诗，
    # 词会安错对象（《迢迢牵牛星》的"迢迢"跑到《寒食》头上）。
    """CREATE OR REPLACE TABLE lesson_glossary(
        piece_id VARCHAR PRIMARY KEY, lesson_id VARCHAR, book_id VARCHAR,
        title VARCHAR, glossary VARCHAR, model VARCHAR, ts BIGINT)""",
    # 白话译文（LLM 补充层）：逐句对照 literal 存 JSON 串，
    # source 记原文取自 lesson 段落还是 piece（可信度不同）。
    """CREATE OR REPLACE TABLE lesson_translation(
        piece_id VARCHAR PRIMARY KEY, lesson_id VARCHAR, book_id VARCHAR,
        title VARCHAR, translation VARCHAR, literal VARCHAR, source VARCHAR,
        model VARCHAR, ts BIGINT)""",
    # 作者（LLM 补充层）：挂在**篇**上——一课多首诗时挂课会把作者安错。
    # key = piece_id（篇）或 lesson_id（没有子篇的课）。
    """CREATE OR REPLACE TABLE lesson_author(
        key VARCHAR PRIMARY KEY, piece_id VARCHAR, lesson_id VARCHAR,
        book_id VARCHAR, title VARCHAR, parent_title VARCHAR, author VARCHAR,
        dynasty VARCHAR, model VARCHAR, ts BIGINT)""",
    # 作者简介（LLM 补充层）：按人名去重，一个人一条。
    # book_ids / lesson_titles 由 enrich.link_intro() 从 lesson_author 反查回填，
    # 有它才能按册检索"这一册出现了哪些作家"。
    """CREATE OR REPLACE TABLE author_intro(
        author VARCHAR PRIMARY KEY, dynasty VARCHAR, intro VARCHAR,
        works VARCHAR, book_ids VARCHAR, lesson_titles VARCHAR,
        n_lessons INTEGER, model VARCHAR, ts BIGINT)""",
    # 数学/科学的小节正文（切分层）：一节一条，blocks 里分好例题/练习/实验。
    """CREATE OR REPLACE TABLE section_text(
        section_id VARCHAR PRIMARY KEY, book_id VARCHAR, subject VARCHAR,
        grade VARCHAR, term VARCHAR, unit_no INTEGER, unit_name VARCHAR,
        title VARCHAR, printed_from INTEGER, printed_to INTEGER,
        page_from INTEGER, page_to INTEGER, n_pages INTEGER, chars INTEGER,
        text VARCHAR, blocks VARCHAR, n_examples INTEGER, n_exercises INTEGER)""",
    # 小节知识点（LLM 概括层）：概括正文而非添补外部知识，一节一条。
    """CREATE OR REPLACE TABLE section_keypoint(
        section_id VARCHAR PRIMARY KEY, book_id VARCHAR, subject VARCHAR,
        grade VARCHAR, term VARCHAR, unit_name VARCHAR, title VARCHAR,
        summary VARCHAR, points VARCHAR, formulas VARCHAR, terms VARCHAR,
        model VARCHAR, ts BIGINT)""",
    # 英语词汇（附录规则层）：unit 版按单元归类，vocab 版是书末字母序总表
    """CREATE OR REPLACE TABLE en_vocab(
        vocab_id VARCHAR PRIMARY KEY, book_id VARCHAR, subject VARCHAR,
        grade VARCHAR, term VARCHAR, unit_no INTEGER, word VARCHAR,
        phonetic VARCHAR, meaning VARCHAR, level VARCHAR,
        printed_page INTEGER, source VARCHAR, topic VARCHAR, example VARCHAR)""",
    # 英语常用表达/功能句：一问一答成对出现，靠 unit_no 归到单元
    """CREATE OR REPLACE TABLE en_expr(
        expr_id VARCHAR PRIMARY KEY, book_id VARCHAR, subject VARCHAR,
        grade VARCHAR, term VARCHAR, unit_no INTEGER, en VARCHAR,
        zh VARCHAR, printed_page INTEGER)""",
    # 数学公式（看图抽的 LaTeX）：一页可有多条，靠 page_key 续跑去重。
    # 列名不叫 desc —— 那是 DuckDB 保留字，裸写会撞语法错误。
    """CREATE OR REPLACE TABLE section_formula(
        formula_id VARCHAR PRIMARY KEY, page_key VARCHAR, section_id VARCHAR,
        book_id VARCHAR, subject VARCHAR, grade VARCHAR, term VARCHAR,
        unit_name VARCHAR, title VARCHAR, page_no INTEGER, latex VARCHAR,
        kind VARCHAR, note VARCHAR, vars VARCHAR, model VARCHAR, ts BIGINT,
        subsection_id VARCHAR)""",
    # 科学探究活动：器材/步骤/变量/现象/结论，数组与对象存 JSON 串
    """CREATE OR REPLACE TABLE experiment(
        exp_id VARCHAR PRIMARY KEY, section_id VARCHAR, book_id VARCHAR,
        subject VARCHAR, grade VARCHAR, term VARCHAR, unit_name VARCHAR,
        title VARCHAR, name VARCHAR, kind VARCHAR, purpose VARCHAR,
        materials VARCHAR, steps VARCHAR, phenomenon VARCHAR, conclusion VARCHAR,
        variables VARCHAR, safety VARCHAR, page_hint VARCHAR,
        model VARCHAR, ts BIGINT)""",
    # 概念：术语 + 定义 + 生活实例 + 常见迷思，科学与数学共用（subject 区分）。
    # 术语列叫 name 而非 term —— term 在本库里一律指学期，重名会撞 Catalog Error。
    # symbol/property 是数学概念才有的（数学表示、性质法则），科学留空。
    """CREATE OR REPLACE TABLE concept(
        concept_id VARCHAR PRIMARY KEY, section_id VARCHAR, book_id VARCHAR,
        subject VARCHAR, grade VARCHAR, term VARCHAR, unit_name VARCHAR,
        title VARCHAR, name VARCHAR, definition VARCHAR, symbol VARCHAR,
        property VARCHAR, example VARCHAR, misconception VARCHAR,
        category VARCHAR, model VARCHAR, ts BIGINT)""",
    # 数学课时（mathunit 切分）：单元级小节再拆成教材真实的课，
    # 例题与公式都靠它的 page_from/page_to 归到"课"而不是"单元"
    """CREATE OR REPLACE TABLE subsection(
        subsection_id VARCHAR PRIMARY KEY, section_id VARCHAR, book_id VARCHAR,
        subject VARCHAR, grade VARCHAR, term VARCHAR, unit_name VARCHAR,
        title VARCHAR, seq INTEGER, page_from INTEGER, page_to INTEGER,
        n_pages INTEGER, chars INTEGER, text VARCHAR, blocks VARCHAR,
        model VARCHAR, ts BIGINT)""",
    # 数学例题：题面 + 分步解法 + 答案，formula_refs 存本节 LaTeX（JSON 串），
    # 动画层拿它把"这一步"和"这条公式"对上。课时级抽取时 subsection_id 非空
    """CREATE OR REPLACE TABLE example(
        example_id VARCHAR PRIMARY KEY, section_id VARCHAR,
        subsection_id VARCHAR, book_id VARCHAR,
        subject VARCHAR, grade VARCHAR, term VARCHAR, unit_name VARCHAR,
        title VARCHAR, name VARCHAR, type VARCHAR, stem VARCHAR, given VARCHAR,
        ask VARCHAR, steps VARCHAR, latex VARCHAR, answer VARCHAR,
        answer_latex VARCHAR, keypoint VARCHAR, difficulty VARCHAR,
        page_hint VARCHAR, formula_refs VARCHAR,
        model VARCHAR, ts BIGINT)""",
    # 英语情景对话：turns 与 patterns 存 JSON 串
    """CREATE OR REPLACE TABLE en_dialogue(
        dialogue_id VARCHAR PRIMARY KEY, section_id VARCHAR, book_id VARCHAR,
        subject VARCHAR, grade VARCHAR, term VARCHAR, unit_name VARCHAR,
        title VARCHAR, scene VARCHAR, function VARCHAR, turns VARCHAR,
        patterns VARCHAR, page_hint VARCHAR, model VARCHAR, ts BIGINT)""",
    # 英语句型语法：可替换结构式 + 规则 + 例句（examples 存 JSON 串）
    """CREATE OR REPLACE TABLE en_grammar(
        grammar_id VARCHAR PRIMARY KEY, section_id VARCHAR, book_id VARCHAR,
        subject VARCHAR, grade VARCHAR, term VARCHAR, unit_name VARCHAR,
        title VARCHAR, point VARCHAR, pattern VARCHAR, rule VARCHAR,
        category VARCHAR, tense VARCHAR, examples VARCHAR, page_hint VARCHAR,
        model VARCHAR, ts BIGINT)""",
    # 英语拼读：字母（组合）+ 发音 + 例词 + 歌谣
    """CREATE OR REPLACE TABLE en_phonics(
        phonics_id VARCHAR PRIMARY KEY, section_id VARCHAR, book_id VARCHAR,
        subject VARCHAR, grade VARCHAR, term VARCHAR, unit_name VARCHAR,
        title VARCHAR, letters VARCHAR, sound VARCHAR, examples VARCHAR,
        chant VARCHAR, page_hint VARCHAR, model VARCHAR, ts BIGINT)""",
    # 英语语篇：Read and write / Start to read / Story time 的成篇原文、体裁、
    # 阅读理解题（comprehension）与配套写作任务（writing_task）——阅读与写作
    # 两个课标维度在库里的落点，前三层（对话/语法/拼读）都覆盖不到。
    """CREATE OR REPLACE TABLE en_passage(
        passage_id VARCHAR PRIMARY KEY, section_id VARCHAR, book_id VARCHAR,
        subject VARCHAR, grade VARCHAR, term VARCHAR, unit_name VARCHAR,
        title VARCHAR, name VARCHAR, genre VARCHAR, source VARCHAR,
        text VARCHAR, zh VARCHAR, topic VARCHAR, words VARCHAR,
        comprehension VARCHAR, writing_task VARCHAR, keypoints VARCHAR,
        model VARCHAR, ts BIGINT)""",
    # 英语项目：Project / Make a ... 的任务目标、步骤、产出与要用的语言（"做中学"）
    """CREATE OR REPLACE TABLE en_project(
        project_id VARCHAR PRIMARY KEY, section_id VARCHAR, book_id VARCHAR,
        subject VARCHAR, grade VARCHAR, term VARCHAR, unit_name VARCHAR,
        title VARCHAR, name VARCHAR, type VARCHAR, goal VARCHAR, steps VARCHAR,
        language VARCHAR, product VARCHAR, materials VARCHAR,
        model VARCHAR, ts BIGINT)""",
    # 插图描述（VLM 侧车）：一页一条，靠 (book_id, page_no) 挂到课/小节。
    # VLM 通道册的正文里也有 [图N]，那是转录时顺带写的，与本表不重复计。
    """CREATE OR REPLACE TABLE page_figure(
        book_id VARCHAR, page_no INTEGER, n_figures INTEGER,
        text VARCHAR, model VARCHAR, ts VARCHAR,
        PRIMARY KEY (book_id, page_no))""",
    # 语文单元要素：课文里抽不到，只有单元导语页印着，一单元一条。
    """CREATE OR REPLACE TABLE unit_element(
        unit_id VARCHAR PRIMARY KEY, book_id VARCHAR, subject VARCHAR,
        grade VARCHAR, term VARCHAR, unit_no INTEGER, unit_name VARCHAR,
        unit_title VARCHAR, theme VARCHAR, reading_focus VARCHAR,
        writing_focus VARCHAR, points VARCHAR, page_no INTEGER,
        model VARCHAR, ts BIGINT)""",
    # 数学知识结构图：整理与复习页那张树状图，nodes 是扁平数组 + parent。
    """CREATE OR REPLACE TABLE unit_map(
        map_id VARCHAR PRIMARY KEY, section_id VARCHAR, subsection_id VARCHAR,
        book_id VARCHAR, subject VARCHAR, grade VARCHAR, term VARCHAR,
        unit_no INTEGER, unit_name VARCHAR, title VARCHAR, topic VARCHAR,
        summary VARCHAR, nodes VARCHAR, n_nodes INTEGER, page_from INTEGER,
        page_to INTEGER, model VARCHAR, ts BIGINT)""",
    # 数学单位与符号：按单元抽（教材没有独立栏目，规则抓不全进率）。
    """CREATE OR REPLACE TABLE math_unit(
        item_id VARCHAR PRIMARY KEY, section_id VARCHAR, book_id VARCHAR,
        subject VARCHAR, grade VARCHAR, term VARCHAR, unit_no INTEGER,
        unit_name VARCHAR, units VARCHAR, symbols VARCHAR, n_units INTEGER,
        n_symbols INTEGER, model VARCHAR, ts BIGINT)""",
]


def connect() -> duckdb.DuckDBPyConnection:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    con = duckdb.connect(DB_PATH)
    # 逐条 INSERT 大表（公式 6k 行、概念 2k 行、插图 4k 页）时不设上限会 OOM：
    # 限制内存 + 允许溢写到磁盘，慢一点但不会中途炸掉
    con.execute("SET memory_limit='3GB'")
    con.execute("SET temp_directory='%s'" % os.path.join(
        config.DATA_DIR, "_tmp").replace("\\", "/"))
    return con


def build(subject: str = "", verbose: bool = True) -> dict:
    """重建库并导入目录与字表。

    subject 为空表示**全部学科**：语文的课文层与数学/科学的小节层共用一套
    lesson_id / section_id 主键，同库共存互不冲突。
    """
    con = connect()
    for ddl in SCHEMA:
        con.execute(ddl)
    for t in ("books", "lessons", "words", "lesson_text", "lesson_meta", "piece",
              "lesson_genre", "lesson_structure", "lesson_glossary",
              "lesson_translation", "lesson_author", "author_intro",
              "section_text", "section_keypoint", "en_vocab", "en_expr",
              "section_formula", "experiment", "concept", "page_figure",
              "example", "en_dialogue", "en_grammar", "en_phonics",
              "en_passage", "en_project", "subsection", "unit_element",
              "unit_map", "math_unit"):
        con.execute(f"DELETE FROM {t}")
    # 清空后先落盘：旧版本行一直攒在内存/WAL 里，后面逐条 INSERT 大表会 OOM
    con.execute("CHECKPOINT")

    def _tick(i: int) -> None:
        """大表导入时定期落盘，把已完成的行从内存里放掉。"""
        if i and i % 2000 == 0:
            con.execute("CHECKPOINT")

    nb = nl = 0
    for f in sorted(glob.glob(os.path.join(config.OUTLINE_DIR, "*.jsonl"))):
        rs = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        if not rs:
            continue
        meta, entries = rs[0], rs[1:]
        if subject and meta.get("subject") != subject:
            continue
        con.execute("INSERT OR REPLACE INTO books VALUES (?,?,?,?,?,?,?,?,?)", [
            meta.get("book_id"), meta.get("stage"), meta.get("subject"),
            meta.get("version"), meta.get("grade"), meta.get("term"),
            meta.get("title"), meta.get("total_pages"),
            json.dumps(meta.get("toc_pages") or [], ensure_ascii=False),
        ])
        nb += 1
        for e in entries:
            con.execute("INSERT OR REPLACE INTO lessons VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
                e.get("lesson_id"), e.get("book_id"), e.get("seq"),
                e.get("unit_no"), e.get("unit_name"), e.get("unit_tag"),
                e.get("section"), e.get("lesson_no"), e.get("title"),
                e.get("printed_start"), bool(e.get("elective")),
            ])
            nl += 1

    nw = 0
    if os.path.exists(WORDS_FILE):
        for l in open(WORDS_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT INTO words VALUES (?,?,?,?,?,?,?,?)", [
                r.get("book_id"), r.get("grade"), r.get("term"), r.get("kind"),
                r.get("lesson_no"), r.get("value"), r.get("pinyin"), r.get("page_no"),
            ])
            nw += 1

    def _j(v):
        return json.dumps(v or [], ensure_ascii=False)

    nt = 0
    if os.path.exists(LESSON_TEXT_FILE):
        for l in open(LESSON_TEXT_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO lesson_text VALUES (%s)" % ",".join(["?"] * 23), [
                r.get("lesson_id"), r.get("book_id"), r.get("grade"), r.get("term"),
                r.get("unit_no"), r.get("unit_name"), r.get("section"), r.get("lesson_no"),
                r.get("title"), r.get("printed_start"), r.get("printed_end"),
                r.get("page_from"), r.get("page_to"), r.get("n_pages"), r.get("chars"),
                r.get("text"), r.get("text_plain"),
                _j(r.get("paragraphs")), _j(r.get("tasks")),
                _j(r.get("exercises")), _j(r.get("notes")),
                _j(r.get("reading_links")), _j(r.get("newchars")),
            ])
            nt += 1

    nm = 0
    if os.path.exists(LESSON_META_FILE):
        for l in open(LESSON_META_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO lesson_meta VALUES (?,?,?,?,?,?,?)", [
                r.get("lesson_id"), r.get("book_id"), r.get("title"),
                r.get("genre"), r.get("author"), r.get("dynasty"), r.get("source"),
            ])
            nm += 1

    npi = 0
    if os.path.exists(PIECE_FILE):
        for l in open(PIECE_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO piece VALUES (%s)" % ",".join(["?"] * 21), [
                r.get("piece_id"), r.get("lesson_id"), r.get("book_id"),
                r.get("grade"), r.get("term"), r.get("unit_no"), r.get("unit_name"),
                r.get("lesson_no"), r.get("parent_title"), r.get("seq"),
                r.get("title"), r.get("kind"), r.get("printed_start"),
                r.get("printed_end"), r.get("dynasty"), r.get("author"),
                bool(r.get("located")), r.get("chars"), r.get("text"),
                _j(r.get("sentences")), _j(r.get("notes")),
            ])
            npi += 1

    ng = 0
    if os.path.exists(GENRE_FILE):
        for l in open(GENRE_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO lesson_genre VALUES (?,?,?,?,?,?,?)", [
                r.get("lesson_id"), r.get("book_id"), r.get("title"),
                r.get("genre_sub"), r.get("reason"), r.get("model"), r.get("ts"),
            ])
            ng += 1

    nst = 0
    if os.path.exists(STRUCT_FILE):
        for l in open(STRUCT_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO lesson_structure VALUES (?,?,?,?,?,?,?,?)", [
                r.get("lesson_id"), r.get("book_id"), r.get("title"),
                r.get("n_paragraphs"), _j(r.get("parts")), r.get("main_idea"),
                r.get("model"), r.get("ts"),
            ])
            nst += 1

    ngl = 0
    if os.path.exists(GLOSS_FILE):
        for l in open(GLOSS_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO lesson_glossary VALUES (?,?,?,?,?,?,?)", [
                r.get("piece_id"), r.get("lesson_id"), r.get("book_id"),
                r.get("title"), _j(r.get("glossary")), r.get("model"), r.get("ts"),
            ])
            ngl += 1

    ntr = 0
    if os.path.exists(TRANS_FILE):
        for l in open(TRANS_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute(
                "INSERT OR REPLACE INTO lesson_translation VALUES (?,?,?,?,?,?,?,?,?)", [
                    r.get("piece_id"), r.get("lesson_id"), r.get("book_id"),
                    r.get("title"), r.get("translation"), _j(r.get("literal")),
                    r.get("source"), r.get("model"), r.get("ts"),
                ])
            ntr += 1

    nau = 0
    if os.path.exists(AUTHOR_FILE):
        for l in open(AUTHOR_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute(
                "INSERT OR REPLACE INTO lesson_author VALUES (?,?,?,?,?,?,?,?,?,?)", [
                    r.get("key"), r.get("piece_id"), r.get("lesson_id"),
                    r.get("book_id"), r.get("title"), r.get("parent_title"),
                    r.get("author"), r.get("dynasty"), r.get("model"), r.get("ts"),
                ])
            nau += 1

    nin = 0
    if os.path.exists(INTRO_FILE):
        for l in open(INTRO_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO author_intro VALUES (%s)"
                        % ",".join(["?"] * 9), [
                r.get("author"), r.get("dynasty"), r.get("intro"),
                _j(r.get("works")), _j(r.get("book_ids") or []),
                _j(r.get("lesson_titles") or []), r.get("n_lessons") or 0,
                r.get("model"), r.get("ts"),
            ])
            nin += 1

    nel = 0
    if os.path.exists(ELEM_FILE):
        for l in open(ELEM_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO unit_element VALUES (%s)"
                        % ",".join(["?"] * 15), [
                r.get("unit_id"), r.get("book_id"), r.get("subject"),
                r.get("grade"), r.get("term"), r.get("unit_no"),
                r.get("unit_name"), r.get("unit_title"), r.get("theme"),
                r.get("reading_focus"), r.get("writing_focus"),
                _j(r.get("points") or []), r.get("page_no"),
                r.get("model"), r.get("ts"),
            ])
            nel += 1

    nmp = 0
    if os.path.exists(MAP_FILE):
        for l in open(MAP_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO unit_map VALUES (%s)"
                        % ",".join(["?"] * 18), [
                r.get("map_id"), r.get("section_id"), r.get("subsection_id"),
                r.get("book_id"), r.get("subject"), r.get("grade"), r.get("term"),
                r.get("unit_no"), r.get("unit_name"), r.get("title"),
                r.get("topic"), r.get("summary"), _j(r.get("nodes") or []),
                r.get("n_nodes") or 0, r.get("page_from"), r.get("page_to"),
                r.get("model"), r.get("ts"),
            ])
            nmp += 1

    nun = 0
    if os.path.exists(MATH_UNIT_FILE):
        for l in open(MATH_UNIT_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO math_unit VALUES (%s)"
                        % ",".join(["?"] * 14), [
                r.get("item_id"), r.get("section_id"), r.get("book_id"),
                r.get("subject"), r.get("grade"), r.get("term"), r.get("unit_no"),
                r.get("unit_name"), _j(r.get("units") or []),
                _j(r.get("symbols") or []), r.get("n_units") or 0,
                r.get("n_symbols") or 0, r.get("model"), r.get("ts"),
            ])
            nun += 1

    nse = 0
    if os.path.exists(SECTION_FILE):
        for l in open(SECTION_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO section_text VALUES (%s)"
                        % ",".join(["?"] * 18), [
                            r.get("section_id"), r.get("book_id"), r.get("subject"),
                            r.get("grade"), r.get("term"), r.get("unit_no"),
                            r.get("unit_name"), r.get("title"), r.get("printed_from"),
                            r.get("printed_to"), r.get("page_from"), r.get("page_to"),
                            r.get("n_pages"), r.get("chars"), r.get("text"),
                            _j(r.get("blocks")), r.get("n_examples"),
                            r.get("n_exercises"),
                        ])
            nse += 1

    nkp = 0
    if os.path.exists(KP_FILE):
        for l in open(KP_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO section_keypoint VALUES (%s)"
                        % ",".join(["?"] * 13), [
                            r.get("section_id"), r.get("book_id"), r.get("subject"),
                            r.get("grade"), r.get("term"), r.get("unit_name"),
                            r.get("title"), r.get("summary"), _j(r.get("points")),
                            _j(r.get("formulas")), _j(r.get("terms")),
                            r.get("model"), r.get("ts"),
                        ])
            nkp += 1

    nvocab = 0
    if os.path.exists(EN_VOCAB_FILE):
        for l in open(EN_VOCAB_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO en_vocab VALUES (%s)"
                        % ",".join(["?"] * 14), [
                            r.get("vocab_id"), r.get("book_id"), r.get("subject"),
                            r.get("grade"), r.get("term"), r.get("unit_no"),
                            r.get("word"), r.get("phonetic"), r.get("meaning"),
                            r.get("level"), r.get("printed_page"), r.get("source"),
                            r.get("topic") or "", _j(r.get("example")),
                        ])
            nvocab += 1

    nexpr = 0
    if os.path.exists(EN_EXPR_FILE):
        for l in open(EN_EXPR_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            con.execute("INSERT OR REPLACE INTO en_expr VALUES (%s)"
                        % ",".join(["?"] * 9), [
                            r.get("expr_id"), r.get("book_id"), r.get("subject"),
                            r.get("grade"), r.get("term"), r.get("unit_no"),
                            r.get("en"), r.get("zh"), r.get("printed_page"),
                        ])
            nexpr += 1

    # 课时索引：公式与例题只记页码，靠它把"这一页的公式"归到具体的课
    sub_by_book: dict[str, list[tuple]] = {}
    if os.path.exists(SUBSEC_FILE):
        for l in open(SUBSEC_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            pf, pt = r.get("page_from"), r.get("page_to")
            if isinstance(pf, int) and isinstance(pt, int):
                sub_by_book.setdefault(r.get("book_id") or "", []).append(
                    (pf, pt, r.get("subsection_id")))

    def _sub_of(book_id, page_no) -> str:
        for pf, pt, sid in sub_by_book.get(book_id or "", ()):
            if isinstance(page_no, int) and pf <= page_no <= pt:
                return sid or ""
        return ""

    nfo = 0
    if os.path.exists(FORMULA_FILE):
        for l in open(FORMULA_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if not r.get("latex"):
                continue          # 整页无公式的空壳记录不入库
            con.execute("INSERT OR REPLACE INTO section_formula VALUES (%s)"
                        % ",".join(["?"] * 17), [
                            r.get("formula_id"), r.get("page_key"),
                            r.get("section_id"), r.get("book_id"),
                            r.get("subject"), r.get("grade"), r.get("term"),
                            r.get("unit_name"), r.get("title"),                             r.get("page_no"),
                            r.get("latex"), r.get("kind"),
                            r.get("note") or r.get("desc"),
                            r.get("vars"), r.get("model"), r.get("ts"),
                            _sub_of(r.get("book_id"), r.get("page_no")),
                        ])
            nfo += 1
            _tick(nfo)

    nexp = 0
    if os.path.exists(EXP_FILE):
        for l in open(EXP_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if not (r.get("name") or r.get("steps")):
                continue          # 空壳：该节没有探究活动
            con.execute("INSERT OR REPLACE INTO experiment VALUES (%s)"
                        % ",".join(["?"] * 20), [
                            r.get("exp_id"), r.get("section_id"), r.get("book_id"),
                            r.get("subject"), r.get("grade"), r.get("term"),
                            r.get("unit_name"), r.get("title"), r.get("name"),
                            r.get("kind"), r.get("purpose"),
                            _j(r.get("materials")), _j(r.get("steps")),
                            r.get("phenomenon"), r.get("conclusion"),
                            json.dumps(r.get("variables") or {}, ensure_ascii=False),
                            _j(r.get("safety")), r.get("page_hint"),
                            r.get("model"), r.get("ts"),
                        ])
            nexp += 1

    ncp = 0
    if os.path.exists(CONCEPT_FILE):
        # 早期概念记录里"学期"被"术语"覆盖了同一个 term 键，用小节层回填学期/年级，
        # 免得为了修字段把 300 节的抽取重跑一遍
        sec_meta = {}
        if os.path.exists(SECTION_FILE):
            for l2 in open(SECTION_FILE, encoding="utf-8"):
                if not l2.strip():
                    continue
                s = json.loads(l2)
                sec_meta[s.get("section_id")] = (s.get("grade"), s.get("term"))
        for l in open(CONCEPT_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            # 旧科学记录里术语落在 term 键（当年与学期撞名），新记录用 term_name
            name = (r.get("term_name") or r.get("term") or "").strip()
            if not name:
                continue
            g, t = sec_meta.get(r.get("section_id"), (r.get("grade"), r.get("term")))
            con.execute("INSERT OR REPLACE INTO concept VALUES (%s)"
                        % ",".join(["?"] * 17), [
                            r.get("concept_id"), r.get("section_id"),
                            r.get("book_id"), r.get("subject"),
                            r.get("grade") or g, t,
                            r.get("unit_name"), r.get("title"), name,
                            r.get("definition"), r.get("symbol") or "",
                            r.get("property") or "", r.get("example"),
                            r.get("misconception"), r.get("category"),
                            r.get("model"), r.get("ts"),
                        ])
            ncp += 1
            _tick(ncp)

    nsb = 0
    if os.path.exists(SUBSEC_FILE):
        for l in open(SUBSEC_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if not r.get("subsection_id"):
                continue
            con.execute("INSERT OR REPLACE INTO subsection VALUES (%s)"
                        % ",".join(["?"] * 17), [
                            r.get("subsection_id"), r.get("section_id"),
                            r.get("book_id"), r.get("subject"), r.get("grade"),
                            r.get("term"), r.get("unit_name"), r.get("title"),
                            r.get("seq"), r.get("page_from"), r.get("page_to"),
                            r.get("n_pages"), r.get("chars"), r.get("text"),
                            _j(r.get("blocks")), r.get("model") or "",
                            r.get("ts"),
                        ])
            nsb += 1
            _tick(nsb)

    nex = 0
    if os.path.exists(EXAMPLE_FILE):
        for l in open(EXAMPLE_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if not r.get("stem"):
                continue          # 空壳：该节没有题目
            con.execute("INSERT OR REPLACE INTO example VALUES (%s)"
                        % ",".join(["?"] * 24), [
                            r.get("example_id"), r.get("section_id"),
                            r.get("subsection_id") or "",
                            r.get("book_id"), r.get("subject"), r.get("grade"),
                            r.get("term"), r.get("unit_name"), r.get("title"),
                            r.get("name"), r.get("type"), r.get("stem"),
                            r.get("given"), r.get("ask"), _j(r.get("steps")),
                            _j(r.get("latex")),
                            r.get("answer"), r.get("answer_latex"),
                            r.get("keypoint"), r.get("difficulty"),
                            r.get("page_hint"), _j(r.get("formula_refs")),
                            r.get("model"), r.get("ts"),
                        ])
            nex += 1
            _tick(nex)

    ndia = 0
    if os.path.exists(EN_DIALOGUE_FILE):
        for l in open(EN_DIALOGUE_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if not r.get("turns"):
                continue          # 空壳：该节没有对话
            con.execute("INSERT OR REPLACE INTO en_dialogue VALUES (%s)"
                        % ",".join(["?"] * 15), [
                            r.get("dialogue_id"), r.get("section_id"),
                            r.get("book_id"), r.get("subject"), r.get("grade"),
                            r.get("term"), r.get("unit_name"), r.get("title"),
                            r.get("scene"), r.get("function"),
                            _j(r.get("turns")), _j(r.get("patterns")),
                            r.get("page_hint"), r.get("model") or "", r.get("ts"),
                        ])
            ndia += 1

    ngra = 0
    if os.path.exists(EN_GRAMMAR_FILE):
        for l in open(EN_GRAMMAR_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if not r.get("point"):
                continue
            con.execute("INSERT OR REPLACE INTO en_grammar VALUES (%s)"
                        % ",".join(["?"] * 17), [
                            r.get("grammar_id"), r.get("section_id"),
                            r.get("book_id"), r.get("subject"), r.get("grade"),
                            r.get("term"), r.get("unit_name"), r.get("title"),
                            r.get("point"), r.get("pattern"), r.get("rule"),
                            r.get("category"), r.get("tense"),
                            _j(r.get("examples")), r.get("page_hint"),
                            r.get("model") or "", r.get("ts"),
                        ])
            ngra += 1

    nph = 0
    if os.path.exists(EN_PHONICS_FILE):
        for l in open(EN_PHONICS_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if not r.get("letters"):
                continue
            con.execute("INSERT OR REPLACE INTO en_phonics VALUES (%s)"
                        % ",".join(["?"] * 15), [
                            r.get("phonics_id"), r.get("section_id"),
                            r.get("book_id"), r.get("subject"), r.get("grade"),
                            r.get("term"), r.get("unit_name"), r.get("title"),
                            r.get("letters"), r.get("sound"),
                            _j(r.get("examples")), r.get("chant"),
                            r.get("page_hint"), r.get("model") or "", r.get("ts"),
                        ])
            nph += 1

    npsg = 0
    if os.path.exists(EN_PASSAGE_FILE):
        for l in open(EN_PASSAGE_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if not (r.get("text") or "").strip():
                continue          # 空壳：该节没有成篇内容
            con.execute("INSERT OR REPLACE INTO en_passage VALUES (%s)"
                        % ",".join(["?"] * 20), [
                            r.get("passage_id"), r.get("section_id"),
                            r.get("book_id"), r.get("subject"), r.get("grade"),
                            r.get("term"), r.get("unit_name"), r.get("title"),
                            r.get("name"), r.get("genre"), r.get("source"),
                            r.get("text"), r.get("zh"), r.get("topic"),
                            _j(r.get("words")), _j(r.get("comprehension")),
                            r.get("writing_task"), _j(r.get("keypoints")),
                            r.get("model") or "", r.get("ts"),
                        ])
            npsg += 1

    npj = 0
    if os.path.exists(EN_PROJECT_FILE):
        for l in open(EN_PROJECT_FILE, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if not r.get("name"):
                continue
            con.execute("INSERT OR REPLACE INTO en_project VALUES (%s)"
                        % ",".join(["?"] * 17), [
                            r.get("project_id"), r.get("section_id"),
                            r.get("book_id"), r.get("subject"), r.get("grade"),
                            r.get("term"), r.get("unit_name"), r.get("title"),
                            r.get("name"), r.get("type"), r.get("goal"),
                            _j(r.get("steps")), _j(r.get("language")),
                            r.get("product"), _j(r.get("materials")),
                            r.get("model") or "", r.get("ts"),
                        ])
            npj += 1

    nfig = 0
    idx_path = os.path.join(config.FIGURES_DIR, "_index.jsonl")
    if os.path.exists(idx_path):
        seen = set()
        for l in open(idx_path, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            key = (r.get("book_id"), r.get("page_no"))
            if key in seen:
                continue
            seen.add(key)
            fp = os.path.join(config.FIGURES_DIR, str(r.get("book_id")),
                              "%04d.md" % int(r.get("page_no") or 0))
            text = ""
            if os.path.exists(fp):
                text = open(fp, encoding="utf-8").read()
            con.execute("INSERT OR REPLACE INTO page_figure VALUES (?,?,?,?,?,?)", [
                r.get("book_id"), r.get("page_no"), r.get("figures") or 0,
                text, r.get("model"), r.get("ts"),
            ])
            nfig += 1
            _tick(nfig)

    con.close()
    stat = {"books": nb, "lessons": nl, "words": nw, "lesson_text": nt,
            "lesson_meta": nm, "piece": npi, "lesson_genre": ng,
            "lesson_structure": nst, "lesson_glossary": ngl,
            "lesson_translation": ntr, "lesson_author": nau, "author_intro": nin,
            "section_text": nse, "section_keypoint": nkp,
            "en_vocab": nvocab, "en_expr": nexpr, "section_formula": nfo,
            "experiment": nexp, "concept": ncp, "page_figure": nfig,
            "example": nex, "en_dialogue": ndia, "en_grammar": ngra,
            "en_phonics": nph, "en_passage": npsg, "en_project": npj,
            "subsection": nsb, "unit_element": nel, "unit_map": nmp,
            "math_unit": nun, "db": DB_PATH}
    if verbose:
        print("建库完成：%d 册 / %d 条目 / %d 字词条 / %d 篇课文 / %d 条元数据 / "
              "%d 篇 / %d 条细分体裁 / %d 条结构 / %d 条词语 / %d 条译文 / "
              "%d 条作者 / %d 条简介 / %d 节 / %d 条知识点 / "
              "%d 英语词 / %d 英语表达 / %d 条公式 / %d 个探究 / %d 个概念 / "
              "%d 页插图 / %d 道例题 / %d 段对话 / %d 条语法 / %d 条拼读 / "
              "%d 段语篇 / %d 个项目 / %d 个课时 / %d 个单元要素 / "
              "%d 张结构图 / %d 个单元单位符号 → %s"
              % (nb, nl, nw, nt, nm, npi, ng, nst, ngl, ntr, nau, nin, nse, nkp,
                 nvocab, nexpr, nfo, nexp, ncp, nfig, nex, ndia, ngra, nph,
                 npsg, npj, nsb, nel, nmp, nun, DB_PATH))
    return stat


def query(sql: str, verbose: bool = True):
    con = connect()
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        con.close()
    if verbose:
        print(" | ".join(cols))
        print("-" * min(80, max(20, len(" | ".join(cols)))))
        for r in rows[:50]:
            print(" | ".join("" if v is None else str(v) for v in r))
        if len(rows) > 50:
            print("… 共 %d 行" % len(rows))
    return cols, rows
