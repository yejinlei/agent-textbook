# -*- coding: utf-8 -*-
"""OCR 错位修复第三波：VLM 精修 multi_lesson_page（17 条）。

策略：
  1. 从 audit CSV 挑出 17 条 multi_lesson_page
  2. 每条：定位对应 PDF + 页码范围
  3. 用 PyMuPDF 渲染成 PNG，base64 编码
  4. 调用 VLM API（sensenova-6.8-flash-lite），Prompt 说清楚任务
  5. 解析 VLM 返回的 JSON，写回 lesson_text.jsonl

用法：
    python scripts/fix_ocr_vlm.py --dry-run      # 只调用 VLM，不写文件
    python scripts/fix_ocr_vlm.py                # 落地修复
    python scripts/fix_ocr_vlm.py --limit 3      # 只处理前 3 条
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
import requests

ROOT = Path(__file__).resolve().parents[1]
TEXT_PATH = ROOT / "data" / "attrs" / "lesson_text.jsonl"
AUDIT_DIR = ROOT / "data" / "audit"
DOWNLOADS_PATH = ROOT / "data" / "downloads.jsonl"
BACKUP_PATH = TEXT_PATH.with_suffix(".jsonl.bak3")
OUT_DIR = AUDIT_DIR / "vlm_runs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 读取 .env
def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

ENV = load_env()
API_KEY = ENV.get("VLM_API_KEY")
BASE_URL = ENV.get("VLM_BASE_URL", "https://token.sensenova.cn/v1")
MODEL = ENV.get("VLM_MODEL", "sensenova-6.8-flash-lite")
DPI = int(ENV.get("VLM_DPI", "150"))
MAX_TOKENS = int(ENV.get("VLM_MAX_TOKENS", "16384"))

SYSTEM_PROMPT = """你是中文小学语文教材的 OCR 校对专家。

任务：给定"共页同文"问题（两到三篇课文被错误地合并到了一起），从 PDF 页面图片中
识别原文，把被混在一起的课文正确拆开，为每篇课文生成完整的正文。

要求：
1. 严格按 PDF 页面上的文字为准，OCR 修正错字。
2. 保留原有的换行/分段结构（用 \\n 表示段落分隔）。
3. 去掉所有页眉、页脚、页码、圆圈数字标记（①②③）、课文标题下方的作者说明块
   （如"本文作者...选作课文时有改动"）、"识字""写字"等提示块、以及课文注释部分。
4. 只保留课文正文。

输出严格 JSON（直接以 { 开头，以 } 结尾，不要 markdown code fence，不要任何思考过程）：
{"lessons":[{"title":"课文标题1","text":"课文正文1","confidence":0.95,"notes":""},{"title":"课文标题2","text":"课文正文2","confidence":0.90,"notes":""}],"merge_note":"一句话说明这是哪几篇课文同页"}

再次强调：只输出一个 JSON 对象，禁止输出任何推理、思考、markdown 代码块或其他文字。"""


def render_pages(pdf_path: str, page_from: int, page_to: int) -> list[str]:
    """渲染 PDF 页码范围，返回 base64 PNG 列表。page_from/to 是 0-based 物理页 index。"""
    imgs = []
    doc = fitz.open(pdf_path)
    start = max(0, page_from or 0)
    end = min(doc.page_count, (page_to or 0) + 1)
    for pno in range(start, end):
        page = doc.load_page(pno)
        pix = page.get_pixmap(dpi=DPI)
        buf = pix.tobytes("png")
        imgs.append(base64.b64encode(buf).decode("ascii"))
    doc.close()
    return imgs


def call_vlm(prompt_text: str, images_b64: list[str]) -> tuple[str, dict]:
    """调用 VLM API，返回 (content, raw_response)。"""
    url = f"{BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    # 用户消息：文本 + 图片
    user_content = [{"type": "text", "text": prompt_text}]
    for b64 in images_b64:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })
    messages.append({"role": "user", "content": user_content})
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": 0.2,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=180)
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"].get("content", "")
    return content, data


def parse_vlm_json(content: str) -> dict:
    """从 VLM 返回文本里提取 JSON。"""
    content = (content or "").strip()
    if not content:
        raise ValueError("VLM 返回空 content")
    # 去掉可能的 code fence
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # 找第一个 { 到最后一个 }
    i = content.find("{")
    j = content.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(content[i:j + 1])
        except json.JSONDecodeError as e:
            raise ValueError(f"无法解析 VLM JSON (片段 {i}..{j}): {e}\n原文前300字: {content[:300]}")
    raise ValueError(f"无法解析 VLM JSON: {content[:300]}")


def recompute_paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n") if p.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", type=str, default="")  # 过滤：只处理指定 lesson_id 前缀
    args = ap.parse_args()

    if not API_KEY:
        print("[ERROR] 未配置 VLM_API_KEY，检查 .env")
        return 1

    if not args.dry_run:
        if not BACKUP_PATH.exists():
            import shutil
            shutil.copy2(TEXT_PATH, BACKUP_PATH)
            print(f"备份 -> {BACKUP_PATH}")

    # 加载 downloads 索引
    book_paths = {}
    with DOWNLOADS_PATH.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("subject") == "语文" and r.get("abs_path"):
                book_paths[r["id"]] = r["abs_path"]

    # 加载 lesson_text
    texts = {}
    text_rows = []
    with TEXT_PATH.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                L = json.loads(line)
                texts[L["lesson_id"]] = L
                text_rows.append(L)

    # 加载 multi_lesson_page 清单
    # 注意：CSV 里 lesson_id 为空（因为 detail 含逗号导致列错位）
    # 需要 book_id + lesson_label 反查
    issues = list(csv.DictReader((AUDIT_DIR / "ocr_issues.csv").open(encoding="utf-8-sig")))
    mlp_raw = [r for r in issues if r["issue_type"] == "multi_lesson_page"]

    # 按 book_id 建索引：冒号后 3 位（如 "026"）-> lesson_id
    # audit detail 里 "24:026" 的 "24" 是 lesson_id 最后 2 位（book_short），
    # ":026" 是冒号后 3 位序号，book 内唯一。
    by_book = {}
    for L in text_rows:
        by_book.setdefault(L["book_id"], {})
        idx = L["lesson_id"].rfind(":")
        if idx > 0:
            tail_num = L["lesson_id"][idx + 1:]  # 如 "026"
            by_book[L["book_id"]][tail_num] = L["lesson_id"]

    # 判断 detail 里第一个 title 是否为"合辑类"父课标题（含"首"/"则"/"篇"等）
    # 这类是父课+子课问题，不是真·多课共页，VLM 处理无意义，跳过
    RE_COLLECTION = re.compile(r"^[^（(\s]{1,8}(?:首|则|篇)(?:（[^）]*）|（[^）]*）)?$")
    # 清理零宽字符（U+200B ZWNJ / U+FEFF BOM 等），CSV 里部分标题混入了
    ZW_RE = re.compile(r"[\u200B-\u200F\uFEFF\u2060]")

    mlp = []
    skipped_collection = 0
    for r in mlp_raw:
        bid = r["book_id"]
        detail = r.get("detail", "")

        # 从 detail 末尾取最后一个"标题串"，形如 "24:026/24:027 马诗/石灰吟"
        # 简单方式：取最后一组"由/分隔的中文字"
        m = re.search(r"p\s*\d+\s+[\w:-]+(?:/[\w:-]+)*\s+([^\s]+(?:/[^\s]+)*)\s*$", detail)
        title_str = m.group(1) if m else ""
        first_title_raw = title_str.split("/")[0] if title_str else ""
        first_title = ZW_RE.sub("", first_title_raw).strip()

        if RE_COLLECTION.match(first_title):
            print(f"  [SKIP collection] 《{first_title}》 (raw={first_title_raw!r})")
            skipped_collection += 1
            continue

        # 解析 page 和 involved
        m2 = re.search(r"p\s*(\d+)\s+([\w:-]+(?:/[\w:-]+)*)", detail)
        if not m2:
            print(f"  [SKIP] 无法解析 detail: {detail}")
            continue
        page_num = int(m2.group(1))
        parts = m2.group(2).split("/")
        involved = []
        for p in parts:
            pno = p.split(":")[-1]
            lid = by_book.get(bid, {}).get(pno, "")
            if lid:
                involved.append(lid)
        if not involved:
            print(f"  [SKIP] book_short={book_short} parts={parts} 未匹配")
            continue
        mlp.append({
            "book_id": bid,
            "primary_lid": involved[0],
            "involved": involved,
            "location": str(page_num),
            "detail": r.get("detail", ""),
        })

    if args.only:
        mlp = [r for r in mlp if r["primary_lid"].endswith(args.only)]
    if args.limit > 0:
        mlp = mlp[:args.limit]
    print(f"待处理 multi_lesson_page: {len(mlp)} 条")

    stats = {"success": 0, "fail": 0, "skipped": 0}
    report_lines = []

    for i, r in enumerate(mlp, 1):
        lid = r["primary_lid"]
        involved = r["involved"]
        L = texts.get(lid)
        if not L:
            print(f"[{i}/{len(mlp)}] {lid[-12:]} NOT FOUND in lesson_text")
            stats["skipped"] += 1
            continue

        pdf_path = book_paths.get(L.get("book_id", ""))
        if not pdf_path or not Path(pdf_path).exists():
            print(f"[{i}/{len(mlp)}] {lid[-12:]} PDF not found: {pdf_path}")
            stats["skipped"] += 1
            continue

        page_from = L.get("page_from") or 0
        page_to = L.get("page_to") or page_from
        print(f"[{i}/{len(mlp)}] {lid[-12:]} 《{L['title']}》 p{page_from}-{page_to}  involved={len(involved)}")

        try:
            imgs = render_pages(pdf_path, page_from, page_to)
        except Exception as e:
            print(f"    [ERR] 渲染失败: {e}")
            stats["fail"] += 1
            continue

        # 构造 prompt
        prompt = (
            f"这是语文教材第 {page_from}-{page_to} 页的扫描图。\n"
            f"当前课文 {L['title']} 疑似与其他课文共页合并（涉及 {len(involved)} 篇）。\n"
            f"当前提取的正文（有问题）：\n```\n{L.get('text','')[:2000]}\n```\n"
            f"问题描述：{r['detail']}\n\n"
            f"请从图片识别原文，正确拆分课文。lessons[0] 应对应标题为「{L['title']}」的课文，"
            f"其他混入的课文放在后续 lessons 中。\n"
            f"输出 JSON。"
        )

        t0 = time.time()
        try:
            content, raw = call_vlm(prompt, imgs)
            elapsed = time.time() - t0
        except Exception as e:
            print(f"    [ERR] VLM 调用失败: {e}")
            stats["fail"] += 1
            continue

        # 保存 raw（文件名去除冒号，Windows 不合法）
        safe_id = lid.replace(":", "_")
        run_file = OUT_DIR / f"{safe_id}.json"
        with run_file.open("w", encoding="utf-8") as f:
            json.dump({"lesson_id": lid, "prompt": prompt, "response": raw,
                       "elapsed_sec": round(elapsed, 2)}, f, ensure_ascii=False, indent=2)

        # 解析
        try:
            result = parse_vlm_json(content)
        except Exception as e:
            print(f"    [ERR] JSON 解析失败: {e}")
            stats["fail"] += 1
            continue

        lessons = result.get("lessons", [])
        if not lessons:
            print(f"    [WARN] VLM 返回空 lessons")
            stats["fail"] += 1
            continue

        old_len = len(L.get("text", ""))
        fixed_count = 0

        # 按顺序对齐：lessons[i] -> involved[i]
        # 校验 title：lessons[j].title 应与 involved[j] 的 lesson.title 一致
        for j, cur in enumerate(lessons):
            target_lid = involved[j] if j < len(involved) else lid
            TL = texts.get(target_lid)
            if not TL:
                print(f"    [WARN] involved[{j}]={target_lid[-12:]} 不在 lesson_text")
                continue
            exp_title = TL.get("title", "").strip()
            got_title = (cur.get("title") or "").strip()
            if exp_title and got_title and exp_title not in got_title and got_title not in exp_title:
                print(f"    [WARN] lessons[{j}].title='{got_title}' != 目标'{exp_title}'，仍写入")
            new_text = (cur.get("text") or "").strip()
            if not new_text:
                print(f"    [WARN] lessons[{j}] 空正文，跳过")
                continue
            old_t = TL.get("text", "")
            old_n = len(old_t)
            new_n = len(new_text)
            # 校验：VLM 去除注释后可能显著变短，阈值放宽到 0.2
            # 但极短（<10 字）视为幻觉，拒绝
            if new_n < 10:
                print(f"    [WARN] 《{TL['title']}》 新正文仅 {new_n} 字，视为幻觉，跳过")
                continue
            if new_n < old_n * 0.2:
                print(f"    [WARN] 《{TL['title']}》 新正文 {new_n} < 旧 {old_n}*0.2，跳过")
                continue
            if not args.dry_run:
                TL["text"] = new_text
                TL["paragraphs"] = recompute_paragraphs(new_text)
            fixed_count += 1
            if j == 0:
                stats["success"] += 1

        report_lines.append(
            f"- `{lid[-12:]}` 《{L['title']}》 p{page_from}-{page_to}  "
            f"修复 {fixed_count}/{len(lessons)} 篇\n"
            f"  - merge_note: {result.get('merge_note','')}\n"
            + "\n".join(
                f"  - lessons[{j}] 《{ls.get('title','?')}》 "
                f"-> involved[{j}] {involved[j][-12:] if j < len(involved) else '?'} "
                f"({len(ls.get('text',''))} 字, conf={ls.get('confidence','?')})"
                for j, ls in enumerate(lessons)
            )
        )
        print(f"    OK: 修复 {fixed_count} 篇, 共 {len(lessons)} 篇, {elapsed:.1f}s")

    # 落地
    if not args.dry_run:
        with TEXT_PATH.open("w", encoding="utf-8") as f:
            for L in text_rows:
                f.write(json.dumps(L, ensure_ascii=False) + "\n")
        print(f"\n已写回 {TEXT_PATH}")

    # 报告
    report = AUDIT_DIR / "fix_vlm_report.md"
    with report.open("w", encoding="utf-8") as f:
        f.write("# OCR VLM 精修报告（multi_lesson_page）\n\n")
        f.write(f"处理模式：{'dry-run' if args.dry_run else '落地修改'}\n")
        f.write(f"成功 {stats['success']} / 失败 {stats['fail']} / 跳过 {stats['skipped']}\n\n")
        f.write("## 明细\n\n")
        for line in report_lines:
            f.write(line + "\n")
    print(f"报告 -> {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
