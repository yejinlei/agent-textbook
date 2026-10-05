# -*- coding: utf-8 -*-
"""agent-textbook：面向小学生的教材 Agent 工程。

分阶段（pipeline）：
    collect  采集   —— 从国家中小学智慧教育平台抓取电子课本（当前已实现）
    parse    解析   —— PDF 文本/OCR、章节切分（待实现）
    index    入库   —— 分块、向量与关键词索引（待实现）
    agent    应用   —— 基于教材原文的答疑/讲解/出题（待实现）
"""

__version__ = "0.1.0"
