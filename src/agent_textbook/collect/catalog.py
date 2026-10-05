# -*- coding: utf-8 -*-
"""目录采集：拉取平台电子课本层级与书目，并按学段/学科/版本/年级筛选。"""

import json
import os

from .. import config
from .net import get_json

FIELD_STAGE, FIELD_SUBJECT, FIELD_VERSION, FIELD_GRADE = 1, 2, 3, 4


def _parse_hierarchy(hierarchy: list) -> dict:
    """把平台层级解析成 {tag_id: {display_name, children}}。"""
    parsed: dict = {}
    for h in hierarchy or []:
        for ch in h.get("children") or []:
            parsed[ch["tag_id"]] = {
                "display_name": ch.get("tag_name"),
                "children": _parse_hierarchy(ch.get("hierarchies")),
            }
    return parsed


def _path_of(book: dict, hier: dict) -> list[str] | None:
    """用 tag_paths 在层级树里还原 ['电子教材','小学','数学','人教版','一年级']。"""
    tag_paths = book.get("tag_paths") or []
    if not tag_paths:
        return None
    parts = tag_paths[0].split("/")
    if len(parts) < 2 or parts[1] not in hier:
        return None
    node = hier[parts[1]]
    path = [node["display_name"]]
    for p in parts[2:]:
        children = node.get("children") or {}
        if p in children:
            node = children[p]
            path.append(node["display_name"])
    return [x for x in path if x]


def fetch_catalog(verbose: bool = True) -> list[dict]:
    """联网拉取全量书目，返回扁平记录：id/title/path/preview_url。"""
    hier = _parse_hierarchy(get_json(config.TAG_URL).get("hierarchies"))
    version = get_json(config.VERSION_URL)
    raw = version.get("urls")
    urls = raw.split(",") if isinstance(raw, str) else list(raw or [])

    books: list[dict] = []
    for i, url in enumerate(urls, 1):
        data = get_json(url)
        if verbose:
            print(f"  目录分片 {i}/{len(urls)}：{len(data)} 条", flush=True)
        for book in data:
            path = _path_of(book, hier)
            if not path:
                continue
            cid = book.get("id")
            books.append({
                "id": cid,
                "title": book.get("title") or book.get("name") or cid,
                "path": path,
                "preview_url": config.PREVIEW_URL.format(cid=cid),
            })
    return books


def load_catalog() -> list[dict]:
    if not os.path.exists(config.CATALOG_FILE):
        return []
    with open(config.CATALOG_FILE, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save_catalog(rows: list[dict]) -> str:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.CATALOG_FILE, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return config.CATALOG_FILE


def _is_grade(text: str) -> bool:
    return bool(text) and ("年级" in text or "全一册" in text or text in "一二三四五六")


def classify(path: list[str]) -> tuple[str, str, str, str]:
    """从分类路径解析出 (学段, 学科, 版本, 年级)。

    小学路径长为 5（学段/学科/版本/年级），高中长为 4（学段/学科/版本），
    少数条目（如信息科技）没有版本层，此时把年级层让位给年级。
    """
    stage = path[FIELD_STAGE] if len(path) > FIELD_STAGE else ""
    subject = path[FIELD_SUBJECT] if len(path) > FIELD_SUBJECT else "其他"
    version = "通用"
    grade = ""
    tail = path[FIELD_VERSION:]
    if len(tail) >= 2:
        version, grade = tail[0], (tail[1] if _is_grade(tail[1]) else "")
    elif len(tail) == 1:
        if _is_grade(tail[0]):
            grade = tail[0]
        else:
            version = tail[0]
    return stage, subject, version, grade


def is_stage(row: dict, stages=config.STAGES, include_wusi: bool = False) -> bool:
    path = row.get("path") or []
    if len(path) <= FIELD_SUBJECT:
        return False
    stage = path[FIELD_STAGE]
    if stage in stages:
        return True
    return include_wusi and stage.startswith(("小学", "初中"))


def _match(value: str, keywords: str) -> bool:
    if not keywords:
        return True
    return any(k.strip() and k.strip() in value for k in keywords.split(","))


def select_rows(
    rows: list[dict],
    stage: str = "",
    subject: str = "",
    version: str = "",
    grade: str = "",
    preset: str = "",
    include_teacher: bool = False,
    include_wusi: bool = False,
) -> list[dict]:
    """按条件筛选书目。preset 为版本预设名（见 config.VERSION_PRESETS）。"""
    preset_map = config.VERSION_PRESETS.get(preset, {})
    stages = tuple(preset_map) or config.STAGES
    if stage:  # 预设内再按学段收窄
        wanted = tuple(s.strip() for s in stage.split(",") if s.strip())
        stages = tuple(s for s in stages if s in wanted) or wanted
    out = []
    for r in rows:
        if not is_stage(r, stages, include_wusi):
            continue
        if not include_teacher and "教师用书" in (r.get("title") or ""):
            continue
        s, subj, ver, gr = classify(r["path"])
        if subject and not _match(subj, subject):
            continue
        if grade and not _match(gr, grade):
            continue
        picks = preset_map.get(s, {})
        if picks:
            if not any(key in subj and (want == "*" or want in ver) for key, want in picks.items()):
                continue
        elif version and not _match(ver, version):
            continue
        out.append(r)
    return out
