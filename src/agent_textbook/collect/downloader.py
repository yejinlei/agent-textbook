# -*- coding: utf-8 -*-
"""详情解析与批量下载：产出 books/ 下的教材文件与 data/downloads.jsonl 清单。"""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from .. import config
from .catalog import classify
from .net import download_to, get_json, sanitize_filename

_print_lock = threading.Lock()


def read_manifest() -> list[dict]:
    if not os.path.exists(config.MANIFEST_FILE):
        return []
    with open(config.MANIFEST_FILE, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_manifest(rows: list[dict]) -> str:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.MANIFEST_FILE, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return config.MANIFEST_FILE


def merge_manifest(records: list[dict]) -> None:
    """按 id 合并清单，保留已有字段。"""
    merged = {r["id"]: r for r in read_manifest()}
    for r in records:
        old = merged.get(r["id"], {})
        # 已成功的记录不被重新解析降级，避免重复下载
        if old.get("status") == "ok" and r.get("status") != "ok":
            r = {**r, "status": "ok", "path": old.get("path") or r.get("path"), "size": old.get("size", 0)}
        merged[r["id"]] = {**old, **r}
    write_manifest(list(merged.values()))


def _pick_source(data: dict) -> tuple[str, str, int] | None:
    """从详情 ti_items 中挑出源文件直链、格式与声明大小。"""
    for item in data.get("ti_items") or []:
        if not item.get("ti_is_source_file"):
            continue
        fmt = (item.get("ti_format") or "pdf").lower()
        if fmt == "folder":
            continue
        url = item.get("ti_storage")
        if url:
            return url.replace("cs_path:${ref-path}", f"https://{config.PRIVATE_HOSTS[0]}"), fmt, int(item.get("ti_size") or 0)
        url = next((u for u in item.get("ti_storages") or [] if u), None)
        if url:
            return url, fmt, int(item.get("ti_size") or 0)
    return None


def _resource_title(data: dict) -> str:
    gt = data.get("global_title")
    if isinstance(gt, dict):
        return gt.get("zh-CN") or gt.get("en") or data.get("title") or data["id"]
    return gt or data.get("title") or data.get("id")


def target_rel(row: dict, title: str, fmt: str, region: str) -> str:
    """教材存放相对路径：<地区>/<学段>/<学科>/<版本>/<年级>/<书名>.<fmt>"""
    stage, subject, version, grade = classify(row["path"])
    filename = sanitize_filename(f"{title}.{fmt}")
    return os.path.join(region, stage or "小学", subject, version, grade or "不分年级", filename)


def resolve(row: dict, region: str = config.DEFAULT_REGION) -> dict:
    """解析单本教材详情，得到清单记录（不下载）。"""
    stage, subject, version, grade = classify(row["path"])
    rec = {
        "id": row["id"],
        "title": row["title"],
        "region": region,
        "stage": stage,
        "subject": subject,
        "version": version,
        "grade": grade,
        "preview_url": row.get("preview_url", ""),
        "status": "failed",
        "reason": "",
        "path": "",
        "url": "",
    }
    try:
        data = get_json(config.DETAIL_URL.format(cid=row["id"]), retries=2)
    except Exception as e:  # noqa: BLE001
        rec["reason"] = f"详情请求失败：{e}"
        return rec

    picked = _pick_source(data)
    if not picked:
        rec["reason"] = "详情中没有可下载的源文件"
        return rec

    url, fmt, size = picked
    title = _resource_title(data)
    rec.update({
        "status": "pending",
        "title": title,
        "url": url,
        "format": fmt,
        "expected_size": size,
        "path": target_rel(row, title, fmt, region),
    })
    return rec


def resolve_all(
    rows: list[dict],
    workers: int = config.DEFAULT_WORKERS,
    region: str = config.DEFAULT_REGION,
) -> list[dict]:
    print(f"正在解析详情（{len(rows)} 本）...", flush=True)
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, rec in enumerate(pool.map(lambda r: resolve(r, region), rows), 1):
            out.append(rec)
            if i % 50 == 0 or i == len(rows):
                print(f"  解析 {i}/{len(rows)}", flush=True)
    ok = [r for r in out if r["status"] == "pending"]
    total = sum(r.get("expected_size") or 0 for r in ok) / 1024 ** 3
    print(f"解析完成：可取文件 {len(ok)}，失败 {len(out) - len(ok)}，预计体积 {total:.2f} GB")
    return out


def download_all(
    records: list[dict],
    out_dir: str = config.BOOKS_DIR,
    workers: int = config.DEFAULT_WORKERS,
) -> list[dict]:
    """下载清单中尚未完成的条目，就地更新 status/reason/size。"""
    targets = [r for r in records if r["status"] == "pending" and r.get("url")]
    print(f"开始下载 {len(targets)} 个文件 -> {out_dir}", flush=True)
    done = 0

    def work(rec: dict) -> dict:
        nonlocal done
        abs_path = os.path.join(out_dir, rec["path"])
        expect = rec.get("expected_size") or 0
        if os.path.exists(abs_path) and (not expect or os.path.getsize(abs_path) == expect):
            rec.update(status="ok", reason="", size=os.path.getsize(abs_path))
            with _print_lock:
                done += 1
                print(f"  [{done}/{len(targets)}] 已有 {rec['path']}", flush=True)
            return rec
        try:
            ok, reason = download_to(rec["url"], abs_path, expected_size=expect)
        except Exception as e:  # noqa: BLE001 单个文件异常不能中断整批
            ok, reason = False, f"异常：{e}"
        rec["status"] = "ok" if ok else "failed"
        rec["reason"] = reason
        rec["size"] = os.path.getsize(abs_path) if ok and os.path.exists(abs_path) else 0
        with _print_lock:
            done += 1
            flag = "OK " if ok else "ERR"
            print(f"  [{done}/{len(targets)}] {flag} {rec['path']} {reason}", flush=True)
        return rec

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(work, targets))
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"下载完成：成功 {ok}，失败 {len(results) - ok}")
    return results


def sync_from_disk(out_dir: str = config.BOOKS_DIR) -> int:
    """扫描 out_dir 已存在的 PDF，按文件名回填清单状态（用于中断后续跑）。"""
    index: dict[str, str] = {}
    for dirpath, _dirs, files in os.walk(out_dir):
        for name in files:
            if name.endswith(".part"):
                continue
            index.setdefault(name, os.path.relpath(os.path.join(dirpath, name), out_dir))

    rows = read_manifest()
    updated = 0
    for rec in rows:
        rel = index.get(os.path.basename(rec.get("path") or ""))
        if not rel:
            continue
        abs_path = os.path.join(out_dir, rel)
        rec.update(path=rel, status="ok", reason="", size=os.path.getsize(abs_path))
        updated += 1
    write_manifest(rows)
    return updated


def organize(out_dir: str = config.BOOKS_DIR, region: str = config.DEFAULT_REGION) -> int:
    """把已下载文件搬迁到 <地区>/<学段>/<学科>/<版本>/<年级>/ 布局，并更新清单。"""
    rows = read_manifest()
    moved = 0
    for rec in rows:
        if rec.get("status") != "ok" or not rec.get("path"):
            continue
        name = os.path.basename(rec["path"])
        old = os.path.join(out_dir, rec["path"])
        if not os.path.exists(old):  # 清单路径与磁盘不一致时按文件名找回
            for dirpath, _dirs, files in os.walk(out_dir):
                if name in files:
                    old = os.path.join(dirpath, name)
                    break
            else:
                continue
        new_rel = os.path.join(
            rec.get("region") or region,
            rec.get("stage") or "小学",
            rec.get("subject") or "其他",
            rec.get("version") or "通用",
            rec.get("grade") or "不分年级",
            name,
        )
        new = os.path.join(out_dir, new_rel)
        if os.path.abspath(old) == os.path.abspath(new):
            rec["path"] = new_rel
            continue
        os.makedirs(os.path.dirname(new), exist_ok=True)
        os.replace(old, new)
        rec["path"] = new_rel
        moved += 1
    write_manifest(rows)
    return moved
