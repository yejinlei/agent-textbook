# -*- coding: utf-8 -*-
"""给英语对话加教学层数据：情境、动作、词汇卡、句型、语法。

目标：把 turns 从"扁平 4 字段"扩展为"教学 7 维"，
让渲染层可以像语文一样呈现多层次内容。

用法：
    python tools/enrich_english_dialogues.py          # 处理 pages/data/english.json
    python tools/enrich_english_dialogues.py --html    # 同步 8 个 english/*.html 里的 DATA
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "pages" / "data" / "english.json"
HTML_GLOB = ROOT / "pages" / "english" / "*.html"

# ---- 手工标注库：只覆盖三年级上册 Unit 1 让样本先跑通。
#      每个 dialogue 的 key = (book, unit_no, scene, function)
#      字段解释见 docs/dialogue_schema.md（待补）
NOTES = {
    ("三年级上册", 1, "Let's talk", "问候与介绍"): {
        "scene_desc": "Mike 和 Sarah 第一次见面，互道问候并介绍自己。",
        "scene_icon": "hello",
        "vocab_cards": [
            {"word": "name", "ipa": "/neɪm/", "pos": "n.", "zh": "名字", "note": "My name is ___ 常用自我介绍"},
            {"word": "nice", "ipa": "/naɪs/", "pos": "adj.", "zh": "令人愉快的；友好的", "note": "Nice to meet you 是常见问候套语"},
            {"word": "meet", "ipa": "/miːt/", "pos": "v.", "zh": "遇见；见面", "note": "Nice to meet you / too"},
        ],
        "sentence_patterns": [
            {"en": "Hello! My name is ___.", "zh": "你好！我叫……", "fill": "___", "variants": ["Mike Black", "Sarah Miller", "your name"]},
            {"en": "Hi! I'm ___.", "zh": "嗨！我是……", "fill": "___", "variants": ["Sarah Miller", "Mike Black", "your name"]},
            {"en": "Nice to meet you.", "zh": "很高兴认识你。", "fill": None, "variants": []},
            {"en": "Nice to meet you too.", "zh": "我也很高兴认识你。", "fill": None, "variants": []},
        ],
        "grammar_points": ["be 动词第三人称单数 is / am"],
        "usage_tags": ["初次见面", "自我介绍", "半正式"],
    },
}


def find_and_enrich(data: dict) -> tuple:
    """在 data['dialogues'] 里按 key 匹配并注入字段。返回 (data, count_enriched)."""
    enriched = 0
    for d in data.get("dialogues", []):
        key = (d.get("book"), d.get("unit_no"), d.get("scene"), d.get("function"))
        note = NOTES.get(key)
        if not note:
            continue
        # 顶层字段
        d["scene_desc"] = note["scene_desc"]
        d["scene_icon"] = note["scene_icon"]
        d["usage_tags"] = note["usage_tags"]
        d["grammar_points"] = note["grammar_points"]
        d["vocab_cards"] = note["vocab_cards"]
        d["sentence_patterns"] = note["sentence_patterns"]

        # 给 turns 加动作/表情 + 角色标签
        # 用简单规则匹配：Mike = A（自我介绍）, Sarah = B
        for t in d.get("turns", []):
            speaker = t.get("speaker") or t.get("s")
            en = t.get("en", "")
            if speaker == "A":
                t.setdefault("emo", "👋 挥手")
                t.setdefault("role_label", "自我介绍")
            elif speaker == "B":
                t.setdefault("emo", "🙂 微笑点头")
                t.setdefault("role_label", "回应问候")
            # 高亮关键词：从 vocab_cards 里挑
            if not t.get("highlights"):
                hits = []
                for c in note["vocab_cards"]:
                    if re.search(r"\b" + re.escape(c["word"]) + r"\b", en, re.IGNORECASE):
                        hits.append(c["word"])
                t["highlights"] = hits
        enriched += 1
    return data, enriched


def patch_json():
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    data, n = find_and_enrich(data)
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"[enrich] {JSON_PATH.relative_to(ROOT)}  enriched={n}")
    return n


def patch_htmls():
    """把 JSON 里的 enriched dialogues 同步回各 english/*.html 的 window.DATA。"""
    # 先从 JSON 拿 enriched dialogues
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    enriched = {(d.get("book"), d.get("unit_no"), d.get("scene"), d.get("function")): d
                for d in data.get("dialogues", []) if d.get("vocab_cards")}
    print(f"[enrich] 已标注 dialogue 数={len(enriched)}")

    count_total = 0
    for html in sorted(HTML_GLOB.parent.glob(HTML_GLOB.name)):
        s = html.read_text(encoding="utf-8")
        # 定位 <script>window.DATA=JSON;</script>，整段取出再解析回写。
        m = re.search(r"window\.DATA\s*=\s*(.+?)\s*;\s*</script>", s, re.DOTALL)
        if not m:
            continue
        obj = json.loads(m.group(1))
        changed = False
        for d in obj.get("dialogues", []):
            key = (d.get("book"), d.get("unit_no"), d.get("scene"), d.get("function"))
            if key in enriched and not d.get("vocab_cards"):
                d.update(enriched[key])
                changed = True
                count_total += 1
        if changed:
            new_json = json.dumps(obj, ensure_ascii=False)
            new_s = s[:m.start(1)] + new_json + s[m.end(1):]
            html.write_text(new_s, encoding="utf-8")
            print(f"  \u2713 {html.name}")
    print(f"[enrich] 共更新了 {count_total} 处 dialogues 条目（跨 8 个页面文件）")


if __name__ == "__main__":
    patch_json()
    if "--html" in sys.argv:
        patch_htmls()
