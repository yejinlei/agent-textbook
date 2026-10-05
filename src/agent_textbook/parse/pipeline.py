# -*- coding: utf-8 -*-
"""解析编排：按册选择通道，产出 data/parsed/<book_id>.jsonl。

通道选择：
    有文本层（平均字符数 >= 阈值） → 通道 A：PyMuPDF + 拼音字体映射（权威顺序）
    无文本层（扫描版）             → 通道 B：VLM 转录（唯一来源）

VLM 的原始输出同时落到 data/vlm_raw/，便于换模型后 diff 与人工核对。
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from .. import config
from . import extract, vlm

MAX_RETRIES = 2   # 单页 VLM 调用失败重试次数（应对限流与偶发超时）


def _need_vlm_map() -> dict[str, bool]:
    """从 data/scan.json 读取「该册是否无文本层」。"""
    try:
        with open(config.SCAN_FILE, encoding="utf-8") as f:
            return {r["rel"]: r["need_vlm"] for r in json.load(f) if "rel" in r}
    except Exception:
        return {}


def load_books(stage: str = "", subject: str = "", grade: str = "",
               version: str = "", need_vlm_only: bool = False) -> list[dict]:
    """从下载清单取已成功教材，附加绝对路径。"""
    from ..collect import downloader as dl

    rows = [r for r in dl.read_manifest() if r.get("status") == "ok" and r.get("path")]
    out = []
    vlm_map = _need_vlm_map() if need_vlm_only else {}
    for r in rows:
        if stage and stage not in (r.get("stage") or ""):
            continue
        if subject and subject not in (r.get("subject") or ""):
            continue
        if grade and grade not in (r.get("grade") or ""):
            continue
        if version and version not in (r.get("version") or ""):
            continue
        abs_path = os.path.join(config.BOOKS_DIR, r["path"])
        if not os.path.exists(abs_path):
            continue
        if need_vlm_only:
            need = vlm_map.get(r["path"])
            if need is None:  # 无 scan.json 时现场判定
                need = extract.scan_book(abs_path)["need_vlm"]
            if not need:
                continue
        out.append({**r, "_abs": abs_path})
    out.sort(key=lambda r: r["path"])
    return out


def _write(book_id: str, meta: dict, pages: list[dict]) -> str:
    os.makedirs(config.PARSED_DIR, exist_ok=True)
    path = os.path.join(config.PARSED_DIR, f"{book_id}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "meta", **meta}, ensure_ascii=False) + "\n")
        for p in pages:
            f.write(json.dumps({"type": "page", **p}, ensure_ascii=False) + "\n")
    return path


def parse_text_book(rec: dict) -> dict:
    """通道 A：文本层抽取 + 拼音字体映射修复。"""
    pages = extract.extract_pages(rec["_abs"])
    rows = [p.to_dict() for p in pages]
    chars = sum(p["chars"] for p in rows)
    meta = {
        "book_id": rec.get("id"),
        "stage": rec.get("stage"), "subject": rec.get("subject"),
        "version": rec.get("version"), "grade": rec.get("grade"),
        "title": rec.get("title"), "rel_path": rec.get("path"),
        "engine": "text_layer", "pages": len(rows), "chars": chars,
        "pinyin_pages": sum(1 for p in rows if p["has_pinyin"]),
        "empty_pages": sum(1 for p in rows if p["chars"] == 0),
    }
    path = _write(rec.get("id") or "unknown", meta, rows)
    return {**meta, "out": path}


def parse_vlm_book(rec: dict, client: vlm.VLMClient | None = None,
                   workers: int | None = None, resume: bool = True) -> dict:
    """通道 B：VLM 逐页转录（用于无文本层的扫描册）。

    resume=True 时复用 ``data/vlm_raw/<book_id>/`` 里已解析过的页——
    整册跑到一半中断后重跑不会浪费已完成的部分。
    """
    client = client or vlm.VLMClient()
    workers = workers or config.VLM_WORKERS
    doc_pages = extract.scan_book(rec["_abs"])["pages"]
    raw_dir = os.path.join(config.VLM_RAW_DIR, str(rec.get("id") or "unknown"))
    os.makedirs(raw_dir, exist_ok=True)

    results: dict[int, vlm.VLMResult] = {}
    errors: dict[int, str] = {}

    cached: dict[int, str] = {}
    if resume:
        for name in os.listdir(raw_dir):
            if not name.endswith(".md"):
                continue
            try:
                with open(os.path.join(raw_dir, name), encoding="utf-8") as f:
                    cached[int(name[:-3])] = f.read()
            except Exception:
                continue
    todo = [i for i in range(doc_pages) if i not in cached]

    def one(i: int) -> tuple[int, vlm.VLMResult | None, str]:
        """单页失败不拖垮整册：重试若干次仍失败则记下原因，留空待补。"""
        last = ""
        for attempt in range(MAX_RETRIES + 1):
            try:
                return i, vlm.extract_page_vlm(rec["_abs"], i, client=client), ""
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
                time.sleep(2 * (attempt + 1))
        return i, None, last

    for i, text in cached.items():
        results[i] = vlm.VLMResult(text=text, model="cache", elapsed=0.0)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, res, err in pool.map(one, todo):
            if res is None:
                errors[i] = err
                continue
            results[i] = res
            with open(os.path.join(raw_dir, f"{i:04d}.md"), "w", encoding="utf-8") as f:
                f.write(res.text)

    rows: list[dict] = []
    for i in range(doc_pages):
        r = results.get(i)
        row = {
            "page_no": i,
            "printed_no": None,
            "chars": len(r.text) if r else 0,
            "source": "vlm" if r else "vlm_error",
            "has_pinyin": False,
            "figures": r.text.count("[图") if r else 0,
            "fonts": [],
            "text": r.text if r else "",
        }
        if r is None:
            row["error"] = errors[i]
        rows.append(row)

    meta = {
        "book_id": rec.get("id"),
        "stage": rec.get("stage"), "subject": rec.get("subject"),
        "version": rec.get("version"), "grade": rec.get("grade"),
        "title": rec.get("title"), "rel_path": rec.get("path"),
        "engine": "vlm", "model": client.model, "pages": len(rows),
        "chars": sum(r["chars"] for r in rows), "pinyin_pages": 0,
        "figures": sum(r["figures"] for r in rows),
        "failed_pages": len(errors),
    }
    path = _write(rec.get("id") or "unknown", meta, rows)
    return {**meta, "out": path}


def _should_skip(out_path: str, engine: str) -> bool:
    """是否跳过已解析的册。

    关键：扫描册先用文本层跑过会留下**空壳文件**（有文件、几乎没内容），
    不能因为有文件就跳过，否则这些册永远不会被 VLM 补上。
    """
    if not os.path.exists(out_path):
        return False
    try:
        with open(out_path, encoding="utf-8") as f:
            meta = json.loads(f.readline())
    except Exception:
        return False
    prev = meta.get("engine")
    if engine == "vlm":
        return prev == "vlm" and not meta.get("failed_pages")
    if engine == "text_layer":
        return prev == "text_layer"
    # auto：VLM 结果只要没有失败页就够；文本层结果不能是空壳
    if prev == "vlm":
        return not meta.get("failed_pages")
    pages = meta.get("pages") or 1
    empty = meta.get("empty_pages")
    if empty is None:  # 老产物没统计，按总字数粗判
        return (meta.get("chars") or 0) > 1000
    return empty / pages < 0.5


def parse_book(rec: dict, engine: str = "auto", client: vlm.VLMClient | None = None,
               workers: int | None = None, force: bool = False) -> dict:
    """解析一册。engine: auto / text_layer / vlm。"""
    out_path = os.path.join(config.PARSED_DIR, f"{rec.get('id')}.jsonl")
    if not force and _should_skip(out_path, engine):
        return {"book_id": rec.get("id"), "title": rec.get("title"),
                "engine": "skipped", "out": out_path}

    if engine == "vlm":
        return parse_vlm_book(rec, client=client, workers=workers)
    if engine == "text_layer":
        return parse_text_book(rec)

    info = extract.scan_book(rec["_abs"])
    if info["need_vlm"]:
        return parse_vlm_book(rec, client=client, workers=workers)
    return parse_text_book(rec)


def parse_all(books: list[dict], engine: str = "auto", workers: int | None = None,
              force: bool = False) -> list[dict]:
    """批量解析。册级串行、页级并发，避免放大 VLM 并发。"""
    client = None
    if engine in ("vlm", "auto"):
        try:
            client = vlm.VLMClient()
        except RuntimeError:
            if engine == "vlm":
                raise
            client = None  # auto 模式下无凭据也能先跑文本层册
    stats = []
    for i, rec in enumerate(books, 1):
        try:
            st = parse_book(rec, engine=engine, client=client, workers=workers, force=force)
        except Exception as exc:
            st = {"book_id": rec.get("id"), "title": rec.get("title"),
                  "engine": "error", "error": str(exc)}
        stats.append(st)
        print(f"  [{i}/{len(books)}] {st.get('engine'):11s} "
              f"{st.get('pages', '-')}页 {rec.get('title', '')[:34]}", flush=True)
    return stats


def parse_status() -> dict:
    """统计解析进度。"""
    d = config.PARSED_DIR
    if not os.path.isdir(d):
        return {"books": 0, "pages": 0, "engines": {}, "chars": 0}
    engines: dict[str, int] = {}
    pages = 0
    chars = 0
    for name in os.listdir(d):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(d, name), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("type") == "meta":
                    engines[row.get("engine", "?")] = engines.get(row.get("engine", "?"), 0) + 1
                elif row.get("type") == "page":
                    pages += 1
                    chars += row.get("chars") or 0
    return {"books": sum(engines.values()), "pages": pages,
            "engines": engines, "chars": chars}
