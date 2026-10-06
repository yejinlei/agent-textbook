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
        newchars VARCHAR)""",
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
]


def connect() -> duckdb.DuckDBPyConnection:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    return duckdb.connect(DB_PATH)


def build(subject: str = "语文", verbose: bool = True) -> dict:
    """重建库并导入目录与字表。"""
    con = connect()
    for ddl in SCHEMA:
        con.execute(ddl)
    for t in ("books", "lessons", "words", "lesson_text", "lesson_meta", "piece"):
        con.execute(f"DELETE FROM {t}")

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
            con.execute("INSERT OR REPLACE INTO lesson_text VALUES (%s)" % ",".join(["?"] * 22), [
                r.get("lesson_id"), r.get("book_id"), r.get("grade"), r.get("term"),
                r.get("unit_no"), r.get("unit_name"), r.get("section"), r.get("lesson_no"),
                r.get("title"), r.get("printed_start"), r.get("printed_end"),
                r.get("page_from"), r.get("page_to"), r.get("n_pages"), r.get("chars"),
                r.get("text"), r.get("text_plain"),
                _j(r.get("paragraphs")), _j(r.get("tasks")),
                _j(r.get("exercises")), _j(r.get("notes")), _j(r.get("newchars")),
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

    con.close()
    stat = {"books": nb, "lessons": nl, "words": nw,
            "lesson_text": nt, "lesson_meta": nm, "piece": npi, "db": DB_PATH}
    if verbose:
        print("建库完成：%d 册 / %d 条目 / %d 字词条 / %d 篇课文 / %d 条元数据 / %d 篇 → %s"
              % (nb, nl, nw, nt, nm, npi, DB_PATH))
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
