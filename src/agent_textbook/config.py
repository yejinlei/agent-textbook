# -*- coding: utf-8 -*-
"""工程路径、平台常量与版本预设。"""

import os

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SRC_DIR))

# 数据产物
BOOKS_DIR = os.path.join(ROOT, "books")        # 教材文件：books/<学段>/<学科>/<版本>/<年级>/*.pdf
DATA_DIR = os.path.join(ROOT, "data")          # 元数据：目录、下载清单、凭据
CATALOG_FILE = os.path.join(DATA_DIR, "catalog.jsonl")
MANIFEST_FILE = os.path.join(DATA_DIR, "downloads.jsonl")
TOKEN_FILE = os.path.join(DATA_DIR, "token.json")

# 平台地址（方法参考 happycola233/tchMaterial-parser）
SFILE = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrs"
TAG_URL = f"{SFILE}/tags/tch_material_tag.json"
VERSION_URL = f"{SFILE}/resources/tch_material/version/data_version.json"
DETAIL_URL = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{cid}.json"
PREVIEW_URL = (
    "https://basic.smartedu.cn/tchMaterial/detail?contentType=assets_document"
    "&contentId={cid}&catalogType=tchMaterial&subCatalog=tchMaterial"
)
PRIVATE_HOSTS = tuple(f"r{i}-ndr-private.ykt.cbern.com.cn" for i in range(1, 4))

# 网络策略：私有 CDN 短时间连打会回 400，需要限速 + 退避重试
REQUEST_TIMEOUT = (10, 60)
MIN_REQUEST_INTERVAL = 0.2
RETRY_400_DELAYS = (1.0, 3.0)
DEFAULT_WORKERS = 3

# 学段
STAGES = ("小学", "初中", "高中")
PRIMARY_STAGES = ("小学", "小学（五•四学制）")

# 地区层：教材选用以地区为单位，目录第一层放地区
DEFAULT_REGION = "浙江杭州"

# 版本预设：地区 -> 学段 -> 学科 -> 版本关键字（* 表示不限版本）
VERSION_PRESETS: dict[str, dict[str, dict[str, str]]] = {
    "hangzhou": {
        "小学": {
            "语文": "统编版",
            "道德与法治": "统编版",
            "数学": "人教版",
            "英语": "人教版（主编：吴欣）",
            "科学": "教科版",
            "艺术·音乐": "人音版（主编：赵季平，杜永寿）",
            "艺术·美术": "浙人美版",
            "体育与健康": "人教版",
            "信息科技": "*",
            "语文·书法练习指导": "西泠印社版",
        },
        "初中": {
            "语文": "统编版",
            "道德与法治": "统编版",
            "历史": "统编版",
            "数学": "浙教版",
            "英语": "人教版",
            "科学": "浙教版",
            "地理": "人教版",
            "地理图册": "配套人教版",
            "艺术·音乐": "人音版（主编：赵季平，杜永寿）",
            "艺术·美术": "浙人美版",
            "体育与健康": "人教版",
            "信息科技": "*",
        },
        "高中": {
            "语文": "统编版",
            "思想政治": "统编版",
            "历史": "统编版",
            "数学": "人教A版",
            "英语": "人教版",
            "物理": "人教版",
            "化学": "人教版",
            "生物学": "人教版",
            "地理": "人教版",
            "地理图册": "配套人教版",
            "信息技术": "浙教版",
            "通用技术": "苏教版",
            "音乐": "人音版",
            "美术": "人美版",
            "体育与健康": "人教版",
        },
    },
}
