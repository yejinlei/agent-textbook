# -*- coding: utf-8 -*-
"""African Storybook 抓取器。

用法：
    python tools/fetch_asb.py --id 21974
    python tools/fetch_asb.py --id 21974 --pages          # 下载原图
    python tools/fetch_asb.py --ids 21974,32811 --pages
    python tools/fetch_asb.py --id 21974 --dry             # 只打印不写文件

设计约定：
    * 抓取 newviewer/index.php?id=<id> 翻书页，逐 <div class="page"> 解析
    * 只处理 CC-BY / CC-BY-SA / PD 授权的书，其它授权直接跳过
    * 图片落到 data/picturebooks/images/<slug>/p{n}.png
    * 元数据+页面结构追加进 data/picturebooks/books.json（幂等，按 id 去重）
    * 原朗读音频不下载（授权风险 + 我们走 Piper TTS 合成）
    * 请求间隔 1.5s，尊重对方服务器
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib import request, error

ROOT = Path(__file__).resolve().parents[1]
PB = ROOT / "data" / "picturebooks"
IMAGES = PB / "images"
BOOKS_JSON = PB / "books.json"

log = logging.getLogger("fetch_asb")
UA = "agent-textbook/0.1 (+contact: maintainer)"
OK_LICENSES = {"CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-NC-4.0",
               "CC-BY-NC-SA-4.0", "CC0-1.0", "PD"}

# 一个 <div class="page">...</div>，跨标签
_RE_PAGE = re.compile(
    r'<div\s+class="page[^"]*"[^>]*>(.*?)</div>\s*</div>\s*<div\s+class="gradient">',
    re.S,
)
# 每个 page 里的 <image src="...">
_RE_IMG = re.compile(r'<image\s+src="([^"]+)"', re.I)
# 正文段：一个或多个 <p class="single-text ">...</p>
_RE_TEXT = re.compile(r'<p\s+class="single-text[^"]*"[^>]*>(.*?)</p>', re.S | re.I)
# 页码 <div class="page-number">N</div>
_RE_PN = re.compile(r'<div\s+class="page-number">\s*(\d+)\s*</div>', re.I)
# 封面 title / author / artist
_RE_COVER_TITLE = re.compile(r'<div\s+class="cover-title[^"]*"[^>]*>(.*?)</div>', re.S | re.I)
_RE_COVER_AUTHOR = re.compile(r'<div\s+class="cover-author"[^>]*>(.*?)</div>', re.S | re.I)
_RE_COVER_ARTIST = re.compile(r'<div\s+class="cover-artist"[^>]*>(.*?)</div>', re.S | re.I)
# 只抓真正封面图：URL 必须指向 /illustrations/ 或 .png/.jpg（排除 data:svg 装饰）
_RE_COVER_IMG = re.compile(
    r'id="cover-image"[^>]*background-image:\s*url\(([^)]+?)\)',
    re.I,
)
# 封底 metadata：Author -  xxx
_RE_BACK_META = re.compile(
    r'<span\s+class="backcover_bold">([^<]+?)</span>\s*([^<]+?)(?:<br>|</div>)',
    re.S | re.I,
)
_RE_COPYRIGHT = re.compile(r'<div\s+class="backcover_copyright"[^>]*>(.*?)</div>', re.S | re.I)
_RE_CC = re.compile(r'Creative Commons:\s*([^\n<]+)', re.I)


def http_get(url: str, timeout: int = 30, retries: int = 3) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = request.Request(url, headers={"User-Agent": UA})
            with request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except error.HTTPError as e:
            last = e
            log.warning("HTTP %s on %s (retry %d)", e.code, url, i + 1)
        except (error.URLError, TimeoutError) as e:
            last = e
            log.warning("URL error on %s: %s (retry %d)", url, e, i + 1)
        time.sleep(1 + i * 2)
    raise RuntimeError(f"failed after {retries} retries: {url} ({last})")


def slugify(title: str) -> str:
    # 先折叠 Unicode（ũ→u, ö→o 等），再转 slug；避免非 ASCII 变 `-`
    import unicodedata
    s = unicodedata.normalize("NFKD", title.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "book"


def clean_tag(text: str) -> str:
    t = re.sub(r"<[^>]+>", "", text)
    t = htmllib.unescape(t)
    t = t.replace("&nbsp;", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def is_english(meta: dict) -> bool:
    """判断是否英语版本。ASB 很多书有几十种语言版本，只保留英语。"""
    lang = (meta.get("language") or "").strip()
    if not lang:
        return False
    return lang.lower() == "english"


def detect_license(html_text: str) -> str:
    m = _RE_CC.search(html_text)
    if m:
        cc_line = m.group(1).lower()
    else:
        cc_line = html_text.lower()
    if "nc-sa" in cc_line:
        return "CC-BY-NC-SA-4.0"
    if "nc" in cc_line:
        return "CC-BY-NC-4.0"
    if "by-sa" in cc_line or "by-sa" in cc_line:
        return "CC-BY-SA-4.0"
    if "attribution" in cc_line or "by" in cc_line:
        return "CC-BY-4.0"
    return "CC-BY-4.0"


def parse_newviewer(html_text: str) -> dict:
    """解析 newviewer/index.php HTML。"""
    # 封面
    m = _RE_COVER_TITLE.search(html_text)
    title = clean_tag(m.group(1)) if m else "Unknown"
    m = _RE_COVER_AUTHOR.search(html_text)
    cover_author = clean_tag(m.group(1)) if m else None
    m = _RE_COVER_ARTIST.search(html_text)
    cover_artist = clean_tag(m.group(1)) if m else None

    # 封底 metadata
    meta: dict = {}
    for m in _RE_BACK_META.finditer(html_text):
        key = clean_tag(m.group(1)).rstrip(" -").strip().lower()
        val = clean_tag(m.group(2))
        if key:
            meta[key] = val

    # 授权
    lic = detect_license(html_text)

    # 封面主图：只接受真正的图片 URL（排除 data: svg 装饰）
    cover_img = None
    m = _RE_COVER_IMG.search(html_text)
    if m:
        url = m.group(1).strip().strip("'\"")
        if not url.startswith("data:") and (".png" in url or ".jpg" in url or ".jpeg" in url):
            cover_img = url

    # 遍历所有 page
    pages: list[dict] = []
    for pm in _RE_PAGE.finditer(html_text):
        block = pm.group(1)
        # 跳过封底（含 backcover_disclaimer）
        if "backcover_disclaimer" in block or "backcover_title" in block:
            continue
        # 跳过封面（cover-wrapper）
        if "cover-wrapper" in block or "cover-title" in block:
            continue
        pn_m = _RE_PN.search(block)
        pn = int(pn_m.group(1)) if pn_m else None
        img_m = _RE_IMG.search(block)
        img_url = img_m.group(1) if img_m else None
        text_parts = [clean_tag(x) for x in _RE_TEXT.findall(block)]
        text = " ".join([t for t in text_parts if t])
        pages.append({"n": pn if pn is not None else len(pages) + 1,
                      "text": text, "image_url": img_url})

    return {
        "title": title,
        "cover_author": cover_author,
        "cover_artist": cover_artist,
        "meta": meta,
        "license": lic,
        "cover_img": cover_img,
        "pages": pages,
    }


def download_file(url: str, out_path: Path) -> bool:
    if out_path.exists():
        return True
    try:
        data = http_get(url, timeout=20)
        out_path.write_bytes(data)
        log.info("  saved %s (%.1f KB)", out_path.name, len(data) / 1024)
        return True
    except Exception as e:
        log.error("  download failed %s: %s", url, e)
        return False


def load_books() -> dict:
    if BOOKS_JSON.exists():
        return json.loads(BOOKS_JSON.read_text(encoding="utf-8"))
    return {"_doc": "", "_updated": "", "books": []}


def _smart_merge(old: dict, new: dict) -> dict:
    """抓取来的 None/[] 值不覆盖旧字段，保留手录入的人工标注。"""
    out = {**old}
    for k, v in new.items():
        if v is None and old.get(k) not in (None, ""):
            continue  # 抓取没值 → 保留人工标注
        if v == [] and old.get(k) not in ([], None, ""):
            continue  # 抓取空列表 → 保留人工标注
        out[k] = v
    return out


def upsert_book(store: dict, book: dict) -> str:
    """按 asb_id 优先、其次 id 匹配去重。命中就 smart merge，否则追加。"""
    for i, b in enumerate(store["books"]):
        if book.get("asb_id") and b.get("asb_id") == book["asb_id"]:
            store["books"][i] = _smart_merge(b, book)
            return "updated"
    for i, b in enumerate(store["books"]):
        if b.get("id") == book["id"]:
            store["books"][i] = _smart_merge(b, book)
            return "updated"
    store["books"].append(book)
    return "added"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int)
    ap.add_argument("--ids", type=str, help="逗号分隔")
    ap.add_argument("--pages", action="store_true", help="下载插图")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--sleep", type=float, default=1.5)
    ap.add_argument("--out", type=str, default=None, help="写入的 books.json 路径")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    ids: list[int] = []
    if args.id:
        ids.append(args.id)
    if args.ids:
        ids.extend(int(x) for x in args.ids.split(",") if x.strip())
    ids = list(dict.fromkeys(ids))
    if not ids:
        ap.print_help()
        return 1

    store_path = Path(args.out) if args.out else BOOKS_JSON
    store = load_books() if store_path.exists() else {"_doc": "", "books": []}

    summary = {"fetched": 0, "skipped": 0, "failed": 0}
    for bid in ids:
        url = f"https://www.africanstorybook.org/newviewer/index.php?id={bid}&bt=3&dual=false"
        try:
            html_text = http_get(url).decode("utf-8", errors="replace")
        except Exception as e:
            log.error("fetch failed id=%d: %s", bid, e)
            summary["failed"] += 1
            continue

        if args.dry:
            (PB / "raw").mkdir(parents=True, exist_ok=True)
            (PB / "raw" / f"_{bid}.html").write_text(html_text, encoding="utf-8")

        try:
            parsed = parse_newviewer(html_text)
        except Exception as e:
            log.error("parse failed id=%d: %s", bid, e)
            summary["failed"] += 1
            continue

        lic = parsed["license"]
        if lic not in OK_LICENSES:
            log.warning("skip id=%d license=%s", bid, lic)
            summary["skipped"] += 1
            continue

        # 空 title 或空 pages → 无效 id（可能是 ASB 已下架的书），直接跳过
        if not parsed["title"] or not parsed["pages"]:
            log.warning("skip id=%d empty book (title=%r pages=%d)",
                        bid, parsed["title"], len(parsed["pages"]))
            summary["skipped"] += 1
            continue

        # 非英语版本：ASB 一本书有几十种语言，我们只要英语
        if not is_english(parsed["meta"]):
            lang = parsed["meta"].get("language") or "(unknown)"
            log.warning("skip id=%d non-English (lang=%s)", bid, lang)
            summary["skipped"] += 1
            continue

        slug = slugify(parsed["title"])
        log.info("id=%d slug=%s title=%r pages=%d lic=%s",
                 bid, slug, parsed["title"], len(parsed["pages"]), lic)

        if args.pages:
            book_img_dir = IMAGES / slug
            book_img_dir.mkdir(parents=True, exist_ok=True)
            cover_rel = None
            if parsed["cover_img"]:
                cover_rel = str((book_img_dir / "cover.png").relative_to(PB))
                if not args.dry:
                    download_file(parsed["cover_img"], book_img_dir / "cover.png")
            for p in parsed["pages"]:
                if p["image_url"]:
                    p["image"] = f"images/{slug}/p{p['n']}.png"
                    if not args.dry:
                        download_file(p["image_url"], book_img_dir / f"p{p['n']}.png")
                    p.pop("image_url", None)
                else:
                    p["image"] = None
            parsed["cover_image"] = cover_rel
        else:
            for p in parsed["pages"]:
                p.pop("image_url", None)
                p["image"] = None

        meta = parsed["meta"]
        year = None
        if "©" in html_text:
            m = re.search(r"©\s*[^0-9\n]{0,60}?(\d{4})", html_text)
            if m:
                year = int(m.group(1))

        book = {
            "id": slug,
            "title": parsed["title"],
            "author": meta.get("author") or parsed["cover_author"],
            "translator": meta.get("translation"),
            "illustrator": meta.get("illustration") or parsed["cover_artist"],
            "year": year,
            "level": None,
            "primary_topic": None,
            "secondary_topics": [],
            "source": "african-storybook",
            "source_url": f"https://www.africanstorybook.org/read.php?id={bid}",
            "asb_id": bid,
            "asb_level": meta.get("level"),  # ASB 自带的分级（First words / First paragraphs ...）
            "license": {"text": lic, "image": lic, "audio_raw": None},
            "attribution": (
                f"Source: https://www.africanstorybook.org/read.php?id={bid}. "
                f"License: {lic}."
            ),
            "tags": [],
            "pages": parsed["pages"],
        }

        if args.dry:
            log.info("[dry] would %s book=%s with %d pages",
                     "upsert", book["id"], len(book["pages"]))
        else:
            action = upsert_book(store, book)
            log.info("  %s %s (%d pages)", action, book["id"], len(book["pages"]))
            store["_updated"] = time.strftime("%Y-%m-%d")
            store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        summary["fetched"] += 1
        time.sleep(args.sleep)

    log.info("summary: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
