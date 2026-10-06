# -*- coding: utf-8 -*-
"""篇（piece）子层：把「古诗三首 / 文言文二则」这类一课多篇拆成独立篇。

为什么必须有这一层：目录条目 ≠ 篇。一个「古诗三首」条目里装着 3 首诗、
2~3 个作者、2 个朝代；按条目建实体，作者/朝代/意象/译文全都无处安放。

来源以**目录为准**，不在正文里猜正则——目录里明写着子篇名与页码：

    3  古诗三首....11       14  文言文二则....80
       寒食........11           学弈..........80
       迢迢牵牛星..11           两小儿辩日....81
       十五夜望月..12

正文只用来**定位切分边界**：同一页上有多首时，从本篇题名所在行切到下一篇
题名行之前（目录只给页码，同页多首必须靠正文才能分开）。

产物 data/attrs/piece.jsonl，靠 lesson_id 挂回父条目。
"""

import json
import os
import re

from .. import config
from . import lessons as L

PIECE_FILE = os.path.join(config.ATTRS_DIR, "piece.jsonl")

# 父条目（课题）特征：教材里一课多篇的命名惯例
RE_PARENT = re.compile(r"(古诗|古诗词|文言文|现代诗|短诗|诗|词|曲)|(首|则|组|篇)$")
# 栏目与附录：无课号的条目里大量是这些，不是子篇
RE_COLUMN = re.compile(
    r"^(口语交际|习作|语文园地|综合性学习|快乐读书吧|我爱阅读|日积月累|"
    r"梳理与交流|专题学习|演讲|交流平台|初试身手|写字|识字|选读)")
RE_APPENDIX = re.compile(r"(写字表|识字表|词语表|附录|后记|索引|注音表)$")
RE_NOTE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]")
# 朝代标记：`[唐]` / `〔宋〕`。作者**不在这里抽**：题名与首句粘连时
# （`[明]于谦千锤万凿出深山，`）无法切准，硬取会污染作者字段，留待 LLM 校对。
RE_DYNASTY = re.compile(
    r"[\[〔(（]\s*(西汉|东汉|汉|三国|魏|晋|南北朝|唐|五代|宋|元|明|清)\s*[\]〕)）]")
RE_CJK_ONLY = re.compile(r"^[一-鿿]{2,4}$")
RE_SENT = re.compile(r"(?<=[，。！？；])")
RE_TASK = re.compile(r"^(有感情地)?(朗读|背诵|默读|分角色朗读|复述|默写)")


def norm(s: str) -> str:
    """归一化：去掉空白、间隔号与**零宽字符**。

    零宽空格（U+200B 等）是文本层/VLM 产物的常客，目录里就出现过
    `示儿\u200b`——不清掉的话篇题永远匹配不上正文里的 `示儿`。
    """
    return re.sub(r"[\s　·•・​-‏﻿]", "", s or "")


def strip_title(line: str, title: str) -> str:
    """从行首剥掉篇题，返回剩余部分（保留原始空格与后续内容）。"""
    t = norm(title)
    i = j = 0
    while j < len(t) and i < len(line):
        # 教材用 EM SPACE(\u2003)/EN SPACE(\u2002) 撑开诗题（`寒  食`），
        # 只认空格和全角空格会漏，一律按 isspace 跳过。
        if line[i].isspace():
            i += 1
            continue
        if line[i] == t[j]:
            i += 1
            j += 1
            continue
        break
    return line[i:] if j == len(t) else line


def find_head(lines: list[str], title: str, after: int = 0) -> int:
    """定位篇题在正文行中的起点；找不到返回 -1。

    两个实测障碍：
      * 排版会把题名拆成多行（`亡` / `羊补` / `牢`），逐行比不了，必须拼起来找；
      * 注释里几乎必然出现题名（`①〔寒食〕寒食节…`），会抢在正文前面误命中。

    故按可信度排序：① 题名后紧跟朝代标记（`寒食[唐]`）最可靠，注释里的
    `〔寒食〕` 是题名**前**有括号，不会命中；② 退而求其次，题名后 24 字内
    出现句读，说明后面接着正文而不是注释。
    """
    t = norm(title)
    if not t:
        return -1
    joined: list[str] = []
    owner: list[int] = []
    for i in range(after, len(lines)):
        if RE_NOTE.match(lines[i]):
            continue
        for ch in norm(lines[i]):
            joined.append(ch)
            owner.append(i)
    s = "".join(joined)
    if not s:
        return -1
    pat = re.escape(t)
    for m in re.finditer(pat + r"[\[〔(（]", s):
        return owner[m.start()]
    for m in re.finditer(pat, s):
        # 题名后紧接收尾标点（`…有感》。借助注释…`）说明是**引用**这个篇名
        # 的课后题，不是篇题本身——照旧匹配会把整篇定位到课后题区。
        if s[m.end():m.end() + 1] in ("》", "」", "』", "）", ")"):
            continue
        if re.search(r"[，。！？、]", s[m.end():m.end() + 24]):
            return owner[m.start()]
    return -1


def split_sentences(text: str) -> list[str]:
    """按句读切句——古诗一句就是一联，逗号也要断。"""
    out = []
    cur = ""
    for ch in text:
        cur += ch
        if ch in "，。！？；":
            out.append(cur.strip())
            cur = ""
    if cur.strip():
        out.append(cur.strip())
    return [s for s in out if s]


def collect_subentries(entries: list[dict]) -> list[tuple[dict, dict, int]]:
    """挑出子篇：无课号、最近的**有课号祖先**是一课多篇的课题。

    父判定用「最近的有课号条目」而不是「前一条」——否则
    `古诗三首 / 寒食 / 迢迢牵牛星` 里，迢迢牵牛星的前一条（寒食）
    同样没有课号，会被漏掉。

    同时返回子篇在目录中的下标：正文区间要延伸到**最后一个子篇之后**的
    条目，只取父课起始页会把后面几首（在下一页）整篇丢掉。
    """
    out = []
    last_no = None
    for i, e in enumerate(entries):
        if e.get("lesson_no"):
            last_no = e
            continue
        if last_no is None:
            continue
        t = re.sub(r"[​-‏﻿]", "", (e.get("title") or "").strip())
        if not t or RE_COLUMN.search(t) or RE_APPENDIX.search(t):
            continue
        if not RE_PARENT.search(last_no.get("title") or ""):
            continue
        sub = dict(e)
        sub["title"] = t
        out.append((last_no, sub, i))
    return out


def clean_lines(lines: list[str], newchars: set | None = None,
                titles: list[str] | None = None,
                parent_title: str = "") -> list[str]:
    """行级清洗：篇级切分必须自己洗一遍，不能指望 lesson 层。

    lesson 层的清洗发生在**段落**切分之后，而篇是直接在行上切的，
    于是什么都没过滤——实测《石灰吟》尾部挂着课后题与生字条
    （`借助注释，说说下面诗句的意思…络锤凿焚`），《寒食》尾部挂着
    下一篇的注释碎片，全靠这一步去掉。

    与 lesson 层同样采取"正文是连续块"的截断策略：遇到课后题或
    阅读链接就丢弃其后所有行。
    """
    ts = [norm(t) for t in (titles or []) if t]
    # 页眉碎片：`三首古诗`（父课题名打散后的几个字）。判据是字符全部落在
    # 父课题名里且没有句读——正文短句不会这么巧。
    pchars = set(norm(parent_title))
    out = []
    skip = 0  # 注释块：栏名行之后还跟着若干解释行，一并去掉
    for ln in lines:
        s = L.RE_FIGURE.sub("", ln.strip())
        s = L.RE_PAGENO.sub("", s)
        if not s or not re.search(r"[一-鿿]", s):
            continue
        # 含篇题的行一律保住：`15 十五夜望月` 长得像页眉（数字+短串），
        # 按页眉删掉之后这一篇就永远定位不到了。
        has_title = any(t and t in norm(s) for t in ts)
        if skip:
            skip -= 1
            if not has_title:
                continue
        if L.RE_HEADNUM.match(s) and not has_title:
            continue
        if L.RE_NOTE.match(s):
            continue
        if s.startswith("注释"):
            skip = 3
            continue
        if (not has_title and len(pchars) >= 3 and 2 <= len(s) <= 8
                and set(s) <= pchars):
            continue
        # 只跳过、不截断：同一页上诗歌与课后题可能交替出现（注释/习题
        # 排在页底，下一篇的正文反而排在它们之后），一截断就把后面的
        # 篇整首丢了——实测《十五夜望月》《竹石》就是这样没的。
        if not has_title and (L.RE_EXERCISE.search(s) or L.RE_TASK_HEAD.search(s)):
            continue
        m = L.RE_EXE_INLINE.search(s)
        if m and not has_title:
            # 课后题粘在这一行里，只留前半截
            s = s[:m.start()].strip()
            if not s:
                continue
        if L.RE_LINK.search(s) and not has_title:
            continue
        # 整行都是本课生字（`络锤凿焚`）＝页边字条
        if (newchars and not has_title and len(s) >= 4
                and all(c in newchars for c in s)):
            continue
        out.append(s)
    return out


def build_piece(parent: dict, subs: list[dict], lines: list[str],
                printed_end: int, newchars: set | None = None) -> list[dict]:
    """按目录子篇切父课的正文行。"""
    lines = clean_lines(lines, newchars, [s.get("title") or "" for s in subs],
                        parent.get("title") or "")
    if not lines:
        return [{
            "title": s.get("title"), "seq": i + 1, "located": False,
            "printed_start": s.get("printed_start"), "printed_end": None,
            "dynasty": None, "author": None, "text": "",
            "sentences": [], "notes": [], "chars": 0,
        } for i, s in enumerate(subs)]

    # 必须**顺序**查找：每篇只在前一篇之后找。若各自从行 0 找，
    # 后一篇会命中注释里重复出现的题名（`①〔寒食〕…`）而撞车，
    # 再按单调性校正就把它判死了——实测组内第 2、3 篇正是这样丢的。
    marks = []
    after = 0
    for s in subs:
        m = find_head(lines, s.get("title") or "", after)
        marks.append(m)
        if m != -1:
            after = m + 1

    out = []
    for i, s in enumerate(subs):
        st = marks[i]
        located = st != -1
        nxt = next((m for m in marks[i + 1:] if m != -1), len(lines))
        seg = lines[st:nxt] if located else []
        if located:
            body = list(seg)
            # 题名可能与朝代/作者同一行（`寒 食[唐] 韩 翃`），也可能独占一行，
            # 后者朝代在**下一行**，故前两行都要看。
            body[0] = strip_title(body[0], s.get("title") or "").strip()
            dynasty = author = None
            for k in range(min(2, len(body))):
                m = RE_DYNASTY.search(body[k])
                if not m:
                    continue
                dynasty = m.group(1)
                rest = (body[k][:m.start()] + body[k][m.end():]).strip()
                cand = norm(rest)
                if RE_CJK_ONLY.match(cand):
                    author = cand
                    rest = ""
                elif not cand and k + 1 < len(body) and \
                        RE_CJK_ONLY.match(norm(body[k + 1])):
                    author = norm(body[k + 1])
                    body[k + 1] = ""
                body[k] = rest
                break
            body = [x for x in body if x.strip()]
        else:
            dynasty = author = None
            body = []

        # 注释两种形态：编号条目（`①〔洞庭〕…`）与栏名粘连的正文（`注释者不详，`）
        notes = [x for x in body if RE_NOTE.match(x) or x.startswith("注释")]
        body = [x for x in body
                if not (RE_NOTE.match(x) or x.startswith("注释")) and not RE_TASK.match(x)]
        text = "".join(body)
        p = {
            "title": s.get("title"),
            "seq": i + 1,
            "printed_start": s.get("printed_start"),
            "printed_end": (
                (subs[i + 1]["printed_start"] - 1)
                if i + 1 < len(subs) and isinstance(subs[i + 1].get("printed_start"), int)
                and subs[i + 1]["printed_start"] > (s.get("printed_start") or 0)
                else printed_end),
            "dynasty": dynasty,
            "author": author,
            "located": located,
            "text": text,
            "sentences": split_sentences(text),
            "notes": notes,
            "chars": len(norm(text)),
        }
        out.append(p)
    return out


def build_book(book_id: str) -> list[dict]:
    from . import lessons as L
    from . import outline as ol

    path = os.path.join(config.OUTLINE_DIR, book_id + ".jsonl")
    if not os.path.exists(path):
        return []
    rs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    if len(rs) < 2:
        return []
    head, entries = rs[0], rs[1:]
    subs = collect_subentries(entries)
    if not subs:
        return []

    meta, pages = ol.load_book(book_id)
    by = L.printed_index(pages, set(head.get("toc_pages") or []))
    maxp = max(by) + 1 if by else 0

    by_parent: dict[str, list[tuple[dict, int]]] = {}
    for p, s, i in subs:
        by_parent.setdefault(p.get("lesson_id"), []).append((s, i))

    out = []
    for pid, slist in by_parent.items():
        parent = next((e for e in entries if e.get("lesson_id") == pid), {})
        ptitle = parent.get("title") or ""
        # 区间：首个子篇的页码 → 最后一个子篇之后那条目的页码。
        # 只取父课起始页的话，`古诗三首` 会只剩 p11 上的第一首。
        start = slist[0][0].get("printed_start")
        last_i = max(i for _, i in slist)
        nxt = next((e["printed_start"] for e in entries[last_i + 1:]
                    if isinstance(e.get("printed_start"), int)), None)
        end = nxt if (isinstance(start, int) and isinstance(nxt, int) and nxt > start) \
            else (start + 1 if isinstance(start, int) else None)
        if not isinstance(start, int):
            continue
        r = L.slice_lesson(pages, by, start, end or maxp, ptitle) if by else {}
        lines = r.get("lines") or []
        end = end or maxp
        kind = ("文言文" if "文言文" in ptitle
                else "古诗" if re.search(r"诗|词|曲", ptitle) else "篇")
        nc = L.book_newchars(book_id).get(str(parent.get("lesson_no") or ""))
        for p in build_piece(parent, [s for s, _ in slist], lines, end - 1, nc):
            p.update({
                "piece_id": "%s:%02d" % (pid, p["seq"]),
                "lesson_id": pid,
                "book_id": book_id,
                "grade": head.get("grade", ""),
                "term": head.get("term", ""),
                "unit_no": parent.get("unit_no"),
                "unit_name": parent.get("unit_name"),
                "lesson_no": parent.get("lesson_no"),
                "parent_title": ptitle,
                "kind": kind,
            })
            out.append(p)
    return out


def build_all(subject: str = "语文", verbose: bool = True) -> dict:
    os.makedirs(config.ATTRS_DIR, exist_ok=True)
    n = nmiss = 0
    with open(PIECE_FILE, "w", encoding="utf-8") as f:
        for fn in sorted(os.listdir(config.OUTLINE_DIR)):
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(config.OUTLINE_DIR, fn)
            head = json.loads(open(path, encoding="utf-8").readline())
            if subject and head.get("subject") != subject:
                continue
            ps = build_book(fn[:-6])
            for p in ps:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
                n += 1
                if not p.get("located"):
                    nmiss += 1
            if verbose and ps:
                print("  %s%s %2d 篇（未定位 %d）" % (
                    head.get("grade", ""), head.get("term", ""), len(ps),
                    sum(1 for p in ps if not p.get("located"))))
    if verbose:
        print("→ %s（%d 篇，未定位 %d）" % (PIECE_FILE, n, nmiss))
    return {"pieces": n, "miss": nmiss}
