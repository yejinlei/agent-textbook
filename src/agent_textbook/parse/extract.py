# -*- coding: utf-8 -*-
"""通道 A：文本层抽取（PyMuPDF）+ 拼音字体映射修复。

教材的拼音使用独立字体（如 HanyuXi-JZ），其 ToUnicode 把带调元音映射成了大写字母，
于是 ``tiQn`` 实为 ``tiān``。任何 PDF 库都还原不了（字体本身就是这么标的），
只能按字体定位后做映射替换。

只对命中拼音字体的 span 做替换，正文里的大写字母（如英语 ``A``、``B``）不受影响。
映射表由 parse/pinyin_map.json 提供，可用 pypinyin 反查汉字读音自动推断与校验。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import pymupdf

from .. import config

_MAP: dict[str, str] | None = None


def load_pinyin_map() -> dict[str, str]:
    """加载并缓存拼音乱码映射表。"""
    global _MAP
    if _MAP is None:
        try:
            with open(config.PINYIN_MAP_FILE, encoding="utf-8") as f:
                _MAP = json.load(f)
        except FileNotFoundError:
            _MAP = {}
    return _MAP


def is_pinyin_font(font: str | None) -> bool:
    return bool(font) and config.PINYIN_FONT_PATTERN in font


def fix_pinyin(text: str, font: str | None = None) -> str:
    """修复拼音乱码。

    font 传入时，仅命中拼音字体才替换；font 为 None 时无条件替换（调用方已自行筛选）。
    """
    if not text:
        return text
    m = load_pinyin_map()
    if not m:
        return text
    if font is not None and not is_pinyin_font(font):
        return text
    return "".join(m.get(ch, ch) for ch in text)


@dataclass
class Page:
    """一页教材的解析结果。"""

    page_no: int                      # 物理页码（0-based）
    text: str
    chars: int
    source: str                       # text_layer / empty / vlm
    printed_no: int | None = None     # 书上页码（取自页末独立数字）
    has_pinyin: bool = False
    fonts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "page_no": self.page_no,
            "printed_no": self.printed_no,
            "chars": self.chars,
            "source": self.source,
            "has_pinyin": self.has_pinyin,
            "fonts": self.fonts,
            "text": self.text,
        }


def _page_text(page, fix: bool = True) -> tuple[str, bool, set[str]]:
    """按 span 重建页面文本，返回 (文本, 是否含拼音, 字体集合)。"""
    lines: list[str] = []
    fonts: set[str] = set()
    has_pinyin = False
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            parts: list[str] = []
            for span in line.get("spans", []):
                t = span["text"]
                font = span.get("font", "")
                fonts.add(font)
                if is_pinyin_font(font):
                    has_pinyin = True
                    if fix:
                        t = fix_pinyin(t, font)
                parts.append(t)
            s = "".join(parts).strip()
            if s:
                lines.append(s)
    return "\n".join(lines), has_pinyin, fonts


def _guess_printed_no(text: str) -> int | None:
    """页末独立成行的 1–3 位数字，通常是书上页码。

    注意：教材页脚会出现带圈数字（①②③）等装饰符号，``str.isdigit()`` 对它们
    返回 True 但 ``int()`` 会抛错，因此限定为 ASCII 数字。
    """
    for line in reversed(text.splitlines()[-3:]):
        s = line.strip()
        if 1 <= len(s) <= 3 and s.isascii() and s.isdigit():
            return int(s)
    return None


def extract_pages(pdf_path: str, fix: bool = True) -> list[Page]:
    """逐页抽取文本层，并修复拼音字体乱码。"""
    doc = pymupdf.open(pdf_path)
    pages: list[Page] = []
    try:
        for i in range(len(doc)):
            text, has_pinyin, fonts = _page_text(doc[i], fix=fix)
            pages.append(Page(
                page_no=i,
                text=text,
                chars=len(text),
                source="text_layer" if text.strip() else "empty",
                printed_no=_guess_printed_no(text),
                has_pinyin=has_pinyin,
                fonts=sorted(fonts),
            ))
    finally:
        doc.close()
    return pages


def scan_book(pdf_path: str, sample: int = 5) -> dict:
    """抽样判定整册是否有文本层，决定走哪个通道。"""
    doc = pymupdf.open(pdf_path)
    n = len(doc)
    idxs = sorted({min(n - 1, max(0, int(n * i / sample) + 1)) for i in range(sample)})
    vals = []
    try:
        for i in idxs:
            vals.append(len(doc[i].get_text().strip()))
    finally:
        doc.close()
    avg = sum(vals) / max(1, len(vals))
    return {
        "pages": n,
        "avg_chars": round(avg, 1),
        "need_vlm": avg < config.TEXT_LAYER_MIN_CHARS,
    }


def scan_all(books_dir: str | None = None) -> list[dict]:
    """扫描全部教材，输出每册的页数与通道判定。"""
    root = books_dir or config.BOOKS_DIR
    rows: list[dict] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(".pdf"):
                continue
            path = os.path.join(dirpath, name)
            try:
                info = scan_book(path)
            except Exception as exc:  # 单册失败不影响整体
                info = {"pages": 0, "avg_chars": 0.0, "need_vlm": True, "error": str(exc)}
            info["rel"] = os.path.relpath(path, root)
            info["path"] = path
            rows.append(info)
    rows.sort(key=lambda r: r["rel"])
    return rows
