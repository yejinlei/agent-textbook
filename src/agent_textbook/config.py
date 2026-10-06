# -*- coding: utf-8 -*-
"""工程路径、平台常量与版本预设。"""

import os

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SRC_DIR))


def _load_dotenv(path=None):
    """把项目根 ``.env`` 载入环境变量——**不覆盖**已存在的环境变量。

    不引第三方依赖，只认 ``KEY=VALUE`` 与 ``#`` 注释。
    命令行里显式设置的值（如临时换模型）优先于 .env。
    """
    p = path or os.path.join(ROOT, ".env")
    if not os.path.exists(p):
        return
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_dotenv()

# 数据产物
BOOKS_DIR = os.path.join(ROOT, "books")        # 教材文件：books/<学段>/<学科>/<版本>/<年级>/*.pdf
DATA_DIR = os.path.join(ROOT, "data")          # 元数据：目录、下载清单、凭据
CATALOG_FILE = os.path.join(DATA_DIR, "catalog.jsonl")
MANIFEST_FILE = os.path.join(DATA_DIR, "downloads.jsonl")
TOKEN_FILE = os.path.join(DATA_DIR, "token.json")

# 解析产物
PARSED_DIR = os.path.join(DATA_DIR, "parsed")        # parsed/<book_id>.jsonl
VLM_RAW_DIR = os.path.join(DATA_DIR, "vlm_raw")      # VLM 原始输出，可回溯可 diff
FIGURES_DIR = os.path.join(DATA_DIR, "figures")      # figures/<book_id>/<page_no>.md：只补插图，正文不动
OUTLINE_DIR = os.path.join(DATA_DIR, "outline")      # outline/<book_id>.jsonl：目录与结构骨架（知识库 L1）
ATTRS_DIR = os.path.join(DATA_DIR, "attrs")          # attrs/*.jsonl：外挂属性，一律靠 lesson_id/book_id 挂载
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
TEXT_LAYER_MIN_CHARS = int(os.environ.get("TEXT_LAYER_MIN_CHARS", "50"))  # 低于此值判定无文本层
PINYIN_FONT_PATTERN = "Hanyu"    # 拼音字体名特征
PINYIN_MAP_FILE = os.path.join(SRC_DIR, "parse", "pinyin_map.json")

# 通道 B：VLM。构建期（教材扫描页）与运行期（孩子拍的照片）共用同一套客户端。
VLM_BASE_URL = os.environ.get("VLM_BASE_URL", "https://token.sensenova.cn/v1")
VLM_MODEL = os.environ.get("VLM_MODEL", "sensenova-6.8-flash-lite")
VLM_API_KEY = os.environ.get("VLM_API_KEY", "")
# 200 dpi 实测会让该模型把 token 全耗在推理上、返回空内容（160 页因此失败），
# 且单页图片 ~1.6MB 会触发 413。降到 150 后图片 ~937KB，转录稳定成功。
VLM_DPI = int(os.environ.get("VLM_DPI", "150"))
VLM_WORKERS = int(os.environ.get("VLM_WORKERS", "8"))
VLM_TIMEOUT = int(os.environ.get("VLM_TIMEOUT", "180"))
# 推理型模型会用掉上千 token 做思考，max_tokens 给小了会导致正文被截断甚至为空
VLM_MAX_TOKENS = int(os.environ.get("VLM_MAX_TOKENS", "8192"))

# 失败重试。429 是平台侧限流，退避必须够长（秒级重试只会继续被拒）
VLM_MAX_RETRIES = int(os.environ.get("VLM_MAX_RETRIES", "2"))
VLM_RETRY_DELAYS = tuple(int(x) for x in os.environ.get("VLM_RETRY_DELAYS", "5,20,60").split(","))

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
VLM_PROMPT_FIGURE = (
    "请只描述这页小学教材里的插图，不要转录正文。严格要求：\n"
    "1. 对每个插图、图表、照片、示意图，按出现顺序输出一行：\n"
    "   [图N] 描述：图中画了什么、有哪些标注与数据、说明了什么规律或关系\n"
    "   （N 从 1 开始递增）\n"
    "2. 几何图要说清形状、已知条件与数量关系；实验装置要说清器材与步骤；\n"
    "   统计图要说清数据、单位与趋势；地图与示意图要说清方位与图例。\n"
    "3. 不要转录正文、题目、页码等文字，也不要解释你在做什么。\n"
    "4. 若整页没有任何插图，只输出一行：[无图]"
)
# 目录骨架：分栏版式（数学/科学常见）只有看图才读得出「标题 ↔ 页码」的配对
VLM_PROMPT_TOC = (
    "请读这页教材的目录页，按目录里**从上到下**的真实顺序，输出每一条的："
    "单元序号、单元名、标题、起始印刷页码。严格要求：\n"
    "1. 只输出一个 JSON 数组，每个元素一行，形如：\n"
    '   {"unit":1,"unit_name":"数与代数","title":"分数乘法","page":12}\n'
    "2. 标题与单元名照抄目录原文，不要改写、不要补字、不要把多个条目合并。\n"
    "3. 目录是分栏排的（单元号/标题/页码各成一列），请按**同一行**配对，"
    "不要把这一列的标题错配到另一列的页码上。\n"
    "4. page 取该条目在目录里标注的**印刷页码**（书中标注的页数），必须是数字。\n"
    "5. 目录里的「整理与复习」「综合与实践」「复习与关联」等栏目也算条目，照实输出。\n"
    "6. unit 填单元的数字序号（一→1、二→2）；unit_name 填目录里写的单元名，"
    "目录没写就填空字符串。\n"
    "7. 不要输出解释，不要输出 JSON 以外的内容。"
)
VLM_PROMPT_PHOTO = (
    "请把图片中的题目/作业内容完整转录为纯文本。\n"
    "1. 保留原题文字、数字与符号，不要做题、不要解释、不要改动原题表述。\n"
    "2. 若题目含有图形（几何图、线段图、统计图等），在题目后追加一行：\n"
    "   [图1] 描述：图形的形状、已知条件、数量关系与标注。\n"
    "3. 若图片中没有图形，则不要编造图描述。"
)
