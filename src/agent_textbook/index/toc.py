# -*- coding: utf-8 -*-
"""分栏目录的骨架抽取（VLM 通道）。

为什么规则在这里失效
--------------------
数学/科学的目录是**分栏排版**：单元号、标题、印刷页码各占一列。PDF 文本层
按视觉块输出，于是三列被拆成三段，顺序还常常错位——三年级数学目录抽出来是：

    数字编码 / 曹冲称象的故事 / 观察物体 / …（9 个标题）
    39 / 61 / 57 / 73 / 92 / 1 / 6 / 20 / 31（9 个页码）
    一 / 二 / 三 / 四 / 五 / 六 / 七（7 个单元号）

人一眼能按行配对，规则不行：文本顺序里标题与页码的对应关系已经丢了，而
解析产物**没有坐标**（只有 text），推不回来。所以这类版式只能看图。

产物与规则通道完全同构（``data/outline/<book_id>.jsonl``），下游不用分家。
"""

from __future__ import annotations

import json
import os
import time

from .. import config
from ..parse import vlm
from ..parse.online import find_book
from . import outline

MIN_ENTRIES = 5          # 少于此数视为没读对（一册不可能只有几条）
MAX_TOC_PAGES = 3        # 目录最多跨 3 页


def _find_toc_page_nos(pages: list[dict]) -> list[int]:
    """目录页：优先用规则通道的判定，退化时找带「目录」字样的页。"""
    idxs = outline.find_toc_pages(pages)
    if idxs:
        nos = [pages[i].get("page_no") for i in idxs[:MAX_TOC_PAGES]]
        # 目录常跨页，而续页未必再写一遍「目录」（六年级下册 p5 只剩
        # `比例 4 38` 这种标题+页码）。多带一页让模型一并读——不是目录的页
        # 它只会返回空，不会污染结果；少带一页则整个下册只有半份骨架。
        nxt = pages[idxs[-1] + 1].get("page_no") if idxs[-1] + 1 < len(pages) else None
        if nxt is not None and nxt not in nos:
            nos.append(nxt)
        return nos[:MAX_TOC_PAGES]
    nos = []
    for p in pages[:12]:
        if outline.RE_TOC_WORD.search(p.get("text") or ""):
            nos.append(p.get("page_no"))
        if len(nos) >= MAX_TOC_PAGES:
            break
    return nos


def _parse_array(text: str) -> list[dict]:
    """从模型输出里抠出 JSON 数组。

    模型爱给 Markdown 代码围栏，也爱在 JSON 前后加两句客套话——直接
    ``json.loads`` 整个回答会炸，故只取第一个 ``[`` 到与之配对的 ``]``。
    """
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()
    i = s.find("[")
    if i < 0:
        raise ValueError("回答里没有 JSON 数组")
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "[":
            depth += 1
        elif s[j] == "]":
            depth -= 1
            if depth == 0:
                return json.loads(s[i:j + 1])
    raise ValueError("JSON 数组没有闭合")


def _validate(rows: list[dict], total_pages: int) -> list[dict]:
    """可校验的部分一律不放过：页码越界、页码倒退、标题为空。

    目录天然按印刷页码升序，倒退说明模型把两列配错了——这种骨架一旦入库，
    后面所有切分都会跟着错位，宁可整册判失败。
    """
    if len(rows) < MIN_ENTRIES:
        raise ValueError("只读出 %d 条，不像一册目录" % len(rows))
    # 单条坏数据（模型偶尔给空标题、页码写成"12页"）只丢这一条，不废整册；
    # 但**页码倒退**说明两列配错了，那种骨架一入库后面全跟着错位，必须整册重来。
    out, last = [], 0
    for r in rows:
        title = (str(r.get("title") or "")).strip()
        try:
            page = int(r.get("page"))
        except (TypeError, ValueError):
            continue
        if not title or not (1 <= page <= max(total_pages, 1)) or page < last:
            if page and last and page < last:
                raise ValueError("页码倒退：%d → %d" % (last, page))
            continue
        last = page
        try:
            unit = int(r.get("unit") or 0) or None
        except (TypeError, ValueError):
            unit = None
        out.append({
            "title": title, "printed_start": page,
            "unit_no": unit, "unit_name": (r.get("unit_name") or "").strip(),
        })
    return out


def build_book_vlm(book_id: str, client=None, verbose: bool = False) -> dict:
    """看图抽一册目录骨架，返回与规则通道同构的 {meta, entries}。"""
    meta, pages = outline.load_book(book_id)
    if not meta:
        return {}
    rec = find_book(book_id)
    if not rec or not rec.get("_abs"):
        raise RuntimeError(f"下载清单里找不到 PDF：{book_id}")
    nos = _find_toc_page_nos(pages)
    if not nos:
        raise RuntimeError(f"定位不到目录页：{book_id}")

    client = client or vlm.VLMClient()
    rows: list[dict] = []
    model = ""
    # 429 是平台侧限流（后台批量补插图时会撞上），一次调用只等 5s 肯定不够，
    # 目录这种一册就 1~3 次的调用值得多等几轮。
    tries, delays = 4, (10, 30, 60, 120)
    for n in nos:
        last = ""
        for attempt in range(tries):
            try:
                r = vlm.extract_page_vlm(
                    rec["_abs"], int(n), client=client,
                    prompt=config.VLM_PROMPT_TOC,
                    dpi=vlm.dpi_for_attempt(attempt),
                )
                got = _parse_array(r.text)
                if got:
                    rows.extend(got)
                    model = r.model
                break
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
                if attempt < tries - 1 and vlm.needs_backoff(last):
                    time.sleep(delays[attempt])
        if verbose:
            print(f"   目录 p{n}：{len(rows)} 条" + (f"（{last}）" if last else ""))
        if last and not rows:
            raise RuntimeError(f"目录页 p{n} 读取失败：{last}")

    # 跨页目录会重复上一次的收尾行，按 (标题, 页码) 去重后再排序
    seen, uniq = set(), []
    for r in rows:
        k = ((r.get("title") or "").strip(), r.get("page"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    uniq.sort(key=lambda x: int(x.get("page") or 0))
    got = _validate(uniq, len(pages))

    title = meta.get("title", "")
    term = "上册" if "上册" in title else ("下册" if "下册" in title else "")
    head = {
        "type": "meta", "book_id": book_id,
        "stage": meta.get("stage", ""), "subject": meta.get("subject", ""),
        "version": meta.get("version", ""), "grade": meta.get("grade", ""),
        "term": term, "title": title, "total_pages": len(pages),
        "toc_pages": nos, "entries": len(got), "source": "vlm_toc", "model": model,
    }
    entries = []
    for seq, e in enumerate(got, 1):
        entries.append({
            # 主键口径与规则通道一致：册 id + 目录内序号
            "lesson_id": f"{book_id}:{seq:03d}", "seq": seq,
            "unit_no": e["unit_no"],
            "unit_name": e["unit_name"] or (f"第{e['unit_no']}单元" if e["unit_no"] else ""),
            "unit_tag": "", "section": "", "lesson_no": None,
            "title": e["title"], "printed_start": e["printed_start"],
            "elective": False,
        })
    return {"meta": head, "entries": entries}


def build_all_vlm(subject: str = "", limit: int = 0, force: bool = False,
                  min_entries: int = 0, verbose: bool = True) -> list[dict]:
    """对规则抽不出骨架的册（条目过少）看图重抽。

    ``min_entries`` 是**质量闸门**：目录跨页读漏时会剩半份骨架（数学五年级
    下册只读出 5 条，实际 8 个单元），条目数明显少于同科其它册就该重抽，
    否则残缺骨架会一路带到切分和检索里。
    """
    if not os.path.isdir(config.PARSED_DIR):
        return []
    ids = sorted(f[:-6] for f in os.listdir(config.PARSED_DIR) if f.endswith(".jsonl"))
    client = None
    out = []
    for bid in ids:
        meta, pages = outline.load_book(bid)
        if not meta or not pages:
            continue
        if subject and meta.get("subject") != subject:
            continue
        path = os.path.join(config.OUTLINE_DIR, bid + ".jsonl")
        if not force and os.path.exists(path):
            n = sum(1 for l in open(path, encoding="utf-8") if l.strip()) - 1
            if n >= max(MIN_ENTRIES, min_entries):
                continue
        if client is None:
            client = vlm.VLMClient()
        if verbose:
            print("  %s%s 看图抽目录…" % (meta.get("grade"), meta.get("subject")))
        try:
            r = build_book_vlm(bid, client=client, verbose=verbose)
        except Exception as e:
            if verbose:
                print("    失败：%s" % e)
            continue
        if not r.get("entries"):
            continue
        outline.save_book(r)
        out.append(r)
        if verbose:
            print("    → %d 条" % len(r["entries"]))
        if limit and len(out) >= limit:
            break
    return out
