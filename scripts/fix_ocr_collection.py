# -*- coding: utf-8 -*-
"""合辑类父课子课正文错位修复（第四波）。

背景：multi_lesson_page 中 13 条为"合辑类"父课（古诗三首/古诗二首/文言文二则/古诗词三首/短诗三首），
其子课（如 :022 示儿、:023 题临安邸）的 text 字段错误地重复了整页合并的多首诗正文，
而非只含各自那一首。本脚本用 VLM 对每个子课单独精修，只提取该课标题对应的正文。

父课保留原 text（合辑标题，供导航用），子课 text 被正确切分。

用法：
    python scripts/fix_ocr_collection.py --dry-run   # 只调 VLM，不写文件
    python scripts/fix_ocr_collection.py             # 落地修复
    python scripts/fix_ocr_collection.py --limit 5
"""
from __future__ import annotations

import argparse
import base64
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
BACKUP_PATH = TEXT_PATH.with_suffix(".jsonl.bak4")
OUT_DIR = AUDIT_DIR / "vlm_runs_collection"
OUT_DIR.mkdir(parents=True, exist_ok=True)


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

任务：给定一页课文扫描图，这一页上印有「合辑标题」和「若干篇独立课文」（如同页印有《示儿》《题临安邸》两首诗，
合辑标题为《古诗三首》）。我要你**只提取其中某一篇指定课文的正文**。

要求：
1. 严格按 PDF 页面上的文字为准，OCR 修正错字。
2. 只提取**指定标题**的那一篇课文正文，不要混入同页其他课文。
3. 保留原有的换行/分段结构（用 \\n 表示段落分隔）。
4. 去掉页眉页脚、页码、圆圈数字标记（①②③）、作者说明块、"识字""写字"提示、课文注释部分。
5. 只保留该课文的正文诗句/文段。

输出严格 JSON（直接以 { 开头，以 } 结尾，不要 markdown code fence，不要任何思考过程）：
{"title":"指定课文标题","text":"该课文正文","confidence":0.95,"note":"一句话说明提取是否正确"}

再次强调：只输出一个 JSON 对象，禁止输出任何推理、思考、markdown 代码块或其他文字。"""


def render_pages(pdf_path: str, page_from: int, page_to: int) -> list[str]:
    imgs = []
    doc = fitz.open(pdf_path)
    start = max(0, page_from or 0)
    end = min(doc.page_count, (page_to or 0) + 1)
    for pno in range(start, end):
        page = doc.load_page(pno)
        pix = page.get_pixmap(dpi=DPI)
        imgs.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
    doc.close()
    return imgs


def call_vlm(prompt_text: str, images_b64: list[str]) -> tuple[str, dict]:
    url = f"{BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
    last_err = None
    for attempt in range(5):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=180)
            if r.status_code == 429:
                last_err = "429 限流"
                wait = 30 * (attempt + 1)
                print(f"    429 限流，等待 {wait}s 重试 ({attempt+1}/5)")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"].get("content", "")
            return content, data
        except requests.exceptions.RequestException as e:
            last_err = str(e)
            wait = 20 * (attempt + 1)
            print(f"    请求异常 {e}，等待 {wait}s 重试 ({attempt+1}/5)")
            time.sleep(wait)
    raise RuntimeError(f"VLM 调用最终失败: {last_err}")


def parse_vlm_json(content: str) -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("VLM 返回空 content")
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    i, j = content.find("{"), content.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(content[i:j + 1])
        except json.JSONDecodeError as e:
            raise ValueError(f"无法解析 VLM JSON (片段 {i}..{j}): {e}")
    raise ValueError(f"无法解析 VLM JSON: {content[:300]}")


def recompute_paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n") if p.strip()]


# 清理零宽字符
ZW_RE = re.compile(r"[\u200B-\u200F\uFEFF\u2060]")
def clean_title(t: str) -> str:
    return ZW_RE.sub("", t or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if not API_KEY:
        print("[ERROR] 未配置 VLM_API_KEY，检查 .env")
        return 1

    if not args.dry_run and not BACKUP_PATH.exists():
        import shutil
        shutil.copy2(TEXT_PATH, BACKUP_PATH)
        print(f"备份 -> {BACKUP_PATH}")

    # 加载 downloads 索引
    book_paths = {}
    with (ROOT / "data" / "downloads.jsonl").open(encoding="utf-8") as f:
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

    # 合辑父课 -> 子课映射（页码序号）
    # 父课为合辑标题（如"古诗三首"），子课为紧邻的独立课文
    COLLECTIONS = {
        "06422d77-21f1-45c3-b409-fa2947eee424": {"034": ["035", "036"]},
        "0f93b83e-b3c2-4a5d-8acd-ea460ab962d4": {"029": ["030"]},
        "2ce8f153-7bff-4c97-b6db-9aac414fea19": {"005": ["006"], "042": ["043"]},
        "2e3dc199-9c42-486b-bbee-7731bd0ee227": {"003": ["004", "005"], "037": ["038", "039"]},
        "53d6315e-5f90-42c4-904f-2d4e95fe99ed": {"004": ["005", "006"], "042": ["043", "044"], "053": ["054", "055"]},
        "5cd7e623-5c38-4602-871a-3fba8a551db2": {"053": ["054", "055"]},
        "98172dc9-8fba-4da6-9fae-6a3d1166f038": {"001": ["002", "003"]},
        "aabf2e4a-3ceb-4e86-8804-22c10223cc57": {"021": ["022", "023"], "041": ["042", "043"]},
    }

    # 展开为 (子课lid, 父课lid, 期望标题) 列表
    jobs = []
    for book, pages in COLLECTIONS.items():
        for parent_pno, child_pnos in pages.items():
            parent_lid = f"{book}:{parent_pno}"
            for cp in child_pnos:
                child_lid = f"{book}:{cp}"
                if child_lid in texts:
                    jobs.append({
                        "child_lid": child_lid,
                        "parent_lid": parent_lid,
                        "title": clean_title(texts[child_lid].get("title", "")),
                        "book_id": book,
                    })

    # 断点续跑：跳过已有成功日志的子课
    done_ids = {p.stem.replace("_", ":", 1) for p in OUT_DIR.glob("*.json")}
    jobs = [j for j in jobs if j["child_lid"] not in done_ids]
    print(f"待处理子课: {len(jobs)} 条（已跳过 {len(done_ids)} 条已完成）")
    if args.limit > 0:
        jobs = jobs[:args.limit]

    stats = {"success": 0, "fail": 0, "skipped": 0}
    report_lines = []

    for i, job in enumerate(jobs, 1):
        clid = job["child_lid"]
        title = job["title"]
        L = texts.get(clid)
        if not L:
            print(f"[{i}/{len(jobs)}] {clid[-12:]} NOT FOUND")
            stats["skipped"] += 1
            continue

        pdf_path = book_paths.get(L.get("book_id", ""))
        if not pdf_path or not Path(pdf_path).exists():
            print(f"[{i}/{len(jobs)}] {clid[-12:]} PDF not found")
            stats["skipped"] += 1
            continue

        page_from = L.get("page_from") or 0
        page_to = L.get("page_to") or page_from
        print(f"[{i}/{len(jobs)}] {clid[-12:]} 《{title}》 p{page_from}-{page_to}")

        try:
            imgs = render_pages(pdf_path, page_from, page_to)
        except Exception as e:
            print(f"    [ERR] 渲染失败: {e}")
            stats["fail"] += 1
            continue

        prompt = (
            f"这是语文教材第 {page_from}-{page_to} 页的扫描图。\n"
            f"这一页上有合辑标题《{clean_title(texts[job['parent_lid']].get('title',''))}》，包含多篇课文。\n"
            f"我只需要你提取其中标题为「{title}」的那一篇课文正文。\n"
            f"当前提取的正文（有问题，含多篇混在一起）：\n```\n{L.get('text','')[:2000]}\n```\n\n"
            f"请从图片识别原文，只输出「{title}」这一篇的正文，不要混入其他课文。\n"
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
        finally:
            # 两条之间延时，避免触发 API 429 限流
            time.sleep(3)

        safe_id = clid.replace(":", "_")
        run_file = OUT_DIR / f"{safe_id}.json"
        with run_file.open("w", encoding="utf-8") as f:
            json.dump({"lesson_id": clid, "title": title, "prompt": prompt,
                       "response": raw, "elapsed_sec": round(elapsed, 2)},
                      f, ensure_ascii=False, indent=2)

        try:
            result = parse_vlm_json(content)
        except Exception as e:
            print(f"    [ERR] JSON 解析失败: {e}")
            stats["fail"] += 1
            continue

        got_title = clean_title(result.get("title", ""))
        new_text = (result.get("text") or "").strip()
        old_text = L.get("text", "")
        old_n = len(old_text)
        new_n = len(new_text)

        if not new_text or new_n < 5:
            print(f"    [WARN] 《{title}》 新正文 {new_n} 字，视为幻觉，跳过")
            stats["fail"] += 1
            continue
        if new_n < old_n * 0.15:
            print(f"    [WARN] 《{title}》 新正文 {new_n} < 旧 {old_n}*0.15，跳过")
            stats["fail"] += 1
            continue

        if not args.dry_run:
            L["text"] = new_text
            L["paragraphs"] = recompute_paragraphs(new_text)
        stats["success"] += 1

        report_lines.append(
            f"- `{clid[-12:]}` 《{title}》 p{page_from}-{page_to} "
            f"旧{old_n}字 -> 新{new_n}字 (conf={result.get('confidence','?')})\n"
            f"  - 提取标题: {got_title!r} | note: {result.get('note','')}\n"
            f"  - 新正文: {new_text[:120]!r}"
        )
        print(f"    OK: 《{title}》 {old_n}->{new_n}字, {elapsed:.1f}s, conf={result.get('confidence','?')}")

    if not args.dry_run:
        with TEXT_PATH.open("w", encoding="utf-8") as f:
            for L in text_rows:
                f.write(json.dumps(L, ensure_ascii=False) + "\n")
        print(f"\n已写回 {TEXT_PATH}")

    report = AUDIT_DIR / "fix_collection_report.md"
    with report.open("w", encoding="utf-8") as f:
        f.write("# 合辑父课子课正文切分修复报告\n\n")
        f.write(f"处理模式：{'dry-run' if args.dry_run else '落地修改'}\n")
        f.write(f"成功 {stats['success']} / 失败 {stats['fail']} / 跳过 {stats['skipped']}\n\n")
        f.write("## 明细\n\n")
        for line in report_lines:
            f.write(line + "\n")
    print(f"报告 -> {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
