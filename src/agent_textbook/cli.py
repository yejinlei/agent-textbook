# -*- coding: utf-8 -*-
"""命令行入口：python -m agent_textbook <子命令>"""

import argparse
import os
from collections import Counter

from . import config
from . import parse as ps
from .collect import catalog as cat
from .collect import downloader as dl
from .collect.net import has_credentials, load_token


def _add_filters(p: argparse.ArgumentParser) -> None:
    p.add_argument("--stage", default="", help="学段，默认小学（六三学制）")
    p.add_argument("--subject", default="", help="学科，逗号分隔（模糊匹配）")
    p.add_argument("--version", default="", help="版本，逗号分隔（模糊匹配）")
    p.add_argument("--grade", default="", help="年级，逗号分隔（模糊匹配）")
    p.add_argument("--preset", default="", choices=sorted(config.VERSION_PRESETS), help="版本预设")
    p.add_argument("--include-teacher", action="store_true", help="包含教师用书")
    p.add_argument("--include-wusi", action="store_true", help="包含五·四学制")


def _select(args) -> list[dict]:
    rows = cat.load_catalog()
    if not rows:
        raise SystemExit("没有目录数据，请先运行：python -m agent_textbook catalog")
    rows = cat.select_rows(
        rows,
        stage=args.stage,
        subject=args.subject,
        version=args.version,
        grade=args.grade,
        preset=args.preset,
        include_teacher=args.include_teacher,
        include_wusi=args.include_wusi,
    )
    if getattr(args, "limit", 0):
        rows = rows[: args.limit]
    return rows


def cmd_catalog(args) -> None:
    rows = cat.fetch_catalog()
    path = cat.save_catalog(rows)
    print(f"共 {len(rows)} 本，已写入 {path}")
    primary = [r for r in rows if cat.is_stage(r, include_wusi=True)]
    print("学段分布：", dict(Counter(cat.classify(r["path"])[0] for r in primary)))


def cmd_list(args) -> None:
    rows = _select(args)
    print(f"命中 {len(rows)} 本")
    for key, n in sorted(Counter(
        (cat.classify(r["path"])[1], cat.classify(r["path"])[2]) for r in rows
    ).items()):
        print(f"  {key[0]} / {key[1]}：{n} 本")


def cmd_fetch(args) -> None:
    load_token(args.token)
    if has_credentials():
        print("已载入登录凭据，请求将使用真实签名")
    rows = _select(args)
    print(f"待处理 {len(rows)} 本")
    records = dl.resolve_all(rows, workers=args.workers, region=args.region)
    if not args.dry_run:
        records = dl.download_all(records, out_dir=args.out, workers=args.workers)
    dl.merge_manifest(records)
    print(f"清单已写入 {config.MANIFEST_FILE}")


def cmd_retry(args) -> None:
    load_token(args.token)
    failed = [r for r in dl.read_manifest() if r.get("status") != "ok" and r.get("url")]
    print(f"重跑失败项 {len(failed)} 条")
    if not failed:
        return
    for r in failed:  # download_all 只处理 pending，失败项需先复位
        r["status"] = "pending"
    records = dl.download_all(failed, out_dir=args.out, workers=args.workers)
    dl.merge_manifest(records)


def cmd_sync(args) -> None:
    n = dl.sync_from_disk(out_dir=args.out)
    print(f"按磁盘回填 {n} 条清单记录")


def cmd_organize(args) -> None:
    moved = dl.organize(out_dir=args.out, region=args.region)
    print(f"搬迁 {moved} 个文件到 <地区>/<学段>/<学科>/<版本>/<年级>/ 布局")


def cmd_status(args) -> None:
    rows = dl.read_manifest()
    stat = Counter(r.get("status") for r in rows)
    size = sum(r.get("size") or 0 for r in rows if r.get("status") == "ok")
    print(f"清单 {len(rows)} 条：{dict(stat)}，已下载 {size / 1024 ** 3:.2f} GB")
    for r in rows:
        if r.get("status") != "ok":
            print(f"  失败：{r.get('subject')}/{r.get('version')}/{r.get('title')} —— {r.get('reason')}")


def cmd_parse(args) -> None:
    books = ps.pipeline.load_books(
        stage=args.stage, subject=args.subject, grade=args.grade,
        version=args.version, need_vlm_only=args.need_vlm,
    )
    if args.limit:
        books = books[: args.limit]
    if not books:
        raise SystemExit("没有可解析的教材（需先 fetch 且 status 为 ok）")
    print(f"待解析 {len(books)} 册，engine={args.engine}")
    stats = ps.pipeline.parse_all(books, engine=args.engine,
                                  workers=args.workers, force=args.force)
    bad = [s for s in stats if s.get("engine") == "error"]
    print(f"完成 {len(stats) - len(bad)} 册，失败 {len(bad)} 册")
    for s in bad:
        print(f"  失败：{s.get('title')} —— {s.get('error')}")


def cmd_parse_status(args) -> None:
    st = ps.pipeline.parse_status()
    print(f"已解析 {st['books']} 册 / {st['pages']} 页 / {st['chars'] / 1e4:.1f} 万字")
    print("  通道分布：", st["engines"] or "（无）")


def cmd_backfill(args) -> None:
    """全量核对 + 补齐未提取的册/页（含插图理解）。"""
    from .parse import backfill as bf

    bf.backfill(subject=args.subject, workers=args.workers,
                page_workers=args.page_workers, dry_run=args.dry_run)


def cmd_figures(args) -> None:
    """只补插图描述：正文一字不动（避免 VLM 转录覆盖精确的文本层正文）。"""
    from .parse import figures as fg

    fg.backfill_figures(subject=args.subject, workers=args.workers,
                        limit=args.limit, dry_run=args.dry_run, force=args.force)


def cmd_outline(args) -> None:
    """抽取目录与结构骨架（知识库 L1）：单元 → 课/栏目 → 起始印刷页码。"""
    from .index import outline as ol

    if args.book_id:
        r = ol.build_book(args.book_id)
        if not r.get("entries"):
            print("未识别到目录：%s" % args.book_id)
            return
        path = ol.save_book(r)
        m = r["meta"]
        print("%s%s 目录页%s → %d 条 → %s" % (
            m["grade"], m["term"], m["toc_pages"], m["entries"], path))
        for e in r["entries"][: args.show]:
            print("  第%s单元 %-6s %-4s %-24s 起 p%s" % (
                e.get("unit_no"), (e.get("section") or e.get("unit_tag") or ""),
                e.get("lesson_no") or "", (e.get("title") or "")[:24],
                e.get("printed_start")))
        return

    print("抽取目录骨架：%s" % (args.subject or "全部学科"))
    rs = ol.build_all(subject=args.subject)
    print("共 %d 册 / %d 条" % (len(rs), sum(r["meta"]["entries"] for r in rs)))
    for r in rs[: args.show]:
        print("--- %s%s ---" % (r["meta"]["grade"], r["meta"]["term"]))
        for e in r["entries"][:10]:
            print("   %-4s %-22s p%s" % (
                e.get("lesson_no") or "◎", (e.get("title") or "")[:22],
                e.get("printed_start")))


def cmd_words(args) -> None:
    """抽取识字表 / 写字表 / 词语表（知识库 L1 资产）。"""
    from .index import words as wd

    if args.book_id:
        r = wd.build_book(args.book_id)
        if not r.get("rows"):
            print("未抽到字表：%s" % args.book_id)
            return
        m = r["meta"]
        print("%s%s 附录位置 %s" % (m["grade"], m["term"], m["appendix"]))
        print("统计：%s" % m["stat"])
        for row in r["rows"][: args.show]:
            print("  %-6s %-4s %-8s %s" % (
                row["kind"], row.get("lesson_no") or "", row["value"],
                row.get("pinyin") or ""))
        return

    print("抽取字表：%s" % (args.subject or "全部学科"))
    rs = wd.build_all(subject=args.subject)
    print("共 %d 册" % len(rs))


def cmd_science(args) -> None:
    """科学本体深挖：探究活动（器材/步骤/变量）与科学概念（含常见迷思）。"""
    from .index import science

    if args.kind == "concept":
        science.build_concepts(subject=args.subject or "科学",
                               limit=args.limit, force=args.force)
    else:
        science.build_experiments(subject=args.subject or "科学",
                                  limit=args.limit, force=args.force)


def cmd_mathex(args) -> None:
    """数学本体深挖：例题（题面/分步解法/答案）与数学概念（含符号、性质）。"""
    from .index import mathex

    if args.kind == "concept":
        mathex.build_concepts(subject=args.subject or "数学",
                              limit=args.limit, force=args.force)
    elif args.kind == "exercise":
        mathex.build_exercises(subject=args.subject or "数学",
                               level=getattr(args, "level", "subsection"),
                               limit=args.limit)
    else:
        mathex.build_examples(subject=args.subject or "数学",
                              level=getattr(args, "level", "section"),
                              limit=args.limit, force=args.force)


def cmd_mathmap(args) -> None:
    """数学补充槽位：整理与复习的知识结构图、按单元的单位与符号表。"""
    from .index import mathmap

    if args.kind == "unit":
        mathmap.build_units(subject=args.subject or "数学",
                            limit=args.limit, force=args.force)
    else:
        mathmap.build_maps(subject=args.subject or "数学",
                           limit=args.limit, force=args.force)


def cmd_enlang(args) -> None:
    """英语本体深挖：对话 / 句型语法 / 拼读 / 语篇 / 项目。"""
    from .index import enlang

    kind = args.kind
    if kind == "grammar":
        enlang.build_grammar(subject=args.subject or "英语",
                             limit=args.limit, force=args.force)
    elif kind == "phonics":
        enlang.build_phonics(subject=args.subject or "英语",
                             limit=args.limit, force=args.force)
    elif kind == "passage":
        enlang.build_passages(subject=args.subject or "英语",
                              limit=args.limit, force=args.force)
    elif kind == "project":
        enlang.build_projects(subject=args.subject or "英语",
                              limit=args.limit, force=args.force)
    else:
        enlang.build_dialogues(subject=args.subject or "英语",
                               limit=args.limit, force=args.force)


def cmd_mathunit(args) -> None:
    """数学课级切分：--retag 重挂单元 / --fill-gaps 补漏 / 默认全页 VLM 判定。"""
    from .index import mathunit

    if getattr(args, "retag", False):
        mathunit.retag(subject=args.subject or "数学")
    elif getattr(args, "fill_gaps", False):
        mathunit.fill_gaps(subject=args.subject or "数学",
                           min_gap=getattr(args, "min_gap", 2),
                           limit=args.limit)
    else:
        mathunit.build(subject=args.subject or "数学", limit=args.limit,
                       force=args.force)


def cmd_formula(args) -> None:
    """数学公式 → LaTeX（看图，文本层里的公式是坏的）；--retag 只重挂单元。"""
    from .index import formula

    if getattr(args, "retag", False):
        formula.retag(subject=args.subject or "数学")
    else:
        formula.build(subject=args.subject or "数学", limit=args.limit,
                      force=args.force)


def cmd_enwords(args) -> None:
    """抽英语词汇表与常用表达（英语本体的核心资产）；--enrich 补教材原句与话题。"""
    from .index import enwords

    if getattr(args, "enrich", False):
        enwords.enrich(subject=args.subject or "英语")
    else:
        enwords.build_all(subject=args.subject or "英语")


def cmd_toc(args) -> None:
    """看图抽分栏目录骨架（数学/科学等规则对不上标题↔页码的册）。"""
    from .index import toc

    rs = toc.build_all_vlm(subject=args.subject, limit=args.limit, force=args.force,
                           min_entries=args.min_entries)
    print("看图抽出骨架 %d 册 / %d 条"
          % (len(rs), sum(len(r["entries"]) for r in rs)))
    for r in rs:
        m = r["meta"]
        print("  %-4s %-4s %d 条" % (m.get("grade"), m.get("term"), len(r["entries"])))


def cmd_keypoints(args) -> None:
    """抽数学/科学的小节知识点（摘要 / 知识点 / 公式 / 术语）。"""
    from .index import keypoints as kp

    kp.build(limit=args.limit, force=args.force, subject=args.subject)


def cmd_sections(args) -> None:
    """切分数学/科学的小节正文。"""
    from .index import sections as sc

    sc.build_all(subject=args.subject)


def cmd_kb(args) -> None:
    """知识库（DuckDB）：不给 --sql 则重建库，给了就查询。"""
    from .index import kb

    if args.sql:
        kb.query(args.sql)
    else:
        kb.build(subject=args.subject)


def cmd_lessons(args) -> None:
    """切分课文原文、还原段落并抽取学习任务（知识库地基）。"""
    import json
    import os

    from .index import lessons

    if args.book_id:
        r = lessons.build_book(args.book_id)
        if not r:
            print("未找到该册，或它还没有目录产物：%s" % args.book_id)
            return
        print("%s%s %d 篇" % (r["meta"].get("grade", ""), r["meta"].get("term", ""),
                              len(r["rows"])))
    else:
        lessons.build_all(subject=args.subject)

    if args.show:
        fp = os.path.join(config.ATTRS_DIR, "lesson_text.jsonl")
        if not os.path.exists(fp):
            return
        rs = [json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]
        for r in rs[:args.show]:
            print("\n【%s】%s%s U%s p%s-%s  %d 段 / %d 字" % (
                r.get("title"), r.get("grade"), r.get("term"), r.get("unit_no"),
                r.get("page_from"), r.get("page_to"),
                len(r.get("paragraphs") or []), r.get("chars") or 0))
            for p in (r.get("paragraphs") or [])[:3]:
                print("    %s" % p[:66])
            if r.get("tasks"):
                print("    任务：%s" % "；".join(r["tasks"])[:88])
            if r.get("exercises"):
                print("    练习：%s" % "；".join(r["exercises"])[:88])
            if r.get("newchars"):
                print("    生字：%s" % " ".join(r["newchars"])[:60])


def cmd_pieces(args) -> None:
    """拆一课多篇：来源以目录为准，正文只用于定位切分边界。"""
    import json

    from .index import pieces

    stat = pieces.build_all(subject=args.subject)
    # 重跑会覆盖规则定位失败的篇，生成后必须立刻回填 LLM 补抽的结果，
    # 否则每跑一次 pieces 就丢一次补抽内容（未定位数会反弹）。
    from .index import audit

    applied = audit.apply_piece_fixes(verbose=False)
    if applied:
        rs = [json.loads(l) for l in open(pieces.PIECE_FILE, encoding="utf-8")
              if l.strip()]
        print("回填 LLM 补抽 %d 篇，未定位 %d 篇" % (
            applied, sum(1 for x in rs if not x.get("located"))))
    if args.show:
        rs = [json.loads(l) for l in open(pieces.PIECE_FILE, encoding="utf-8") if l.strip()]
        for r in rs[:args.show]:
            print("\n【%s】%s%s U%s 父：%s  %s/%s p%s" % (
                r.get("title"), r.get("grade"), r.get("term"), r.get("unit_no"),
                r.get("parent_title"), r.get("dynasty") or "-", r.get("author") or "-",
                r.get("printed_start")))
            for s in (r.get("sentences") or [])[:6]:
                print("    %s" % s)
            if r.get("notes"):
                print("    注：%s" % r["notes"][0][:60])


def cmd_audit(args) -> None:
    """LLM 校对层：只修规则修不了的（细分体裁 / 未定位篇补正文）。"""
    from .index import audit

    try:
        audit.sync_piece_genre()
        if args.kind == "piece":
            audit.fix_pieces(limit=args.limit, force=args.force)
        else:
            audit.classify_genre(limit=args.limit, force=args.force)
    except RuntimeError as e:
        print("跳过：%s" % e)


def cmd_digest(args) -> None:
    """LLM 整理层与补充层：段意 / 字词 / 译文 / 作者。"""
    from .index import audit, enrich, organize

    try:
        audit.sync_piece_genre()
        if args.kind == "gloss":
            organize.build_glossary(limit=args.limit, force=args.force)
        elif args.kind == "trans":
            enrich.build_translation(limit=args.limit, force=args.force)
        elif args.kind == "author":
            enrich.build_author(limit=args.limit, force=args.force)
        elif args.kind == "intro":
            enrich.build_intro(limit=args.limit, force=args.force)
        elif args.kind == "elem":
            from .index import cnelem

            cnelem.build(subject="语文", limit=args.limit, force=args.force)
        else:
            organize.build_structure(limit=args.limit, force=args.force)
    except RuntimeError as e:
        print("跳过：%s" % e)


def cmd_ensure_page(args) -> None:
    """按需在线补解析教材页：本地产物里没有才调 VLM，结果回填。"""
    import time

    from .parse import online

    _, pages = online.read_book(args.book_id)
    for n in args.page_no:
        row = next((p for p in pages if p.get("page_no") == n), None)
        src = "在线解析" if (args.force or online.needs_online(row)) else "本地命中"
        t0 = time.time()
        text = online.ensure_page(args.book_id, n, force=args.force)
        print(f"[{src}] 第 {n} 页：{len(text)} 字  图描述 {text.count('[图')} 处  "
              f"耗时 {time.time() - t0:.1f}s")
        if args.show:
            print(text[:600])


def cmd_photo(args) -> None:
    """运行期在线提取：孩子拍的题目照片 → 文本。"""
    import time

    from .parse import online

    with open(args.image, "rb") as f:
        img = f.read()
    t0 = time.time()
    text = online.transcribe_photo(img)
    print(f"耗时 {time.time() - t0:.1f}s，{len(text)} 字\n")
    print(text)


def main() -> None:
    p = argparse.ArgumentParser(prog="agent-textbook", description="小学生教材 Agent 工程命令行")
    p.add_argument("--out", default=config.BOOKS_DIR, help="教材输出目录")
    p.add_argument("--region", default=config.DEFAULT_REGION, help="地区层目录名，默认浙江杭州")
    p.add_argument("--token", default=config.TOKEN_FILE, help="登录凭据 JSON 路径")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("catalog", help="拉取平台全量书目").set_defaults(func=cmd_catalog)

    sp = sub.add_parser("list", help="按条件筛选书目")
    _add_filters(sp)
    sp.add_argument("--limit", type=int, default=0)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("fetch", help="解析并下载教材")
    _add_filters(sp)
    sp.add_argument("--limit", type=int, default=0)
    sp.add_argument("--workers", type=int, default=config.DEFAULT_WORKERS)
    sp.add_argument("--dry-run", action="store_true", help="只解析写清单，不下载")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("retry", help="重跑清单中失败的条目")
    sp.add_argument("--workers", type=int, default=config.DEFAULT_WORKERS)
    sp.set_defaults(func=cmd_retry)

    sp = sub.add_parser("sync", help="按磁盘已下载文件回填清单状态")
    sp.set_defaults(func=cmd_sync)

    sub.add_parser("organize", help="整理已下载文件到新目录布局").set_defaults(func=cmd_organize)
    sub.add_parser("status", help="查看下载清单状态").set_defaults(func=cmd_status)

    sp = sub.add_parser("parse", help="解析教材为结构化文本（双通道）")
    sp.add_argument("--stage", default="", help="学段过滤")
    sp.add_argument("--subject", default="", help="学科过滤（模糊匹配）")
    sp.add_argument("--grade", default="", help="年级过滤（模糊匹配）")
    sp.add_argument("--version", default="", help="版本过滤（模糊匹配）")
    sp.add_argument("--engine", default="auto", choices=["auto", "text_layer", "vlm"],
                    help="auto：按文本层判定自动选择；vlm：强制多模态通道")
    sp.add_argument("--workers", type=int, default=config.VLM_WORKERS, help="VLM 页级并发")
    sp.add_argument("--limit", type=int, default=0, help="只解析前 N 册")
    sp.add_argument("--need-vlm", action="store_true", help="只解析无文本层的扫描册")
    sp.add_argument("--force", action="store_true", help="已解析也重跑")
    sp.set_defaults(func=cmd_parse)

    sub.add_parser("parse-status", help="查看解析进度").set_defaults(func=cmd_parse_status)

    sp = sub.add_parser("backfill", help="核对全量产物并补齐未提取的册/页（含插图理解）")
    sp.add_argument("--subject", default="", help="学科过滤（模糊匹配）")
    sp.add_argument("--workers", type=int, default=config.VLM_WORKERS, help="整册补时的并发")
    sp.add_argument("--page-workers", type=int, default=1, help="单页补时的并发（建议 1）")
    sp.add_argument("--dry-run", action="store_true", help="只核对不提取")
    sp.set_defaults(func=cmd_backfill)

    sp = sub.add_parser("figures", help="只补插图描述（正文不动，产物存 data/figures/）")
    sp.add_argument("--subject", default="", help="学科过滤（模糊匹配）")
    sp.add_argument("--workers", type=int, default=config.VLM_WORKERS, help="页级并发（整册批量用 8）")
    sp.add_argument("--limit", type=int, default=0, help="本次最多补多少页（试跑用）")
    sp.add_argument("--force", action="store_true", help="已补过也重跑")
    sp.add_argument("--dry-run", action="store_true", help="只核对不调用")
    sp.set_defaults(func=cmd_figures)

    sp = sub.add_parser("outline", help="抽取目录与结构骨架（知识库 L1）")
    sp.add_argument("--subject", default="", help="学科过滤（如 语文）")
    sp.add_argument("--book-id", default="", help="只抽一册")
    sp.add_argument("--show", type=int, default=0, help="打印前 N 条样例")
    sp.set_defaults(func=cmd_outline)

    sp = sub.add_parser("science", help="科学本体深挖：探究活动 / 科学概念")
    sp.add_argument("--kind", default="exp", choices=["exp", "concept"],
                    help="exp=探究活动，concept=科学概念")
    sp.add_argument("--subject", default="科学", help="学科过滤")
    sp.add_argument("--limit", type=int, default=0, help="本次最多处理多少节")
    sp.add_argument("--force", action="store_true", help="已抽过也重跑")
    sp.set_defaults(func=cmd_science)

    sp = sub.add_parser("formula", help="数学公式转 LaTeX（看图逐页抽）")
    sp.add_argument("--subject", default="数学", help="学科过滤")
    sp.add_argument("--limit", type=int, default=0, help="本次最多抽多少页")
    sp.add_argument("--force", action="store_true", help="已抽过的页也重跑")
    sp.add_argument("--retag", action="store_true",
                    help="单元页区间变了之后，把已有公式重挂到正确单元")
    sp.set_defaults(func=cmd_formula)

    sp = sub.add_parser("mathex", help="数学本体深挖：例题（含步骤）/ 数学概念")
    sp.add_argument("--kind", default="example",
                    choices=["example", "concept", "exercise"],
                    help="example=例题与解题步骤，concept=数学概念，"
                         "exercise=补回被 10 道上限截掉的练习题")
    sp.add_argument("--level", default="section", choices=["section", "subsection"],
                    help="section=单元级小节，subsection=课时（先跑 mathunit）")
    sp.add_argument("--subject", default="数学", help="学科过滤")
    sp.add_argument("--limit", type=int, default=0, help="本次最多处理多少节")
    sp.add_argument("--force", action="store_true", help="已抽过也重跑")
    sp.set_defaults(func=cmd_mathex)

    sp = sub.add_parser("mathmap", help="数学补充槽位：整理与复习的知识结构图 / 单位与符号表")
    sp.add_argument("--kind", default="map", choices=["map", "unit"],
                    help="map=整理复习页的知识结构图，unit=按单元的计量单位与数学符号")
    sp.add_argument("--subject", default="数学", help="学科过滤")
    sp.add_argument("--limit", type=int, default=0, help="本次最多处理多少节")
    sp.add_argument("--force", action="store_true", help="已抽过也重跑")
    sp.set_defaults(func=cmd_mathmap)

    sp = sub.add_parser("enlang", help="英语本体深挖：对话 / 句型语法 / 拼读 / 语篇 / 项目")
    sp.add_argument("--kind", default="dialogue",
                    choices=["dialogue", "grammar", "phonics", "passage", "project"],
                    help="dialogue=情景对话，grammar=句型语法，phonics=拼读，"
                         "passage=语篇（Read and write 等），project=项目任务")
    sp.add_argument("--subject", default="英语", help="学科过滤")
    sp.add_argument("--limit", type=int, default=0, help="本次最多处理多少节")
    sp.add_argument("--force", action="store_true", help="已抽过也重跑")
    sp.set_defaults(func=cmd_enlang)

    sp = sub.add_parser("mathunit", help="数学课级切分：单元级小节再拆成课时")
    sp.add_argument("--subject", default="数学", help="学科过滤")
    sp.add_argument("--fill-gaps", action="store_true",
                    help="补漏模式：只复查课时之间没被覆盖的页")
    sp.add_argument("--retag", action="store_true",
                    help="重挂模式：单元页区间变了之后，把课时重新归到正确单元")
    sp.add_argument("--min-gap", type=int, default=2,
                    help="补漏：至少连续几页的空档才复查")
    sp.add_argument("--limit", type=int, default=0, help="本次最多处理多少册")
    sp.add_argument("--force", action="store_true", help="已切过也重跑")
    sp.set_defaults(func=cmd_mathunit)

    sp = sub.add_parser("enwords", help="抽英语词汇表与常用表达（附录规则层）")
    sp.add_argument("--subject", default="英语", help="学科过滤")
    sp.add_argument("--enrich", action="store_true",
                    help="给已抽出的词补教材原句（对话/语篇里取）与所属话题")
    sp.set_defaults(func=cmd_enwords)

    sp = sub.add_parser("toc", help="看图抽分栏目录骨架（数学/科学等规则抽不出的册）")
    sp.add_argument("--subject", default="", help="学科过滤（如 数学）")
    sp.add_argument("--limit", type=int, default=0, help="本次最多抽多少册")
    sp.add_argument("--force", action="store_true", help="已抽出也重跑")
    sp.add_argument("--min-entries", type=int, default=0,
                    help="已有骨架少于此条数就重抽（如数学填 6）")
    sp.set_defaults(func=cmd_toc)

    sp = sub.add_parser("words", help="抽取识字表/写字表/词语表（知识库 L1 资产）")
    sp.add_argument("--subject", default="", help="学科过滤（如 语文）")
    sp.add_argument("--book-id", default="", help="只抽一册")
    sp.add_argument("--show", type=int, default=0, help="打印前 N 条样例")
    sp.set_defaults(func=cmd_words)

    sp = sub.add_parser("lessons", help="切分课文原文、段落与学习任务（知识库地基）")
    sp.add_argument("--subject", default="语文", help="学科过滤")
    sp.add_argument("--book-id", default="", help="只切一册（不写产物）")
    sp.add_argument("--show", type=int, default=0, help="打印前 N 篇样例")
    sp.set_defaults(func=cmd_lessons)

    sp = sub.add_parser("pieces", help="拆一课多篇（古诗三首/文言文二则）为独立篇")
    sp.add_argument("--subject", default="语文", help="学科过滤")
    sp.add_argument("--show", type=int, default=0, help="打印前 N 篇样例")
    sp.set_defaults(func=cmd_pieces)

    sp = sub.add_parser("audit", help="LLM 校对层：课文细分体裁 / 未定位篇补正文")
    sp.add_argument("--kind", default="genre", choices=["genre", "piece"],
                    help="genre=细分体裁；piece=补未定位篇的正文")
    sp.add_argument("--limit", type=int, default=0, help="本次最多处理多少条")
    sp.add_argument("--force", action="store_true", help="已处理过也重跑")
    sp.set_defaults(func=cmd_audit)

    # 命令名叫 digest：`organize` 已被"下载文件整理"占用
    sp = sub.add_parser("digest", help="LLM 整理层与补充层：段意 / 字词 / 译文 / 作者")
    sp.add_argument("--kind", default="structure",
                    choices=["structure", "gloss", "trans", "author", "intro",
                             "elem"],
                    help="structure=段意与全文大意；gloss=古诗文言文字词解释；"
                         "trans=古诗文言文白话译文；author=作者校对；intro=作者简介；"
                         "elem=单元语文要素（导语页上的读写要素）")
    sp.add_argument("--limit", type=int, default=0, help="本次最多处理多少条")
    sp.add_argument("--force", action="store_true", help="已处理过也重跑")
    sp.set_defaults(func=cmd_digest)

    sp = sub.add_parser("keypoints", help="抽数学/科学小节知识点（摘要/知识点/公式/术语）")
    sp.add_argument("--subject", default="", help="学科过滤（如 数学、科学）")
    sp.add_argument("--limit", type=int, default=0, help="本次最多抽多少节")
    sp.add_argument("--force", action="store_true", help="已抽过也重跑")
    sp.set_defaults(func=cmd_keypoints)

    sp = sub.add_parser("sections", help="切分数学/科学小节正文（骨架 → 一节正文 + 例题/练习）")
    sp.add_argument("--subject", default="", help="学科过滤（如 数学、科学）")
    sp.set_defaults(func=cmd_sections)

    sp = sub.add_parser("kb", help="知识库（DuckDB）：默认重建库，--sql 直接查询")
    sp.add_argument("--subject", default="", help="建库时的学科过滤（默认全部）")
    sp.add_argument("--sql", default="", help="执行 SQL 查询")
    sp.set_defaults(func=cmd_kb)

    sp = sub.add_parser("ensure-page", help="按需在线补解析教材页（本地没有才调 VLM，结果回填）")
    sp.add_argument("book_id")
    sp.add_argument("page_no", type=int, nargs="+")
    sp.add_argument("--force", action="store_true", help="已有内容也重新在线解析")
    sp.add_argument("--show", action="store_true", help="打印正文")
    sp.set_defaults(func=cmd_ensure_page)

    sp = sub.add_parser("photo", help="在线转录孩子拍的题目照片")
    sp.add_argument("image", help="图片路径（png / jpg）")
    sp.set_defaults(func=cmd_photo)

    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
