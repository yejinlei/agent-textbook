# -*- coding: utf-8 -*-
"""
Build upgraded math textbook data from D:\src\books\数学\OCR
Integrates all 12 volumes, 104 units, 1,349 textbook figures,
Markdown full-text, KaTeX formulas, and preserves existing drills/problems/kb.
"""

import os
import re
import json

OCR_DIR = r"D:\src\books\数学\OCR"
OLD_JSON = r"pages\data\math.json.bak"
OUT_JSON = r"pages\data\math.json"

book_names = [
    "一年级上册", "一年级下册", "二年级上册", "二年级下册",
    "三年级上册", "三年级下册", "四年级上册", "四年级下册",
    "五年级上册", "五年级下册", "六年级上册", "六年级下册"
]

vols = sorted([d for d in os.listdir(OCR_DIR) if re.match(r"^\d{2}_", d)])
vol_to_book = {vols[i]: book_names[i] for i in range(len(vols))}

# Load old math data
old_data = {}
if os.path.exists(OLD_JSON):
    with open(OLD_JSON, "r", encoding="utf-8") as f:
        old_data = json.load(f)

old_units = old_data.get("units", [])

def clean_unit_title(raw):
    s = raw.strip()
    # Normalize spaces in known words like "四 则运算", "三 角形"
    s = s.replace("四 则运算", "四则运算").replace("三 角形", "三角形")
    # Strip "第X单元" prefix if any
    s = re.sub(r"^第[一二三四五六七八九十\d]+单元[·\s]*", "", s)
    # Strip leading Chinese number ONLY if followed by digit, space, dot, or ideographic comma
    s = re.sub(r"^[一二三四五六七八九十]+(?=[\d\s、.点])[\s、.点]*", "", s)
    # Clean whitespace in numbers
    s = re.sub(r"(\d)\s+([亿万])", r"\1\2", s)
    s = re.sub(r"(\d)\s+以内", r"\1以内", s)
    s = re.sub(r"～\s+", "～", s)
    s = re.sub(r"\s+～", "～", s)
    return s.strip()

def match_old_unit(book, title):
    clean_title = clean_unit_title(title)
    best = None
    best_score = 0
    for u in old_units:
        if u.get("book") != book:
            continue
        u_clean = clean_unit_title(u.get("title", ""))
        if clean_title == u_clean:
            return u
        # Substring match
        score = 0
        if clean_title in u_clean or u_clean in clean_title:
            score = len(set(clean_title) & set(u_clean))
        if score > best_score:
            best_score = score
            best = u
    if best_score >= 3:
        return best
    return None

def classify_domain(title, old_u=None):
    if old_u and old_u.get("domain"):
        return old_u["domain"]
    t = title
    if any(k in t for k in ["立体图形", "平面图形", "图形", "观察物体", "角", "面积", "平行四边形", "梯形", "三角形", "长方体", "正方体", "圆柱", "圆锥", "位置", "圆"]):
        return "geo"
    if any(k in t for k in ["统计", "条形", "折线", "可能性", "收集与整理", "平均数"]):
        return "stat"
    if any(k in t for k in ["游戏", "综合与实践", "实践", "广角", "生活", "密铺", "探索图形", "编码", "导游", "尺子", "时间在哪里", "连环画", "称象", "年月日", "营养午餐", "通知", "找次品", "生命之源", "体育", "自行车", "鸽巢", "寻找宝藏", "购物街", "1亿有多大"]):
        return "prac"
    return "num"

all_units = []

for v_idx, vol in enumerate(vols):
    book = vol_to_book[vol]
    vol_path = os.path.join(OCR_DIR, vol)
    
    # Sort files numerically by P<num>
    md_files = [f for f in os.listdir(vol_path) if f.endswith(".md") and f != "README.md"]
    def get_pnum(fn):
        m = re.search(r"^P(\d+)", fn)
        return int(m.group(1)) if m else 999
    md_files.sort(key=get_pnum)
    
    for u_idx, md_file in enumerate(md_files):
        md_path = os.path.join(vol_path, md_file)
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        m_title = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        raw_title = m_title.group(1).strip() if m_title else md_file.replace(".md", "")
        short_title = clean_unit_title(raw_title)
        if not short_title:
            short_title = raw_title
            
        m_prange = re.search(r"第\s*(\d+)\s*页\s*至\s*第\s*(\d+)\s*页", content)
        page_from = int(m_prange.group(1)) if m_prange else get_pnum(md_file)
        page_to = int(m_prange.group(2)) if m_prange else page_from
        
        m_pdfrange = re.search(r"PDF\s*第\s*(\d+)\s*页\s*至\s*第\s*(\d+)\s*页", content)
        pdf_from = int(m_pdfrange.group(1)) if m_pdfrange else 0
        pdf_to = int(m_pdfrange.group(2)) if m_pdfrange else 0
        
        # Collect figure filenames
        figs = re.findall(r"figures/(p\d+)\.(?:png|webp)", content, re.IGNORECASE)
        figs = [f.lower() + ".webp" for f in figs]
        
        # Match old unit
        old_u = match_old_unit(book, raw_title)
        domain = classify_domain(raw_title, old_u)
        
        unit_obj = {
            "book": book,
            "vol_dir": vol,
            "unit_no": u_idx + 1,
            "title": short_title,
            "full_title": raw_title,
            "domain": domain,
            "page_from": page_from,
            "page_to": page_to,
            "pdf_from": pdf_from,
            "pdf_to": pdf_to,
            "md_file": md_file,
            "figures": figs,
            "figures_count": len(figs),
            "raw_text": content,
            "points": old_u.get("points", []) if old_u else [],
            "literacy": old_u.get("literacy", []) if old_u else [],
            "kb": old_u.get("kb", None) if old_u else None,
            "formulas": old_u.get("formulas", []) if old_u else [],
            "examples": old_u.get("examples", []) if old_u else [],
            "drills": old_u.get("drills", []) if old_u else [],
            "problems": old_u.get("problems", []) if old_u else []
        }
        all_units.append(unit_obj)

print(f"Total units built: {len(all_units)} across {len(vols)} books.")

# Construct output math data
new_math_data = {
    "domains": old_data.get("domains", [
        {"key": "num", "name": "数与代数", "desc": "数的认识与运算、式与方程、比和比例"},
        {"key": "geo", "name": "图形与几何", "desc": "图形的认识与测量、图形的位置与运动"},
        {"key": "stat", "name": "统计与概率", "desc": "数据的收集、整理与分析、可能性"},
        {"key": "prac", "name": "综合与实践", "desc": "主题活动、项目学习、生活应用与广角"}
    ]),
    "books": book_names,
    "total_units": len(all_units),
    "total_figures": sum(u["figures_count"] for u in all_units),
    "units": all_units,
    "measures": old_data.get("measures", []),
    "n_maps": old_data.get("n_maps", []),
    "n_derived_maps": old_data.get("n_derived_maps", []),
    "drills": old_data.get("drills", []),
    "problems": old_data.get("problems", []),
    "keypoints": old_data.get("keypoints", []),
    "life": old_data.get("life", [])
}

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(new_math_data, f, ensure_ascii=False, indent=2)

out_sz = os.path.getsize(OUT_JSON)
print(f"Saved {OUT_JSON}: {out_sz / 1024 / 1024:.2f} MB")
