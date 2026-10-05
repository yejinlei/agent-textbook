# -*- coding: utf-8 -*-
"""全量核对与补齐：把「没提取到的」全部补上（含插图理解）。

三类缺口：
    1. **空壳册**  整册几乎没有内容（扫描册）    → 整册 VLM，且断点续跑
    2. **空洞页**  有文本层的册里的个别空页       → 单页 VLM（多为整页插图/封面）
    3. **失败页**  构建期报错留空的页             → 单页 VLM 重跑

命令可重复执行：补过的页写回产物，下次核对就不再出现在缺口里。
"""

from __future__ import annotations

import glob
import json
import os
import time

from .. import config
from . import online, vlm
from .pipeline import load_books, parse_vlm_book


def read_parsed(path: str) -> tuple[dict, list[dict]]:
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    meta = next((r for r in rows if r.get("type") != "page"), {})
    pages = [r for r in rows if r.get("type") == "page"]
    return meta, pages


def audit(subject: str = "") -> dict:
    """核对全部已解析产物，列出缺口。"""
    empty_books: list[tuple[dict, int, int]] = []
    gaps: dict[str, list[int]] = {}
    total_books = total_pages = 0

    for f in sorted(glob.glob(os.path.join(config.PARSED_DIR, "*.jsonl"))):
        meta, pages = read_parsed(f)
        if not pages:
            continue
        if subject and subject not in (meta.get("subject") or ""):
            continue
        total_books += 1
        total_pages += len(pages)
        missing = [p["page_no"] for p in pages
                   if not (p.get("text") or "").strip() or p.get("source") == "vlm_error"]
        if missing:
            if len(missing) / len(pages) > 0.5:
                empty_books.append((meta, len(pages), len(missing)))
            else:
                gaps[meta.get("book_id") or ""] = missing

    return {
        "total_books": total_books, "total_pages": total_pages,
        "empty_books": empty_books, "gaps": gaps,
        "missing_pages": sum(b[2] for b in empty_books) + sum(len(v) for v in gaps.values()),
    }


def backfill(subject: str = "", workers: int | None = None, page_workers: int = 4,
             dry_run: bool = False, verbose: bool = True) -> dict:
    """核对 + 补齐。dry_run 只核对不提取。"""
    a = audit(subject)
    if verbose:
        print(f"核对：{a['total_books']} 册 / {a['total_pages']} 页，"
              f"待补 {a['missing_pages']} 页")
        if a["empty_books"]:
            print(f"\n空壳册 {len(a['empty_books'])} 册（整册补）：")
            for meta, n, m in a["empty_books"]:
                print(f"   {meta.get('subject'):<18}{meta.get('grade'):<5}"
                      f"{n:>4}页 缺{m:>4}  {meta.get('title', '')[:20]}")
        if a["gaps"]:
            print(f"\n零散缺口 {len(a['gaps'])} 册 / {sum(len(v) for v in a['gaps'].values())} 页：")
            for bid, nos in list(a["gaps"].items())[:10]:
                print(f"   {bid[:8]}… {len(nos)} 页")
    if dry_run or not a["missing_pages"]:
        return {**a, "done_books": [], "done_pages": 0}

    recs = {r.get("id"): r for r in load_books()}
    client = vlm.VLMClient()
    done_books, done_pages, t0 = [], 0, time.time()

    for meta, n, m in a["empty_books"]:
        rec = recs.get(meta.get("book_id"))
        if rec is None:
            print(f"   跳过 {meta.get('title', '')[:20]}：清单里找不到 PDF")
            continue
        st = parse_vlm_book(rec, client=client, workers=workers)
        done_books.append(st)
        if verbose:
            print(f"   整册补完 {st.get('title', '')[:20]}：{st.get('pages')} 页 / "
                  f"{st.get('chars')} 字 / 图 {st.get('figures')} 处 / "
                  f"失败 {st.get('failed_pages')} 页")

    for bid, nos in a["gaps"].items():
        res = online.ensure_pages(bid, nos, client=client, workers=page_workers)
        ok = sum(1 for v in res.values() if v)
        done_pages += ok
        if verbose:
            print(f"   单页补完 {bid[:8]}… {ok}/{len(nos)} 页")

    if verbose:
        print(f"\n补齐完成：{len(done_books)} 册 + {done_pages} 页，"
              f"耗时 {(time.time() - t0) / 60:.1f} 分钟")
        left = audit(subject)
        print(f"复核：仍缺 {left['missing_pages']} 页")
    return {**a, "done_books": done_books, "done_pages": done_pages}
