# -*- coding: utf-8 -*-
"""
Build science data from D:\src\books\科学\OCR
Parses all 12 volumes, 36 units, and 260 lessons into pages/data/science.json
Includes opening textbook illustrations and all page figures for every lesson!
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

# Flexible section extraction regexes
sec_regex = {
    "focus": r"####\s*🎯\s*(?:聚焦|任务|明确任务)[：: \s]*(.*?)(?=\n#### |\n### |\n## |\Z)",
    "exploration": r"####\s*🔬\s*(?:探索|制作|观察|实验)[：: \s]*(.*?)(?=\n#### |\n### |\n## |\Z)",
    "discussion": r"####\s*💬\s*(?:研讨|讨论|交流)[：: \s]*(.*?)(?=\n#### |\n### |\n## |\Z)",
    "expansion": r"####\s*🚀\s*(?:拓展|实践)[：: \s]*(.*?)(?=\n#### |\n### |\n## |\Z)",
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
        
        # Split lessons: pattern that includes preceding ### [第 X 页] and opening figure
        parts = re.split(r"(?=\n*###\s*\[第\s*\d+\s*页\]\s*\n+!\[[^\]]+\]\([^\)]+\)\s*\n+##\s*\d+\.\s+)", content)
        
        unit_lessons = []
        
        for part in parts[1:]:
            # Drop unit summary/reading from lesson end
            sub = re.split(r"\n(?=##\s+单元小结|##\s+科学阅读)", part)[0].strip()
            m_ltitle = re.search(r"##\s*(\d+)\.\s*([^\n]+)", sub)
            if not m_ltitle:
                continue
            
            l_num = int(m_ltitle.group(1))
            l_title = m_ltitle.group(2).strip()
            
            # Match with kg
            kg_item = c260_map.get((vol, md_file, l_num)) or c260_map.get((vol, l_title)) or {}
            
            # Start page of lesson
            m_lpage = re.search(r"###\s*\[第\s*(\d+)\s*页\]", sub)
            l_page = int(m_lpage.group(1)) if m_lpage else kg_item.get("start_page", 0)
            
            # Extract sections
            sections = {}
            for k, reg in sec_regex.items():
                m_sec = re.search(reg, sub, re.DOTALL)
                if m_sec:
                    sections[k] = m_sec.group(1).strip()
                else:
                    sections[k] = ""
            
            # Extract figures
            figs = re.findall(r"!\[[^\]]+\]\((?:figures\/)?([^)]+)\)", sub)
            figs_webp = [os.path.splitext(f)[0] + ".webp" for f in figs]
            
            # Simulation file
            sim_file = kg_item.get("sim_filename", "")
            if not sim_file and kg_item.get("code"):
                sim_file = f"sim_{kg_item['code']}.html"
            
            code = kg_item.get("code", f"g{v_idx+1:02d}_u{u_idx+1:02d}_l{l_num:02d}")
            domain = kg_item.get("domain", "general")
            domain_cn_map = {
                "physics": "物质科学与物理",
                "chemistry": "物质变化与化学",
                "biology": "生命科学与生态",
                "earth": "地球与宇宙科学",
                "tech": "技术与工程实践",
                "general": "综合科学探究"
            }
            domain_cn = domain_cn_map.get(domain, "综合科学探究")
            
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
                "domain": domain,
                "domain_cn": domain_cn,
                "sim_file": sim_file,
                "code": code,
                "sections": sections,
                "figures": figs_webp,
                "raw_text": sub
            }
            
            unit_lessons.append(lesson_obj)
            all_lessons.append(lesson_obj)
            
        unit_obj["lessons_count"] = len(unit_lessons)
        all_units.append(unit_obj)
        vol_units.append(unit_obj)

print(f"Total parsed: {len(book_names)} books, {len(all_units)} units, {len(all_lessons)} lessons")

master_sims = [
    {"file": "circuit_sandbox.html", "title": "闭合回路与电路沙盒", "domain": "physics", "domain_cn": "物质科学", "desc": "电池、灯泡、开关、导线自由组装电路，实时呈现闭合回路电流仿真。"},
    {"file": "pendulum_lab.html", "title": "单摆周期与等时性受控实验", "domain": "physics", "domain_cn": "物质科学", "desc": "伽利略单摆受控实验，自主调节摆长、摆锤质量与摆幅，探究影响单摆周期的决定因素。"},
    {"file": "virtual_microscope.html", "title": "高倍虚拟光学显微镜", "domain": "biology", "domain_cn": "生命科学", "desc": "目镜、物镜倍率切换，粗细准焦螺旋调节，洋葱表皮细胞与水中微小生物微观世界交互观察。"},
    {"file": "buoyancy_boat_lab.html", "title": "浮力与橡皮泥造船工程", "domain": "physics", "domain_cn": "物质科学", "desc": "阿基米德浮力定律与排水量仿真，捏造不同船型测试载重量与沉浮稳定性。"},
    {"file": "mechanics_lever.html", "title": "杠杆平衡与力矩力臂探究", "domain": "physics", "domain_cn": "物质科学", "desc": "支点、用力点、阻力点力矩计算，实时模拟省力杠杆、费力杠杆与等臂天平的受力平衡。"},
    {"file": "optics_light_lab.html", "title": "光的反射定律与潜望镜光路", "domain": "physics", "domain_cn": "物质科学", "desc": "入射角等于反射角动态激光光路模拟，自由转动双平面镜搭建真实潜望镜。"},
    {"file": "optics_prism_lab.html", "title": "牛顿三棱镜七彩色散光具座", "domain": "physics", "domain_cn": "物质科学", "desc": "白光经三棱镜发生色散分解为红橙黄绿蓝靛紫七色光谱，凸透镜成像规律仿真。"},
    {"file": "solar_system_gravity.html", "title": "牛顿大炮与卫星轨道引力场", "domain": "earth", "domain_cn": "地球与宇宙", "desc": "八大行星引力场与卫星环绕轨道受控模拟，发射速度与椭圆轨道动力学。"},
    {"file": "space_eclipse_constellation_lab.html", "title": "日食月食本影全景与四季星空", "domain": "earth", "domain_cn": "地球与宇宙", "desc": "地日月三球空间相对位置、日食月食本影半影视差与北斗七星四季星斗旋转。"},
    {"file": "tower_engineering_lab.html", "title": "塔台结构工程力学与抗风抗震", "domain": "tech", "domain_cn": "技术与工程", "desc": "三角形稳固框架、重心高度控制与地震台震动测试，体验小小工程师塔台建造全流程。"},
    {"file": "acoustics_oscilloscope.html", "title": "声波与频率示波器", "domain": "physics", "domain_cn": "物质科学", "desc": "音叉、吉他琴弦振动幅度与频率变化，动态波形图实时呈现声音高低强弱。"},
    {"file": "meteorology_atmosphere_lab.html", "title": "大气压强与风成因对流实验室", "domain": "earth", "domain_cn": "地球与宇宙", "desc": "冷暖空气对流、温差产生气压梯度力进而形成自然风的全真模拟。"},
    {"file": "gas_combustion_lab.html", "title": "气体生成与蜡烛阶梯燃烧灭火", "domain": "physics", "domain_cn": "物质科学", "desc": "小苏打与白醋反应生成二氧化碳，下层蜡烛先灭证实二氧化碳密度大于空气且不支持燃烧。"},
    {"file": "mineral_soil_lab.html", "title": "矿物晶体与土壤成分全景实验室", "domain": "earth", "domain_cn": "地球与宇宙", "desc": "石英、长石、云母硬度条痕测试与土壤颗粒沉积沉降分层实验。"},
    {"file": "biodiversity_genetics_lab.html", "title": "生物多样性二歧分类与性状编码", "domain": "biology", "domain_cn": "生命科学", "desc": "双眼皮、耳垂附着、卷舌性状二歧编码与校园植物检索表互动实践。"}
]
print(f"Master simulations: {len(master_sims)}")

domains = [
    {"id": "physics", "name": "物质科学", "count": sum(1 for l in all_lessons if l["domain"] in ("physics", "chemistry"))},
    {"id": "biology", "name": "生命科学", "count": sum(1 for l in all_lessons if l["domain"] == "biology")},
    {"id": "earth", "name": "地球与宇宙", "count": sum(1 for l in all_lessons if l["domain"] == "earth")},
    {"id": "tech", "name": "技术与工程", "count": sum(1 for l in all_lessons if l["domain"] == "tech")},
]

final_data = {
    "subject": "science",
    "name": "小学科学",
    "total_books": len(book_names),
    "total_units": len(all_units),
    "total_lessons": len(all_lessons),
    "total_simulations": len(master_sims) + sum(1 for l in all_lessons if l["sim_file"]),
    "books": book_names,
    "domains": domains,
    "units": all_units,
    "lessons": all_lessons,
    "master_simulations": master_sims
}

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(final_data, f, ensure_ascii=False, indent=2)

print(f"Wrote {OUTPUT_PATH} ({os.path.getsize(OUTPUT_PATH) / 1024 / 1024:.2f} MB)")
