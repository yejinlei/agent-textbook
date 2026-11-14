"""把 data/readings/texts/*.txt 转成 pages/extensions/texts/{id}.js（内联 HTML 正文）。

关键清洗步骤：
1. 去掉 Gutenberg 头尾、[Illustration]、*** START/END ***、元数据行
2. 按 80 列合并折行 → 恢复段落（启发式：句末标点/引号/破折号后跟大写 = 新段落）
3. 识别 CHAPTER/Part/Book 标题为章节分隔
4. 短行（<=55 字，无句末标点）当章节小标题
5. 输出 JS：window.TEXTS[id] = { html: "..." }
"""
from __future__ import annotations
import html as _html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDX = json.loads((ROOT / "data" / "readings" / "index.json").read_text(encoding="utf-8"))
OUT_DIR = ROOT / "pages" / "extensions" / "texts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 章节标题
CHAPTER_PAT = re.compile(
    r"^\s*((?:CHAPTER|Chapter|CHAPTER\.|PART|Part|BOOK|Book)\s+"
    r"(?:[IVXLC]+|\d+(?:\.\d+)?)\s*:?\s*[^\n]{0,80})\s*$"
)
# 首字母大写标题（如 "CHAPTER I: The Story"）
TITLE_PAT = re.compile(
    r"^\s*((?:CHAPTER|Chapter|CHAPTER\.|PART|Part|BOOK|Book)[\s:.\-][^\n]{0,80})\s*$"
)
# 元数据（Title/Author/Publisher/Editor/Illustrator/Release Date/Character set/First published 等）
META_LINE = re.compile(
    r"^\s*(Title|Author|Editor|Illustrator|Publisher|First published|Release Date|"
    r"Character set encoding|Language|Produced by|Transcribed|Copyright|Translated|"
    r"[0-9]{1,4}\.)\s*[:—\n]"
)
# 全大写短行（居中/装饰用）
UPPER_ORNAMENT = re.compile(r"^[A-Z][A-Z0-9 ,.\-&'()]{1,60}$")


def _strip_gutenberg_noise(t: str) -> str:
    # 1) 如果有 *** START OF THIS PROJECT GUTENBERG EBOOK ***，砍掉它之前的整段
    m = re.search(r"\*\*\*\s*START OF THIS PROJECT GUTENBERG EBOOK[^\n]*", t)
    if m:
        t = t[m.end():]
    # 2) 去掉结尾 END OF ... + 版权/许可信息
    m = re.search(r"\*\*\*\s*END OF THIS PROJECT GUTENBERG EBOOK[^\n]*", t)
    if m:
        t = t[:m.start()]
    else:
        t = _cut_end_matter(t)
    # 3) 去 header 注释（# 开头的元数据）
    t = re.sub(r"(?m)^#[^\n]*\n", "", t)
    # 4) 去单独成行的 *** ***
    t = re.sub(r"(?m)^[ \t]*\*{3,}[^*]{0,100}\*{3,}[ \t]*$", "", t)
    # 5) 去 [Illustration]
    t = re.sub(r"\[Illustration[^\]]*\]", "", t)
    # 6) 去标题页装饰行（= / — / ~ / · / * 单独成行）
    t = re.sub(r"(?m)^[ \t]*(=+|—+|~+|·+|\*+)[ \t]*$", "", t)
    # 7) 去 BOM
    t = t.replace("\ufeff", "")
    return t


def _cut_end_matter(t: str) -> str:
    """去掉结尾的版权信息、Transcriber 注等。"""
    m = re.search(r"END OF [^\n]*(?:PROJECT GUTENBERG|GUTENBERG)[^\n]*", t, re.IGNORECASE)
    if m:
        t = t[:m.start()]
    return t.rstrip()


def _ends_sentence(text: str) -> bool:
    """判断累积的 buffer 末尾是不是"句末 + 引号收尾"（用于是否开新段落）。"""
    return bool(re.search(r"[\.\!\?][\"'\")\]\}]*$", text))


def _continues(text: str) -> bool:
    """判断 buffer 末尾是不是应该续行的标点（逗号、冒号、分号、破折号等）。"""
    return bool(re.search(r"[,\:\;\-—–]\s*$", text))


# 标题页/元数据常见短行（独立成行）—— 保守匹配
TITLE_NOISE_LINE = re.compile(
    r"^\s*"
    r"(?:"
    r"===+\s*[^=].*===?|"
    r"Hans\s+Andersen'?\s+Fairy\s+Tales?|"
    r"_?Edited\s+by_?\s+[^\n]+|"
    r"Illustrated\s+by\s+[^\n]+|"
    r"Ginn\s+and\s+Company[^\n]*|"
    r"GINN\s+AND\s+COMPANY[^\n]*|"
    r"\d{3,4}\.\d{2}|"
    r"The\s+Athen[a-z]\u00e6um\s+Press|"
    r"THE\s+[A-Z][A-Z\s]{0,30}|"
    r"BY\s+[A-Z][A-Z\s]+|"
    r"(?:WITH|AND|FROM|AS)\s+(?:AN?\s+)?(?:INTRODUCTION|ILLUSTRATIONS?|NOTE|FOREWORD|PREFACE|ESSAY)[^\n]*|"
    r"(?:FIRST|SECOND|THIRD)\s+PUBLISHED\s+\d{4}|"
    r"[A-Z][A-Za-z\s]*&?\s+CO\.?,?\s*\d{4}|"
    r"(?:First|Second)\s+Series|"
    r"Transcriber'?\s+Notes?|"
    r"Produced\s+by\s+.{1,120}|"
    r"Proofreading\s+Team\s+at\s+[^.\n]+\.|"
    r"Online\s+Distributed\s+Proofreading[^\n]*|"
    r"Internet\s+Archive[^\n]*|"
    r"This\s+eBook\s+is\s+for\s+the\s+use[^\n]*|"
    r"almost\s+no\s+restrictions\s+whatsoever\.|"
    r"re-use\s+it\s+under\s+the\s+terms[^\n]*|"
    r"with\s+this\s+eBook\s+or\s+online\s+at\s+www\.gutenberg\.org|"
    r"(?:INTRODUCTION|PREFACE|FOREWORD|TRANSLATOR'?\s+NOTE|"
    r"AUTHOR'?\s+NOTE|EXPLANATORY\s+NOTE|TABLE\s+OF\s+CONTENTS|"
    r"ACKNOWLEDGEMENTS?|BIBLIOGRAPHY|INDEX|GLOSSARY|"
    r"TRANSLATION|NEW\s+TRANSLATION|ILLUSTRATIONS?|"
    r"\d{4}\s+EDITION)"
    r")\s*$",
    re.IGNORECASE,
)


def _cut_title_page(t: str) -> str:
    """去掉开头整块的标题页 —— 找到第一个"看起来像正文"的行，之前的整块丢弃。

    规则：从文件头开始扫描，跳过噪声/装饰行（标题页尾巴、Gutenberg 分隔线），
    第一条"长度足够长且不是噪声"的行即为正文起点。
    """
    # 装饰分隔行（===/---/***/~~~ 单独一行，或包裹整行）
    decorator_pat = re.compile(
        r"^(?:[=*_\-~·]{2,}\s*[^=*\-~·].*?[=*_\-~·]{2,}\s*"
        r"|[=*_\-~·]{3,}\s*)"
    )
    lines = t.split("\n")
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        if decorator_pat.match(s):
            continue
        if _is_meta_or_ornament(s):
            continue
        # 第一条"够长且非噪声"的行 → 正文起点
        if len(s) >= 40:
            return "\n".join(lines[i:])
    return t


def _is_meta_or_ornament(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if META_LINE.match(s):
        return True
    # 纯装饰性 —— 全大写且很短
    if len(s) <= 40 and UPPER_ORNAMENT.match(s):
        # 但要排除 "END OF..." 已在上一级切掉，且排除正常全大写章节
        if not re.match(r"^(CHAPTER|PART|BOOK)\b", s, re.IGNORECASE):
            if s.isupper():
                return True
    # 单行居中装饰（仅含点/星号/破折号/装饰字符）
    if re.match(r"^[\*\s~=\-]{3,}$", s):
        return True
    if TITLE_NOISE_LINE.match(s):
        return True
    return False


def _join_wrapped_lines(lines: list[str]) -> list[str]:
    """把 Gutenberg 折行合并回段落。"""
    paragraphs: list[str] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            joined = re.sub(r"\s+", " ", buf).strip()
            if joined:
                paragraphs.append(joined)
            buf = ""

    for ln in lines:
        s = ln.strip()
        if not s:
            flush()
            continue
        if _is_meta_or_ornament(s):
            flush()
            continue
        if not buf:
            buf = s
            continue
        # 上一句是否以句末收尾？若是，且当前行以大写字母/引号开头 → 新段落
        if _ends_sentence(buf) and re.match(r"^[\w\"'(]", s):
            flush()
            buf = s
        else:
            # 如果 buffer 以冒号/逗号/破折号结尾，或当前行以小写开头 → 续行
            buf = buf + " " + s
    flush()
    return paragraphs


def _split_chapters(paragraphs: list[str]) -> list[tuple[str, list[str]]]:
    """把段落列表切成 [(章节标题, [段落...]), ...]"""
    chunks: list[tuple[str, list[str]]] = []
    cur_heading = ""
    cur: list[str] = []

    for p in paragraphs:
        m = CHAPTER_PAT.match(p) or TITLE_PAT.match(p)
        if m:
            if cur:
                chunks.append((cur_heading, cur))
                cur = []
                cur_heading = m.group(1).strip()
        else:
            cur.append(p)
    if cur:
        chunks.append((cur_heading, cur))
    return chunks


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _looks_like_subtitle(p: str) -> bool:
    """判定副标题 —— 保守：只做全大写或数字编号，避免误判普通段落。"""
    if len(p) > 60:
        return False
    # 全大写副标题（PREFACE / END OF CHAPTER / THE END 等）
    if re.match(r"^[A-Z][A-Z0-9 \-.,'():&]+$", p) and len(p) <= 50:
        if re.match(r"^(THE END|FIN|—+ END —+)$", p, re.IGNORECASE):
            return True  # 作为 h3 保留
        return p.isupper() and len(p.split()) >= 1
    # 数字编号小标题 "1. The Boy Who"
    if re.match(r"^\d+\.\s+[A-Z][A-Za-z0-9 ,'\-:()&]{1,50}$", p):
        return True
    return False


def render_html(text: str) -> str:
    t = _strip_gutenberg_noise(text)
    t = _cut_end_matter(t)
    t = _cut_title_page(t)
    lines = t.split("\n")
    paragraphs = _join_wrapped_lines(lines)
    chunks = _split_chapters(paragraphs)

    out: list[str] = []
    for heading, body in chunks:
        if heading:
            # 把 "CHAPTER I: The Story" 拆标题
            h = re.sub(r"\s+", " ", heading).strip()
            out.append(f'<div class="chap">{_escape(h)}</div>')
        for p in body:
            if _looks_like_subtitle(p):
                out.append(f'<h3>{_escape(p)}</h3>')
            else:
                out.append(f'<p>{_escape(p)}</p>')
    return "\n".join(out)


def js_string(s: str) -> str:
    """把 HTML 打包成 JS 双引号字符串，防 </script> 逃逸"""
    # 顺序关键：先 escape \ 和 "，最后再加 </ -> <\/ 反斜杠
    safe = s.replace("\\", "\\\\").replace('"', '\\"')
    safe = safe.replace("</", "<\\/")
    safe = safe.replace("\n", "\\n").replace("\r", "")
    return '"' + safe + '"'


def build_one(book_id: str, text_path: Path) -> tuple[str, int, str]:
    raw = text_path.read_text(encoding="utf-8", errors="replace")
    html_body = render_html(raw)
    js = (
        "window.TEXTS = window.TEXTS || {};\n"
        f'window.TEXTS["{book_id}"] = {{ html: {js_string(html_body)} }};\n'
    )
    out_path = OUT_DIR / f"{book_id}.js"
    out_path.write_text(js, encoding="utf-8")
    return out_path.name, len(js), html_body


def main():
    total_bytes = 0
    total_paras = 0
    for r in IDX["readings"]:
        src_path = ROOT / r["text_path"]
        if not src_path.exists():
            print(f"  [skip] {r['id']}: not found")
            continue
        name, n, html_body = build_one(r["id"], src_path)
        paras = html_body.count("<p>")
        chapters = html_body.count('class="chap"')
        total_bytes += n
        total_paras += paras
        print(f"  [{n/1024:6.1f} KB] {name:32s}  paras={paras:4d}  chapters={chapters}")
    print(f"\n[build_extensions_texts] → {OUT_DIR}")
    print(f"  files={len(IDX['readings'])}  total={total_bytes/1024:.0f} KB  paras={total_paras}")


if __name__ == "__main__":
    main()
