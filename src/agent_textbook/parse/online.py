# -*- coding: utf-8 -*-
"""运行期在线提取：与构建期共用同一套 VLM 客户端。

两条在线通路：

1. **孩子拍照/截图** —— ``transcribe_photo()``：作业题、试卷、练习册拍下来当场转文本，
   prompt 里带图描述要求（几何图、线段图、统计图），直接进 Agent 管线。
2. **教材页按需补解析** —— ``ensure_page()``：本地产物里没有（未解析 / 空壳 / 失败页）
   就当场解析，并**回填**进 ``data/parsed/<book_id>.jsonl``，下次直接命中。

第 2 条让「低价值册不必预先跑」成为可能：美术、书法这类册可以先不批量解析，
等真有人问到某一页时再花几秒解析一次；解析结果落盘，后续复用。
批量通道（parse 命令）与在线通道写的是同一份产物，互不冲突。
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .. import config
from . import vlm
from .pipeline import _write, load_books

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

ONLINE_SOURCE = "vlm_online"   # 与构建期的 vlm / text_layer 区分，便于统计在线补了多少


def _lock_for(book_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(book_id, threading.Lock())


def parsed_path(book_id: str) -> str:
    return os.path.join(config.PARSED_DIR, f"{book_id}.jsonl")


def read_book(book_id: str) -> tuple[dict, list[dict]]:
    """读已解析产物，返回 (meta, pages)。文件不存在时返回空。"""
    path = parsed_path(book_id)
    if not os.path.exists(path):
        return {}, []
    meta: dict = {}
    pages: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") == "page":
                pages.append(row)
            else:
                meta = row
    pages.sort(key=lambda p: p.get("page_no") or 0)
    return meta, pages


def find_book(book_id: str) -> dict | None:
    """按 book_id 从下载清单找教材记录（含绝对路径）。"""
    for r in load_books():
        if r.get("id") == book_id:
            return r
    return None


def needs_online(row: dict | None) -> bool:
    """这页是否需要在线补解析：不存在 / 空壳 / 构建期失败。"""
    if row is None:
        return True
    if not (row.get("text") or "").strip():
        return True
    return row.get("source") == "vlm_error"


def transcribe_photo(image: bytes, client: vlm.VLMClient | None = None,
                     prompt: str | None = None) -> str:
    """运行期：孩子拍的题目照片 → 文本（含图描述）。"""
    client = client or vlm.VLMClient()
    return client.extract(image, prompt or config.VLM_PROMPT_PHOTO).text


def _apply(pages: list[dict], page_no: int, text: str, err: str = "") -> dict:
    row = next((p for p in pages if p.get("page_no") == page_no), None)
    if row is None:
        row = {"type": "page", "page_no": page_no, "printed_no": None, "fonts": []}
        pages.append(row)
    if text:
        row.update(chars=len(text), source=ONLINE_SOURCE, has_pinyin=False,
                   figures=text.count("[图"), text=text)
        row.pop("error", None)
    else:
        row.update(chars=0, source="vlm_error", text="", error=err or "VLM 返回空")
    return row


def _flush(book_id: str, meta: dict, pages: list[dict],
           raws: dict[int, str] | None = None) -> None:
    """把在线补出的页写回产物（同时落 vlm_raw 便于回溯）。"""
    with _lock_for(book_id):
        for page_no, text in (raws or {}).items():
            raw_dir = os.path.join(config.VLM_RAW_DIR, book_id)
            os.makedirs(raw_dir, exist_ok=True)
            with open(os.path.join(raw_dir, f"{page_no:04d}.md"), "w", encoding="utf-8") as f:
                f.write(text)
        pages.sort(key=lambda p: p.get("page_no") or 0)
        if meta:
            meta["chars"] = sum(p.get("chars") or 0 for p in pages)
            meta["figures"] = sum(p.get("figures") or 0 for p in pages)
            meta["failed_pages"] = sum(1 for p in pages if p.get("source") == "vlm_error")
            meta["online_pages"] = sum(1 for p in pages if p.get("source") == ONLINE_SOURCE)
        _write(book_id, meta or {"book_id": book_id, "engine": ONLINE_SOURCE}, pages)


def ensure_page(book_id: str, page_no: int, client: vlm.VLMClient | None = None,
                force: bool = False) -> str:
    """取教材某页文本：本地有就直接用，没有就在线解析并回填。"""
    meta, pages = read_book(book_id)
    row = next((p for p in pages if p.get("page_no") == page_no), None)
    if not force and not needs_online(row):
        return row["text"]

    rec = find_book(book_id)
    if rec is None:
        raise FileNotFoundError(f"下载清单里找不到教材 {book_id}")
    client = client or vlm.VLMClient()
    text, err = "", ""
    try:
        text = vlm.extract_page_vlm(rec["_abs"], page_no, client=client).text
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    _apply(pages, page_no, text, err)
    _flush(book_id, meta, pages, raws={page_no: text} if text else None)
    return text


def ensure_pages(book_id: str, page_nos: list[int],
                 client: vlm.VLMClient | None = None,
                 workers: int = 4) -> dict[int, str]:
    """批量按需补解析：并发调 VLM，但只在最后统一写一次盘，避免并发覆盖。"""
    meta, pages = read_book(book_id)
    have = {p["page_no"]: p["text"] for p in pages if p.get("text")}
    todo = [n for n in page_nos if n not in have]
    if not todo:
        return {n: have[n] for n in page_nos if n in have}

    rec = find_book(book_id)
    if rec is None:
        raise FileNotFoundError(f"下载清单里找不到教材 {book_id}")
    client = client or vlm.VLMClient()

    def one(n: int) -> tuple[int, str, str]:
        """带退避重试：429 限流需要间隔够长才可能成功。"""
        last = ""
        for attempt in range(config.VLM_MAX_RETRIES + 1):
            try:
                return n, vlm.extract_page_vlm(rec["_abs"], n, client=client,
                                                dpi=vlm.dpi_for_attempt(attempt)).text, ""
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
                if attempt < config.VLM_MAX_RETRIES and vlm.needs_backoff(last):
                    time.sleep(config.VLM_RETRY_DELAYS[attempt])
        return n, "", last

    raws: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(todo)))) as pool:
        for n, text, err in pool.map(one, todo):
            _apply(pages, n, text, err)
            if text:
                raws[n] = text
    _flush(book_id, meta, pages, raws=raws)
    return {n: have.get(n) or raws.get(n, "") for n in page_nos}
