# -*- coding: utf-8 -*-
"""采集阶段：从国家中小学智慧教育平台抓取电子课本。

对外能力：
    catalog    拉取并缓存平台书目
    downloader 解析详情直链、下载教材、维护 data/downloads.jsonl
    net        HTTP 限速 / X-ND-AUTH 签名 / 镜像切换
"""
