# -*- coding: utf-8 -*-
"""解析阶段：把 books/ 下的 PDF 变成结构化内容。

双通道（见 docs/系统设计文档.md §6）：
    通道 A 文本层  extract.extract_pages  PyMuPDF + 拼音字体映射修复，严格保持原文顺序
    通道 B VLM    vlm.extract_page_vlm   多模态转录；扫描版教材页 / 运行期孩子拍的照片

编排：pipeline.parse_book / parse_all / parse_status

教材的拼音使用独立字体（HanyuXi-JZ），其 ToUnicode 把带调元音映射成大写字母，
于是 tiQn 实为 tiān——由 pinyin_map.json 按字体定位后还原。
"""

from . import extract, pipeline, vlm
from .extract import Page, extract_pages, fix_pinyin, load_pinyin_map, scan_book
from .vlm import VLMClient, VLMResult, extract_photo, extract_page_vlm, render_page

__all__ = [
    "extract", "vlm", "pipeline",
    "Page", "extract_pages", "fix_pinyin", "load_pinyin_map", "scan_book",
    "VLMClient", "VLMResult", "extract_page_vlm", "extract_photo", "render_page",
]
