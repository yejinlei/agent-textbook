# -*- coding: utf-8 -*-
"""解析阶段（待实现）：把 books/ 下的 PDF 变成结构化内容。

计划接口：
    extract_text(pdf_path) -> list[Page]        # 文本层优先，扫描件走 OCR
    split_chapters(pages, toc) -> list[Section] # 结合平台章节树切到「课」粒度
输出带 学段/学科/版本/年级/册次/页码 元数据，供下一阶段入库。
"""
