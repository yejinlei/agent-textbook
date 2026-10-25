# -*- coding: utf-8 -*-
"""OCR 错位修复第二波：变体作者说明 + note_glue + 文本类去重。

处理：
  1. variant_author  16 条：
     "本文选自..." / "本诗作者..." / "本文由..." / "本文是..." / "民间歌谣..."
     + 尾巴 "选作课文时有改动"
  2. note_glue       21 条（与变体大量重叠，去重后走同一逻辑）
  3. newchars_leak   6 条：课文里混入"识字""写字""书写提示"等内容
  4. repeat_paragraph 1 条：段落重复

multi_lesson_page 17 条留给 VLM 脚本（需要 PDF 视觉定位）。

用法：
    python scripts/fix_ocr_v2.py --dry-run
    python scripts/fix_ocr_v2.py
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
BACKUP_PATH = TEXT_PATH.with_suffix(".jsonl.bak2")

# ---------- 正则 ----------

# 变体作者说明块：从"本文选自/本诗作者/本文由/本文是"等开始，到"选作课文时有改动"或句号/换行
RE_VARIANT_FULL = re.compile(
    r"(?:本文选自|本诗作者|本文由|本文是|本诗|本书|本讲)[^。\n]*?"
    r"(?:选作课文时有改动[。]?|。[^\n]*?选作课文时有改动[。]?)"
)
# 简化：以"本X"开头，含"选作课文时有改动"
RE_VARIANT_ANY = re.compile(
    r"本(?:文|诗|书|讲)[^。\n]{0,80}?选作课文时有改动[。]?"
)

# 纯尾巴：前面已有部分被剥，只剩 "，选作课文时有改动。" 或 ",选作课文时有改动。"
RE_TAIL_ONLY = re.compile(
    r"[，,]\s*选作课文时有改动[。]?\s*"
)

# 圆圈数字尾巴（作者说明剥除后残留 ①）
RE_TRAILING_CIRCLE = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩]\s*$", re.MULTILINE)

# "识字/写字/书写提示" 等混入内容（newchars_leak）
# 常见模式：段落以"识字""写字""书写提示""课文朗读""书写顺序"开头
RE_NEWCHARS_LEAK = re.compile(
    r"^[\s\u2003\u2002]*(?:识字|写字|书写提示|书写顺序|课文朗读|书写指导|书写示例|写字提示|课文朗读)[^\n]*\n"
    r"(?:[\u4e00-\u9fa5·、，。？！：；（）()\s\u2003\u2002]{2,80}\n?){0,20}",
    re.MULTILINE
)
# 单行模式：整段只是"识字XX YY ZZ"
RE_SINGLE_LINE_LEAK = re.compile(
    r"^[\s\u2003\u2002]*(?:识字|写字|书写提示|书写顺序|课文朗读|写字提示|书写指导|书写示例|识字写字)[^\n]*$",
    re.MULTILINE
)

# 重复段落检测阈值
REPEAT_MIN_LEN = 20

# 句末标点
RE_SENT_END = "。！？…』」】"


def strip_variant_author(text: str) -> tuple[str, list[str]]:
    """剥离变体作者说明块。

    覆盖 6 种开头：本文选自 / 本诗作者 / 本文由 / 本文是 / 本诗 / 本书
    """
    removed_list = []
    if not text:
        return text, removed_list

    # 反复剥，因为可能有多段（如 99ed:004 里有 3 段"本诗作者"）
    while True:
        m = RE_VARIANT_ANY.search(text)
        if not m:
            # 检查纯尾巴
            m2 = RE_TAIL_ONLY.search(text)
            if m2:
                removed_list.append(m2.group()[:80])
                text = text[:m2.start()] + text[m2.end():]
                # 尾巴剥后可能残留句末标点重复
                text = re.sub(r"[。]{2,}", "。", text)
                continue
            break
        block_start, block_end = m.start(), m.end()

        # 向左剥空白 + 圆圈数字
        left = block_start
        while left > 0 and text[left - 1] in " \t\u2003\u2002":
            left -= 1
        if left > 0 and text[left - 1] in "①②③④⑤⑥⑦⑧⑨⑩":
            left -= 1
            while left > 0 and text[left - 1] in " \t\u2003\u2002":
                left -= 1

        # 判断右端是否剥 \n（同第一波逻辑）
        right = block_end
        prev_char = text[left - 1] if left > 0 else ""
        after_char = text[right] if right < len(text) else ""
        after_after_char = text[right + 1] if right + 1 < len(text) else ""

        extend_right_nl = False
        if after_char == "\n":
            if prev_char and prev_char not in RE_SENT_END and \
               after_after_char in "的了吗呀啊哦呢嘛":
                extend_right_nl = True
        if extend_right_nl:
            right += 1

        removed = text[left:right]
        text = text[:left] + text[right:]
        removed_list.append(removed[:120])

    # 清理残留
    text = re.sub(r"\n[ \t\u2003\u2002]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, removed_list


def strip_newchars_leak(text: str) -> tuple[str, list[str]]:
    """剥离混入的识字/写字提示块。"""
    removed_list = []
    if not text:
        return text, removed_list

    # 先试多行块
    for m in RE_NEWCHARS_LEAK.finditer(text):
        removed_list.append(m.group()[:120])
    text = RE_NEWCHARS_LEAK.sub("", text)

    # 再试单行
    for m in RE_SINGLE_LINE_LEAK.finditer(text):
        removed_list.append(m.group()[:80])
    text = RE_SINGLE_LINE_LEAK.sub("", text)

    # 清理空行
    text = re.sub(r"\n[ \t\u2003\u2002]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, removed_list


def dedup_paragraphs(text: str) -> tuple[str, list[str]]:
    """删除完全重复的段落（长度>=20）。"""
    lines = text.split("\n")
    seen = {}
    out = []
    removed = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if len(stripped) >= REPEAT_MIN_LEN:
            if stripped in seen:
                removed.append(stripped[:80])
                continue
            seen[stripped] = i
        out.append(line)
    return "\n".join(out), removed


def recompute_paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n") if p.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not TEXT_PATH.exists():
        print(f"[ERROR] {TEXT_PATH} 不存在")
        return 1

    # 备份
    if not args.dry_run and not BACKUP_PATH.exists():
        shutil.copy2(TEXT_PATH, BACKUP_PATH)
        print(f"备份 -> {BACKUP_PATH}")

    # 加载审计清单（找出要处理的目标）
    audit_ids = {}
    issues_csv = AUDIT_DIR / "ocr_issues.csv"
    if issues_csv.exists():
        with issues_csv.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["issue_type"] in {"variant_author", "note_glue", "newchars_leak", "repeat_paragraph"}:
                    audit_ids.setdefault(r["lesson_id"], []).append(r["issue_type"])

    # 也扫描全量（防止审计遗漏的变体）
    rows = []
    with TEXT_PATH.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    stats = {
        "variant_author": 0,
        "note_glue_tail": 0,
        "newchars_leak": 0,
        "repeat_paragraph": 0,
    }
    samples = []  # (lid_short, type, snippet)

    for L in rows:
        lid = L["lesson_id"]
        lid_short = lid[-8:]
        text_before = L.get("text") or ""
        text = text_before

        # 1) 变体作者说明 + 尾巴
        text, removed = strip_variant_author(text)
        if removed:
            stats["variant_author"] += len(removed)
            for r in removed:
                samples.append((lid_short, "VAR", r[:80]))

        # 2) newchars_leak
        text, removed = strip_newchars_leak(text)
        if removed:
            stats["newchars_leak"] += len(removed)
            for r in removed:
                samples.append((lid_short, "LEAK", r[:80]))

        # 3) 重复段落
        text, removed = dedup_paragraphs(text)
        if removed:
            stats["repeat_paragraph"] += len(removed)
            for r in removed:
                samples.append((lid_short, "DUP", r[:80]))

        if text != text_before:
            L["text"] = text
            L["paragraphs"] = recompute_paragraphs(text)

    total = sum(stats.values())

    if args.dry_run:
        print("[dry-run] 预计修改：")
        for k, v in stats.items():
            print(f"  {k:20s} {v}")
        print(f"  {'TOTAL':20s} {total}")
        print(f"\n前 30 条样本：")
        for lid_short, kind, snippet in samples[:30]:
            print(f"  {kind:6s} {lid_short:10s} {snippet}")
        return 0

    # 落地
    with TEXT_PATH.open("w", encoding="utf-8") as f:
        for L in rows:
            f.write(json.dumps(L, ensure_ascii=False) + "\n")

    print(f"修复完成 -> {TEXT_PATH}")
    for k, v in stats.items():
        print(f"  {k:20s} {v}")
    print(f"  {'TOTAL':20s} {total}")

    # 写报告
    report = AUDIT_DIR / "fix_v2_report.md"
    with report.open("w", encoding="utf-8") as f:
        f.write(f"# OCR 修复报告（第二波）\n\n")
        f.write(f"备份：`{BACKUP_PATH}`\n\n")
        f.write(f"## 修复统计\n\n")
        f.write(f"| 类型 | 数量 |\n|---|---|\n")
        for k, v in stats.items():
            f.write(f"| {k} | {v} |\n")
        f.write(f"| **合计** | **{total}** |\n\n")
        f.write(f"## 修改样本（前 50 条）\n\n")
        f.write(f"```\n")
        for lid_short, kind, snippet in samples[:50]:
            f.write(f"{kind:6s} {lid_short:10s} {snippet}\n")
        f.write(f"```\n")
    print(f"报告 -> {report}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
