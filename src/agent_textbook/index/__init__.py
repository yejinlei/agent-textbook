# -*- coding: utf-8 -*-
"""入库阶段（待实现）：解析结果分块并建索引。

计划接口：
    chunk(sections) -> list[Chunk]     # 按课/页分块，保留页码
    build_index(chunks)                # 向量库 + 关键词索引，带学科/年级等过滤字段
"""
