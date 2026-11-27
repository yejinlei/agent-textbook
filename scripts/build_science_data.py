# -*- coding: utf-8 -*-
"""
Build science data from D:\src\books\科学\OCR
Parses all 12 volumes, 36 units, and 260 lessons into pages/data/science.json
"""

import os
import re
import json

OCR_DIR = r"D:\src\books\科学\OCR"
SIM_DIR = os.path.join(OCR_DIR, "simulations")
KG_PATH = os.path.join(OCR_DIR, "catalogs", "science_knowledge_graph_full.json")
OUTPUT_PATH = "pages/data/science.json"

with open(KG_PATH, "r", encoding="utf-8") as f:
    kg = json.load(f)

c260 = kg.get("curriculum_260_lessons", [])
c260_map = {}
for item in c260:
    # Key by (grade_dir, unit_file, lesson_num) and (grade_dir, lesson_title)
    c260_map[(item["grade_dir"], item["lesson_title"])] = item
    c260_map[(item["grade_dir"], item["unit_file"], item["lesson_num"])] = item

vols = sorted([d for d in os.listdir(OCR_DIR) if re.match(r"^\d{2}_", d)])

book_names = [
    "一年级上册", "一年级下册", "二年级上册", "二年级下册",
    "三年级上册", "三年级下册", "四年级上册", "四年级下册",
    "五年级上册", "五年级下册", "六年级上册", "六年级下册"
]

vol_to_book = {vols[i]: book_names[i] for i in range(len(vols))}

all_books = []
all_units = []
all_lessons = []

# Section extraction regexes
sec_regex = {
    "focus": r"#### 🎯 聚焦\s*\n(.*?)(?=\n#### |\n### |\n## |\Z)",
    "exploration": r"#### 🔬 探索\s*\n(.*?)(?=\n#### |\n### |\n## |\Z)",
    "discussion": r"#### 💬 研讨\s*\n(.*?)(?=\n#### |\n### |\n## |\Z)",
    "expansion": r"#### 🚀 拓展\s*\n(.*?)(?=\n#### |\n### |\n## |\Z)",
    "frontier": r"- 🌐 \*\*前沿科技[^*]*\*\*：(.*?)(?=\n- |\n#### |\n### |\n## |\Z)",
    "big_concept": r"- 🧠 \*\*跨学科大概念[^*]*\*\*：(.*?)(?=\n- |\n#### |\n### |\n## |\Z)",
    "misconception": r"- ⚠️ \*\*前概念迷思纠偏\*\*：(.*?)(?=\n- |\n#### |\n### |\n## |\Z)",
}

lesson_counter = 0

for v_idx, vol in enumerate(vols):
    book_name = vol_to_book[vol]
    vol_path = os.path.join(OCR_DIR, vol)
    md_files = sorted([f for f in os.listdir(vol_path) if f.endswith(".md") and f != "README.md"])
    
    vol_units = []
    
    for u_idx, md_file in enumerate(md_files):
        md_path = os.path.join(vol_path, md_file)
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Unit title: first # header
        m_utitle = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        unit_title = m_utitle.group(1).strip() if m_utitle else md_file.replace(".md", "")
        # Unit page range
        m_uprange = re.search(r"第\s*(\d+)\s*页\s*至\s*第\s*(\d+)\s*页", content)
        page_start = int(m_uprange.group(1)) if m_uprange else 0
        page_end = int(m_uprange.group(2)) if m_uprange else 0
        
        unit_obj = {
            "book": book_name,
            "vol_dir": vol,
            "unit_no": u_idx + 1,
            "unit_title": unit_title,
            "page_start": page_start,
            "page_end": page_end,
            "md_file": md_file,
            "lessons_count": 0
        }
        
        # Split lessons: by ## \d+\.
        parts = re.split(r"\n(?=## \d+\. )", content)
        # parts[0] is unit header / nav
        
        unit_lessons = []
        
        for part in parts[1:]:
            m_ltitle = re.match(r"## (\d+)\.\s*([^\n]+)", part)
            if not m_ltitle:
                continue
            
            l_num = int(m_ltitle.group(1))
            l_title = m_ltitle.group(2).strip()
            
            # Match with kg
            kg_item = c260_map.get((vol, md_file, l_num)) or c260_map.get((vol, l_title)) or {}
            
            # Start page of lesson
            m_lpage = re.search(r"### \[第\s*(\d+)\s*页\]", part)
            l_page = int(m_lpage.group(1)) if m_lpage else kg_item.get("start_page", 0)
            
            # Extract sections
            sections = {}
            for k, reg in sec_regex.items():
                m_sec = re.search(reg, part, re.DOTALL)
                if m_sec:
                    sections[k] = m_sec.group(1).strip()
            
            # Figures in lesson
            figs = re.findall(r"!\[(.*?)\]\((figures/[^)]+)\)", part)
            
            # Simulation filename
            sim_file = kg_item.get("sim_filename", "")
            if not sim_file and kg_item.get("code"):
                sim_file = f"sim_{kg_item['code']}.html"
            
            lesson_counter += 1
            lesson_id = f"sci_{v_idx+1:02d}_u{u_idx+1:02d}_l{l_num:02d}"
            
            lesson_obj = {
                "id": lesson_id,
                "lesson_idx": lesson_counter,
                "book": book_name,
                "vol_dir": vol,
                "unit_no": u_idx + 1,
                "unit_title": unit_title,
                "lesson_no": l_num,
                "title": l_title,
                "page": l_page,
                "domain": kg_item.get("domain", "physics"),
                "domain_cn": kg_item.get("domain_cn", "物质科学"),
                "sim_file": sim_file,
                "code": kg_item.get("code", ""),
                "sections": sections,
                "figures": [f[1] for f in figs],
                "raw_text": part.strip()
            }
            
            unit_lessons.append(lesson_obj)
            all_lessons.append(lesson_obj)
        
        unit_obj["lessons_count"] = len(unit_lessons)
        all_units.append(unit_obj)
        vol_units.append(unit_obj)
    
    all_books.append({
        "book": book_name,
        "vol_dir": vol,
        "units": vol_units,
        "lessons_count": sum(u["lessons_count"] for u in vol_units)
    })

# Collect master simulations
master_sims = [
    {"file": "circuit_sandbox.html", "title": "闭合回路与电路沙盒", "domain": "physics", "domain_cn": "物质科学", "desc": "电池、灯泡、开关、导线自由组装电路，实时呈现闭合回路电流仿真。"},
    {"file": "pendulum_lab.html", "title": "单摆周期与等时性受控实验", "domain": "physics", "domain_cn": "物质科学", "desc": "摆长、摆锤质量、摆幅三变量精确受控实验，探究钟摆周期的唯一决定因素。"},
    {"file": "virtual_microscope.html", "title": "高倍虚拟光学显微镜", "domain": "biology", "domain_cn": "生命科学", "desc": "粗准焦螺旋、细准焦螺旋、目镜物镜倍率切换，观察洋葱表皮细胞与气孔微观结构。"},
    {"file": "buoyancy_boat_lab.html", "title": "浮力与橡皮泥造船工程", "domain": "engineering", "domain_cn": "技术与工程", "desc": "排水体积计算与橡皮泥船底面积优化，探究浮力原理与最大载重测试。"},
    {"file": "mechanics_lever.html", "title": "杠杆平衡与力矩力臂探究", "domain": "physics", "domain_cn": "物质科学", "desc": "支点、用力点、阻力点自由滑动，探究省力杠杆、费力杠杆与等臂天平的受力平衡。"},
    {"file": "optics_light_lab.html", "title": "光的反射定律与潜望镜光路", "domain": "physics", "domain_cn": "物质科学", "desc": "入射角等于反射角动态激光光路模拟，自由转动双平面镜搭建真实潜望镜。"},
    {"file": "optics_prism_lab.html", "title": "牛顿三棱镜七彩色散光具座", "domain": "physics", "domain_cn": "物质科学", "desc": "白光经三棱镜发生色散分解为红橙黄绿蓝靛紫七色光谱，凸透镜成像规律仿真。"},
    {"file": "solar_system_gravity.html", "title": "牛顿大炮与卫星轨道引力场", "domain": "earth", "domain_cn": "地球与宇宙", "desc": "八大行星引力场与卫星环绕轨道受控模拟，发射速度与椭圆轨道动力学。"},
    {"file": "space_eclipse_constellation_lab.html", "title": "日食月食本影全景与四季星空", "domain": "earth", "domain_cn": "地球与宇宙", "desc": "地日月三球空间相对位置、日食月食本影半影视差与北斗七星四季星斗旋转。"},
    {"file": "tower_engineering_lab.html", "title": "塔台结构工程力学与抗风抗震", "domain": "engineering", "domain_cn": "技术与工程", "desc": "三角形稳固框架、重心高度控制与地震台震动测试，体验小小工程师塔台建造全流程。"},
    {"file": "acoustics_oscilloscope.html", "title": "声波与频率示波器", "domain": "physics", "domain_cn": "物质科学", "desc": "音叉、吉他琴弦振动幅度与频率变化，动态波形图实时呈现声音高低强弱。"},
    {"file": "meteorology_atmosphere_lab.html", "title": "大气压强与风成因对流实验室", "domain": "earth", "domain_cn": "地球与宇宙", "desc": "冷暖空气对流、温差产生气压梯度力进而形成自然风的全真模拟。"},
    {"file": "gas_combustion_lab.html", "title": "气体生成与蜡烛阶梯燃烧灭火", "domain": "physics", "domain_cn": "物质科学", "desc": "小苏打与白醋反应生成二氧化碳，下层蜡烛先灭证实二氧化碳密度大于空气且不支持燃烧。"},
    {"file": "mineral_soil_lab.html", "title": "矿物晶体与土壤成分全景实验室", "domain": "earth", "domain_cn": "地球与宇宙", "desc": "石英、长石、云母硬度条痕测试与土壤颗粒沉积沉降分层实验。"},
    {"file": "biodiversity_genetics_lab.html", "title": "生物多样性二歧分类与性状编码", "domain": "biology", "domain_cn": "生命科学", "desc": "双眼皮、耳垂附着、卷舌性状二歧编码与校园植物检索表互动实践。"}
]

domains = [
    {"key": "all", "name": "全部领域", "desc": "覆盖小学科学四大领域全景知识"},
    {"key": "physics", "name": "物质科学", "desc": "物质的性质、位置与运动、能的形式与转换"},
    {"key": "biology", "name": "生命科学", "desc": "生命的结构与功能、生命系统的延续与演化"},
    {"key": "earth", "name": "地球与宇宙", "desc": "地球系统与地表变化、人类生存的宇宙环境"},
    {"key": "engineering", "name": "技术与工程", "desc": "工程设计与制作、工具与社会可持续发展"}
]

data = {
    "books": [b["book"] for b in all_books],
    "domains": domains,
    "book_details": all_books,
    "units": all_units,
    "lessons": all_lessons,
    "master_simulations": master_sims
}

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Successfully generated {OUTPUT_PATH}!")
print(f"Total Books: {len(all_books)}")
print(f"Total Units: {len(all_units)}")
print(f"Total Lessons: {len(all_lessons)}")
print(f"Master Simulations: {len(master_sims)}")
