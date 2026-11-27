# -*- coding: utf-8 -*-
"""
Generate pages/science/index.html and pages/science/simulations.html
Updates navigation in all HTML pages across the project.
"""

import os
import json
import glob

DATA_PATH = "pages/data/science.json"
with open(DATA_PATH, "r", encoding="utf-8") as f:
    science_data = json.load(f)

json_str = json.dumps(science_data, ensure_ascii=False)

os.makedirs("pages/science", exist_ok=True)

# 1. Generate pages/science/index.html (课文文本)
text_html = f"""<!DOCTYPE html>
<html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>科学 · 课文文本 · 小学知识大全</title>
<link rel="stylesheet" href="../assets/app.css?v=a63fbb0a"></head>
<body data-page="science-text" data-base="../">
<header>
  <span class="seal">课本</span>
  <h1>小学知识大全</h1>
  <div class="sub">按教学目标编排 · 每条都来自教材，可核对到册次与页码</div>
</header>
<div class="wrap">
  <aside class="side">
    <p class="sidet">学科</p>
    <nav><a href="../index.html">总览</a><a href="../chinese/index.html">语文</a><a href="../math/index.html">数学</a><a href="../english/index.html">英语</a><a href="../science/index.html" class="on">科学</a></nav>
    <p class="sidet">专题</p><nav class="sub"><a href="index.html" class="on">课文文本</a><a href="simulations.html">科学实验</a></nav>
  </aside>
  <main>
<h2>科学 · 课文文本</h2><p class="lead">教科版全套12册小学科学教科书原版课文，涵盖生命科学、物质科学、地球与宇宙、技术与工程四大核心领域。每课完整保留聚焦、探索、研讨、拓展全环节，内嵌配套微仿真实验，并提供中科院前沿科技拓展与迷思纠偏。</p>
<div id="app"></div>
  </main>
</div>
<script>window.DATA={json_str};</script>
<script src="../assets/app.js?v=a63fbb0a"></script>
</body></html>
"""

with open("pages/science/index.html", "w", encoding="utf-8") as f:
    f.write(text_html)
print("Generated pages/science/index.html")

# 2. Generate pages/science/simulations.html (科学实验)
sim_html = f"""<!DOCTYPE html>
<html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>科学 · 科学实验 · 小学知识大全</title>
<link rel="stylesheet" href="../assets/app.css?v=a63fbb0a"></head>
<body data-page="science-simulations" data-base="../">
<header>
  <span class="seal">课本</span>
  <h1>小学知识大全</h1>
  <div class="sub">按教学目标编排 · 每条都来自教材，可核对到册次与页码</div>
</header>
<div class="wrap">
  <aside class="side">
    <p class="sidet">学科</p>
    <nav><a href="../index.html">总览</a><a href="../chinese/index.html">语文</a><a href="../math/index.html">数学</a><a href="../english/index.html">英语</a><a href="../science/index.html" class="on">科学</a></nav>
    <p class="sidet">专题</p><nav class="sub"><a href="index.html">课文文本</a><a href="simulations.html" class="on">科学实验</a></nav>
  </aside>
  <main>
<h2>科学 · 科学实验</h2><p class="lead">小学科学 287 个全景互动微仿真中心。包含 15 个大师级物理/化学/生物/工程虚拟沙盒实验室，以及覆盖 1-6 年级 260 节课的全量真实验微仿真。支持受控变量调节、动态示波、光路折射、力矩平衡与三维引力模拟，点击即可在台运行或全屏操作。</p>
<div id="app"></div>
  </main>
</div>
<script>window.DATA={json_str};</script>
<script src="../assets/app.js?v=a63fbb0a"></script>
</body></html>
"""

with open("pages/science/simulations.html", "w", encoding="utf-8") as f:
    f.write(sim_html)
print("Generated pages/science/simulations.html")

# 3. Update navigation in all other HTML pages
# 3.1 pages/index.html
with open("pages/index.html", "r", encoding="utf-8") as f:
    idx_content = f.read()

# Add 科学 link to index nav if not present
old_nav = '<a href="english/index.html">英语</a></nav>'
new_nav = '<a href="english/index.html">英语</a><a href="science/index.html">科学</a></nav>'
if old_nav in idx_content:
    idx_content = idx_content.replace(old_nav, new_nav)
    print("Updated pages/index.html nav")

# Add 科学 card to 规模 grid
old_card = '<div class="card">英语 词汇 <big>1621</big> · 句型 <big>771</big> · 拼读 <big>251</big> · 歌谣 <big>66</big></div>'
new_card = '<div class="card">英语 词汇 <big>1621</big> · 句型 <big>771</big> · 拼读 <big>251</big> · 歌谣 <big>66</big></div>\n<div class="card">科学 册次 <big>12</big> 册 · 单元 <big>36</big> 个 · 课文 <big>260</big> 篇 · 仿真实验 <big>287</big> 个</div>'
if old_card in idx_content and "科学 册次" not in idx_content:
    idx_content = idx_content.replace(old_card, new_card)
    print("Updated pages/index.html stats card")

with open("pages/index.html", "w", encoding="utf-8") as f:
    f.write(idx_content)

# 3.2 Update all subpages: chinese, math, english
all_sub_pages = glob.glob("pages/**/*.html", recursive=True)
updated_count = 0
for page_file in all_sub_pages:
    if "science" in page_file or "index.html" == os.path.basename(page_file) and os.path.dirname(page_file) == "pages":
        continue
    with open(page_file, "r", encoding="utf-8") as f:
        c = f.read()
    
    old_sub_nav = '<a href="../english/index.html">英语</a></nav>'
    new_sub_nav = '<a href="../english/index.html">英语</a><a href="../science/index.html">科学</a></nav>'
    if old_sub_nav in c:
        c = c.replace(old_sub_nav, new_sub_nav)
        with open(page_file, "w", encoding="utf-8") as f:
            f.write(c)
        updated_count += 1

print(f"Updated navigation in {updated_count} subpages!")
