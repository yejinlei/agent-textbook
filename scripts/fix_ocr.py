# -*- coding: utf-8 -*-
"""语文 OCR 错位自动修复脚本（第一波，不依赖 VLM）。

处理三类可自动修的问题：
  1. author_glue    "本文作者X（YYYY—YYYY），选作课文时有改动" 从 text 头剥离
  2. note_glue      正文末尾的 "（YYYY—YYYY），译者X，选作课文时有改动" 剥离
  3. empty_exercise exercises 数组里的空字符串删掉

原则：
  - 不动 text_plain / lines（保留原始脏数据做审计对照）
  - 只改 text 和 paragraphs（paragraphs 按 \n 切分 text 同步）
  - 备份原文件到 lesson_text.jsonl.bak 和 audit/backup 目录

用法：
    python scripts/fix_ocr.py --dry-run    # 只打印修改，不写文件
    python scripts/fix_ocr.py              # 落地修改
    python scripts/fix_ocr.py --report     # 打印修复报告
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_PATH = ROOT / "data" / "attrs" / "lesson_text.jsonl"
AUDIT_DIR = ROOT / "data" / "audit"
BACKUP_PATH = TEXT_PATH.with_suffix(".jsonl.bak")
REPORT_PATH = AUDIT_DIR / "fix_report.md"


# ---------- 正则 ----------

# "本文作者" 段：从"本文作者"开始，一直到"选作课文时有改动"或换行结束
# 可能包含：拼音括号、生卒年括号、译者信息
RE_AUTHOR_BLOCK = re.compile(
    r"本文作者[^，。；\n]{0,60}[，,]?"
    r"(?:译者[^，。；\n]{1,20}[，,])?"
    r"(?:选作课文时有改动[。.]*\s*)?"
)
# 前面的圆圈数字标记 ①②③ 或独立数字
RE_CIRCLE_NUM = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩]")
# 前面残留的页眉/课题文字（"朱德的扁担①"、"草原阅读①"、"繁 星"）
# 特征：在换行之前紧挨着"本文作者"的 3-8 字标题片段
RE_PAGEMARK_PREFIX = re.compile(
    r"[\u4e00-\u9fa5]{1,10}[①②③④⑤]?\s*"
)
# 单独的 "（YYYY—YYYY）" 生卒年（在注释尾巴上）
RE_LIFESPAN = re.compile(r"（\d{4}\s*[—\-–~至]\s*\d{4}）")


# 完整的作者说明块（从"本文作者"开始到"选作课文时有改动"结束）
RE_AUTHOR_FULL = re.compile(
    r"本文作者[^。\n]*?选作课文时有改动[。]?"
)
# 前面紧跟的 "①" 圆圈数字 + 可能的空格
RE_LEAD_MARKER = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩]\s*")
# 前面紧跟的页眉标题残留（"朱德的扁担"、"草原阅读"、"繁星"）
# 特征：3-8 个汉字 + 可能在最前一个汉字前有空格
RE_LEAD_TITLE = re.compile(r"[\u4e00-\u9fa5]{2,10}\s*")


# 作者块前是句末标点时，认为这是"独立注释段"，作者块后不应剥 \n
RE_SENT_END = "。！？…\"』」】"
# 作者块后如果紧跟虚词，说明前一句被作者块切断了，需要合并
RE_POST_NL_JOIN = set("的了吗呀啊哦呢嘛")


def strip_author_block(text: str) -> tuple[str, str | None]:
    """从正文里剥离"本文作者X（YYYY—YYYY），选作课文时有改动"这类作者说明。

    保守策略（只做作者块本身剥离，不修页眉残留 / 不补句号）：
      - 剥除范围 = [可能的"①" + 空格] + "本文作者...选作课文时有改动。"
      - 右端是否剥掉作者块后的 \n 分两种情况：
        * 前字符是句末标点（。！？等）→ 保留 \n，让注释独立成段被剥后前后仍分段
        * 前字符是汉字/逗号，且 \n 后是虚词（的/了/吗/呢/啊/呀）→ 剥 \n，
          让被作者块切断的同一句连回
        * 其他情况 → 保留 \n（保守）

    不做（留给 VLM/人工）：
      - 页眉残留（"朱德的扁担"、"原阅读"）
      - 剥除后前句缺句号
    """
    if not text or "本文作者" not in text:
        return text, None

    # Step 1: 定位作者说明块本身
    m = RE_AUTHOR_FULL.search(text)
    if not m:
        # 退化：找不到"选作课文时有改动"结尾时，剥"本文作者...。"直到句号/换行
        idx = text.find("本文作者")
        end_dq = text.find("。", idx)
        nl = text.find("\n", idx)
        if 0 <= nl and (end_dq < 0 or nl < end_dq):
            end = nl
        elif end_dq >= 0:
            end = end_dq + 1  # 含句号
        else:
            return text, None
        block_start, block_end = idx, max(end, 0)
    else:
        block_start, block_end = m.start(), m.end()

    # Step 2: 向左剥空白 + 圆圈数字 + 空白
    left = block_start
    while left > 0 and text[left - 1] in " \t\u2003\u2002":
        left -= 1
    if left > 0 and text[left - 1] in "①②③④⑤⑥⑦⑧⑨⑩":
        left -= 1
        while left > 0 and text[left - 1] in " \t\u2003\u2002":
            left -= 1

    # Step 3: 判断右端是否延伸剥掉 \n
    right = block_end
    prev_char = text[left - 1] if left > 0 else ""
    after_char = text[right] if right < len(text) else ""
    after_after_char = text[right + 1] if right + 1 < len(text) else ""

    extend_right_nl = False
    if after_char == "\n":
        # 前字符是句末标点 → 注释是独立段，保留 \n
        # 前字符是汉字/逗号且 \n 后是虚词 → 剥 \n 让句子连回
        if prev_char and prev_char not in RE_SENT_END and \
           after_after_char in RE_POST_NL_JOIN:
            extend_right_nl = True
    if extend_right_nl:
        right += 1

    removed = text[left:right]
    new = text[:left] + text[right:]

    # Step 4: 清理残留空行
    new = re.sub(r"\n[ \t\u2003\u2002]+\n", "\n", new)
    new = re.sub(r"\n{3,}", "\n\n", new)

    if new == text:
        return text, None
    return new, removed[:150]


# 保留别名以兼容旧调用
def clean_head(text: str) -> tuple[str, str | None]:
    return strip_author_block(text)


def clean_tail(text: str) -> tuple[str, str | None]:
    """尾部孤立的生卒年括号。"""
    if not text:
        return text, None
    # 只在最后一行末尾找
    last_nl = text.rfind("\n")
    last_line = text[last_nl + 1:] if last_nl >= 0 else text
    m = re.search(r"[，,]\s*（\d{4}\s*[—\-–~至]\s*\d{4}）(?:选作课文时有改动)?[。]?\s*$",
                  last_line)
    if not m:
        return text, None
    removed = last_line[m.start():]
    new = text[:last_nl + 1] + last_line[:m.start()]
    new = re.sub(r"[，,。；\s]+$", "", new)
    return new, removed[:80]


def clean_exercises(exercises: list) -> tuple[list, int]:
    """删除 exercises 里的空字符串。"""
    cleaned = [e for e in (exercises or []) if e and e.strip()]
    return cleaned, len(exercises or []) - len(cleaned)


def recompute_paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n") if p.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if not TEXT_PATH.exists():
        print(f"[ERROR] {TEXT_PATH} 不存在", file=sys.stderr)
        return 1

    if not args.dry_run and not BACKUP_PATH.exists():
        shutil.copy2(TEXT_PATH, BACKUP_PATH)
        print(f"备份 -> {BACKUP_PATH}")

    issues_csv = AUDIT_DIR / "ocr_issues.csv"
    affected_ids = set()
    if issues_csv.exists():
        with issues_csv.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["issue_type"] in ("author_glue", "note_glue", "empty_exercise"):
                    affected_ids.add(r["lesson_id"])

    rows = []
    with TEXT_PATH.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    stats = {"author_glue": 0, "note_glue": 0, "empty_exercise": 0}
    fix_samples = []  # (lesson_id, before, after)

    for L in rows:
        lid = L["lesson_id"]
        title = L.get("title", "")
        text_before = L.get("text") or ""
        text_after = text_before

        # 1) 首行作者
        text_after, head_removed = clean_head(text_after)
        if head_removed:
            stats["author_glue"] += 1
            fix_samples.append((lid, "HEAD", head_removed[:60]))

        # 2) 尾行生卒年
        text_after, tail_removed = clean_tail(text_after)
        if tail_removed:
            stats["note_glue"] += 1
            fix_samples.append((lid, "TAIL", tail_removed[:60]))

        # 3) exercises 空
        exercises_before = L.get("exercises") or []
        exercises_after, del_cnt = clean_exercises(exercises_before)
        if del_cnt:
            stats["empty_exercise"] += del_cnt

        if text_after != text_before:
            L["text"] = text_after
            L["paragraphs"] = recompute_paragraphs(text_after)
        if exercises_after != exercises_before:
            L["exercises"] = exercises_after

    total_changes = sum(stats.values())

    if args.dry_run:
        print(f"[dry-run] 预计修改：")
        for k, v in stats.items():
            print(f"  {k:20s} {v}")
        print(f"  {'TOTAL':20s} {total_changes}")
        print(f"\n前 20 条样本（{title} 表示课程）：")
        for lid, kind, snippet in fix_samples[:20]:
            print(f"  {kind:6s} {lid[-8:]:10s} {snippet}")
        return 0

    # 落地
    with TEXT_PATH.open("w", encoding="utf-8") as f:
        for L in rows:
            f.write(json.dumps(L, ensure_ascii=False) + "\n")

    print(f"修复完成 -> {TEXT_PATH}")
    print(f"共修改：")
    for k, v in stats.items():
        print(f"  {k:20s} {v}")
    print(f"  {'TOTAL':20s} {total_changes}")

    # 写报告
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as f:
        f.write(f"# OCR 修复报告\n\n")
        f.write(f"备份：`{BACKUP_PATH}`\n\n")
        f.write(f"## 修复统计\n\n")
        f.write(f"| 类型 | 数量 |\n|---|---|\n")
        for k, v in stats.items():
            f.write(f"| {k} | {v} |\n")
        f.write(f"| **合计** | **{total_changes}** |\n\n")
        f.write(f"## 修改样本（前 30 条）\n\n")
        f.write(f"```\n")
        for lid, kind, snippet in fix_samples[:30]:
            f.write(f"{kind:6s} {lid[-8:]:10s} {snippet}\n")
        f.write(f"```\n")
    print(f"报告 -> {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
