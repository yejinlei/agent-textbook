# -*- coding: utf-8 -*-
"""Piper TTS 批量生成 + 音色索引。

设计
----
- 从 data/attrs/en_*.jsonl 抽取所有可朗读英文文本（去重）。
- 用 Piper（4 个音色）合成 WAV，再用 ffmpeg 转 MP3 32kbps。
- 按内容 hash（sha1 前 12 位）命名，输出到 data/tts/{voice}/{hash}.mp3。
- 生成 data/tts/index.json：前端 speech() 按 (text, voice) 查表拿文件路径。

CLI（在 cli.py 里包一层）
----
    tts gen [--voice X] [--limit N]        生成
    tts list                               列出音色与产出统计
    tts download                           下载缺失的模型

依赖
----
- piper-tts（venv 内已装）
- ffmpeg（PATH 里）
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import config

ATTRS_DIR = config.ATTRS_DIR
MODELS_DIR = os.path.join(config.ROOT, "models", "piper")
TTS_DIR = os.path.join(config.DATA_DIR, "tts")
INDEX_FILE = os.path.join(TTS_DIR, "index.json")

# ------------------------------------------------------------------ 音色
# 每个音色：目录名、性别、标签、HF 镜像下载路径
VOICES: dict[str, dict] = {
    "alan": {
        "label": "Alan · 英音男声",
        "lang": "en_GB",
        "gender": "M",
        "model": "en/en_GB/alan/medium/en_GB-alan-medium",
    },
    "jenny": {
        "label": "Jenny · 英音女声",
        "lang": "en_GB",
        "gender": "F",
        "model": "en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium",
    },
    "amy": {
        "label": "Amy · 美音女声",
        "lang": "en_US",
        "gender": "F",
        "model": "en/en_US/amy/medium/en_US-amy-medium",
    },
    "cori": {
        "label": "Cori · 英音高质量",
        "lang": "en_GB",
        "gender": "F",
        "model": "en/en_GB/cori/high/en_GB-cori-high",
    },
}

HF_MIRROR = "https://hf-mirror.com/rhasspy/piper-voices/resolve/main/"
DEFAULT_VOICE = "alan"

# 前端音色试听按钮用的固定文本；生成时保证这条被 4 个音色都合成过
VOICE_PREVIEW_TEXT = "Hello! This is your TTS voice. Nice to meet you."

# ------------------------------------------------------------------ 提取


def _load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _iter_all():
    for name in ("en_vocab", "en_dialogue", "en_passage", "en_grammar",
                 "en_phonics", "en_expr", "en_song", "en_project",
                 "en_revision"):
        p = os.path.join(ATTRS_DIR, name + ".jsonl")
        if os.path.exists(p):
            for rec in _load_jsonl(p):
                yield name, rec


def _clean(s):
    """把非 ASCII 中文/emoji 剔除，只留英文可朗读字符；标点转 ASCII 统一。"""
    if not isinstance(s, str):
        return ""
    # 先把常见 Unicode 标点半角化（curly quotes / ellipsis / em-dash）
    s = (s.replace("\u2018", "'").replace("\u2019", "'")
           .replace("\u201c", '"').replace("\u201d", '"')
           .replace("\u2013", "-").replace("\u2014", "-")
           .replace("\u2026", "..."))
    # 保留：字母、数字、常见英文标点、连字符、斜杠（用于 a/an 之类）
    out = []
    for ch in s:
        if ch.isascii() and (ch.isalnum() or ch in " .,!?;:'\"-()/-_\\n%"):
            out.append(ch)
        else:
            out.append(" ")
    t = "".join(out).replace("\n", " ")
    # 折叠空白
    while "  " in t:
        t = t.replace("  ", " ")
    return t.strip()


def extract_texts(max_len: int = 400) -> list[str]:
    """从 9 个 jsonl 抽出所有可朗读英文文本（去重）。"""
    seen: set[str] = set()
    out: list[str] = []

    def add(s):
        t = _clean(s)
        if not t:
            return
        # 至少要有一个字母
        if not any(c.isalpha() and c.isascii() for c in t):
            return
        # 太长（比如整篇课文）截断
        if len(t) > max_len:
            # 在最后一个句子边界截断
            cut = t[:max_len].rsplit(".", 1)[0]
            t = cut + "." if cut else t[:max_len]
        # 去重（保留原大小写；转小写做 key）
        k = t.lower()
        if k in seen:
            return
        seen.add(k)
        out.append(t)

    for _name, rec in _iter_all():
        # vocab
        if "word" in rec and isinstance(rec["word"], str):
            add(rec["word"])
        for ex in rec.get("example") or []:
            add(ex)
        # dialogue
        for turn in rec.get("turns") or []:
            add(turn.get("en", ""))
        for p in rec.get("patterns") or []:
            add(p)
        # passage
        add(rec.get("text", ""))
        for w in rec.get("words") or []:
            add(w)
        # grammar: examples 是 dict {en, zh}；phonics: examples 是 str 列表
        add(rec.get("pattern", ""))
        for ex in rec.get("examples") or []:
            if isinstance(ex, dict):
                add(ex.get("en", ""))
            else:
                add(ex)
        add(rec.get("chant", ""))
        # expr
        add(rec.get("en", ""))
        # song
        lyrics = rec.get("lyrics") or []
        for line in lyrics:
            add(line)
        # project / revision
        for lang in rec.get("language") or []:
            add(lang)
        for step in rec.get("steps") or []:
            add(step)

    return out


# ------------------------------------------------------------------ 模型


def _url_for(voice: str, ext: str) -> str:
    m = VOICES[voice]["model"]
    return HF_MIRROR + m + "." + ext


def download_voice(voice: str) -> tuple[str, str]:
    """确保模型文件就绪，返回 (onnx_path, json_path)。"""
    if voice not in VOICES:
        raise ValueError(f"unknown voice: {voice}")
    os.makedirs(MODELS_DIR, exist_ok=True)
    onnx = os.path.join(MODELS_DIR, f"{voice}.onnx")
    cfg = os.path.join(MODELS_DIR, f"{voice}.onnx.json")
    for path, ext in ((onnx, "onnx"), (cfg, "onnx.json")):
        if os.path.exists(path) and os.path.getsize(path) > 0:
            continue
        url = _url_for(voice, ext)
        print(f"[download] {voice} {ext}  {url}")
        tmp = path + ".tmp"
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Invoke-WebRequest -Uri '{url}' -OutFile '{tmp}'"],
            check=True,
        )
        os.replace(tmp, path)
    return onnx, cfg


def download_all() -> None:
    for v in VOICES:
        download_voice(v)


# ------------------------------------------------------------------ 合成


def _find_ffmpeg() -> str:
    for c in ("ffmpeg", "ffmpeg.exe"):
        p = shutil.which(c)
        if p:
            return p
    # 常见 WinGet 安装路径
    gw = r"C:\Users\40108\AppData\Local\Microsoft\WinGet\Packages"
    for root, _dirs, files in os.walk(gw):
        if "ffmpeg.exe" in files:
            return os.path.join(root, "ffmpeg.exe")
    raise RuntimeError("ffmpeg not found in PATH")


_FFMPEG = None


def ffmpeg() -> str:
    global _FFMPEG
    if _FFMPEG is None:
        _FFMPEG = _find_ffmpeg()
    return _FFMPEG


def piper_exe() -> str:
    """piper 可执行文件路径（venv Scripts/piper.exe）。"""
    cand = os.path.join(sys.prefix, "Scripts", "piper.exe")
    if not os.path.exists(cand):
        cand = shutil.which("piper") or shutil.which("piper.exe")
        if not cand:
            raise RuntimeError("piper not found; run: pip install piper-tts")
    return cand


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def synth_voice(texts: list[str], voice: str, limit: int | None = None) -> dict:
    """对一个音色合成 texts 列表，返回 {text: {file, size}}。"""
    onnx, cfg = download_voice(voice)
    vdir = os.path.join(TTS_DIR, voice)
    os.makedirs(vdir, exist_ok=True)
    piper = piper_exe()

    # 先按 limit 截断，再把试听文本 append 到末尾，避免 preview 被 limit 切掉
    if limit is not None:
        texts = texts[:limit]
    if VOICE_PREVIEW_TEXT not in texts:
        texts.append(VOICE_PREVIEW_TEXT)

    results: dict[str, dict] = {}
    p = Path(piper)
    done = 0
    for i, text in enumerate(texts):
        h = text_hash(text)
        mp3 = os.path.join(vdir, h + ".mp3")
        if os.path.exists(mp3) and os.path.getsize(mp3) > 0:
            results[text] = {"file": f"{voice}/{h}.mp3",
                             "size": os.path.getsize(mp3)}
            done += 1
            continue
        # 合成 wav 到临时目录，再转 mp3
        with tempfile.TemporaryDirectory(prefix="piper_") as td:
            wav = os.path.join(td, "out.wav")
            try:
                subprocess.run(
                    [str(piper), "--model", onnx, "--config", cfg,
                     "--output_file", wav, "--text", text],
                    check=True, capture_output=True, timeout=30,
                )
            except subprocess.CalledProcessError as e:
                # Piper 偶发会失败（如空音素），跳过
                sys.stderr.write(f"[skip] {voice} {h} {text!r}: {e}\n")
                continue
            if not os.path.exists(wav) or os.path.getsize(wav) == 0:
                continue
            try:
                subprocess.run(
                    [ffmpeg(), "-y", "-loglevel", "error",
                     "-i", wav, "-codec:a", "libmp3lame",
                     "-b:a", "32k", "-ar", "22050", mp3],
                    check=True, capture_output=True, timeout=15,
                )
            except subprocess.CalledProcessError as e:
                sys.stderr.write(f"[ffmpeg skip] {voice} {h}: {e}\n")
                continue
        if os.path.exists(mp3) and os.path.getsize(mp3) > 0:
            results[text] = {"file": f"{voice}/{h}.mp3",
                             "size": os.path.getsize(mp3)}
            done += 1
        if (i + 1) % 200 == 0:
            print(f"  [{voice}] {i+1}/{len(texts)} (done={done})")
    return results


def synth_worker(args):
    voice, texts = args
    return voice, synth_voice(texts, voice)


# ------------------------------------------------------------------ 编排


TEXTMAP_FILE = os.path.join(TTS_DIR, "map.json")
PREVIEW_FILE = os.path.join(TTS_DIR, "preview.json")


def build_index(data: dict[str, dict[str, dict]],
                texts: list[str] | None = None) -> dict:
    """写三个文件：
    - index.json  ：voices + entries（内部索引，按 hash）
    - map.json    ：{cleaned_text: {voice: "file.mp3"}}，前端 speech() 直接查表
    - preview.json：{voice: "file.mp3"}，前端音色试听按钮用
    """
    index = {"voices": [
        {"id": k, "label": v["label"], "lang": v["lang"], "gender": v["gender"]}
        for k, v in VOICES.items()
    ], "default": DEFAULT_VOICE, "entries": data}
    os.makedirs(TTS_DIR, exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    if texts:
        # map: cleaned_text -> {voice: relpath}
        h2text = {text_hash(t): t for t in texts}
        map_out: dict[str, dict] = {}
        for h, entry in data.items():
            for v in VOICES:
                if v in entry:
                    map_out.setdefault(entry.get("text") or h2text.get(h, ""), {})[v] = entry[v]["file"]
        with open(TEXTMAP_FILE, "w", encoding="utf-8") as f:
            json.dump(map_out, f, ensure_ascii=False, separators=(",", ":"))
        # preview: voice -> relpath (for the voice-preview button)
        ph = text_hash(VOICE_PREVIEW_TEXT)
        preview = {}
        if ph in data:
            for v in VOICES:
                if v in data[ph]:
                    preview[v] = data[ph][v]["file"]
        if preview:
            with open(PREVIEW_FILE, "w", encoding="utf-8") as f:
                json.dump(preview, f, ensure_ascii=False, separators=(",", ":"))
    return index


def generate(voices: list[str] | None = None, limit: int | None = None,
             parallel: bool = True, verbose: bool = True) -> dict:
    """主入口：提取 → 合成 → 索引。"""
    voices = voices or list(VOICES.keys())
    texts = extract_texts()
    # 前端音色试听用的固定文本，4 个音色都保证生成
    if VOICE_PREVIEW_TEXT not in texts:
        texts = texts + [VOICE_PREVIEW_TEXT]
    if verbose:
        print(f"[tts] extracted {len(texts)} unique texts "
              f"({len(voices)} voices → {len(texts)*len(voices)} audio files)")

    # 保留旧 index 里的条目
    existing: dict[str, dict] = {}
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, encoding="utf-8") as f:
                existing = json.load(f).get("entries", {}) or {}
        except Exception:
            existing = {}

    data = dict(existing)

    if parallel:
        with cf.ThreadPoolExecutor(max_workers=len(voices)) as ex:
            futs = [ex.submit(synth_worker, (v, texts)) for v in voices]
            for fut in cf.as_completed(futs):
                v, res = fut.result()
                for text, meta in res.items():
                    h = text_hash(text)
                    data.setdefault(h, {})["text"] = text
                    data[h][v] = {"file": meta["file"], "size": meta["size"]}
                if verbose:
                    print(f"[tts] {v}: {len(res)} files")
    else:
        for v in voices:
            res = synth_voice(texts, v, limit=limit)
            for text, meta in res.items():
                h = text_hash(text)
                data.setdefault(h, {})["text"] = text
                data[h][v] = {"file": meta["file"], "size": meta["size"]}

    # 确保 index 覆盖所有提取到的文本（即便尚未合成成功，也留出 slot）
    for t in texts:
        h = text_hash(t)
        data.setdefault(h, {})["text"] = t

    build_index(data, texts)

    if verbose:
        size_mb = os.path.getsize(INDEX_FILE) / (1024 * 1024)
        print(f"[tts] index → {INDEX_FILE} ({len(data)} entries, {size_mb:.1f} MB)")
        # 总音频体积
        total = 0
        for v in VOICES:
            d = os.path.join(TTS_DIR, v)
            if os.path.isdir(d):
                total += sum(os.path.getsize(os.path.join(d, f))
                             for f in os.listdir(d))
        print(f"[tts] audio total: {total/1024/1024:.1f} MB")
    return {"entries": len(data), "index": INDEX_FILE}


# ------------------------------------------------------------------ 命令行辅助


def cmd_list() -> int:
    print("=== Voices ===")
    for k, v in VOICES.items():
        onnx = os.path.join(MODELS_DIR, f"{k}.onnx")
        state = "downloaded" if os.path.exists(onnx) else "missing"
        n_mp3 = 0
        d = os.path.join(TTS_DIR, k)
        if os.path.isdir(d):
            n_mp3 = len([f for f in os.listdir(d) if f.endswith(".mp3")])
        print(f"  {k:<8s} {v['label']:<20s} lang={v['lang']:<5s} "
              f"gender={v['gender']}  model={state}  mp3={n_mp3}")
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, encoding="utf-8") as f:
            idx = json.load(f)
        print(f"=== Index === {INDEX_FILE}  entries={len(idx.get('entries',{}))}")
    return 0


def cmd_gen(voices: list[str] | None = None, limit: int | None = None,
            parallel: bool = True) -> int:
    generate(voices=voices, limit=limit, parallel=parallel)
    return 0


def cmd_download(voices: list[str] | None = None) -> int:
    for v in voices or list(VOICES.keys()):
        download_voice(v)
    print("done.")
    return 0
