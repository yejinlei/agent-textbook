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
# 注释：编号词条（`①〔洞庭〕…`）与被释词行（`〔孰〕谁。`）。
# 后者不带圈码，是注释块的续行，漏掉它们会让文言文的注释整段留在正文里。
RE_NOTE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]|^\s*〔")
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
# 课后思考题：**只认段首的教材指令**，不认问号。
# 问号不能当判据——《两小儿辩日》的"孰为汝多知乎？"是正文，照问号切会
# 把课文腰斩。正文里出现的问句靠"截断"处理（见 split_body_tasks）。
RE_EXERCISE = re.compile(
    r"^(说说|想一想|想想|交流|讨论|想象|写一写|照样子写一写|结合注释|用自己的话|"
    r"读一读|记一记|默读课文|朗读课文|有感情地朗读课文|找出|画出|读下面的|"
    r"读读下面|体会|反复朗读|分角色|和同学交流|联系上下文|搜集|摘抄|背诵你喜欢|"
    r"小练笔|课文主要写了|选做|活动提示)"
    r"|^◇"
)
# 课后题还可能粘在段落**中间**（`—选自斯妤的《除夕》，有改动默读课文，想想…`），
# 整段判不了，只能在句中定位后切开。
RE_EXE_INLINE = re.compile(
    r"(默读课文|小练笔|朗读课文|找出课文中|读下面的句子|"
    r"说说哪部分|想想这样写|再讨论一下|和同学交流|照样子写|"
    r"结合注释|借助注释|说说下面|想想它们|分别表达了|再想想|"
    r"还有哪些|在你读过的|说说《|的故事，|类似的诗句|选\s*做)"
)
# 作者行被文本层塞进句子末尾：`…并且八儿所说的腊八粥本文作者沈从文，选作课文时有改动。`
RE_AUTHOR_LINE = re.compile(r"本文作者[^，。！？]{2,8}[，。][^，。！？]{0,12}")
# 课内生字条：页边独立成行的纯汉字串（无标点），长度 1~24
RE_NEWCHARS = re.compile(r"^[一-鿿]{1,24}$")
# 课后补充栏目：紧跟课文的"阅读链接/资料袋"，不是课文正文
RE_LINK = re.compile(r"阅读链接|资料袋|阅读连接")
# 图注：`（图）盛锡珊`。**必须限长**——图注后面常直接跟着正文
# （`（图）盛锡珊阅读链接我于是猛地想起…`），不设上限会把整句正文删掉。
RE_FIGURE = re.compile(r"（图）[^，。！？]{0,3}|[（(]\s*图\s*[\d\-.]*\s*[)）]")
# 页眉：`20 文言文二则` / `3 腊八粥`——课号+课题，短且无句读
RE_HEADNUM = re.compile(r"^\d{1,3}\s+[^，。！？]{0,10}$")
# 页码残留在句中：`…色味双1    北京的春节（图）盛锡`。
# 要求数字后跟**两个以上**空格才认，正文里的"读了 3 遍"不会被误删。
RE_PAGENO = re.compile(r"\d{1,3}\s{2,}(?=[一-鿿])")
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

# 栏目优先于正文信号：目录自带的 section 与标题前缀是教材自己写的分类，
# 比在正文里找朝代标记可靠得多——后者的典型误判是把"语文园地"里
# 日积月累的 `[宋]文天祥` 当成课文作者，整条被判成古诗。
COLUMN_BY_SECTION = {
    "口语交际": "口语交际", "习作": "习作", "识字": "识字",
    "汉语拼音": "拼音", "语文园地": "语文园地", "综合性学习": "综合性学习",
    "快乐读书吧": "快乐读书吧", "例文": "例文", "梳理与交流": "梳理与交流",
}
RE_COLUMN_TITLE = re.compile(
    r"^(口语交际|习作|语文园地|综合性学习|快乐读书吧|日积月累|我爱阅读|梳理与交流)")

GENRE_BY_TITLE = (
    (r"古诗|绝句|律诗|七律|五律|词$|曲$|〔唐〕|〔宋〕", "古诗"),
    (r"文言文|司马光|守株待兔|精卫|王戎|囊萤|铁杵|杨氏之子|自相矛盾|伯牙|学弈|"
     r"两小儿|古人谈读书|少年中国说|曹冲称象|书戴嵩画牛|囊萤夜读", "文言文"),
    (r"现代诗|短诗三首|现代诗二首", "现代诗"),
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


_WORDS_CACHE: dict = {}


def book_newchars(book_id: str) -> dict:
    """按课号取该课生字集合（写字表+识字表），用于剥离粘进段落的字条。"""
    if book_id in _WORDS_CACHE:
        return _WORDS_CACHE[book_id]
    out: dict = {}
    fp = os.path.join(config.ATTRS_DIR, "words.jsonl")
    if os.path.exists(fp):
        for l in open(fp, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if r.get("book_id") != book_id or r.get("kind") not in ("写字表", "识字表"):
                continue
            out.setdefault(str(r.get("lesson_no") or ""), set()).add(r.get("value") or "")
    _WORDS_CACHE[book_id] = out
    return out


def strip_newchar_prefix(s: str, chars: set) -> tuple[str, str]:
    """剥掉段首粘连的生字条：`醋饺摊拌筝…骆驼一眨眼，到了残灯末庙…`

    判据是"连续 6 个以上的本课生字"。正文开头连着 6 个字恰好全是本课生字
    几乎不可能，而页边字条正是这一课的字——拿生字表比对，比猜长度可靠。
    """
    if len(chars) < 5:
        return s, ""
    i = 0
    while i < len(s) and s[i] in chars:
        i += 1
    if i >= 6 and (i >= len(s) or s[i] not in chars):
        return s[i:], s[:i]
    return s, ""


def split_body_tasks(paras: list[str], newchars: set | None = None, title: str = ""
                     ) -> tuple[list[str], list[str], list[str], list[str], list[str], list[str]]:
    """把段落分成 正文 / 学习任务 / 课后题 / 生字条 / 注释 / 阅读链接。

    课文区间里课后内容与正文混排，单看一段往往分不清，但**正文是连续块**：
    一旦出现课后题或"阅读链接"，其后的段落就都不再是课文。故先逐段打标，
    再从第一个课后题/链接处截断——截断之后的正文段落也一并归入课后部分。

    这条规则顺带解决了一个反例：《两小儿辩日》的"孰为汝多知乎？"是正文里
    的问句，如果按"问号即课后题"逐段判断，课文会被腰斩。
    """
    items: list[tuple[str, str]] = []
    t = (title or "").strip()
    for p in paras:
        s = RE_FIGURE.sub("", p.strip())
        s = RE_PAGENO.sub("", s)
        s = RE_AUTHOR_LINE.sub("", s)
        # 页眉+图注会被文本层插进句子中间：`…色味双1    北京的春节（图）盛锡珊…`。
        # **不能按课题原样删除**——课文正文常提到自己的题目（《腊八粥》里
        # 就有"提到腊八粥"），原样删会破坏句子。只删"课题紧挨着图注"或
        # "页码+课题"这两种页眉形态。
        if len(t) >= 3:
            te = re.escape(t)
            s = re.sub(r"\d{0,3}\s{0,4}" + te + r"\s*（图）[^，。！？]{0,3}", "", s)
            s = re.sub(r"\d{1,3}\s{2,}" + te, "", s)
        s = s.strip()
        # 删掉图注/作者行之后可能只剩标点（`本文作者老舍，…` 删完剩个句号）
        if not s or not re.search(r"[一-鿿]", s):
            continue
        if RE_HEADNUM.match(s):
            continue
        if RE_NOTE.match(s) or s.startswith("注释"):
            items.append(("note", s))
            continue
        # 课后题粘在段落中间时切开（`…有改动默读课文，想想…`）
        m = RE_EXE_INLINE.search(s)
        if m and m.start() > 0:
            items.append(("body", s[:m.start()].strip()))
            items.append(("exe", s[m.start():].strip()))
            continue
        # 生字条与任务句挤在同一段时切开。前半截必须是**纯汉字串**才认：
        # 否则"上课了，大家在教室里一起朗读课文，那声音真好听！"会被切成两半。
        m = RE_TASK_INLINE.search(s)
        if m and m.start() > 0 and RE_CJK_ONLY.match(s[:m.start()].strip()):
            head = s[:m.start()].strip()
            if head:
                items.append(("char", head))
            items.append(("task", s[m.start():].strip()))
            continue
        if RE_TASK_HEAD.search(s):
            items.append(("task", s))
            continue
        if RE_LINK.search(s):
            items.append(("link", s))
            continue
        if RE_EXERCISE.search(s):
            items.append(("exe", s))
            continue
        if newchars:
            s, head = strip_newchar_prefix(s, newchars)
            if head:
                items.append(("char", head))
        if RE_NEWCHARS.match(s) and len(s) <= 24 and not RE_PARA_END.search(s):
            items.append(("char", s))
            continue
        items.append(("body", s))

    cut = next((i for i, (k, _) in enumerate(items) if k in ("exe", "link")), len(items))
    out = {k: [] for k in ("body", "task", "exe", "char", "note", "link")}
    cur = None
    for i, (k, s) in enumerate(items):
        if i >= cut and k == "body":
            k = cur or "exe"
        if k in ("exe", "link"):
            cur = k
        out[k].append(s)
    return (out["body"], out["task"], out["exe"], out["char"],
            out["note"], out["link"])


def _is_header(ln: str, title: str) -> bool:
    """页眉行：`秋天的雨①`——以课题开头、极短、且没有句末标点。

    页眉会在每一页重复，拼接后变成"秋天的雨①秋天的雨，吹起了…"混进正文，
    必须在行级别拦掉；正文行虽然也以课题开头，但长度远超"课题+圈码"。
    """
    if not title or not ln.startswith(title):
        return False
    return len(ln) <= len(title) + 6 and not RE_PARA_END.search(ln)


def _looks_poem(head: str) -> bool:
    """诗句结构判据：句读切分后，五言/七言句占多数。

    只凭"正文里有 `[唐]`"会把《海上日出》这类提到古人的现代散文判成古诗，
    加上句式判据才稳——古诗的句子长度是整齐的 5 或 7。
    """
    sents = [s.strip() for s in re.split(r"[，。！？；]", head) if len(s.strip()) >= 4]
    if len(sents) < 2:
        return False
    hit = sum(1 for s in sents if len(s) in (5, 7))
    return hit / len(sents) >= 0.5


def _looks_classical(head: str) -> bool:
    """文言文判据：虚词密度高 **且** 句子短。

    原判据（出现任意一个"之/其/以/而"就判文言）把《乡下人家》
    《海滨小城》全判成了文言文，实测误判 37 条。文言文是**密集**出现虚词，
    现代散文只是偶尔用到，故要求命中 >=4 次且平均句长不超过 12 字。
    """
    sents = [s.strip() for s in re.split(r"[，。！？；]", head) if s.strip()]
    if len(sents) < 2:
        return False
    if sum(len(s) for s in sents) / len(sents) > 12:
        return False
    return len(RE_CLASSIC.findall(head)) >= 4


def extract_meta(title: str, body: str, section: str = "") -> dict:
    """体裁 / 作者 / 朝代 / 出处——只抽原文里写明的，不猜。

    两条实测教训：
      * 栏目优先。目录的 section 与标题前缀是教材自己写的分类，比正文信号可靠；
      * 作者/朝代只看**开头**。课文区间常把单元末"日积月累"一起吞进来，
        扫全篇会把里面诗句的作者当成课文作者（`让真情自然流露` 的作者变文天祥）。
    """
    t = title or ""
    head = body[:300]
    # 书末附录（写字表/词语表）不是课文，且目录里常常排在最后、会被并进上一课
    if re.search(r"(写字表|识字表|词语表|附录|后记)", t):
        genre = "附录"
    else:
        genre = COLUMN_BY_SECTION.get(section or "")
        m = RE_COLUMN_TITLE.match(t)
        if m:
            genre = m.group(1)
    if genre is None:
        for pat, g in GENRE_BY_TITLE:
            if re.search(pat, t):
                genre = g
                break
    if genre is None and RE_DYNASTY.search(head) and _looks_poem(head):
        genre = "古诗"
    if genre is None and _looks_classical(head):
        genre = "文言文"
    # 普通课文也必须有体裁，空着会让"按体裁筛选"直接漏掉一半库
    if genre is None:
        genre = "课文"

    author = None
    m = RE_AUTHOR.search(head)
    if m:
        author = m.group(1)
    if author is None:
        m = RE_POET.search(head)
        if m:
            author = m.group(1)
    dynasty = None
    if genre in ("古诗", "文言文"):
        m = RE_DYNASTY.search(head)
        if m:
            dynasty = m.group(1)
    source = None
    m = RE_AUTHOR_SEL.search(body[:600])
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


def slice_lesson(pages: list[dict], by: dict, start: int, end: int, title: str = "",
                 newchars: set | None = None) -> dict:
    """取 [start, end) 印刷页码区间的页，还原正文与各部分。

    newchars 为该课生字集合，用来剥离粘进段落开头的页边字条。
    """
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
    # 行级纯文本（去拼音行）：古诗/文言文拆篇必须基于行——段落级会把
    # 诗题与首句粘成一段（`寒 食[唐] 韩 翃春城无处不飞花，…`），无法切分。
    plain_lines = [ln for ln in lines if not RE_PINYIN.match(ln)]
    paras = split_paragraphs(plain_lines)
    body, tasks, exes, chars, notes, links = split_body_tasks(paras, newchars, title)
    return {
        "page_from": by[keys[0]].get("page_no"),
        "page_to": by[keys[-1]].get("page_no"),
        "n_pages": len(keys),
        "text": "\n".join(body),
        "text_plain": "".join(plain),
        "lines": plain_lines,
        "paragraphs": body,
        "tasks": tasks,
        "exercises": exes,
        "notes": notes,
        "reading_links": links,
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
    # 生字表按课号组织，用它在切分时剥掉粘进段落的字条
    nc = book_newchars(book_id)

    rows, metas = [], []
    for i, e in enumerate(items):
        s = e["printed_start"]
        nxt = items[i + 1]["printed_start"] if i + 1 < len(items) else maxp
        end = nxt if nxt > s else s + 1
        r = slice_lesson(pages, by, s, end, e.get("title") or "",
                         nc.get(str(e.get("lesson_no") or "")))
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
