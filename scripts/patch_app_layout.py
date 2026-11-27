# -*- coding: utf-8 -*-
import os
import shutil
import subprocess

APP_JS_SRC = 'src/agent_textbook/site/assets/app.js'
APP_JS_PAGES = 'pages/assets/app.js'

with open(APP_JS_SRC, 'r', encoding='utf-8') as f:
    code = f.read()

# 0. Fix mark function to avoid replacing inside HTML attributes/tags
old_mark = """  function mark(html, w, cls, tip) {
    var s = esc(w);
    if (!s || html.indexOf(s) < 0) return html;
    // 单字（多音字、易错字）到处都是，只标第一次，不然满屏都是色块
    if (s.length <= 2) {
      return html.replace(s, '<mark class="' + cls + '"' +
        (tip ? ' title="' + esc(tip) + '"' : "") + ">" + s + "</mark>");
    }
    return html.split(s).join('<mark class="' + cls + '"' +
      (tip ? ' title="' + esc(tip) + '"' : "") + ">" + s + "</mark>");
  }"""

new_mark = """  function mark(html, w, cls, tip) {
    var s = esc(w);
    if (!s || html.indexOf(s) < 0) return html;
    var rep = '<mark class="' + cls + '"' + (tip ? ' title="' + esc(tip) + '"' : "") + ">" + s + "</mark>";
    var parts = html.split(/(<[^>]+>)/);
    var replaced = false;
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].charAt(0) !== "<") {
        if (s.length <= 2) {
          if (!replaced && parts[i].indexOf(s) >= 0) {
            parts[i] = parts[i].replace(s, rep);
            replaced = true;
          }
        } else {
          parts[i] = parts[i].split(s).join(rep);
        }
      }
    }
    return parts.join("");
  }"""

if old_mark in code:
    code = code.replace(old_mark, new_mark, 1)
    print("Patched mark function (safe attribute replacement)")
else:
    print("Warning: old_mark not found")

# 1. Update cnText to add button
old_cn_target = '\'<span class="name">\' + esc(x.title) + "</span>" +'
new_cn_target = '\'<span class="name">\' + esc(x.title) + "</span>" + (x.domain === "reading" ? \'<button class="list-mode-switch-btn" data-tid="\' + esc(x.id) + \'" type="button">📖 单课精读</button>\' : "") +'

if old_cn_target in code:
    code = code.replace(old_cn_target, new_cn_target, 1)
    print("Patched cnText successfully!")
else:
    print("Warning: old_cn_target not found")

# 2. Update mathUnit to add button
old_math_unit_top = '><div class="top"><span class="name">\' + esc(u.title) + "</span>" +'
new_math_unit_top = '><div class="top"><span class="name">\' + esc(u.title) + "</span>" + \'<button class="list-mode-switch-btn" data-mid="\' + idx + \'" type="button">📐 单单元精学</button>\' +'

if old_math_unit_top in code:
    code = code.replace(old_math_unit_top, new_math_unit_top, 1)
    print("Patched mathUnit")
else:
    print("Warning: old_math_unit_top not found")

# 3. Update enLesson to add button
old_en_lesson_top = """'<span class="tag d1">' + (type === "dlg" ? "对话" : "短文") + "</span>" +
      '<span class="name">' + esc(name) + "</span>" +"""

new_en_lesson_top = """'<span class="tag d1">' + (type === "dlg" ? "对话" : "短文") + "</span>" +
      '<span class="name">' + esc(name) + "</span>" +
      '<button class="list-mode-switch-btn" data-lkey="' + esc(key) + '" type="button">📖 单课精学</button>' +"""

if old_en_lesson_top in code:
    code = code.replace(old_en_lesson_top, new_en_lesson_top, 1)
    print("Patched enLesson")
else:
    print("Warning: old_en_lesson_top not found")

# 4. In renderChinese: intercept kind === "reading"
old_render_cn = """  function renderChinese() {
    if (kind === "poetry") {
      var pl = document.createElement("div");
      pl.innerHTML = poetryLab();
      app.appendChild(pl);
      bindPoetry();
    }
    var box = listBox();
    if (kind === "literacy") bindCharCard();
    var elems = {};   // 册+单元 → 语文要素
    (D.elements || []).forEach(function (e) {
      elems[e.book + "#" + e.unit_no] = e;
    });
    var t = tools([], function (st, cnt) {"""

new_render_cn = """  function renderChinese() {
    if (kind === "poetry") {
      var pl = document.createElement("div");
      pl.innerHTML = poetryLab();
      app.appendChild(pl);
      bindPoetry();
    }
    var box = listBox();
    if (kind === "literacy") bindCharCard();
    var elems = {};   // 册+单元 → 语文要素
    (D.elements || []).forEach(function (e) {
      elems[e.book + "#" + e.unit_no] = e;
    });
    if (kind === "reading") {
      renderChineseReading(box, elems);
      return;
    }
    var t = tools([], function (st, cnt) {"""

if old_render_cn in code:
    code = code.replace(old_render_cn, new_render_cn, 1)
    print("Patched renderChinese")
else:
    print("Warning: old_render_cn not found")

# 5. In renderEnglish: intercept kind === "discourse"
old_render_en = """  function renderEnglish() {
    if (kind === "vocab") {
      var ql = document.createElement("div");
      ql.innerHTML = quizLab();
      app.appendChild(ql);
      bindQuiz();
    }
    var box = listBox();
    var topics = [];"""

new_render_en = """  function renderEnglish() {
    if (kind === "vocab") {
      var ql = document.createElement("div");
      ql.innerHTML = quizLab();
      app.appendChild(ql);
      bindQuiz();
    }
    var box = listBox();
    if (kind === "discourse") {
      renderEnglishDiscourse(box);
      return;
    }
    var topics = [];"""

if old_render_en in code:
    code = code.replace(old_render_en, new_render_en, 1)
    print("Patched renderEnglish")
else:
    print("Warning: old_render_en not found")

# 6. In renderMath: intercept unit-by-unit
old_render_math = """  /* ================================================================ 数学 */
  function renderMath() {
    var box = listBox();
    // 子页就是领域页，只在"全部单元"页给领域页签
    var t = tools(kind === "all" ? (D.domains || []) : [], function (st, cnt) {"""

new_render_math = """  /* ================================================================ 数学 */
  function renderMath() {
    var box = listBox();
    renderMathUnitByUnit(box);
    return;
    // 子页就是领域页，只在"全部单元"页给领域页签
    var t = tools(kind === "all" ? (D.domains || []) : [], function (st, cnt) {"""

if old_render_math in code:
    code = code.replace(old_render_math, new_render_math, 1)
    print("Patched renderMath")
else:
    print("Warning: old_render_math not found")

# Read custom code from scripts/custom_runtime.js
with open('scripts/custom_runtime.js', 'r', encoding='utf-8') as f:
    custom_functions = f.read()

# Insert custom_functions before renderChinese
cn_marker = '  function renderChinese() {'
idx = code.find(cn_marker)
if idx >= 0:
    code = code[:idx] + custom_functions + '\n' + code[idx:]
    print("Injected custom_functions before renderChinese")
else:
    print("Warning: renderChinese marker not found")

# Save to APP_JS_SRC and APP_JS_PAGES
with open(APP_JS_SRC, 'w', encoding='utf-8') as f:
    f.write(code)

with open(APP_JS_PAGES, 'w', encoding='utf-8') as f:
    f.write(code)

print("Saved updated app.js to both locations!")
