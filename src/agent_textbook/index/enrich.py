# -*- coding: utf-8 -*-
"""构建期 LLM 补充层（四层里的第三层）：补教材没给的。

补充 = 教材里没有、但教学需要的：
  * 译文：古诗/文言文的白话翻译（教材只给字词注释，不给整篇翻译）；
  * 作者：课文作者是谁、是什么人（教材常只写"本文作者XXX"）。

这是四层里唯一会引入**教材外知识**的一层，编出来的东西和课文混在一起
没人分得清。故每一类都配一道硬校验，校不过就判失败重来：

  * 译文要求**逐句对照**，原句必须是原文里连续的一句——模型一旦发挥
    （换说法、补情节），src 就对不上原文，直接判掉；
  * 作者名先由 LLM 从正文里校对（规则抽的那批是脏的：`李白小时`、
    `是俄国的屠格涅`），简介只写常识范围内的，拿不准就返回空。

产物 data/attrs/lesson_translation.jsonl、lesson_author.jsonl。
"""

import json
import os
import re
import time

from .. import config
from . import llm

TRANS_FILE = os.path.join(config.ATTRS_DIR, "lesson_translation.jsonl")
AUTHOR_FILE = os.path.join(config.ATTRS_DIR, "lesson_author.jsonl")
INTRO_FILE = os.path.join(config.ATTRS_DIR, "author_intro.jsonl")

# 主观/传闻标记：这些词一出现，说明模型不是在译，是在猜。
# "可能/大概"不在此列——白话译文里它只是语气，不代表编造。
# "我认为"不能算：文言文的"我以/以为"译出来正是这个词。
RE_HEDGE = re.compile(r"据说|无从考证|待考|也许是|大概是作者")

PROMPT_TRANS = (
    "你是小学语文教材助手。把下面这首古诗（或这篇文言文）译成白话文，"
    "供小学生对照着理解。\n\n"
    "【篇名】《{title}》\n"
    "【原文】共 {n} 句\n{text}\n"
    "{known}"
    "\n任务：\n"
    "1. literal 要列出**全部 {n} 句**，一句不落——漏一句整条就作废；\n"
    "2. 每句的 src 必须与原文**逐字一致**（含标点与用字，不许改字）；\n"
    "3. translation 是把这些句子连起来的通顺白话。\n\n"
    "严格要求：\n"
    "- 译文**不添加**原文没有的人物、事件、情感与道理，也不要写"
    "“表达了作者怎样的感情”这类分析；\n"
    "- 拿不准的词照字面直译，不要编情节；\n"
    "- 不要用引号（书名用《》），引号会破坏 JSON。\n\n"
    "只输出一行 JSON，不要任何解释：\n"
    '{{"literal":[{{"src":"...","tr":"..."}}],"translation":"..."}}'
)

PROMPT_AUTHOR = (
    "你是小学语文教材助手。判断下面这篇课文的作者是谁。\n\n"
    "【课文】《{title}》\n"
    "【正文开头】\n{head}\n\n"
    "【教材里的线索】{clue}\n\n"
    "要求：\n"
    "- 作者是**常识**，请依据正文与你所知作答；教材里的标注只作参考——\n"
    "  它常被正文首字污染（`李白日照`），也可能标的是同课的另一篇；\n"
    "- 答案是纯人名（中国人名 2~4 字，外国人名可长一些，如“屠格涅夫”）；\n"
    "- **拿不准就返回空字符串**，不要猜；正文确实是佚名/民间作品也返回空。\n\n"
    '只输出一行 JSON：{{"author":"..."}}'
)

PROMPT_INTRO = (
    "你是小学语文教材助手。用一句话介绍下面这位作者，供小学生读课文前了解。\n\n"
    "【作者】{name}（{dynasty}）\n"
    "【代表作举例】{works}\n\n"
    "要求：\n"
    "- 只写**常识范围内确凿**的事：朝代/国籍、身份、以什么著称；\n"
    "- 不超过 60 字，不要评价、不要轶事、不要具体生卒年；\n"
    "- 拿不准就返回空字符串，绝不猜测。\n\n"
    '只输出一行 JSON：{{"intro":"..."}}'
)


def _norm(s: str) -> str:
    """只留汉字与字母数字，用于比对原句是否出自原文。"""
    return re.sub(r"[^一-鿿A-Za-z0-9]", "", s or "")


def check_translation(text: str, d: dict) -> str:
    """译文校验。返回错误说明，通过返回空串。

    核心是**逐句对照**：src 必须能在原文里找到。模型一旦换说法、补情节，
    src 就对不上——这道校验就是为了让"编"无处可藏。
    """
    tr = (d.get("translation") or "").strip()
    if not tr:
        return "缺白话译文"
    if len(tr) < len(text) * 0.5:
        return "译文过短（%d 字 < 原文 %d 的一半）" % (len(tr), len(text))
    if RE_HEDGE.search(tr):
        return "译文有推测措辞"
    lit = d.get("literal") or []
    if not lit:
        return "缺逐句对照"
    src_all = "".join((x.get("src") or "") for x in lit)
    a, b = _norm(text), _norm(src_all)
    if not b:
        return "逐句对照为空"
    if len(b) < len(a) * 0.6:
        return "逐句只覆盖原文 %.0f%%" % (100 * len(b) / max(1, len(a)))
    for x in lit:
        s = _norm(x.get("src") or "")
        if s and s not in a:
            return "对照原句不在原文里：%s" % (x.get("src") or "")[:16]
        if not (x.get("tr") or "").strip():
            return "对照句缺译文：%s" % (x.get("src") or "")[:16]
    return ""


def _translate_by_sentence(r: dict, text: str, verbose: bool = True) -> dict | None:
    """整篇翻译漏句时的兜底：一句一句译，覆盖必然是 100%。

    temperature=0 下的失败是**确定性**的——同一 prompt 再问一次还是漏同样
    的句子。故换个问法：把句子拆开单独问，每句 src 就是原句本身，
    不需要模型再复述原文，也就无处可漏。
    """
    from . import pieces as P

    sents = P.split_sentences(text)
    if len(sents) < 2:
        return None
    lit = []
    for s in sents:
        res = llm.chat(PROMPT_SENT.format(title=r.get("title") or "", src=s),
                       max_tokens=1024)
        d = llm.parse_json(res.text)
        tr = (d.get("tr") or "").strip()
        if not tr or RE_HEDGE.search(tr):
            raise ValueError("逐句译文不可用：%s" % s[:16])
        lit.append({"src": s, "tr": tr})
    return {"literal": lit, "translation": "".join(x["tr"] for x in lit)}


def _load_lesson_texts() -> dict:
    """lesson_id → 该课正文（lesson 层清洗过的段落）。"""
    fp = os.path.join(config.ATTRS_DIR, "lesson_text.jsonl")
    out = {}
    if os.path.exists(fp):
        for l in open(fp, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                out[r.get("lesson_id")] = r
    return out


def _norm_map(s: str) -> tuple[list[int], str]:
    """归一化并记下标映射：找得到位置，才能切回原文。"""
    idx, out = [], []
    for i, ch in enumerate(s):
        if ch.isspace() or ch in "·•・​-‏﻿":
            continue
        idx.append(i)
        out.append(ch)
    return idx, "".join(out)


def _find_at(s: str, title: str, after: int = 0) -> int:
    """在 s 里找题名起点（忽略空格与间隔号），找不到返回 -1。"""
    t = re.sub(r"[\s　·•・​-‏﻿]", "", title or "")
    if not t:
        return -1
    idx, ns = _norm_map(s)
    p = ns.find(t, after)
    return idx[p] if p >= 0 else -1


def _clean_source(s: str) -> str:
    """剥掉不属于原文的东西：注释圈码、注音声调、题名。"""
    from . import pieces as P

    return P.RE_PINYIN.sub("", P.RE_NOTE_NUM.sub("", s or "")).strip()


# 不可能是原文的东西：课后题、页眉、注释括号
PROMPT_SENT = (
    "把下面这句古诗（或文言文）译成白话。\n\n"
    "【篇名】《{title}》\n"
    "【原句】{src}\n\n"
    "要求：只译这一句，不补人物、不补情节、不加分析；"
    "不要用“可能、大概”这类不肯定的词；一句话说清即可。\n"
    '只输出一行 JSON：{{"tr":"..."}}'
)

# 不可能是原文的东西：课后题、页眉、注释括号
RE_JUNK = re.compile(r"说一说|说说|画一画|读一读|朗读课文|想一想|填一填|"
                     r"照样子|用自己的话|想象画面|第.{0,3}单元|语文园地|"
                     r"这一单元|本单元|单元导语|语文要素|〔")


def _source_text(p: dict, pieces: list[dict], texts: dict) -> tuple[str, str]:
    """取这一篇的干净原文，返回（原文, 来源）。

    两个来源各有各的脏法，谁都不能全信：
      * piece.text 可能整段是课后题——实测《望庐山瀑布》取出来是
        `想画面，再用自己的话说一说。`；
      * 父课正文段落是 lesson 层清洗过的，但按题名截的时候，若同课下一篇
        没定位到，会把下一篇的正文也截进来（《马诗》后面跟着《石灰吟》）。

    故两边都算出来，先剔掉明显不是原文的，再**取短的**——多截的那个一定更长。
    """
    from . import organize as O

    cand: list[tuple[int, str, str]] = []
    lt = texts.get(p.get("lesson_id")) or {}
    paras = lt.get("paragraphs") or []
    if paras:
        s = "\n".join(paras)
        a = _find_at(s, p.get("title") or "")
        if a >= 0:
            a += len(re.sub(r"[\s　·•・​-‏﻿]", "", p.get("title") or ""))
            # 截到同课下一篇的题名处；没有下一篇就取到本节末尾
            b = len(s)
            for q in sorted((x for x in pieces
                             if x.get("lesson_id") == p.get("lesson_id")
                             and (x.get("seq") or 0) > (p.get("seq") or 0)),
                            key=lambda x: x.get("seq") or 0):
                m = _find_at(s, q.get("title") or "", after=a)
                if m > a:
                    b = m
                    break
            seg = _clean_source(s[a:b])
            if len(seg) >= 8 and not RE_JUNK.search(seg):
                cand.append((len(seg), "lesson", seg))
    pc = _clean_source(O._poem_text(p))
    if len(pc) >= 8 and not RE_JUNK.search(pc):
        cand.append((len(pc), "piece", pc))
    if cand:
        cand.sort()
        return cand[0][2], cand[0][1]
    # 兜底来源未必是这一篇：题名若出现在**中间**，多半抓的是上一篇的正文
    # （《六月二十七日望湖楼醉书》取出来是《宿建德江》）。题名不在文本里
    # 是可以的（篇题常独占一行、正文里不再出现），交给 RE_JUNK 兜底。
    fb = pc or "\n".join(paras)[:600]
    at = _find_at(fb, p.get("title") or "")
    return _strip_head_tail(fb, p), ("bad" if at > 8 else "fallback")


def _strip_head_tail(s: str, p: dict) -> str:
    """剥掉原文前后的题名、朝代作者与页眉栏名。

    fallback 来源常整段带着这些：
    `登鹳雀楼[唐王之涣白日依山尽…更上一层楼古诗二首第四单元·阅读`
    """
    a = _find_at(s, p.get("title") or "")
    if a >= 0:
        s = s[a + len(re.sub(r"[\s　·•・​-‏﻿]", "", p.get("title") or "")):]
    # 朝代与作者：`[唐] 李白` / `[宋]杨万里`。转录常丢右括号（ `[唐王之涣` ），
    # 故右括号可选，靠"括号后不长且没有句读"来界定。
    m = re.match(r"^\s*[\[〔(（]\s*(?:西汉|东汉|汉|三国|魏|晋|南北朝|唐|五代|宋|元|"
                 r"明|清)?\s*[一-鿿]{0,4}\s*[\]〕)）]?", s)
    if m:
        s = s[m.end():]
    s = re.sub(r"第.{0,3}单元.*$", "", s, flags=re.S)
    pt = (p.get("parent_title") or "").strip()
    if pt and s.rstrip().endswith(pt):
        s = s.rstrip()[:-len(pt)]
    return s.strip()


def _poem_head(p: dict) -> str:
    """给模型的原文：取前 8 个短句，避开粘在篇尾的课后题与注释碎片。"""
    from . import organize as O

    return O._poem_text(p)


def build_translation(limit: int = 0, force: bool = False,
                      verbose: bool = True) -> dict:
    """古诗/文言文的白话译文。"""
    from . import organize as O
    from . import pieces as P

    todo = [p for p in O._load_pieces()
            if p.get("kind") in O.GLOSS_GENRES and (p.get("text") or "").strip()]
    if not force:
        done = llm.load_done(TRANS_FILE, "piece_id")
        todo = [p for p in todo if p.get("piece_id") not in done]
    if limit:
        todo = todo[:limit]
    if verbose:
        print("待补充译文：%d 篇" % len(todo))
    if not todo:
        return {"ok": 0, "fail": 0, "reject": 0}

    all_pieces = O._load_pieces()
    texts = _load_lesson_texts()
    ok = fail = reject = skip = 0
    for i, r in enumerate(todo, 1):
        text, src = _source_text(r, all_pieces, texts)
        # 原文不可靠就不译：译出来只是把课后题或上一篇的正文再说一遍，
        # 混进库里比没有更糟——宁可留空，等篇定位修好再补。
        if src == "bad" or RE_JUNK.search(text):
            skip += 1
            if verbose:
                print("  [%d/%d] %s 跳过：原文不可靠（%s）"
                      % (i, len(todo), r.get("title"), src))
            continue
        notes = r.get("notes") or []
        known = ""
        if notes:
            known = "【教材注释】\n%s\n" % "\n".join(notes[:12])
        # 句数由规则切出来给模型——不给的话它常只译前两三句，
        # 逐句覆盖校验就会判掉（实测《村居》只覆盖 54%）。
        n = len(P.split_sentences(text))
        prompt = PROMPT_TRANS.format(title=r.get("title") or "",
                                     text=text, known=known, n=n)
        try:
            # 逐句对照 + 一段译文，2048 足够；给到 4096 反而更容易被网关吐空
            res = llm.chat(prompt, max_tokens=2048)
            d = llm.parse_json(res.text)
            err = check_translation(text, d)
            if err:
                raise ValueError(err)
            model = res.model
        except Exception as e:
            # 漏句是确定性失败（temperature=0），换个问法：拆成一句一句译
            if "覆盖" not in str(e):
                if "对照" in str(e) or "译文" in str(e):
                    reject += 1
                else:
                    fail += 1
                if verbose:
                    print("  [%d/%d] %s 失败：%s" % (i, len(todo), r.get("title"), e))
                continue
            try:
                d = _translate_by_sentence(r, text) or {}
                err = check_translation(text, d)
                if err:
                    raise ValueError(err)
                model = "sent"
            except Exception as e2:
                reject += 1
                if verbose:
                    print("  [%d/%d] %s 逐句兜底也失败：%s"
                          % (i, len(todo), r.get("title"), e2))
                continue
        llm.append_jsonl(TRANS_FILE, {
            "piece_id": r.get("piece_id"), "lesson_id": r.get("lesson_id"),
            "book_id": r.get("book_id"), "title": r.get("title"),
            "translation": d["translation"].strip(),
            "literal": d["literal"], "source": src,
            "model": model, "ts": int(time.time()),
        })
        ok += 1
        if verbose:
            print("  [%d/%d] %s → %s" % (
                i, len(todo), r.get("title"), d["translation"].strip()[:36]))
    if verbose:
        print("→ %s（成功 %d / 失败 %d / 校验丢弃 %d / 原文不可靠跳过 %d）"
              % (TRANS_FILE, ok, fail, reject, skip))
    return {"ok": ok, "fail": fail, "reject": reject, "skip": skip}


def build_intro(limit: int = 0, force: bool = False,
                verbose: bool = True) -> dict:
    """作者一句话简介（按人名去重，一个人只问一次）。

    简介是最容易编出花来的地方——模型爱写生卒年、轶事、评价，一错就是硬伤。
    故只问常识范围内确凿的三件事（朝代/国籍、身份、以什么著称），并把该作者
    在**教材里的作品**一并给它，免得把同名的另一个人认错（两个"李贺"？不，
    是怕把"叶圣陶"和别人混）。拿不准就返回空——简介留白比写错强。
    """
    if not os.path.exists(AUTHOR_FILE):
        return {"ok": 0, "fail": 0, "reject": 0}
    rows = [json.loads(l) for l in open(AUTHOR_FILE, encoding="utf-8") if l.strip()]
    people: dict[str, dict] = {}
    for r in rows:
        name = (r.get("author") or "").strip()
        if not name:
            continue
        p = people.setdefault(name, {"dynasty": r.get("dynasty") or "", "works": []})
        if r.get("dynasty") and not p["dynasty"]:
            p["dynasty"] = r["dynasty"]
        t = (r.get("title") or "").strip()
        if t and t not in p["works"]:
            p["works"].append(t)
    todo = [(n, p) for n, p in people.items()]
    if not force:
        done = llm.load_done(INTRO_FILE, "author")
        todo = [(n, p) for n, p in todo if n not in done]
    todo.sort()
    if limit:
        todo = todo[:limit]
    if verbose:
        print("待补充简介：%d 位作者" % len(todo))
    if not todo:
        return {"ok": 0, "fail": 0, "reject": 0}

    ok = fail = reject = 0
    for i, (name, p) in enumerate(todo, 1):
        prompt = PROMPT_INTRO.format(
            name=name, dynasty=p["dynasty"] or "未标朝代",
            works="、".join(("《%s》" % w) for w in p["works"][:6]) or "（未举）")
        try:
            res = llm.chat(prompt, max_tokens=1024)
            d = llm.parse_json(res.text)
            intro = (d.get("intro") or "").strip()
            if intro:
                if len(intro) > 80:
                    raise ValueError("简介超 80 字：%d" % len(intro))
                if RE_HEDGE.search(intro) or re.search(r"\d{3,4}年", intro):
                    raise ValueError("简介含不确定或具体年份：%s" % intro[:20])
            llm.append_jsonl(INTRO_FILE, {
                "author": name, "dynasty": p["dynasty"], "intro": intro,
                "works": p["works"][:6], "model": res.model, "ts": int(time.time()),
            })
            ok += 1
            if verbose:
                print("  [%d/%d] %s → %s" % (i, len(todo), name, intro[:40] or "（空）"))
        except Exception as e:
            if "简介" in str(e):
                reject += 1
            else:
                fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(todo), name, e))
    if verbose:
        print("→ %s（成功 %d / 失败 %d / 校验丢弃 %d）" % (INTRO_FILE, ok, fail, reject))
    return {"ok": ok, "fail": fail, "reject": reject}


def _load_meta_rows() -> list[dict]:
    fp = os.path.join(config.ATTRS_DIR, "lesson_meta.jsonl")
    if not os.path.exists(fp):
        return []
    return [json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]


def _author_targets(texts: dict) -> list[dict]:
    """作者要挂在**篇**上，不是挂在课上。

    一课常常是多首诗（《古诗三首》里有白居易、苏轼、卢钺），给课标一个作者
    毫无意义——而且证据若取父课开头，同课每篇都会被判成第一首的作者
    （实测《题西林壁》被判成"白居易"）。故目标是篇；只有**没有子篇**的课
    才自己标作者。
    """
    from . import organize as O

    pieces = O._load_pieces()
    out = []
    for p in pieces:
        if not (p.get("text") or "").strip():
            continue
        out.append({
            "key": p.get("piece_id"), "piece_id": p.get("piece_id"),
            "lesson_id": p.get("lesson_id"), "book_id": p.get("book_id"),
            "title": p.get("title"), "parent_title": p.get("parent_title"),
        })
    with_piece = {p.get("lesson_id") for p in pieces}
    for m in _load_meta_rows():
        if m.get("lesson_id") in with_piece or not (m.get("author") or "").strip():
            continue
        out.append({
            "key": m.get("lesson_id"), "piece_id": None,
            "lesson_id": m.get("lesson_id"), "book_id": m.get("book_id"),
            "title": m.get("title"), "parent_title": "",
        })
    return out


def build_author(limit: int = 0, force: bool = False,
                 verbose: bool = True) -> dict:
    """作者校对：规则抽的 author 是脏的，按**篇**重新校准。

    规则从正文里抓作者时会把首字一起抓进来（`李白日照`、`是俄国的屠格涅`），
    直接拿去问简介只会张冠李戴。故先校准人名：证据用**这一篇自己的正文**，
    教材标注只当参考——它可能标的是同课的另一篇。
    """
    from . import organize as O

    texts = _load_lesson_texts()
    all_pieces = O._load_pieces()
    metas = {m.get("lesson_id"): m for m in _load_meta_rows()}
    todo = _author_targets(texts)
    if not force:
        done = llm.load_done(AUTHOR_FILE, "key")
        todo = [t for t in todo if t.get("key") not in done]
    if limit:
        todo = todo[:limit]
    if verbose:
        print("待校对作者：%d 条" % len(todo))
    if not todo:
        return {"ok": 0, "fail": 0, "reject": 0}

    ok = fail = reject = 0
    for i, m in enumerate(todo, 1):
        # 证据取**这一篇自己的正文**，不能用父课开头——否则同课各篇会被判成
        # 同一个作者（《题西林壁》→ 白居易 就是这么错的）。
        if m.get("piece_id"):
            piece = next((p for p in all_pieces
                          if p.get("piece_id") == m.get("piece_id")), None)
            head, _ = _source_text(piece or m, all_pieces, texts)
        else:
            t = texts.get(m.get("lesson_id")) or {}
            head = "".join((t.get("paragraphs") or [])[:2])[:300]
        if len(head.strip()) < 8:
            fail += 1
            if verbose:
                print("  [%d/%d] %s 取不到正文，跳过" % (i, len(todo), m.get("title")))
            continue
        clue = (metas.get(m.get("lesson_id")) or {}).get("author") or ""
        prompt = PROMPT_AUTHOR.format(title=m.get("title") or "",
                                      head=head[:400], clue=clue or "（教材未标注）")
        try:
            res = llm.chat(prompt, max_tokens=1024)
            d = llm.parse_json(res.text)
            name = (d.get("author") or "").strip()
            # "佚名"也是一种答案，但库里统一留空，免得简介去介绍"佚名"
            if name in ("佚名", "无名氏", "不详", "未知", "无"):
                name = ""
            # 可校验：人名里不该有虚词与标点——`是俄国的屠格涅` 这类脏值
            # 一眼看得出；空是合法答案（教材确实没写作者）。
            if name and (len(name) > 8 or re.search(r"[的是了，。、？！]", name)):
                raise ValueError("作者名不合法：%s" % name[:20])
            llm.append_jsonl(AUTHOR_FILE, {
                "key": m.get("key"),
                "piece_id": m.get("piece_id"), "lesson_id": m.get("lesson_id"),
                "book_id": m.get("book_id"), "title": m.get("title"),
                "parent_title": m.get("parent_title"), "author": name,
                "dynasty": (metas.get(m.get("lesson_id")) or {}).get("dynasty") or "",
                "intro": "", "model": res.model, "ts": int(time.time()),
            })
            ok += 1
            if verbose:
                print("  [%d/%d] %s → %s" % (i, len(todo), m.get("title"), name or "（空）"))
        except Exception as e:
            if "作者名" in str(e):
                reject += 1
            else:
                fail += 1
            if verbose:
                print("  [%d/%d] %s 失败：%s" % (i, len(todo), m.get("title"), e))
    if verbose:
        print("→ %s（成功 %d / 失败 %d / 校验丢弃 %d）" % (AUTHOR_FILE, ok, fail, reject))
    return {"ok": ok, "fail": fail, "reject": reject}
