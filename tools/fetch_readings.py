"""
fetch_readings.py
=================
从 Gutenberg 抓取英文长文，按 catalog.json 配置分章节拆分，落 data/readings/texts/。
使用 curl.exe（PowerShell 沙箱中 shell 直连 gutenberg.org，Python requests 不通）。

Usage:
    python tools/fetch_readings.py --all
    python tools/fetch_readings.py --id peter-rabbit,alice-wonderland
    python tools/fetch_readings.py --id alice-wonderland --retry 3

URL 优先级：
    1. https://www.gutenberg.org/files/{gid}/{gid}-0.txt          （原始文件，最可靠）
    2. https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt     （备用）
    3. https://www.gutenberg.org/files/{gid}/{gid}-8.txt          （编码备选）
"""
from __future__ import annotations
import argparse, json, re, subprocess, time, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
READINGS_DIR = ROOT / "data" / "readings"
CATALOG_PATH = READINGS_DIR / "catalog.json"
TEXTS_DIR = READINGS_DIR / "texts"
INDEX_PATH = READINGS_DIR / "index.json"
CACHE_DIR = READINGS_DIR / "_cache"

HEADERS = [
    "-H", "User-Agent: Mozilla/5.0 (agent-textbook/1.0)",
    "-H", "Accept-Language: en-US,en;q=0.9",
]
TIMEOUT = 45
DELAY_SEC = 0.8

HEADER_MARK = "*** START OF THE PROJECT GUTENBERG"
FOOTER_MARK = "*** END OF THE PROJECT GUTENBERG"

CHAPTER_PATTERNS = [
    # 1. "Chapter N. Title" / "Chapter N — Title" / "Chapter N: Title"
    #    num 允许罗马数字、阿拉伯数字、或 A/B/C（Introduction 风格）
    re.compile(
        r"^\s*Chapter\s+(?P<num>[0-9]+|[IVXLCDM]+|[A-Z])\s*[.:—–-]\s*"
        r"(?:(?:[-–—:]\s*)?(?P<title>.+))?\s*$",
        re.MULTILINE | re.IGNORECASE
    ),
    # 2. "Chapter N" 独占一行，标题在下一行（Wizard of Oz 风格）
    re.compile(
        r"^\s*Chapter\s+(?P<num>[0-9]+|[IVXLCDM]+|[A-Z])\s*$",
        re.MULTILINE | re.IGNORECASE
    ),
    # 3. "Part N" / "Book N"（次级分卷）
    re.compile(
        r"^\s*(?:Part|Book)\s+(?P<num>[0-9]+|[IVXLCDM]+)\s*[.:]?\s*"
        r"(?:[-–—:]\s*(?P<title>.+))?\s*$",
        re.MULTILINE | re.IGNORECASE
    ),
    # 4. "The <Title>" 独占一行（Gutenberg 短文本常见）
    re.compile(r"^\s*(?P<title>The [A-Z][^\n]{4,50})\s*$", re.MULTILINE),
    # 5. "Of ..."（古典散文）
    re.compile(r"^\s*(?P<title>Of [A-Z][^\n]{4,50})\s*$", re.MULTILINE),
    # 6. "A <Noun Phrase>"（寓言体）
    re.compile(r"^\s*(?P<title>A [A-Z][A-Za-z]+(?:\s+[A-Za-z-]+){1,6})\s*$", re.MULTILINE),
]

# 全书级正则覆盖：某些书的目录/章节标记过于特殊（Aesop / Huckleberry / Robin Hood 等）
# 配置在 catalog.json 的 book["heading_pattern"]，用 re.DOTALL + MULTILINE 编译
BOOK_HEADING_OVERRIDES = {}

MIN_CHUNK_WORDS = 60   # 过滤目录页噪声（Aesop TOC 标题 ~200 字符但正文极短）

ROMAN_MAP = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _curl_fetch(url: str, out: Path, max_retries: int = 3) -> bool:
    """curl 拉取，返回是否成功（文件非空）"""
    for i in range(max_retries):
        r = subprocess.run(
            ["curl.exe", "-sS", "--retry", "2", "--retry-delay", "1",
             "--max-time", str(TIMEOUT), *HEADERS, "-o", str(out), url],
            capture_output=True, text=True
        )
        if r.returncode == 0 and out.exists() and out.stat().st_size > 500:
            return True
        time.sleep(1.5 * (i + 1))
    return False


def fetch_fulltext(gid: int, max_retries: int = 3) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"gb_{gid}.txt"
    if cache.exists() and cache.stat().st_size > 500:
        return cache.read_text(encoding="utf-8", errors="replace")

    tmp = CACHE_DIR / f"gb_{gid}.tmp"
    urls = [
        f"https://www.gutenberg.org/files/{gid}/{gid}-0.txt",
        f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt",
        f"https://www.gutenberg.org/files/{gid}/{gid}-8.txt",
        f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.zip",  # 跳过
    ]
    for url in urls:
        if url.endswith(".zip"):
            continue
        print(f"  [curl] {url}")
        if _curl_fetch(url, tmp, max_retries):
            cache.write_bytes(tmp.read_bytes())
            return cache.read_text(encoding="utf-8", errors="replace")
    raise RuntimeError(f"gutenberg_id {gid} 所有 URL 均失败")


def strip_wrapper(text: str) -> str:
    s = text.find(HEADER_MARK)
    e = text.find(FOOTER_MARK)
    if s != -1 and e != -1 and e > s:
        text = text[s:e]
    # 去掉 Gutenberg 元数据行
    text = re.sub(r"^Produced by[^\n]*\n", "", text, count=1)
    text = re.sub(r"^Release date[^\n]*\n", "", text, count=1)
    text = re.sub(r"^License[^\n]*\n", "", text, count=1)
    text = re.sub(r"^This etext[^\n]*\n", "", text, count=1)
    text = re.sub(r"<!--[\s\S]*?-->", "", text)
    # 去掉 [Illustration] / [Footnote N] 等占位符
    text = re.sub(r"\[Illustration[^\]]*\]", " ", text)
    text = re.sub(r"\[Footnote[^\]]*\]", " ", text)
    text = re.sub(r"\[End Notes?\]", " ", text)

    # 去掉前部 Contents / Table of Contents 章节
    # 策略：定位 Contents 行，从其后开始扫描所有 "Chapter N. ..." / "PART N" / "Book N" 独占行
    # 前若干行（<=5）若为空行允许跳过
    toc_start = -1
    m = re.search(r"^\s*(?:TABLE OF CONTENTS|CONTENTS|Contents|Table of Contents)\s*$", text, re.MULTILINE)
    if m:
        toc_start = m.start()

    if toc_start >= 0:
        i = m.end()
        while i < len(text) and text[i] in "\r\n":
            i += 1

        line_pat = re.compile(r"^\s*(?:Chapter|CHAPTER|Part|PART|Book|BOOK)\s+[0-9IVXLC]+\b")

        # 允许开头最多 3 行是空行（TOC 常见前置空白）
        skip_count = 0
        while skip_count < 3 and i < len(text):
            nl = text.find("\n", i)
            if nl < 0:
                break
            line = text[i:nl]
            if line.strip() == "":
                i = nl + 1
                skip_count += 1
            else:
                break

        body_start = i
        last_toc_end = body_start
        run_count = 0
        while i < len(text):
            nl = text.find("\n", i)
            if nl < 0:
                break
            line = text[i:nl]
            if line_pat.match(line):
                run_count += 1
                last_toc_end = nl + 1
                # 检查紧跟着的续行（TOC 常见 "Chapter N.\nTitle."）
                probe = last_toc_end
                extra = 0
                while extra < 2 and probe < len(text):
                    nl2 = text.find("\n", probe)
                    if nl2 < 0:
                        break
                    nxt = text[probe:nl2].strip()
                    if nxt and len(nxt) < 80 and not line_pat.match(nxt) and nxt[-1] not in ".?!":
                        last_toc_end = nl2 + 1
                        probe = nl2 + 1
                        extra += 1
                    else:
                        break
            elif line.strip() == "":
                pass
            else:
                break
            i = nl + 1

        if run_count >= 3 and last_toc_end > body_start:
            text = text[:toc_start] + text[last_toc_end:]

    return text.strip()


def _is_roman(s: str) -> bool:
    return bool(s) and all(c in "IVXLCDM" for c in s)


def _roman_to_int(s: str) -> int:
    total, prev = 0, 0
    for ch in reversed(s):
        v = ROMAN_MAP[ch]
        if v < prev:
            total -= v
        else:
            total += v
        prev = v
    return total


def _num_from_title(title: str) -> int | None:
    m = re.search(r"(?:(?:Chapter|CHAPTER|Part|PART|Book|BOOK)\s+)?([0-9]+|[IVXLCDM]+)", title)
    if not m:
        return None
    v = m.group(1)
    if v.isdigit():
        return int(v)
    if _is_roman(v):
        return _roman_to_int(v)
    return None


def split_chapters(text: str, book: dict) -> list[dict]:
    excerpt = book.get("excerpt") or {"type": "full"}
    etype = excerpt.get("type", "full")

    if etype == "full":
        return [{"index": 0, "title": book["title"], "text": text}]

    # 使用 book["heading_pattern"] 覆盖默认 CHAPTER_PATTERNS（针对 Aesop/Huck/Robin Hood 等特例）
    patterns = CHAPTER_PATTERNS
    custom = book.get("heading_pattern")
    if custom:
        patterns = [re.compile(custom, re.MULTILINE | re.IGNORECASE)]

    matches = []
    for pat in patterns:
        for m in pat.finditer(text):
            matches.append((m.start(), m.end(), m.groupdict()))

    # 去重：同一 start 保留最短 match（避免 PAT0/PAT1 同时命中 "Chapter I"）
    dedup = {}
    for start, end, groups in matches:
        if start not in dedup or (end - start) < (dedup[start][1] - dedup[start][0]):
            dedup[start] = (start, end, groups)
    matches = sorted(dedup.values())

    if not matches:
        return [{"index": 0, "title": book["title"], "text": text}]

    chunks = []
    for i, (start, end, groups) in enumerate(matches):
        next_start = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        body = text[end:next_start].strip()
        # 标题可能单独一行且标题在下一行（Wizard of Oz "Chapter I\nThe Cyclone"）
        # 尝试从 body 开头取 1 行作为 title 补充
        title = (groups.get("title") or "").strip()
        num = (groups.get("num") or "").strip()

        if not title:
            # 抓 body 第一非空行作为 title 补充（仅当该行 < 60 字符且是纯标题型）
            first_line = ""
            for line in body.split("\n"):
                if line.strip():
                    first_line = line.strip()
                    break
            if first_line and len(first_line) < 60 and "  " not in first_line and first_line[-1] not in ".?!":
                title = first_line
                # 从 body 里去掉这行
                nl = body.find(first_line)
                if nl >= 0:
                    body = (body[:nl] + body[nl + len(first_line):]).strip()

        if title and num:
            full_title = f"Chapter {num}: {title}"
        elif title:
            full_title = title
        elif num:
            full_title = f"Chapter {num}"
        else:
            full_title = f"Chapter {i}"

        wc = len(re.findall(r"[A-Za-z']+", body))
        if wc < MIN_CHUNK_WORDS:
            continue  # 目录页/噪声块，跳过

        chunks.append({"index": len(chunks), "title": full_title, "text": body, "_num": _num_from_title(full_title)})

    if etype == "chapter":
        wanted = set(excerpt.get("chapters", []))
        selected = [c for c in chunks if c.get("_num") in wanted]
        if not selected:
            selected = chunks[:max(1, len(wanted))]
        return selected

    if etype == "story":
        wanted = [w.lower() for w in excerpt.get("stories", [])]
        # 匹配策略 1：story 标题出现在某个 chunk 的 title 里
        selected = [c for c in chunks if any(w in c["title"].lower() for w in wanted)]
        if selected:
            return selected
        # 匹配策略 2：story 标题出现在 chunk 正文开头（前 200 字符）
        for c in chunks:
            head = c["text"][:200].lower()
            if any(w in head for w in wanted):
                return [c]
        # 匹配策略 3：从全书文本按标题定位到下一个标题
        return _extract_story_from_full(text, wanted, chunks)

    return chunks


def _extract_story_from_full(text: str, wanted_titles: list[str], chunks: list[dict]) -> list[dict]:
    """从全书文本按 story 标题正则定位，截取到下一个章节标题为止。"""
    results = []
    # 找所有 chunk 标题在文本中的位置（起点）
    heads = [(c["_num"], c["title"]) for c in chunks]
    for w in wanted_titles:
        # 精确标题匹配：story 标题独占一行
        pat = re.compile(
            r"^\s*" + re.escape(w) + r"\s*(?:\([^\)]*\))?\s*$",
            re.MULTILINE | re.IGNORECASE
        )
        m = pat.search(text)
        if not m:
            continue
        start = m.end()
        # 结束：下一个 chunk 标题行 或 全书末尾
        end_pat = re.compile(r"^\s*(?:Chapter|THE|Of |A |[A-Z][A-Za-z-]+(?:\s+[A-Za-z-]+){1,4})\s*$", re.MULTILINE)
        n = re.search(end_pat, text[start:])
        end = start + n.start() if n else len(text)
        body = text[start:end].strip()
        if len(re.findall(r"[A-Za-z']+", body)) >= MIN_CHUNK_WORDS:
            results.append({"index": 0, "title": w, "text": body, "_num": None})
    return results if results else chunks[:1]


def process_book(book: dict, max_retries: int) -> dict:
    gid = book["gutenberg_id"]
    bid = book["id"]
    print(f"[fetch] {bid} (GB#{gid}) {book['title']}")

    full = fetch_fulltext(gid, max_retries=max_retries)
    full = strip_wrapper(full)
    time.sleep(DELAY_SEC)

    chapters = split_chapters(full, book)
    for c in chapters:
        c.pop("_num", None)

    out = TEXTS_DIR / f"{bid}.txt"
    TEXTS_DIR.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# {book['title']} — {book['author']}\n")
        f.write(f"# gutenberg_id: {gid}\n\n")
        for ch in chapters:
            f.write(f"=== {ch['title']} ===\n\n{ch['text']}\n\n")

    words = re.findall(r"[A-Za-z']+", "".join(c["text"] for c in chapters))
    wc = len(words)
    uniq = len(set(w.lower() for w in words))
    return {
        "id": bid, "title": book["title"], "author": book["author"],
        "gutenberg_id": gid,
        "chapters_count": len(chapters),
        "word_count": wc,
        "unique_words": uniq,
        "reading_time_min": max(1, wc // 150),
        "text_path": f"data/readings/texts/{bid}.txt",
        "audio_archive": book.get("librivox_archive"),
        "audio_url": book.get("librivox_url"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--id", type=str, help="逗号分隔 book_id")
    ap.add_argument("--retry", type=int, default=3)
    ap.add_argument("--skip-failed", action="store_true", help="跳过 gutenberg_id 缺失的条目")
    args = ap.parse_args()

    books = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["books"]
    if args.id:
        wanted = set(args.id.split(","))
        targets = [b for b in books if b["id"] in wanted]
    else:
        targets = books
    if args.skip_failed:
        targets = [b for b in targets if b.get("gutenberg_id")]
    else:
        # 保留顺序：先有 gutenberg_id 的，再没有的（无 id 后续会 skip）
        targets = ([b for b in targets if b.get("gutenberg_id")] +
                   [b for b in targets if not b.get("gutenberg_id")])

    print(f"[fetch] 目标 {len(targets)} 篇，skip_failed={args.skip_failed}")

    index = []
    if INDEX_PATH.exists():
        try:
            index = json.loads(INDEX_PATH.read_text(encoding="utf-8")).get("readings", [])
        except Exception:
            index = []
    by_id = {r["id"]: r for r in index}

    ok, fail = 0, 0
    for b in targets:
        if not b.get("gutenberg_id"):
            print(f"[skip] {b['id']}: no gutenberg_id")
            fail += 1
            continue
        try:
            meta = process_book(b, max_retries=args.retry)
            by_id[meta["id"]] = meta
            ok += 1
        except Exception as e:
            print(f"[error] {b['id']}: {e}")
            fail += 1

    INDEX_PATH.write_text(json.dumps(
        {"_doc": "Gutenberg 长文抓取索引", "_updated": time.strftime("%Y-%m-%d"),
         "readings": list(by_id.values())},
        ensure_ascii=False, indent=2
    ), encoding="utf-8")
    print(f"[fetch] 完成: ok={ok} fail={fail} → {INDEX_PATH}")


if __name__ == "__main__":
    main()
