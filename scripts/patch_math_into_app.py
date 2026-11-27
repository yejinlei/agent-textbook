# -*- coding: utf-8 -*-
"""
Patch math textbook upgrades into app.js, app.css, and pages/math/index.html
"""

import os
import json
import re

MATH_DATA_PATH = "pages/data/math.json"
with open(MATH_DATA_PATH, "r", encoding="utf-8") as f:
    math_data = json.load(f)

json_str = json.dumps(math_data, ensure_ascii=False)

# 1. Update app.css
css_rules = """
/* ---- Math Textbook Specific Styles ---- */
.math-meta-bar {
  background: #f8fafc;
  border-left: 4px solid #0284c7;
  padding: 8px 14px;
  font-size: 13px;
  color: #475569;
  border-radius: 4px;
  margin-bottom: 16px;
}
.math-scene-note {
  background: #fdf4ff;
  border: 1px dashed #d946ef;
  border-radius: 8px;
  padding: 10px 16px;
  margin: 12px 0 16px;
  font-size: 13.5px;
  color: #86198f;
}
.math-sect-title {
  margin: 20px 0 10px;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
  border-left: 3px solid #f59e0b;
  padding-left: 10px;
}
.math-extra-section {
  margin-top: 24px;
  padding-top: 18px;
  border-top: 1px dashed #e2e8f0;
}
.math-extra-section .sect-label {
  font-size: 14.5px;
  font-weight: 700;
  color: #334155;
  margin-bottom: 12px;
}
.math-drill-details {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 16px;
}
.math-drill-details summary {
  cursor: pointer;
  font-weight: 600;
  color: #2563eb;
}
.prob-list {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.prob-card {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 12px 14px;
  font-size: 14px;
}
.prob-stem {
  color: #1e293b;
  margin-bottom: 6px;
}
.prob-steps {
  font-size: 13px;
  color: #475569;
  margin: 6px 0;
  padding-left: 8px;
  border-left: 2px solid #94a3b8;
}
.prob-ans {
  color: #166534;
  font-size: 13.5px;
  background: #f0fdf4;
  padding: 4px 8px;
  border-radius: 4px;
  display: inline-block;
  margin-top: 6px;
}
"""

for css_file in ["pages/assets/app.css", "src/agent_textbook/site/assets/app.css"]:
    if os.path.exists(css_file):
        with open(css_file, "r", encoding="utf-8") as f:
            content = f.read()
        if ".math-meta-bar" not in content:
            content += "\n" + css_rules
            with open(css_file, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Updated {css_file}")

# 2. Update app.js
format_math_code = """
  function formatMathMd(text, volDir) {
    if (!text) return "";
    var s = String(text);

    // 1. 移除顶层标题与 README 冗余
    s = s.replace(/^#\\s+[^\\n]*\\n*/gm, "");

    // 2. 格式化教材页码元数据条
    s = s.replace(/^>\\s*\\*\\*教材页码\\*\\*[：: ]*(.*?)$/gm, '<div class="math-meta-bar"><span>📖 $1</span></div>');

    // 3. 高清教学原书插图替换
    s = s.replace(/!\\[(.*?)\\]\\((?:figures\\/)?([^)]+)\\.(?:png|jpg|webp|jpeg)\\)/gi, function (match, caption, pName) {
      var vol = volDir || "";
      var imgUrl = "figures/" + encodeURIComponent(vol) + "/" + pName + ".webp";
      return '<figure class="sci-figure"><img src="' + imgUrl + '" alt="' + esc(caption) + '" loading="lazy"><figcaption>📐 ' + esc(caption) + '</figcaption></figure>';
    });

    // 4. 课本分界线
    s = s.replace(/###\\s*\\[第\\s*(\\d+)\\s*页\\]/g, '<div class="sci-page-divider"><span>📘 义务教育教科书 · 第 $1 页</span></div>');

    // 5. 课堂情境说明
    s = s.replace(/\\*\\((本页主要为[^\\)]*)\\)\\*/g, '<div class="math-scene-note">🎨 $1（课本教学活动详见上方插图）</div>');

    // 6. KaTeX 公式解析与优化
    s = s.replace(/([0-9a-zA-Z\\+\\-\\*\\/\\=\\>\\<·~～÷×−\\s]{1,30})?（KaTeX:\\s*\\$([^$]+)\\$）/g, function (match, p1, p2) {
      return ' <span class="fbox"><span class="tex">' + tex(p2) + '</span></span> ';
    });
    s = s.replace(/\\$([^$\\n]+)\\$/g, function (match, p1) {
      return ' <span class="tex">' + tex(p1) + '</span> ';
    });

    // 7. 移除 markdown 分割线
    s = s.replace(/^-{3,}\\s*$/gm, "");

    // 8. 粗体、斜体、行内代码
    s = s.replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>");
    s = s.replace(/\\*([^*]+)\\*/g, "<em>$1</em>");
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");

    // 9. 核心教学环节标记
    s = s.replace(/^(做一做|练习\\s*[一二三四五六七八九十\\d]+|整理和复习|你知道吗[？?]?|生活中的数学)\\s*$/gm, function (match, tag) {
      return '<div class="math-sect-title"><span>✍️ ' + esc(tag) + '</span></div>';
    });

    // 10. 列表
    s = s.replace(/^[-*]\\s+(.+)$/gm, '<li class="sci-list-item">$1</li>');
    s = s.replace(/((?:<li class="sci-list-item">.*<\\/li>\\s*)+)/g, '<ul class="sci-list">$1</ul>');
    s = s.replace(/^\\d+\\.\\s+(.+)$/gm, '<li class="sci-num-item">$1</li>');
    s = s.replace(/((?:<li class="sci-num-item">.*<\\/li>\\s*)+)/g, '<ol class="sci-num-list">$1</ol>');

    // 11. 分段渲染
    var lines = s.split(/\\n{2,}/);
    var out = lines.map(function (block) {
      block = block.trim();
      if (!block) return "";
      if (block.startsWith("<div") || block.startsWith("<figure") || block.startsWith("<ul") || block.startsWith("<ol") || block.startsWith("<h")) {
        return block;
      }
      return '<p class="para">' + block.replace(/\\n/g, "<br>") + '</p>';
    }).join("\\n");

    return out;
  }

  function examplesBlock(examples) {
    if (!examples || !examples.length) return "";
    return '<div class="prob-list">' + examples.map(function (ex, i) {
      return '<div class="prob-card"><div class="prob-stem"><b>例题 ' + (i + 1) + ' · ' + esc(ex.name || '') + '：</b>' +
        esc(ex.stem).replace(/\\n/g, '<br>') + '</div>' +
        (ex.steps && ex.steps.length ? '<div class="prob-steps">' + ex.steps.map(function (st) {
          return '<div>• ' + esc(st.text) + (st.latex ? ' (' + tex(st.latex) + ')' : '') + '</div>';
        }).join('') + '</div>' : '') +
        (ex.answer ? '<div class="prob-ans"><b>解题思路/答案：</b>' + esc(ex.answer) + '</div>' : '') +
        '</div>';
    }).join('') + '</div>';
  }
"""

math_unit_code = """  function mathUnit(u, idx) {
    var dom = D.domains.filter(function (d) { return d.key === u.domain; })[0] || {};
    var lit = (u.literacy || []).map(function (x) {
      return '<span class="tag">' + esc(x) + "</span>";
    }).join("");
    var h = '<div class="item"' + (idx != null ? ' id="mu' + idx + '"' : "") +
      '><div class="top"><span class="name">' + (u.unit_no ? '第' + esc(u.unit_no) + '单元 · ' : '') + esc(u.title) + "</span>" +
      where(u, u.page_from) + '<span class="tag d' +
      Math.max(0, D.domains.map(function (d) { return d.key; }).indexOf(u.domain)) +
      '">' + esc(dom.name) + "</span>" + lit + "</div>";

    // 1. 全新 OCR 课本原貌课文与教学插图
    if (u.raw_text) {
      h += '<div class="sci-textbook-card">' +
        '<div class="sci-textbook-card-head">' +
        '<span>📖 义务教育教科书 · 课本原文与教学例题（含原书彩图与做一做）</span>' +
        '<span class="sci-textbook-vol-tag">' + esc(u.book) + (u.page_from ? ' · P' + u.page_from + (u.page_to ? '-' + u.page_to : '') : '') + '</span>' +
        '</div>' +
        '<div class="sci-textbook-body math-textbook-body">' + formatMathMd(u.raw_text, u.vol_dir) + '</div>' +
        '</div>';
    } else if (u.sections && u.sections.length) {
      var np = u.sections.reduce(function (a, s) { return a + s.body.length; }, 0);
      h += "<details><summary>课本原文（" + np + " 段）</summary>" +
        '<div class="full">' + u.sections.map(function (s) {
          return '<p class="sect">' + esc(s.kind) + "</p>" +
            s.body.map(function (p) {
              return '<p class="para">' + esc(p) + "</p>";
            }).join("");
        }).join("") + "</div></details>";
    }

    // 2. 知识要点与思维引导
    if (u.points && u.points.length) {
      h += '<div class="math-extra-section">' +
        '<p class="sect-label">💡 课标核心知识点与思维引导（' + u.points.length + ' 条）</p>' +
        pts(u.points) + '</div>';
    }

    // 3. 结构化知识库 (KB)
    if (u.kb) {
      h += '<div class="math-extra-section"><p class="sect-label">🧠 结构化考点深析与易错辨析</p>' +
        '<div class="chips">' + M_EXTRA.map(function (e) {
          return kbHas(u.kb, e[0])
            ? '<span class="chip' + (ON[e[0]] ? " on" : "") + '" data-ex="' +
              e[0] + '">' + e[1] + "</span>" : "";
        }).join("") + "</div>" +
        M_EXTRA.map(function (e) {
          return kbHas(u.kb, e[0])
            ? '<div class="kb' + (ON[e[0]] ? " show" : "") + '" data-kb="' +
              e[0] + '">' + mBody(u.kb, e[0]) + "</div>" : "";
        }).join("") + '</div>';
    }

    // 4. 公式与算式速查
    if (u.formulas && u.formulas.length) {
      h += '<div class="math-extra-section"><p class="sect-label">🧮 核心公式与算式速查（' + u.formulas.length + " 条）</p>" +
        '<div class="fboxes">' + u.formulas.map(function (f) {
          return '<span class="fbox"><span class="tex">' + tex(f.latex) + "</span>" +
            '<span class="tag">' + esc(f.name) + "</span></span>";
        }).join("") + "</div></div>";
    }

    // 5. 典型例题精讲与思维步骤
    if (u.examples && u.examples.length) {
      h += '<div class="math-extra-section"><p class="sect-label">🎯 典型例题精讲与解题步骤（' + u.examples.length + " 道）</p>" +
        examplesBlock(u.examples) + '</div>';
    }

    // 6. 单元做一做与巩固练习
    var unitProblems = (D.problems || []).filter(function(p) {
      return p.book === u.book && (has(p.unit, u.title) || has(u.title, p.unit));
    });
    if (unitProblems.length > 0) {
      h += '<div class="math-extra-section"><details class="math-drill-details" open><summary>📝 单元课后巩固与自我检测（' + unitProblems.length + ' 道）</summary>' +
        '<div class="prob-list">' + unitProblems.slice(0, 10).map(function(p) {
          return '<div class="prob-card"><div class="prob-stem"><b>题 ' + esc(p.name || '') + '：</b>' + esc(p.stem) + '</div>' +
            (p.steps && p.steps.length ? '<div class="prob-steps">' + p.steps.map(function(st) { return '<div>• ' + esc(st.text) + '</div>'; }).join('') + '</div>' : '') +
            '<div class="prob-ans"><b>参考答案：</b>' + esc(p.answer) + '</div></div>';
        }).join('') + (unitProblems.length > 10 ? '<div class="prob-more"><a href="problem.html#' + encodeURIComponent(u.title) + '">查看全部 ' + unitProblems.length + ' 道习题 &gt;</a></div>' : '') +
        '</div></details></div>';
    }

    h += '</div>';
    return h;
  }
"""

for js_file in ["pages/assets/app.js", "src/agent_textbook/site/assets/app.js"]:
    if os.path.exists(js_file):
        with open(js_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Replace or inject formatMathMd & examplesBlock
        if "function formatMathMd" in content:
            # Replace existing formatMathMd block up to function formatScienceMd
            pos_fm = content.find("function formatMathMd")
            pos_sci = content.find("function formatScienceMd")
            if pos_fm != -1 and pos_sci != -1:
                content = content[:pos_fm] + format_math_code.strip() + "\n\n  " + content[pos_sci:]
        else:
            pos_sci = content.find("function formatScienceMd")
            if pos_sci != -1:
                content = content[:pos_sci] + format_math_code + "\n" + content[pos_sci:]
            else:
                content += "\n" + format_math_code
                
        # Replace mathUnit function
        pos_mu = content.find("function mathUnit(u, idx) {")
        if pos_mu != -1:
            pos_mu_end = content.find("\n  /* 单元目录：", pos_mu)
            if pos_mu_end != -1:
                content = content[:pos_mu] + math_unit_code + content[pos_mu_end:]
            else:
                pos_next = content.find("\n  function ", pos_mu + 30)
                if pos_next != -1:
                    content = content[:pos_mu] + math_unit_code + content[pos_next:]
                    
        with open(js_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated {js_file}")

# 3. Update pages/math/index.html and subpages
for p_file in ["pages/math/index.html", "pages/math/num.html", "pages/math/geo.html", "pages/math/stat.html", "pages/math/prac.html"]:
    if os.path.exists(p_file):
        with open(p_file, "r", encoding="utf-8") as f:
            html = f.read()
        pos_data = html.find("<script>window.DATA=")
        if pos_data != -1:
            pos_data_end = html.find(";</script>", pos_data)
            if pos_data_end != -1:
                html = html[:pos_data] + f"<script>window.DATA={json_str}" + html[pos_data_end:]
                with open(p_file, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"Updated {p_file} with new DATA")

print("Done patching math into app!")
