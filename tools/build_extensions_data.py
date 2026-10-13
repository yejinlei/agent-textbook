"""把 pairings.json + catalog.json + taxonomy.json 打包成 pages/extensions/index.html（元数据内联）。

正文单独走 tools/build_extensions_texts.py 生成 texts/{id}.js，主 HTML 保持轻量。
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "data" / "readings"
DIR = ROOT / "pages" / "extensions"
TPL = DIR / "_template.html"
OUT_HTML = DIR / "index.html"
OUT_JSON = DIR / "_data.json"

pairings = json.loads((R / "pairings.json").read_text(encoding="utf-8"))
catalog = json.loads((R / "catalog.json").read_text(encoding="utf-8"))
roles = json.loads((R / "extension_roles.json").read_text(encoding="utf-8"))
taxonomy = json.loads((R / "taxonomy.json").read_text(encoding="utf-8"))
idx = json.loads((R / "index.json").read_text(encoding="utf-8"))

# 索引：id -> {word_count, reading_time_min, chapters_count, ...}
idx_map = {r["id"]: r for r in idx["readings"]}

# taxonomy 里所有维度的 label 映射，扁平成 {dim_name: {value: {zh, desc?}}}
dims = taxonomy["dimensions"]

def enum_values(dim):
    """把 dimension.values 或 .buckets 或 .bands 转成 {val: desc}"""
    v = dim.get("values") or {}
    if isinstance(v, list):
        return {x: "" for x in v}
    return dict(v)

label_map = {}
for dim_name, dim in dims.items():
    entries = enum_values(dim)
    label_map[dim_name] = {
        k: (v if isinstance(v, str) else (v.get("label", "")))
        for k, v in entries.items()
    }

# lexile / word_count_bucket 的 label 在 bands/buckets 里
label_map["lexile_band"] = {
    k: f"{v['min']}–{v['max']}L"
    for k, v in (dims["lexile"].get("bands") or {}).items()
}
label_map["word_buckets"] = {
    k: (f"{v['min']}–{v['max']}" if v.get("max") else f"{v['min']}+")
    for k, v in (dims["word_count_bucket"].get("buckets") or {}).items()
}
label_map["cultural_origins"] = {x: "" for x in (dims["cultural_origin"].get("values") or [])}
label_map["topics"] = {x: "" for x in (dims["topic"].get("primary_allowed") or [])}
# topic 有些是二级点号形式，如 nature.cosmic，直接原样展示
for b in catalog["books"]:
    pt = b.get("primary_topic")
    if pt and pt not in label_map["topics"]:
        label_map["topics"][pt] = ""

# theme / setting / skill 的 values 在 dims.themes.values 等 dict 里
for src_dim in ("themes", "settings", "target_skill"):
    dim = dims.get(src_dim) or {}
    vs = dim.get("values") or {}
    key = "themes" if src_dim == "themes" else ("settings" if src_dim == "settings" else "skills")
    for k, v in vs.items():
        label_map.setdefault(key, {})[k] = v if isinstance(v, str) else (v.get("zh",""))
# text_type
for k, v in (dims["text_type"].get("values") or {}).items():
    label_map.setdefault("text_types", {})[k] = v
# time_period
for k, v in (dims["time_period"].get("values") or {}).items():
    label_map.setdefault("time_periods", {})[k] = v

books = []
for b in catalog["books"]:
    f = b.get("facets", {})
    inf = idx_map.get(b["id"], {})
    lex = f.get("lexile") or {}
    books.append({
        "id": b["id"],
        "title": b.get("title") or b["id"],
        "author": b.get("author"),
        "primary_topic": b.get("primary_topic"),
        "text_type": f.get("text_type"),
        "word_count_bucket": f.get("word_count_bucket"),
        "word_count": inf.get("word_count"),
        "reading_time_min": inf.get("reading_time_min"),
        "chapters_count": inf.get("chapters_count"),
        "grade": f.get("grade") or [],
        "lexile": lex,
        "lexile_band": lex.get("band"),
        "themes": f.get("themes") or [],
        "settings": f.get("settings") or [],
        "cultural_origin": f.get("cultural_origin"),
        "time_period": f.get("time_period"),
        "target_skills": f.get("target_skills") or [],
        "text_role": f.get("text_role") or [],
        "summary": b.get("summary") or b.get("blurb") or "",
    })

out = {
    "updated": date.today().isoformat(),
    "stats": pairings.get("_counts", {}),
    "roles": roles["roles"],
    "books": books,
    "pairings": pairings["pairings"],
    "facets_labels": label_map,
}

DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

# 渲染 index.html：把 payload 注入 __PAYLOAD__ 占位
tpl = TPL.read_text(encoding="utf-8")
payload = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
payload_safe = payload.replace("</", "<\\/")
html = tpl.replace("__PAYLOAD__", payload_safe)
OUT_HTML.write_text(html, encoding="utf-8")

n_pairs = len(out["pairings"])
n_books = len(out["books"])
n_units = len({p["section_id"] for p in out["pairings"]})
print(f"[build_extensions_data] → {OUT_HTML}  ({html.__len__()/1024:.0f} KB)")
print(f"  books={n_books}  pairings={n_pairs}  distinct_units={n_units}")
