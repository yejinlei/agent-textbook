"""课外拓展译文预生成入库：把课外阅读句子 + 绘本页面批量译成中文。

键 = 英文原文，与 pages/assets/app.js 里 loadTranslation() 的入参严格一致：
- 长文：build.py 的 _clean_reading_text(8000) 截断文本 → 按 JS 的 /\\n\\n+/ 切段
  → \\s+ 折叠 → 按 JS splitSentKeep 正则切句 → 折叠+trim，只留含 [A-Za-z] 的句子
- 绘本：pages[].text 原样（app 里按整页翻译）

译文存 data/readings/zh_trans.json（扁平 {en: zh}），构建期由
site/build.py 导出为 pages/assets/zh_trans.js（window.ZH_TRANS）。

翻译两条路径：
1) LLM 批量（主力，离线无配额）：--dump 导出 TSV 批次 → 翻译 agent 逐批产出
   done/*.tsv（i\\tzh）→ --merge 校验合并入库，缺漏批次 --status 列出重跑。
2) Google gtx 直连（备用，需网络可达）：--fetch 自动逐条抓取。

用法：
  .venv\\Scripts\\python tools\\build_zh_trans.py --dump [--size 150]
  .venv\\Scripts\\python tools\\build_zh_trans.py --status
  .venv\\Scripts\\python tools\\build_zh_trans.py --merge
  .venv\\Scripts\\python tools\\build_zh_trans.py --fetch [--limit N] [--sleep 0.25]
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from agent_textbook.site.build import _clean_reading_text  # noqa: E402

OUT = ROOT / "data" / "readings" / "zh_trans.json"
BATCH_DIR = ROOT / "data" / "readings" / "_zh_batches"
DONE_DIR = BATCH_DIR / "done"
GTX = "https://translate.googleapis.com/translate_a/single"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SAVE_EVERY = 40

# 与 app.js splitSentKeep 完全一致：/[^.!?。！？\n]+[.!?。！？]?\s*/g
SENT_RE = re.compile(r"[^.!?。！？\n]+[.!?。！？]?\s*")
AZ_RE = re.compile(r"[A-Za-z]")


def collect_items() -> list[str]:
    """抽出全部待译键（去重，保持出现顺序）。"""
    items: list[str] = []
    seen: set[str] = set()

    def add(s: str):
        if s and s not in seen:
            seen.add(s)
            items.append(s)

    cat = json.loads((ROOT / "data" / "readings" / "catalog.json")
                     .read_text(encoding="utf-8"))
    n_books = 0
    for b in cat.get("books", []):
        tp = ROOT / "data" / "readings" / "texts" / (b.get("id", "") + ".txt")
        if not tp.exists():
            continue
        n_books += 1
        text = _clean_reading_text(
            tp.read_text(encoding="utf-8", errors="replace"), 8000)
        # JS: text.split(/\n\n+/).filter(p => p.trim())
        for p in re.split(r"\n\n+", text):
            if not p.strip():
                continue
            # JS flatten: p.replace(/\s+/g, " ").trim()
            seg = re.sub(r"\s+", " ", p).strip()
            for chunk in SENT_RE.findall(seg):
                # JS: sp.textContent.replace(/\s+/g, " ").trim()
                en = re.sub(r"\s+", " ", chunk).strip()
                if en and AZ_RE.search(en):
                    add(en)

    pbs = json.loads((ROOT / "data" / "picturebooks" / "books.json")
                     .read_text(encoding="utf-8"))
    for b in pbs.get("books", []):
        for p in b.get("pages", []):
            t = (p.get("text") or "").strip()
            if t:
                add(t)

    print(f"[collect] readings_books={n_books} items={len(items)}")
    return items


# ---------------- LLM 批量路径：dump / status / merge ----------------

def cmd_dump(size: int):
    items = collect_items()
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for bi, start in enumerate(range(0, len(items), size)):
        part = items[start:start + size]
        fp = BATCH_DIR / ("batch_%03d.tsv" % bi)
        with fp.open("w", encoding="utf-8", newline="") as f:
            for i, en in enumerate(part, start):
                f.write("%d\t%s\n" % (i, en.replace("\t", " ").replace("\n", " ")))
        n += 1
    print(f"[dump] {n} batches -> {BATCH_DIR} (size={size})")


def _done_map() -> dict[int, str]:
    out: dict[int, str] = {}
    if not DONE_DIR.is_dir():
        return out
    for fp in sorted(DONE_DIR.glob("*.tsv")):
        for ln in fp.read_text(encoding="utf-8").splitlines():
            if not ln.strip() or "\t" not in ln:
                continue
            i, zh = ln.split("\t", 1)
            i = i.strip()
            if i.isdigit():
                out[int(i)] = zh.strip()
    return out


def _batch_items() -> list[str]:
    items: dict[int, str] = {}
    for fp in sorted(BATCH_DIR.glob("batch_*.tsv")):
        for ln in fp.read_text(encoding="utf-8").splitlines():
            if not ln.strip() or "\t" not in ln:
                continue
            i, en = ln.split("\t", 1)
            i = i.strip()
            if i.isdigit():
                items[int(i)] = en
    return [items[k] for k in sorted(items)]


def cmd_status():
    items = _batch_items()
    done = _done_map()
    missing = [i for i in range(len(items)) if i not in done]
    print(f"[status] items={len(items)} done={len(done)} missing={len(missing)}")
    if missing:
        batches = sorted({i // 1 for i in missing})
        # 按批文件聚合
        size = _guess_batch_size()
        bb = sorted({i // size for i in missing})
        print("  missing batches:", ", ".join("batch_%03d" % b for b in bb[:40]))
        print("  missing idx (前 20):", missing[:20])


def _guess_batch_size() -> int:
    mx = -1
    for fp in sorted(BATCH_DIR.glob("batch_*.tsv")):
        lines = fp.read_text(encoding="utf-8").splitlines()
        if len(lines) > mx:
            mx = len(lines)
    return mx or 150


def cmd_merge():
    items = _batch_items()
    done = _done_map()
    trans = {}
    missing = []
    for i, en in enumerate(items):
        zh = done.get(i, "")
        if zh:
            trans[en] = zh
        else:
            missing.append(i)
    save_store(trans)
    print(f"[merge] -> {OUT}  total={len(trans)} missing={len(missing)}")
    if missing:
        print("  缺漏 idx (前 20):", missing[:20], "→ 补齐后重新 --merge")


# ---------------- Google gtx 直连路径（备用） ----------------

def translate_one(en: str, retries: int = 4) -> str | None:
    q = urllib.parse.urlencode({
        "client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": en,
    })
    url = GTX + "?" + q
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
            if data and data[0]:
                return "".join(seg[0] or "" for seg in data[0]).strip()
            return None
        except Exception as e:  # noqa: BLE001
            wait = 2 ** attempt * 2
            print(f"  [retry {attempt + 1}/{retries}] {e} -> sleep {wait}s")
            time.sleep(wait)
    return None


def load_store() -> dict:
    if OUT.exists():
        raw = json.loads(OUT.read_text(encoding="utf-8"))
        return raw.get("trans", {})
    return {}


def save_store(trans: dict):
    payload = {
        "_doc": ("课外阅读/绘本预生成中文译文。键=英文原文（与 app.js "
                 "loadTranslation 入参一致），值=中文。"
                 "由 tools/build_zh_trans.py 生成（LLM 批量 / Google gtx 备用），"
                 "构建期导出为 pages/assets/zh_trans.js。"),
        "_updated": time.strftime("%Y-%m-%d"),
        "count": len(trans),
        "trans": dict(sorted(trans.items())),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")


def cmd_fetch(limit: int, sleep_s: float):
    items = collect_items()
    trans = load_store()
    todo = [s for s in items if s not in trans]
    print(f"[store] have={len(trans)} todo={len(todo)}")
    if limit:
        todo = todo[:limit]
    t0 = time.time()
    done = 0
    failed: list[str] = []
    for i, en in enumerate(todo, 1):
        zh = translate_one(en)
        if zh:
            trans[en] = zh
            done += 1
        else:
            failed.append(en)
            print(f"  [fail] {en[:80]}")
        if i % SAVE_EVERY == 0:
            save_store(trans)
            rate = done / max(time.time() - t0, 0.01)
            eta = (len(todo) - i) / max(rate, 0.01) / 60
            print(f"  [{i}/{len(todo)}] saved, {rate:.1f}/s, ETA {eta:.1f}min")
        time.sleep(sleep_s)
    save_store(trans)
    print(f"[done] new={done} failed={len(failed)} total={len(trans)}")
    if failed:
        for s in failed[:10]:
            print("  -", s[:100])
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="导出 TSV 批次供 LLM 翻译")
    ap.add_argument("--status", action="store_true", help="查看批次完成度")
    ap.add_argument("--merge", action="store_true", help="合并 done/*.tsv 入库")
    ap.add_argument("--fetch", action="store_true", help="Google gtx 直连抓取（备用）")
    ap.add_argument("--size", type=int, default=150, help="每批条数（--dump）")
    ap.add_argument("--limit", type=int, default=0, help="最多新译 N 条（--fetch）")
    ap.add_argument("--sleep", type=float, default=0.25, help="请求间隔秒（--fetch）")
    args = ap.parse_args()

    if args.dump:
        cmd_dump(args.size)
    elif args.status:
        cmd_status()
    elif args.merge:
        cmd_merge()
    elif args.fetch:
        cmd_fetch(args.limit, args.sleep)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
