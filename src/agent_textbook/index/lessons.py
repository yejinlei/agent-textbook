# -*- coding: utf-8 -*-
"""课文原文切分、段落还原与学习任务抽取（知识库的地基层）。

目录给出每篇课文的**印刷页码**起点，parsed 的正文页带 printed_no，
两者对齐即可按区间切出课文原文——纯规则，零成本、零幻觉。

四个必须处理的实测事实：
 1. 拼音单独成行，把正文切碎（`是一把钥 / yào / 匙 / shi / 。`），必须还原；
 2. 页眉（标题+课号+页码）与页脚（"仅供个人学习使用"）每页重复，拼接后会污染正文；
 3. 目录页的 printed_no 不可信（会抓到目录里的页码数字），建映射时必须排除；
 4. 课文区间里除了正文，还混着注释、课内生字条、课后思考题与学习任务，要分开。

产物 data/attrs/lesson_text.jsonl 与 lesson_meta.jsonl，靠 lesson_id 挂载。
"""

import json
import os
import re

from .. import config
from . import outline as ol

# ---------------------------------------------------------------- 行级清洗
RE_FOOTER = re.compile(r"仅供个人学习使用|未经授权|绿色印刷|责任编辑|义务教育教科书|ISBN|著作权")
RE_PRINTED = re.compile(r"^\d{1,3}$")
# 纯拼音行：含声调字母，无汉字。一年级整页注音（每个字后都带拼音）也命中。
RE_PINYIN = re.compile(r"^[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüńňǹḿěǹ\s]+$")
RE_CJK_ONLY = re.compile(r"^[一-鿿]+$")
RE_NOTE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]")
# 句末标点：段落结束的判据。必须**先有句末标点**，右引号只能跟在后面——
# 否则"我理解了“五彩缤纷” / 的意思。"这种被排版切断的句子会被误判成两段。
RE_PARA_END = re.compile(r"[。！？…][”’」』）]*\s*$")

# ---------------------------------------------------------------- 学习任务
# 学习任务必须**在句首**——正文里出现"一起朗读课文"是内容，不是要求。
RE_TASK_HEAD = re.compile(
    r"^(有感情地)?(朗读|背诵|默读|分角色朗读|复述|默写)"
    r"|^背诵第[一二三四五六七八九十\d]+"
)
# 页边生字条与任务句常常挤在同一段（`凉枚杏…勾挖有感情地朗读课文。`），
# 用这个在段中定位任务起点，把前半截还给生字条。
RE_TASK_INLINE = re.compile(
    r"(有感情地)?朗读课文|背诵第?[一二三四五六七八九十\d]*自然段?|默写[《「]"
)
# 课后思考题：疑问句或以"说说/想想/交流/想象/写一写"开头的祈使句
RE_EXERCISE = re.compile(
    r"[？?]$"
    r"|^(说说|想一想|想想|交流|讨论|想象|写一写|照样子写一写|结合注释|用自己的话|读一读|记一记)"
    r"|^◇"
)
# 课内生字条：页边独立成行的纯汉字串（无标点），长度 1~24
RE_NEWCHARS = re.compile(r"^[一-鿿]{1,24}$")
# 栏目页眉：`阅 读`、`①阅读`——会被文本层插到句子中间（"蝴蝶停①阅读在花朵上"）
RE_SECTION_HEADER = re.compile(
    r"^[①②③]?\s*(阅读|识字|汉语拼音|习作|习作例文|口语交际|语文园地|"
    r"快乐读书吧|综合性学习|梳理与交流|例文|写字)\s*$"
)
# 文本层还会把栏目页眉拆成单字行（`①` / `阅` / `读`），合并后才是"①阅读"。
# 这类行独立成行、只含栏名常用字，正文中极少出现，直接整行丢掉。
RE_SECTION_FRAG = re.compile(r"^[①②③]$|^[阅读识字习作语文园地快乐书信拼音例交际写]{1,4}$")
# 同样的页眉也可能被文本层塞在**行内**（"蝴蝶停①阅读在花朵上"），只能剥离不能整行删。
# 只认"圈码+栏目名"这个组合，正文里的"阅读"二字（如"课外阅读"）不受影响。
RE_SECTION_INLINE = re.compile(
    r"[①②③]\s*(阅读|识字|汉语拼音|习作|习作例文|口语交际|语文园地|"
    r"快乐读书吧|综合性学习|梳理与交流|例文|写字)"
)

# ---------------------------------------------------------------- 元数据
RE_AUTHOR = re.compile(r"本文作者\s*([一-鿿·]{2,8})")
RE_AUTHOR_SEL = re.compile(r"选自\s*《([^》]{2,20})》")
RE_DYNASTY = re.compile(r"[〔\[（(]\s*(西汉|东汉|汉|三国|魏|晋|南北朝|唐|五代|宋|元|明|清)\s*[〕\]）)]")
RE_POET = re.compile(
    r"[〔\[（(]\s*(?:唐|宋|元|明|清|汉|魏|晋)\s*[〕\]）)]\s*([一-鿿]{2,4})")
# 文言文语感特征
RE_CLASSIC = re.compile(r"[曰云]|[，。]\s*(之|其|以|而|者|也)\s*[，。]|……?者[，。]")

GENRE_BY_TITLE = (
    (r"古诗|绝句|律诗|词$|曲$|〔唐〕|〔宋〕", "古诗"),
    (r"司马光|守株待兔|精卫|王戎|囊萤|铁杵|杨氏之子|自相矛盾|伯牙|学弈|两小儿|古人谈读书|少年中国说", "文言文"),
    (r"寓言", "寓言"),
    (r"童话", "童话"),
    (r"神话", "神话"),
    (r"民间故事|民谣|歌谣", "民间文学"),
    (r"^识字|识字$", "识字"),
    (r"汉语拼音|^[aoeiuü]|^[bpmfdtnlgkhjqxzcsryw]{1,3}$", "拼音"),
)


def clean_page_lines(text: str) -> list[str]:
    """单页文本 → 干净行列表（去页脚、印刷页码、空行）。"""
    out = []
    for ln in (text or "").split("\n"):
        s = ln.replace("\t", " ").strip()
        if not s or RE_FOOTER.search(s):
            continue
        if RE_PRINTED.match(s):
            continue
        out.append(s)
    return out


def drop_repeated_head(pages_lines: list[list[str]]) -> list[list[str]]:
    """去掉跨页重复的页眉/页脚。

    页眉（栏目名、标题+课号+页码）在课文中每一页都出现，拼接后会重复多次。
    判据：在**每一页**的前 3 行（或后 2 行）里都出现的行，就是页眉/页脚。
    """
    if len(pages_lines) < 2:
        return pages_lines
    head = set(pages_lines[0][:3])
    tail = set(pages_lines[0][-2:])
    for ls in pages_lines[1:]:
        head &= set(ls[:3])
        tail &= set(ls[-2:])
    noise = head | tail
    return [[ln for ln in ls if ln not in noise] for ls in pages_lines]


def merge_pinyin(lines: list[str]) -> tuple[str, str]:
    """把被拼音切断的正文还原，返回 (带拼音正文, 去拼音纯文本)。

    教材文本层里拼音独占一行：`是一把钥 / yào / 匙 / shi / 。`
    还原时把拼音挂到它前面那个字上：`是一把钥(yào)匙(shi)。`
    """
    buf: list[str] = []
    plain: list[str] = []
    for ln in lines:
        if RE_PINYIN.match(ln) and buf:
            buf.append("(%s)" % ln.strip())
            continue
        buf.append(ln)
        plain.append(ln)
    return "".join(buf), "".join(plain)


def split_paragraphs(lines: list[str]) -> list[str]:
    """把行序列切成段落：行尾出现句末标点即断段。

    教材的物理行不等于段落（拼音会把一个段落切成好几行），
    实测可行的判据是"行尾是句号/问号/感叹号/引号"——段中换行不会以句号结尾。
    """
    paras, cur = [], []
    for ln in lines:
        cur.append(ln)
        if RE_PARA_END.search(ln):
            paras.append("".join(cur))
            cur = []
    if cur:
        paras.append("".join(cur))
    return [p for p in paras if p.strip()]


def split_body_tasks(paras: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    """把段落分成 正文 / 学习任务 / 课后题 / 生字条候选。

    课文区间里课后内容与正文混排，判据是句式而不是位置：
      * 生字条：整段是纯汉字串（页边字条，无标点）；
      * 学习任务：含"朗读/背诵/默写"等教材固定说法；
      * 课后题：疑问句，或以"说说/想想/交流/想象"开头的祈使句。
    """
    body, tasks, exes, chars = [], [], [], []
    for p in paras:
        s = p.strip()
        if not s:
            continue
        if RE_NOTE.match(s):
            continue
        # 生字条与任务句挤在同一段时切开。前半截必须是**纯汉字串**才认：
        # 否则"上课了，大家在教室里一起朗读课文，那声音真好听！"会被切成两半。
        m = RE_TASK_INLINE.search(s)
        if m and m.start() > 0 and RE_CJK_ONLY.match(s[:m.start()].strip()):
            head = s[:m.start()].strip()
            if head:
                chars.append(head)
            tasks.append(s[m.start():].strip())
            continue
        if RE_TASK_HEAD.search(s):
            tasks.append(s)
            continue
        if RE_NEWCHARS.match(s) and len(s) <= 24 and not RE_PARA_END.search(s):
            chars.append(s)
            continue
        if RE_EXERCISE.search(s):
            exes.append(s)
            continue
        body.append(s)
    return body, tasks, exes, chars


def _is_header(ln: str, title: str) -> bool:
    """页眉行：`秋天的雨①`——以课题开头、极短、且没有句末标点。

    页眉会在每一页重复，拼接后变成"秋天的雨①秋天的雨，吹起了…"混进正文，
    必须在行级别拦掉；正文行虽然也以课题开头，但长度远超"课题+圈码"。
    """
    if not title or not ln.startswith(title):
        return False
    return len(ln) <= len(title) + 6 and not RE_PARA_END.search(ln)


def extract_meta(title: str, body: str, section: str = "") -> dict:
    """体裁 / 作者 / 朝代 / 出处——只抽原文里写明的，不猜。"""
    genre = None
    for pat, g in GENRE_BY_TITLE:
        if re.search(pat, title or ""):
            genre = g
            break
    if genre is None and RE_DYNASTY.search(body):
        genre = "古诗"
    if genre is None and section == "习作":
        genre = "习作"
    if genre is None and RE_CLASSIC.search(body[:400]):
        genre = "文言文"

    author = None
    m = RE_AUTHOR.search(body)
    if m:
        author = m.group(1)
    if author is None:
        m = RE_POET.search(body)
        if m:
            author = m.group(1)
    dynasty = None
    m = RE_DYNASTY.search(body)
    if m:
        dynasty = m.group(1)
    source = None
    m = RE_AUTHOR_SEL.search(body)
    if m:
        source = m.group(1)
    return {"genre": genre, "author": author, "dynasty": dynasty, "source": source}


# ---------------------------------------------------------------- 切分
def printed_index(pages: list[dict], toc_pages: set) -> dict:
    """印刷页码 → 页记录（排除目录页，其 printed_no 不可信）。"""
    by = {}
    for p in sorted(pages, key=lambda r: r.get("page_no") or 0):
        if p.get("page_no") in toc_pages:
            continue
        pn = p.get("printed_no")
        if isinstance(pn, int) and pn not in by:
            by[pn] = p
    return by


def slice_lesson(pages: list[dict], by: dict, start: int, end: int, title: str = "") -> dict:
    """取 [start, end) 印刷页码区间的页，还原正文与各部分。"""
    keys = sorted(k for k in by if start <= k < end)
    if not keys:
        return {}
    per_page = [clean_page_lines(by[k].get("text") or "") for k in keys]
    per_page = drop_repeated_head(per_page)
    lines = [ln for ls in per_page for ln in ls
             if not _is_header(ln, title)
             and not RE_SECTION_HEADER.match(ln)
             and not RE_SECTION_FRAG.match(ln)]
    lines = [ln for ln in (RE_SECTION_INLINE.sub("", x).strip() for x in lines) if ln]
    text, plain = merge_pinyin(lines)
    paras = split_paragraphs([ln for ln in lines if not RE_PINYIN.match(ln)])
    body, tasks, exes, chars = split_body_tasks(paras)
    return {
        "page_from": by[keys[0]].get("page_no"),
        "page_to": by[keys[-1]].get("page_no"),
        "n_pages": len(keys),
        "text": "\n".join(body),
        "text_plain": "".join(plain),
        "paragraphs": body,
        "tasks": tasks,
        "exercises": exes,
        "newchars": chars,
        "chars": len(plain),
    }


def build_book(book_id: str) -> dict:
    meta, pages = ol.load_book(book_id)
    if not meta:
        return {}
    path = os.path.join(config.OUTLINE_DIR, book_id + ".jsonl")
    if not os.path.exists(path):
        return {}
    rs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    if len(rs) < 2:
        return {}
    head, entries = rs[0], rs[1:]
    by = printed_index(pages, set(head.get("toc_pages") or []))
    if not by:
        return {}
    items = [e for e in entries if isinstance(e.get("printed_start"), int)]
    items.sort(key=lambda e: e["printed_start"])
    maxp = max(by) + 1

    rows, metas = [], []
    for i, e in enumerate(items):
        s = e["printed_start"]
        nxt = items[i + 1]["printed_start"] if i + 1 < len(items) else maxp
        end = nxt if nxt > s else s + 1
        r = slice_lesson(pages, by, s, end, e.get("title") or "")
        if not r:
            continue
        rec = {
            "lesson_id": e.get("lesson_id"),
            "book_id": book_id,
            "grade": head.get("grade", ""),
            "term": head.get("term", ""),
            "unit_no": e.get("unit_no"),
            "unit_name": e.get("unit_name"),
            "section": e.get("section"),
            "lesson_no": e.get("lesson_no"),
            "title": e.get("title"),
            "printed_start": s,
            "printed_end": end - 1,
        }
        rec.update(r)
        rows.append(rec)
        m = extract_meta(e.get("title") or "", r["text"], e.get("section") or "")
        m.update({"lesson_id": e.get("lesson_id"), "book_id": book_id,
                  "title": e.get("title")})
        metas.append(m)
    return {"meta": head, "rows": rows, "metas": metas}


def build_all(subject: str = "语文", verbose: bool = True) -> dict:
    if not os.path.isdir(config.OUTLINE_DIR):
        return {}
    os.makedirs(config.ATTRS_DIR, exist_ok=True)
    fp_text = os.path.join(config.ATTRS_DIR, "lesson_text.jsonl")
    fp_meta = os.path.join(config.ATTRS_DIR, "lesson_meta.jsonl")
    nrow = nmiss = 0
    empty = []
    with open(fp_text, "w", encoding="utf-8") as ft, open(fp_meta, "w", encoding="utf-8") as fm:
        for fn in sorted(os.listdir(config.OUTLINE_DIR)):
            if not fn.endswith(".jsonl"):
                continue
            bid = fn[:-6]
            r = build_book(bid)
            if not r or not r["rows"]:
                continue
            if subject and r["meta"].get("subject") != subject:
                continue
            for row in r["rows"]:
                ft.write(json.dumps(row, ensure_ascii=False) + "\n")
                nrow += 1
                if not row["text"].strip():
                    empty.append((row["grade"], row["title"]))
            for m in r["metas"]:
                fm.write(json.dumps(m, ensure_ascii=False) + "\n")
            if verbose:
                miss = sum(1 for x in r["rows"] if not x["text"].strip())
                nmiss += miss
                print("  %s%s %3d 篇（空 %d）" % (
                    r["meta"].get("grade", ""), r["meta"].get("term", ""),
                    len(r["rows"]), miss))
    if verbose:
        print("→ %s（%d 篇）" % (fp_text, nrow))
        print("→ %s（%d 条）" % (fp_meta, nrow))
        if empty:
            print("  空正文样例：%s" % empty[:5])
    return {"rows": nrow, "empty": len(empty)}
