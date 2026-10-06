# -*- coding: utf-8 -*-
"""字表抽取（知识库 L1 资产）：识字表 / 写字表 / 词语表，外挂属性靠它挂载。

排版事实（实测 12 册）：
    识字表 ：`1 | 天 | tiān | 地 | dì ...`        字与拼音交替，含注释行
    写字表 ：一上带拼音；二年级起 `1 \t 坡球招呼…`  课序号 + 连续字串（无拼音）
    词语表 ：`1\t 山坡 学校 飘扬 …`                课序号 + 空格分词

两个坑：
  * 附录标题带空格（`写 字 表`），必须去空白后匹配。
  * 识字表首行有注释（"① 识字表中蓝色的字…不计入生字总数"），整句是汉字，
    不跳过就会被当成几百个"生字"。判据：含中文标点或 ① 的行一律跳过。

产物 data/attrs/words.jsonl：{book_id, grade, term, kind, lesson_no, value, pinyin, page_no}
"""

import json
import os
import re

from .. import config
from . import outline as ol

WS = re.compile(r"\s+")
RE_PINYIN = re.compile(r"^[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüńňǹ]+$")
RE_CJK = re.compile(r"^[一-鿿]+$")
RE_NUM = re.compile(r"^\d{1,3}$")
# 注释行/句子：含中文标点或注释圈码
RE_NOISE_LINE = re.compile(r"[，。、；：？！“”（）]|①|②|③|不计入|说明|注")

APPENDIX = ("识字表", "写字表", "词语表", "笔画名称表", "常用偏旁名称表")
# 只解析这三种；笔画/偏旁表只记录位置（一年级独有，格式是表头+例字）
PARSE_KINDS = ("识字表", "写字表", "词语表")


def _head_flat(rec: dict, n: int = 3) -> str:
    """页首若干行去空白——附录标题一定在页首。"""
    lines = (rec.get("text") or "").split("\n")[:n]
    return WS.sub("", "".join(lines))


# 附录在书末的固定顺序，用于纠正误命中
APPENDIX_ORDER = ("识字表", "写字表", "词语表", "笔画名称表", "常用偏旁名称表")
TAIL_RATIO = 0.7      # 只在书末 30% 里找附录


def find_appendix(pages: list[dict], toc_pages: set) -> dict:
    """定位附录首页，产出 [首页, 下一附录前) 的页范围。

    两个实测坑：
      * 标题有时不在页首（四上词语表 p131 页首就是词条），只扫页首会漏掉一半；
      * 书末有干扰页（四下 p123 是语文园地，却含"词语表"字样）。
    对策：只在书末 30% 找，再按 识字→写字→词语 的固定顺序强制页码单调递增。
    """
    tail_from = int(len(pages) * TAIL_RATIO)
    hits: dict[str, list[int]] = {}
    for p in pages:
        pn = p.get("page_no")
        if pn is None or pn in toc_pages or pn < tail_from:
            continue
        flat = WS.sub("", p.get("text") or "")
        for k in APPENDIX_ORDER:
            if k in flat:
                hits.setdefault(k, []).append(pn)

    starts: dict[str, int] = {}
    prev = -1
    for k in APPENDIX_ORDER:
        cands = sorted(x for x in hits.get(k, []) if x > prev)
        if cands:
            starts[k] = cands[0]
            prev = cands[0]

    keys = [k for k in APPENDIX_ORDER if k in starts]
    ranges = {}
    for idx, k in enumerate(keys):
        s = starts[k]
        e = starts[keys[idx + 1]] - 1 if idx + 1 < len(keys) else pages[-1].get("page_no")
        ranges[k] = (s, e)
    return ranges


# 目录/栏目名混在字表里（"识字 | 1 | 天 | tiān"），不当过滤会被当成生字
SECTION_TOKENS = (
    "识字", "阅读", "汉语拼音", "语文园地", "习作", "习作例文", "口语交际",
    "快乐读书吧", "综合性学习", "写字", "梳理与交流", "例文", "交流平台",
    "识字加油站", "书写提示", "词句段运用", "日积月累", "我爱阅读", "注音",
)
# 课序号上限：页码（如"121"）远大于此，避免被误当课号
MAX_LESSON_NO = 40


def _parse_block(lines: list[str], kind: str, default_lesson: str | None):
    """解析一个附录块。

    识字表的文本层是**每字/拼音各占一行**（"1" "天" "tiān" "地" "dì"），
    所以必须展平成 token 流再扫顺序，按行解析会丢光拼音和课序号。
    """
    tokens = []
    for raw in lines:
        line = raw.replace("\t", " ").strip()
        if not line or RE_NOISE_LINE.search(line):
            continue
        if WS.sub("", line) in APPENDIX:
            continue
        for t in line.split():
            if t in SECTION_TOKENS:
                continue
            tokens.append(t)

    out: list[tuple] = []
    lesson = default_lesson
    i = 0
    while i < len(tokens):
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if RE_NUM.match(t):
            # 数字后紧跟汉字才算课序号（排除页码）
            if RE_CJK.match(nxt) and int(t) <= MAX_LESSON_NO:
                lesson = t
            i += 1
            continue
        if RE_CJK.match(t):
            if len(t) == 1:
                if RE_PINYIN.match(nxt):          # 字 + 拼音交替
                    out.append((lesson, t, nxt))
                    i += 2
                    continue
                out.append((lesson, t, None))
                i += 1
                continue
            if kind == "词语表":                   # 词不拆
                out.append((lesson, t, None))
                i += 1
                continue
            for ch in t:                          # 写字表连续字串：逐字拆
                out.append((lesson, ch, None))
            i += 1
            continue
        i += 1                                    # 孤立拼音等噪声
    return out


def build_book(book_id: str) -> dict:
    meta, pages = ol.load_book(book_id)
    if not meta:
        return {}
    toc_pages = set(meta.get("toc_pages") or [])
    if not toc_pages:
        _, pgs = ol.load_book(book_id)
        toc_pages = set(pgs[i].get("page_no") for i in ol.find_toc_pages(pgs))
    ranges = find_appendix(pages, toc_pages)
    title = meta.get("title", "")
    term = "上册" if "上册" in title else ("下册" if "下册" in title else "")
    rows = []
    stat = {}
    for kind in PARSE_KINDS:
        if kind not in ranges:
            stat[kind] = 0
            continue
        s, e = ranges[kind]
        block = []
        for p in pages:
            pn = p.get("page_no")
            if pn is None or pn < s or pn > e:
                continue
            txt = p.get("text") or ""
            # 后记排在附录之后，整段都是文字，混进来会变成一堆假词
            if WS.sub("", txt[:30]).startswith("后记"):
                break
            block.extend(txt.split("\n"))
        # 首页去掉标题行
        block = [ln for ln in block if WS.sub("", ln) not in APPENDIX]
        items = _parse_block(block, kind, None)
        stat[kind] = len(items)
        for lesson, value, py in items:
            rows.append({
                "book_id": book_id,
                "grade": meta.get("grade", ""),
                "term": term,
                "kind": kind,
                "lesson_no": lesson,
                "value": value,
                "pinyin": py,
                "page_no": s,
            })
    return {"meta": {"book_id": book_id, "grade": meta.get("grade", ""), "term": term,
                     "title": title, "stat": stat,
                     "appendix": {k: list(v) for k, v in ranges.items()}},
            "rows": rows}


def build_all(subject: str = "", verbose: bool = True) -> list[dict]:
    if not os.path.isdir(config.PARSED_DIR):
        return []
    ids = sorted(f[:-6] for f in os.listdir(config.PARSED_DIR) if f.endswith(".jsonl"))
    out = []
    for bid in ids:
        meta, _ = ol.load_book(bid)
        if not meta:
            continue
        if subject and meta.get("subject") != subject:
            continue
        r = build_book(bid)
        if not r.get("rows"):
            continue
        out.append(r)
        if verbose:
            m = r["meta"]
            print("  %s%s 识字%d 写字%d 词语%d" % (
                m["grade"], m["term"][0], m["stat"].get("识字表", 0),
                m["stat"].get("写字表", 0), m["stat"].get("词语表", 0)))
    if out:
        os.makedirs(os.path.join(config.DATA_DIR, "attrs"), exist_ok=True)
        path = os.path.join(config.DATA_DIR, "attrs", "words.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in out:
                for row in r["rows"]:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if verbose:
            print("→ %s（%d 条）" % (path, sum(len(r["rows"]) for r in out)))
    return out
