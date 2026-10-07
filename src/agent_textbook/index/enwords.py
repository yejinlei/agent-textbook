# -*- coding: utf-8 -*-
"""英语词汇属性层：单元词汇表 + 总词汇表 + 常用表达。

英语的本体核心不是"课文"，而是**词与表达**：教材把词汇集中放在附录
（`Words in each unit` / `Vocabulary` / `Useful expressions`），文本层排版规整：

    Unit 1
    *where /weə(r)/ 在哪里；到哪里	p. 4
    *from /frɒm/ （表示来源）
    *来自，从……来
    p. 4

坑：一条词常被排版切成 3 行（词+音标 / 释义续行 / 页码单独成行），
必须带状态累积，不能逐行独立解析；`*` 是课标二级词标记，不是词的一部分。

产物：
    attrs/en_vocab.jsonl  词（主键 vocab_id = 册:词:单元）
    attrs/en_expr.jsonl   常用表达/功能句（主键 expr_id）
"""

from __future__ import annotations

import json
import os
import re

from .. import config

VOCAB_FILE = os.path.join(config.ATTRS_DIR, "en_vocab.jsonl")
EXPR_FILE = os.path.join(config.ATTRS_DIR, "en_expr.jsonl")

# `Words in each unit`（按单元）/ `Vocabulary`（总表，字母序）/ `Useful expressions`
RE_UNIT_HEAD = re.compile(r"^Unit\s*(\d+)\s*$", re.I)
# 词条头：`*where /weə(r)/ 在哪里；到哪里   p. 4`
RE_HEAD = re.compile(
    r"^\*?(?P<word>[A-Za-z][A-Za-z'\-\. ]*?)\s*/(?P<ph>[^/]{1,40})/\s*(?P<rest>.*)$"
)
RE_PAGE = re.compile(r"^p\.\s*(\d{1,3})\s*$", re.I)
RE_PAGE_INLINE = re.compile(r"\s*p\.\s*(\d{1,3})\s*$", re.I)
# 释义噪声：注脚里说明星号/黑体含义，不是词条
RE_NOISE = re.compile(r"^(注|Vocabulary|Words in each unit|Useful expressions|"
                      r"注：|黑体词|白体词|附录)", re.I)
RE_EXPR = re.compile(r"^(?P<en>[A-Za-z][^。；;]{2,80}[.?!]?)\s+(?P<zh>[\u4e00-\u9fff][^。]{1,60})$")


def _iter_books(subject: str = "英语"):
    """遍历 parsed 册，产出 (book_id, meta, pages)。"""
    if not os.path.isdir(config.PARSED_DIR):
        return
    for fn in sorted(os.listdir(config.PARSED_DIR)):
        if not fn.endswith(".jsonl"):
            continue
        bid = fn[:-6]
        path = os.path.join(config.PARSED_DIR, fn)
        rows = []
        with open(path, encoding="utf-8") as f:
            for l in f:
                if l.strip():
                    rows.append(json.loads(l))
        meta = next((r for r in rows if r.get("type") == "meta"), None)
        if not meta:
            continue
        if subject and meta.get("subject") != subject:
            continue
        pages = [r for r in rows if r.get("type") == "page"]
        yield bid, meta, pages


def _term_of(meta: dict) -> str:
    t = meta.get("title", "")
    return "上册" if "上册" in t else ("下册" if "下册" in t else "")


def _appendix_pages(pages: list[dict], keyword: str) -> list[dict]:
    """找含某附录标题的页（英文教材附录在书末，从后往前找更快也更准）。"""
    out = []
    for p in pages:
        t = p.get("text") or ""
        if keyword.lower() in t.lower():
            out.append(p)
    return out


def parse_vocab(pages: list[dict], book_id: str, meta: dict) -> list[dict]:
    """抽词汇：先按单元的 `Words in each unit`，再补总表 `Vocabulary`。"""
    grade = meta.get("grade", "")
    term = _term_of(meta)
    out, seen = [], set()

    def flush(cur, unit_no, source):
        if not cur:
            return
        # 落盘前再兜一次底：释义里若整个是「词/音标/中文」，说明这是同一词组
        # 的后半截（总表页排版与单元表不同，前面的同行合并未必覆盖得到）。
        mean = (cur.get("mean") or "").strip()
        mean = re.sub(r"^/[^/]{1,40}/\s*", "", mean)   # 前导多余音标
        m = RE_HEAD.match(mean)
        if m and RE_ZH.search(m.group("rest")):
            cur = dict(cur)
            cur["word"] = (cur["word"] + " " + m.group("word").strip()).strip()
            cur["ph"] = ((cur.get("ph") or "") + " " + m.group("ph").strip()).strip()
            mean = m.group("rest").lstrip("*").strip()
        cur["mean"] = mean
        word = cur["word"].strip().strip("*").strip()
        if not word:
            return
        key = (word.lower(), unit_no)
        if key in seen:
            return
        seen.add(key)
        ph = (cur.get("ph") or "").strip()
        # 音标偶尔整段落到字体私有区（\uf022…），那是乱码不是音标，宁可留空
        if any("\ue000" <= ch <= "\uf8ff" for ch in ph):
            ph = ""
        out.append({
            "vocab_id": "%s:%s:%s" % (book_id, word.lower(), unit_no or 0),
            "book_id": book_id,
            "subject": "英语",
            "grade": grade,
            "term": term,
            "unit_no": unit_no,
            "word": word,
            "phonetic": ph,
            "meaning": re.sub(r"\s+", "", cur.get("mean") or ""),
            "level": cur.get("level") or "",
            "printed_page": cur.get("page"),
            "source": source,
        })

    for keyword, source in (("Words in each unit", "unit"), ("Vocabulary", "vocab")):
        for p in _appendix_pages(pages, keyword):
            unit_no = None
            cur = None
            for ln in (p.get("text") or "").split("\n"):
                ln = ln.replace("\t", " ").strip()
                if not ln or RE_NOISE.search(ln):
                    continue
                # 页码单独成行 → 收尾当前词
                mp = RE_PAGE.match(ln)
                if mp and cur is not None:
                    cur["page"] = int(mp.group(1))
                    flush(cur, unit_no, source)
                    cur = None
                    continue
                mu = RE_UNIT_HEAD.match(ln)
                if mu:
                    flush(cur, unit_no, source)
                    cur = None
                    unit_no = int(mu.group(1))
                    continue
                mh = RE_HEAD.match(ln)
                if mh:
                    rest = mh.group("rest")
                    page = None
                    mpi = RE_PAGE_INLINE.search(rest)
                    if mpi:
                        page = int(mpi.group(1))
                        rest = rest[:mpi.start()]
                    # 同行挤了整个词组：`*a lot /lɒt/ of/əv/大量；许多`、
                    # `*office /ˈɒfɪs/ worker/ˈwɜːkə(r)/公司职员`。
                    # 括号里的复数说明（`（复数children/…/）`）以中文开头，不会被误判。
                    m2 = RE_HEAD.match(rest.strip())
                    if m2 and RE_ZH.search(m2.group("rest")):
                        cur2 = {
                            "word": (mh.group("word").strip() + " "
                                     + m2.group("word").strip()),
                            "ph": mh.group("ph").strip() + " " + m2.group("ph").strip(),
                            "mean": m2.group("rest").lstrip("*").strip(),
                            "level": cur_level(ln),
                            "page": page,
                        }
                        flush(cur2, unit_no, source)
                        cur = None
                        continue
                    # 词组被拆成两行：`*office /ˈɒfɪs/` 换行 `worker/ˈwɜːkə(r)/公司职员`。
                    # 上一行只有词和音标、没有释义，就是同一词组的后半截，必须合并，
                    # 否则会得到 office = worker/…/公司职员 这种脏数据。
                    if cur is not None and not cur.get("mean"):
                        cur["word"] = (cur["word"] + " " + mh.group("word").strip()).strip()
                        cur["ph"] = (cur["ph"] + " " + mh.group("ph").strip()).strip()
                        cur["mean"] = rest.lstrip("*").strip()
                        if page is not None:
                            cur["page"] = page
                            flush(cur, unit_no, source)
                            cur = None
                        continue
                    flush(cur, unit_no, source)
                    cur = {
                        "word": mh.group("word").strip(),
                        "ph": mh.group("ph").strip(),
                        "mean": rest.strip().lstrip("*").strip(),
                        "level": "二级" if ln.startswith("*") else "",
                        "page": page,
                    }
                    if page is not None:
                        flush(cur, unit_no, source)
                        cur = None
                    continue
                if cur is not None:
                    # 释义续行（常带前导 *），页码也可能跟在这一行尾
                    tail = ln.lstrip("*").strip()
                    mpi = RE_PAGE_INLINE.search(tail)
                    if mpi:
                        cur["page"] = int(mpi.group(1))
                        tail = tail[:mpi.start()]
                    if tail:
                        cur["mean"] = (cur["mean"] + tail).strip()
                        if RE_PAGE_INLINE.search(tail) or (
                                tail and not tail.endswith(("。", "；", ";"))):
                            pass
                    if cur.get("page") is not None:
                        flush(cur, unit_no, source)
                        cur = None
            flush(cur, unit_no, source)
    return out


RE_ZH = re.compile(r"[\u4e00-\u9fff]")


def cur_level(ln: str) -> str:
    """行首 `*` 是课标二级词标记。"""
    return "二级" if ln.startswith("*") else ""


def parse_expressions(pages: list[dict], book_id: str, meta: dict) -> list[dict]:
    """抽 `Useful expressions` 常用表达：英文（可能跨行）+ 中文一行，按单元分组。

    标题页往往只有 `Appendix 4 / Useful expressions` 一行，真正的句子在其后
    几页，所以命中页之后要再往后翻几页。
    """
    grade = meta.get("grade", "")
    term = _term_of(meta)
    out, seq = [], [0]
    for p in _appendix_pages(pages, "Useful expressions"):
        start = pages.index(p)
        for p2 in pages[start:start + 5]:
            unit_no = None
            pending = []
            for ln in (p2.get("text") or "").split("\n"):
                ln = ln.replace("\t", " ").strip()
                if not ln:
                    continue
                mu = RE_UNIT_HEAD.match(ln)
                if mu:
                    pending = []
                    unit_no = int(mu.group(1))
                    continue
                if ln.startswith("注") or "expressions" in ln.lower() \
                        or ln.startswith("Appendix"):
                    continue
                if RE_ZH.search(ln):
                    if not pending:
                        continue
                    seq[0] += 1
                    out.append({
                        "expr_id": "%s:%03d" % (book_id, seq[0]),
                        "book_id": book_id,
                        "subject": "英语",
                        "grade": grade,
                        "term": term,
                        "unit_no": unit_no,
                        "en": " ".join(pending).strip(),
                        "zh": ln.strip(),
                        "printed_page": p2.get("printed_no"),
                    })
                    pending = []
                    continue
                if re.match(r"^[A-Za-z]", ln):
                    pending.append(ln)
                else:
                    pending = []
    return out


def enrich(subject: str = "英语", verbose: bool = True) -> dict:
    """给词汇表补**教材原文例句**与所属话题。

    词汇层原来只有 词/音标/释义/级别，做动画或出题时缺两样：这个词在教材里
    到底怎么用（例句）、它属于哪个话题（主题）。两者都不用模型生成——例句直接
    从已抽好的对话、语篇、语法例句里按全词匹配取原句，话题取该词所在单元的
    单元名；教材里没出现过的词就留空。零幻觉，也不会凭空造句。
    """
    if not os.path.exists(VOCAB_FILE):
        return {"n": 0, "with_example": 0}
    vocab = [json.loads(l) for l in open(VOCAB_FILE, encoding="utf-8") if l.strip()]
    if subject:
        vocab = [r for r in vocab if r.get("subject") == subject]

    # (book_id, grade) → 教材原句（对话话轮 / 语篇正文 / 语法例句）
    sents: dict[tuple, list[str]] = {}

    def add(key, text):
        bucket = sents.setdefault(key, [])
        for ln in (text or "").split("\n"):
            s = ln.strip()
            if 3 < len(s) < 160 and re.search(r"[A-Za-z]", s) and s not in bucket:
                bucket.append(s)

    for fn, fields in (("en_dialogue", "turns"), ("en_grammar", "examples"),
                       ("en_passage", None)):
        p = os.path.join(config.ATTRS_DIR, fn + ".jsonl")
        if not os.path.exists(p):
            continue
        for l in open(p, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            key = (r.get("book_id"), r.get("grade"))
            if fields == "turns":
                for t in (r.get("turns") or []):
                    add(key, (t.get("en") or "") if isinstance(t, dict) else str(t))
            elif fields == "examples":
                for t in (r.get("examples") or []):
                    add(key, (t.get("en") or "") if isinstance(t, dict) else str(t))
            else:
                add(key, r.get("text"))

    # 单元号 → 单元名（话题）：取同一册同一单元的小节标题
    topic: dict[tuple, str] = {}
    sp = os.path.join(config.ATTRS_DIR, "section_text.jsonl")
    if os.path.exists(sp):
        for l in open(sp, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if subject and r.get("subject") != subject:
                continue
            u = r.get("unit_no")
            if isinstance(u, int):
                topic.setdefault((r.get("book_id"), u), r.get("title") or "")

    n = 0
    for r in vocab:
        w = (r.get("word") or "").strip()
        pat = (re.compile(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", re.I)
               if w else None)
        got = []
        if pat:
            for key in ((r.get("book_id"), r.get("grade")), (None, r.get("grade"))):
                for s in sents.get(key) or ():
                    if pat.search(s) and s not in got:
                        got.append(s)
                    if len(got) >= 2:
                        break
                if len(got) >= 2:
                    break
        r["example"] = got[:2]
        r["topic"] = (topic.get((r.get("book_id"), r.get("unit_no")), "")
                      if isinstance(r.get("unit_no"), int) else "")
        if got:
            n += 1
    with open(VOCAB_FILE, "w", encoding="utf-8") as f:
        for r in vocab:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if verbose:
        print("→ %s（%d 词，%d 个补到教材原句）" % (VOCAB_FILE, len(vocab), n))
    return {"n": len(vocab), "with_example": n}


def build_all(subject: str = "英语", verbose: bool = True) -> dict:
    """重建英语词汇/表达两个属性层（全量覆盖写）。"""
    os.makedirs(config.ATTRS_DIR, exist_ok=True)
    nv = ne = 0
    with open(VOCAB_FILE, "w", encoding="utf-8") as fv, \
            open(EXPR_FILE, "w", encoding="utf-8") as fe:
        for bid, meta, pages in _iter_books(subject):
            vs = parse_vocab(pages, bid, meta)
            for r in vs:
                fv.write(json.dumps(r, ensure_ascii=False) + "\n")
            nv += len(vs)
            es = parse_expressions(pages, bid, meta)
            for r in es:
                fe.write(json.dumps(r, ensure_ascii=False) + "\n")
            ne += len(es)
            if verbose:
                print("  %s%s 词 %d / 表达 %d" % (meta.get("grade", ""), _term_of(meta),
                                                  len(vs), len(es)))
    if verbose:
        print("→ %s（%d 条）" % (VOCAB_FILE, nv))
        print("→ %s（%d 条）" % (EXPR_FILE, ne))
    return {"vocab": nv, "expr": ne}
