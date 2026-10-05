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

# 解析产物
PARSED_DIR = os.path.join(DATA_DIR, "parsed")        # parsed/<book_id>.jsonl
VLM_RAW_DIR = os.path.join(DATA_DIR, "vlm_raw")      # VLM 原始输出，可回溯可 diff
SCAN_FILE = os.path.join(DATA_DIR, "scan.json")      # 全册扫描：页数、文本层判定、通道选择

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

# ---------------------------------------------------------------- 解析通道
# 通道 A：文本层。教材的拼音使用独立字体（如 HanyuXi-JZ），其 ToUnicode 把带调元音
# 映射成了大写字母（tiQn 实为 tiān）。只对命中该字体的 span 做映射替换，避免误伤正文。
PARSE_ENGINE = os.environ.get("PARSE_ENGINE", "auto")   # auto / text_layer / vlm
TEXT_LAYER_MIN_CHARS = 50        # 平均每页字符数低于此值 → 判定无文本层，走 VLM
PINYIN_FONT_PATTERN = "Hanyu"    # 拼音字体名特征
PINYIN_MAP_FILE = os.path.join(SRC_DIR, "parse", "pinyin_map.json")

# 通道 B：VLM。构建期（教材扫描页）与运行期（孩子拍的照片）共用同一套客户端。
VLM_BASE_URL = os.environ.get("VLM_BASE_URL", "https://token.sensenova.cn/v1")
VLM_MODEL = os.environ.get("VLM_MODEL", "sensenova-6.8-flash-lite")
VLM_API_KEY = os.environ.get("VLM_API_KEY", "")
VLM_DPI = int(os.environ.get("VLM_DPI", "200"))
VLM_WORKERS = int(os.environ.get("VLM_WORKERS", "8"))
VLM_TIMEOUT = int(os.environ.get("VLM_TIMEOUT", "180"))
# 推理型模型会用掉上千 token 做思考，max_tokens 给小了会导致正文被截断甚至为空
VLM_MAX_TOKENS = int(os.environ.get("VLM_MAX_TOKENS", "8192"))

# 转录提示词。
# 教材页：除文字外**必须描述插图**——数学的几何图形/线段图/统计图、科学的实验装置图，
# 少了图就读不懂题。图描述与文字转录在同一次调用里完成，不额外增加成本。
VLM_PROMPT_PAGE = (
    "请把这页小学教材完整转录，并描述页面中的插图。严格要求：\n"
    "1. 正文按阅读顺序分行输出，不要加解释，不要省略。\n"
    "2. 拼音必须保留正确的声调字母（如 tiān、dì、shuǐ），不得丢掉声调。\n"
    "3. 数学符号原样保留（÷ × ＋ － ＝ （ ） 等）；表格用 Markdown 表格输出。\n"
    "4. 对页面中的每个插图、图表、照片、示意图，在其出现的位置插入一行：\n"
    "   [图N] 描述：图中画了什么、有哪些标注与数据、说明了什么规律或关系\n"
    "   （N 从 1 开始递增；几何图要说清形状、已知条件与数量关系，实验装置要说清器材与步骤）\n"
    "5. 若页面没有插图，则不要编造 [图N]。"
)
VLM_PROMPT_PHOTO = (
    "请把图片中的题目/作业内容完整转录为纯文本。\n"
    "1. 保留原题文字、数字与符号，不要做题、不要解释、不要改动原题表述。\n"
    "2. 若题目含有图形（几何图、线段图、统计图等），在题目后追加一行：\n"
    "   [图1] 描述：图形的形状、已知条件、数量关系与标注。\n"
    "3. 若图片中没有图形，则不要编造图描述。"
)
