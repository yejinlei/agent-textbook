# -*- coding: utf-8 -*-
"""只补插图：给**已有正文**的册补插图描述，正文一字不动。

为什么必须单独开一条通道
------------------------
``config.VLM_PROMPT_PAGE`` 把「正文转录」和「插图描述」放在**同一次调用**里完成——
这对无文本层的扫描册是必须的（否则一个字都拿不到），但对**已有正文的文本层册**
就不能复用：用 VLM 重跑整页，会用转录结果**覆盖** PDF 内嵌文本抽出来的正文，
而后者更精确（拼音声调映射、数学符号都是无损的）。

所以本模块只做一件事：渲染页面 → 让模型**只描述插图** → 单独落盘。
``data/parsed/`` 完全不动，产物是侧车文件：

    data/figures/<book_id>/<page_no>.md      # 每页的插图描述（[图N] 行，或 [无图]）
    data/figures/_index.jsonl                # 追加式索引：book_id / page_no / figures / model / ts

检索时按 (book_id, page_no) 关联即可，不侵入既有产物，也可随时删除重来。

命令可重复执行：已补过的页自动跳过（--force 才重跑）。
"""

from __future__ import annotations

import glob
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from .. import config
from . import vlm
from .online import find_book, read_book

NO_FIGURE = "[无图]"          # 模型对"整页没有插图"的统一回答
_INDEX = "_index.jsonl"


def figures_dir(book_id: str) -> str:
    return os.path.join(config.FIGURES_DIR, book_id)


def figures_path(book_id: str, page_no: int) -> str:
    return os.path.join(figures_dir(book_id), f"{page_no:04d}.md")


def count_figures(text: str) -> int:
    """统计一页里描述了几张图；[无图] 视为 0。"""
    if not text or NO_FIGURE in text:
        return 0
    return text.count("[图")


def write_page(book_id: str, page_no: int, text: str, model: str) -> None:
    os.makedirs(figures_dir(book_id), exist_ok=True)
    with open(figures_path(book_id, page_no), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(config.FIGURES_DIR, _INDEX), "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "book_id": book_id, "page_no": page_no,
            "figures": count_figures(text), "model": model,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False) + "\n")


def done_pages(book_id: str) -> set[int]:
    """已经补过（且产物非空）的页码。"""
    d = figures_dir(book_id)
    if not os.path.isdir(d):
        return set()
    out: set[int] = set()
    for p in glob.glob(os.path.join(d, "*.md")):
        try:
            n = int(os.path.splitext(os.path.basename(p))[0])
        except ValueError:
            continue
        try:
            if os.path.getsize(p) > 0:
                out.add(n)
        except OSError:
            continue
    return out


def audit(subject: str = "") -> dict:
    """列出待补范围。

    只处理**正文已经存在**的页——正文缺失的页属于 backfill 的职责，
    先让它把正文补齐，再补插图，避免顺序颠倒。
    """
    targets: list[dict] = []
    total_books = total_pages = 0

    for f in sorted(glob.glob(os.path.join(config.PARSED_DIR, "*.jsonl"))):
        book_id = os.path.splitext(os.path.basename(f))[0]
        meta, pages = read_book(book_id)
        if not pages:
            continue
        if subject and subject not in (meta.get("subject") or ""):
            continue
        total_books += 1
        total_pages += len(pages)
        have = done_pages(book_id)
        todo = [p["page_no"] for p in pages
                if (p.get("text") or "").strip() and p["page_no"] not in have]
        if todo:
            targets.append({
                "book_id": book_id,
                "subject": meta.get("subject") or "",
                "grade": meta.get("grade") or "",
                "title": meta.get("title") or "",
                "pages": len(pages),
                "todo": todo,
            })

    return {
        "total_books": total_books, "total_pages": total_pages,
        "targets": targets,
        "todo_pages": sum(len(t["todo"]) for t in targets),
    }


def backfill_figures(subject: str = "", workers: int | None = None, limit: int = 0,
                     dry_run: bool = False, force: bool = False,
                     verbose: bool = True) -> dict:
    """只补插图。dry_run 只核对不调用。

    workers 默认取 ``config.VLM_WORKERS``（整册批量用 8 求快；失败页留着下次再补）。
    limit 限制本次最多补多少**页**，便于先小批量试跑看质量。
    """
    if force:
        # 重跑：清掉已有产物，让 audit 重新把它们算进 todo
        for d in glob.glob(os.path.join(config.FIGURES_DIR, "*")):
            if os.path.isdir(d):
                for p in glob.glob(os.path.join(d, "*.md")):
                    os.remove(p)

    a = audit(subject)
    if verbose:
        print(f"核对：{a['total_books']} 册 / {a['total_pages']} 页，"
              f"待补插图 {a['todo_pages']} 页")
        for t in a["targets"][:12]:
            print(f"   {t['subject']:<12}{t['grade']:<5}{t['title'][:16]:<18}"
                  f"{len(t['todo']):>5}/{t['pages']:<5} 页")
        if len(a["targets"]) > 12:
            print(f"   …另有 {len(a['targets']) - 12} 册")
    if dry_run or not a["todo_pages"]:
        return {**a, "done_pages": 0, "failed_pages": 0, "figures": 0}

    os.makedirs(config.FIGURES_DIR, exist_ok=True)
    client = vlm.VLMClient()
    w = max(1, workers or config.VLM_WORKERS)
    t0 = time.time()
    done = failed = figs = 0
    budget = limit if limit > 0 else None

    for t in a["targets"]:
        if budget is not None and done + failed >= budget:
            break
        rec = find_book(t["book_id"])
        if rec is None:
            print(f"   跳过 {t['title'][:20]}：下载清单里找不到 PDF")
            continue
        todo = t["todo"]
        if budget is not None:
            room = budget - (done + failed)
            if room <= 0:
                break
            todo = todo[:room]

        def one(n: int) -> tuple[int, str, str, str]:
            """带退避重试：429/413/超时等平台侧问题等一会儿才可能恢复。

            为什么 400 也要重试：整页渲染出的 PNG 过大时平台回 400（而不是 413），
            原先只有 needs_backoff 认的错才重试，400 直接判死，于是一册里总有
            几页永远补不上（实测数学 5 页 / 语文 2 页）。降档 dpi 后图变小就能过，
            所以这里对任何异常都重试，只在平台侧错误时才退避等待。
            """
            last = ""
            for attempt in range(config.VLM_MAX_RETRIES + 1):
                try:
                    r = vlm.extract_page_vlm(
                        rec["_abs"], n, client=client,
                        prompt=config.VLM_PROMPT_FIGURE,
                        dpi=vlm.dpi_for_attempt(attempt),
                    )
                    return n, r.text, r.model, ""
                except Exception as exc:
                    last = f"{type(exc).__name__}: {exc}"
                    if attempt >= config.VLM_MAX_RETRIES:
                        break
                    if vlm.needs_backoff(last):
                        time.sleep(config.VLM_RETRY_DELAYS[attempt])
            # 平台内容审核会把少数页判成 "sensitive image"（code 18）整页拒答——
            # 教材里的儿童照片、人体示意图常被误判。缩到更低分辨率重渲一次往往
            # 能过审（实测数学三上 p95 在 72 dpi 下就通过了），仍被拒就放弃该页。
            try:
                r = vlm.extract_page_vlm(
                    rec["_abs"], n, client=client,
                    prompt=config.VLM_PROMPT_FIGURE, dpi=72,
                )
                if r.text:
                    return n, r.text, r.model, ""
            except Exception as exc:
                last = "低 dpi 仍被拒：%s: %s" % (type(exc).__name__, exc)
            return n, "", "", last

        ok = bad = got = 0
        with ThreadPoolExecutor(max_workers=max(1, min(w, len(todo)))) as pool:
            for n, text, model, err in pool.map(one, todo):
                if text:
                    write_page(t["book_id"], n, text, model)
                    ok += 1
                    got += count_figures(text)
                else:
                    bad += 1
        done += ok
        failed += bad
        figs += got
        if verbose:
            print(f"   插图补完 {t['subject']}{t['grade']} {t['title'][:14]}："
                  f"{ok}/{len(todo)} 页，描述 {got} 处" + (f"，失败 {bad}" if bad else ""))

    if verbose:
        print(f"\n补齐完成：{done} 页 / 插图 {figs} 处，失败 {failed} 页，"
              f"耗时 {(time.time() - t0) / 60:.1f} 分钟")
    return {**a, "done_pages": done, "failed_pages": failed, "figures": figs}
