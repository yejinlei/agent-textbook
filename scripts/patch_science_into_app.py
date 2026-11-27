# -*- coding: utf-8 -*-
"""
Injects updated renderScience (Text & Simulations) into custom_runtime.js
and updates app.js in both src/ and pages/
"""
import os
import re

SCIENCE_CODE = r'''
  /* ============================================================== 科学模块 (课文文本 & 科学实验) */

  function formatScienceMd(text, volDir) {
    if (!text) return "";
    var s = String(text);
    // 移除内嵌仿真链接行（已由仿真卡片独立承载）
    s = s.replace(/-\s*🧪\s*\*\*配套微仿真实验\*\*[^\n]*\n*/g, "");

    // 渲染真实高清插图与实验活动图示
    s = s.replace(/!\[(.*?)\]\((?:figures\/)?([^)]+)\.(?:png|jpg|webp|jpeg)\)/gi, function (match, caption, pName) {
      var vol = volDir || "";
      var imgUrl = "figures/" + encodeURIComponent(vol) + "/" + pName + ".webp";
      return '<figure class="sci-figure"><img src="' + imgUrl + '" alt="' + esc(caption) + '" loading="lazy"><figcaption>🖼️ ' + esc(caption) + '</figcaption></figure>';
    });

    // 移除正文中的 ## 1. 标题（因为课程主卡顶部已展示标题）
    s = s.replace(/^##\s+\d+\.\s+[^\n]*\n*/gm, "");

    // 教材页码分界线
    s = s.replace(/###\s*\[第\s*(\d+)\s*页\]/g, '<div class="sci-page-divider"><span>📘 教材第 $1 页</span></div>');
    // 移除裸露的 markdown 水平线 ---
    s = s.replace(/^-{3,}\s*$/gm, "");

    // 粗体、斜体、行内代码
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");

    // 列表解析 (在卡片转换前以保留行首匹配)
    s = s.replace(/^[-*]\s+(.+)$/gm, '<li class="sci-list-item">$1</li>');
    s = s.replace(/((?:<li class="sci-list-item">.*<\/li>\s*)+)/g, '<ul class="sci-list">$1</ul>');
    s = s.replace(/^\d+\.\s+(.+)$/gm, '<li class="sci-num-item">$1</li>');
    s = s.replace(/((?:<li class="sci-num-item">.*<\/li>\s*)+)/g, '<ol class="sci-num-list">$1</ol>');

    // 各大探究核心环节转为结构化卡片
    s = s.replace(/####\s*🎯\s*(?:聚焦|任务|明确任务)[：: \s]*([^\n]*)/g, '<div class="sci-sec-card focus"><div class="sci-sec-head">🎯 聚焦 · 科学问题与真实情境</div><div class="sci-sec-body">$1');
    s = s.replace(/####\s*🔬\s*(?:探索|制作|观察|实验)[：: \s]*([^\n]*)/g, '</div></div><div class="sci-sec-card exploration"><div class="sci-sec-head">🔬 探索 · 观察实验与探究过程</div><div class="sci-sec-body">$1');
    s = s.replace(/####\s*💬\s*(?:研讨|讨论|交流)[：: \s]*([^\n]*)/g, '</div></div><div class="sci-sec-card discussion"><div class="sci-sec-head">💬 研讨 · 思维碰撞与事实论证</div><div class="sci-sec-body">$1');
    s = s.replace(/####\s*🚀\s*(?:拓展|实践)[：: \s]*([^\n]*)/g, '</div></div><div class="sci-sec-card expansion"><div class="sci-sec-head">🚀 拓展 · 迁移应用与实践探究</div><div class="sci-sec-body">$1');
    s = s.replace(/####\s*💡\s*(?:科学词汇|概念卡)[：: \s]*([^\n]*)/g, '</div></div><div class="sci-sec-card vocab"><div class="sci-sec-head">💡 科学词汇与核心概念</div><div class="sci-sec-body">$1');
    s = s.replace(/####\s*📝\s*(?:记录单|活动记录)[：: \s]*([^\n]*)/g, '</div></div><div class="sci-sec-card record"><div class="sci-sec-head">📝 活动记录单与观察表</div><div class="sci-sec-body">$1');
    s = s.replace(/####\s*🚀\s*科学家视角[^\n]*/g, '</div></div><div class="sci-frontier-box"><div class="sci-frontier-title">🚀 科学家视野 · 深度课外拓展</div><div class="sci-frontier-body">');

    // 段落包装
    var parts = s.split(/\n{2,}/);
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i].trim();
      if (!p) continue;
      if (p.indexOf("<div") === 0 || p.indexOf("</div>") === 0 || p.indexOf("<ul") === 0 || p.indexOf("<ol") === 0 || p.indexOf("<figure") === 0) {
        out.push(p);
      } else {
        out.push("<p>" + p.replace(/\n/g, "<br>") + "</p>");
      }
    }
    var res = out.join("\n");
    // 闭合可能未闭合的卡片
    var openCount = (res.match(/<div class="sci-(?:sec-card|frontier-box)[^"]*">/g) || []).length;
    var closeCount = (res.match(/<\/div><\/div>/g) || []).length;
    for (var c = closeCount; c < openCount; c++) {
      res += "</div></div>";
    }
    return res;
  }

  /* ---------------- 科学课文文本模块 (单课精读 & 单元通读) ---------------- */
  function renderScienceText(box) {
    var books = D.books || [];
    var allLessons = D.lessons || [];

    var loc = typeof window !== "undefined" && window.location ? window.location : { hash: "" };
    var hist = typeof window !== "undefined" && window.history ? window.history : null;
    var hashBook = "", hashLesson = "";
    var m = String(loc.hash || "").match(/#([^#&]+)(?:#|&lesson=)([^&]+)/);
    if (m) {
      hashBook = decodeURIComponent(m[1]);
      hashLesson = decodeURIComponent(m[2]);
    } else if (loc.hash) {
      var rawH = decodeURIComponent(loc.hash.slice(1));
      if (books.indexOf(rawH) >= 0) hashBook = rawH;
    }

    var state = {
      book: hashBook || getStorage("sci_book", books[0] || "一年级上册"),
      lessonId: hashLesson || getStorage("sci_lesson", ""),
      mode: "single",
      showToc: false,
      q: ""
    };

    if (books.indexOf(state.book) < 0 && books.length) {
      state.book = books[0];
    }

    var navWrap = document.createElement("div");
    navWrap.className = "lnav-bar";
    insertBeforeNode(app, navWrap, box);

    function getBookLessons() {
      return allLessons.filter(function (x) { return x.book === state.book; });
    }

    function getUnits(bookLessons) {
      var map = {}, list = [];
      bookLessons.forEach(function (x) {
        var k = String(x.unit_no);
        if (!map[k]) {
          map[k] = { no: x.unit_no, title: x.unit_title, items: [] };
          list.push(map[k]);
        }
        map[k].items.push(x);
      });
      return list;
    }

    function syncHash() {
      try {
        var newHash = "#" + encodeURIComponent(state.book) + "&lesson=" + encodeURIComponent(state.lessonId);
        if (loc.hash !== newHash) {
          if (hist && hist.replaceState) hist.replaceState(null, "", newHash);
          else if (loc.replace) loc.replace(newHash);
        }
      } catch (e) {}
    }

    function render() {
      setStorage("sci_book", state.book);
      setStorage("sci_lesson", state.lessonId);
      syncHash();

      var bookLessons = getBookLessons();
      if (!bookLessons.length && books.length) {
        state.book = books[0];
        bookLessons = getBookLessons();
      }

      var curIdx = -1;
      if (state.lessonId) {
        curIdx = bookLessons.findIndex(function (x) { return x.id === state.lessonId; });
      }
      if (curIdx < 0 && bookLessons.length) {
        curIdx = 0;
        state.lessonId = bookLessons[0].id;
      }
      var curLesson = curIdx >= 0 ? bookLessons[curIdx] : null;
      var units = getUnits(bookLessons);

      // 渲染顶栏
      var topHtml = '<div class="lnav-left">' +
        '<select class="lnav-select" id="sciBookSel" title="切换教材册次">';
      books.forEach(function (b) {
        topHtml += '<option value="' + esc(b) + '"' + (b === state.book ? ' selected' : '') + '>' + esc(b) + '</option>';
      });
      topHtml += '</select>';

      topHtml += '<select class="lnav-select" id="sciLessonSel" title="快速选课">';
      units.forEach(function (u) {
        topHtml += '<optgroup label="' + esc(u.title) + '">';
        u.items.forEach(function (ls) {
          topHtml += '<option value="' + esc(ls.id) + '"' + (curLesson && curLesson.id === ls.id ? ' selected' : '') + '>' +
            '第' + ls.lesson_no + '课 ' + esc(ls.title) + '</option>';
        });
        topHtml += '</optgroup>';
      });
      topHtml += '</select>';

      var hasPrev = curIdx > 0;
      var hasNext = curIdx >= 0 && curIdx < bookLessons.length - 1;
      topHtml += '<button class="lnav-btn prev" id="sciPrevBtn"' + (hasPrev ? '' : ' disabled') + ' title="上一课 (← 方向键)">‹ 上一课</button>';
      topHtml += '<button class="lnav-btn next" id="sciNextBtn"' + (hasNext ? '' : ' disabled') + ' title="下一课 (→ 方向键)">下一课 ›</button>';
      topHtml += '</div>';

      topHtml += '<div class="lnav-right">' +
        '<input type="search" class="lnav-search" id="sciSearch" placeholder="🔍 搜课文/实验/科学概念..." value="' + esc(state.q) + '">' +
        '<button class="lnav-toggle-mode' + (state.mode === 'single' ? ' on' : '') + '" id="sciModeBtn" title="切换模式">' +
        (state.mode === 'single' ? '📖 单课精读' : '📑 本册全部') + '</button>' +
        '<button class="lnav-toc-btn' + (state.showToc ? ' on' : '') + '" id="sciTocBtn" title="本册目录">📑 目录</button>' +
        '</div>';

      // 目录抽屉
      topHtml += '<div class="lnav-toc-panel' + (state.showToc ? ' show' : '') + '" id="sciTocPanel">' +
        '<div class="lnav-toc-title"><span>📘 ' + esc(state.book) + ' · 单元课程目录</span>' +
        '<button class="lnav-toc-close" id="sciTocClose" type="button">✕ 关闭</button></div>' +
        '<div class="lnav-toc-list">';
      units.forEach(function (u) {
        topHtml += '<div class="lnav-toc-group">' +
          '<div class="lnav-toc-grouph">' + esc(u.title) + '</div>';
        u.items.forEach(function (ls) {
          var isCur = curLesson && curLesson.id === ls.id;
          topHtml += '<div class="lnav-toc-item' + (isCur ? ' cur' : '') + '" data-lid="' + esc(ls.id) + '">' +
            '<span class="toc-num">第' + ls.lesson_no + '课</span>' +
            '<span class="toc-name">' + esc(ls.title) + '</span>' +
            '<span class="tag d1" style="font-size:11px;padding:1px 6px;">' + esc(ls.domain_cn || ls.domain) + '</span>' +
            '</div>';
        });
        topHtml += '</div>';
      });
      topHtml += '</div></div>';

      navWrap.innerHTML = topHtml;

      // 绑定顶栏事件
      var bSel = document.getElementById("sciBookSel");
      if (bSel) bSel.addEventListener("change", function () {
        state.book = bSel.value;
        var newLs = getBookLessons();
        state.lessonId = newLs.length ? newLs[0].id : "";
        state.showToc = false;
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });

      var lSel = document.getElementById("sciLessonSel");
      if (lSel) lSel.addEventListener("change", function () {
        state.lessonId = lSel.value;
        state.mode = "single";
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });

      var pBtn = document.getElementById("sciPrevBtn");
      if (pBtn && hasPrev) pBtn.addEventListener("click", function () {
        state.lessonId = bookLessons[curIdx - 1].id;
        state.mode = "single";
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });

      var nBtn = document.getElementById("sciNextBtn");
      if (nBtn && hasNext) nBtn.addEventListener("click", function () {
        state.lessonId = bookLessons[curIdx + 1].id;
        state.mode = "single";
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });

      var mBtn = document.getElementById("sciModeBtn");
      if (mBtn) mBtn.addEventListener("click", function () {
        state.mode = state.mode === "single" ? "all" : "single";
        render();
      });

      var tBtn = document.getElementById("sciTocBtn");
      if (tBtn) tBtn.addEventListener("click", function () {
        state.showToc = !state.showToc;
        var p = document.getElementById("sciTocPanel");
        if (p) {
          if (state.showToc) p.classList.add("show");
          else p.classList.remove("show");
        }
        tBtn.classList.toggle("on", state.showToc);
      });

      var tClose = document.getElementById("sciTocClose");
      if (tClose) tClose.addEventListener("click", function () {
        state.showToc = false;
        var p = document.getElementById("sciTocPanel");
        if (p) p.classList.remove("show");
        var tb = document.getElementById("sciTocBtn");
        if (tb) tb.classList.remove("on");
      });

      var sInp = document.getElementById("sciSearch");
      if (sInp) sInp.addEventListener("input", function () {
        state.q = sInp.value.trim().toLowerCase();
        if (state.mode === "single" && state.q) {
          state.mode = "all";
        }
        renderContentOnly();
      });

      // 绑定抽屉点击
      var panel = document.getElementById("sciTocPanel");
      if (panel) panel.addEventListener("click", function (e) {
        var item = e.target.closest(".lnav-toc-item");
        if (item && item.dataset.lid) {
          state.lessonId = item.dataset.lid;
          state.mode = "single";
          state.showToc = false;
          render();
          window.scrollTo({ top: 0, behavior: "smooth" });
        }
      });

      renderContentOnly();
    }

    function renderContentOnly() {
      var bookLessons = getBookLessons();
      var curIdx = -1;
      if (state.lessonId) {
        curIdx = bookLessons.findIndex(function (x) { return x.id === state.lessonId; });
      }
      var curLesson = curIdx >= 0 ? bookLessons[curIdx] : (bookLessons[0] || null);

      if (state.mode === "single" && curLesson && !state.q) {
        // 单课精读视图
        var hasPrev = curIdx > 0;
        var hasNext = curIdx >= 0 && curIdx < bookLessons.length - 1;

        var html = '<div class="lesson-view">' +
          '<div class="lesson-crumb">' +
          '<a href="../index.html">小学知识库</a> &gt; ' +
          '<span>科学</span> &gt; ' +
          '<span>' + esc(curLesson.book) + '</span> &gt; ' +
          '<span>' + esc(curLesson.unit_title) + '</span> &gt; ' +
          '<b>第' + curLesson.lesson_no + '课 ' + esc(curLesson.title) + '</b>' +
          '</div>';

        // 课程主卡
        html += '<div class="lesson-main-card">' +
          '<div class="lesson-head-row">' +
          '<span class="tag d1" style="font-size:13px;padding:3px 10px;">' + esc(curLesson.domain_cn || curLesson.domain) + '</span>' +
          '<span class="tag d2" style="font-size:12px;padding:3px 8px;">' + esc(curLesson.code) + '</span>' +
          '<span style="color:#64748b;font-size:13px;margin-left:auto;">' + esc(curLesson.book) + ' · ' + esc(curLesson.unit_title) + ' · 教材第 ' + (curLesson.page || 1) + ' 页</span>' +
          '</div>' +
          '<h1 class="lesson-title" style="margin:12px 0 6px;">第' + curLesson.lesson_no + '课 ' + esc(curLesson.title) + '</h1>' +
          '</div>';

        html += '<div class="lesson-body-content">';

        // 1. 📖 完整课文文本与探究活动 (Textbook Full Content)
        html += '<div class="sci-textbook-card">' +
          '<div class="sci-textbook-card-head">' +
          '<span>📖 课文原文与课堂探究指南</span>' +
          '<span class="sci-textbook-vol-tag">' + esc(curLesson.book) + ' · ' + esc(curLesson.unit_title) + '</span>' +
          '</div>' +
          '<div class="sci-textbook-body">' + formatScienceMd(curLesson.raw_text, curLesson.vol_dir) + '</div>' +
          '</div>';

        // 2. 🧪 配套交互科学微实验 (Simulation Embed)
        if (curLesson.sim_file) {
          var simPath = 'simulations/' + curLesson.sim_file;
          html += '<div class="sci-sim-embed">' +
            '<div class="sci-sim-embed-bar">' +
            '<span class="sci-sim-embed-title">🧪 本课配套交互微实验：' + esc(curLesson.title) + ' (' + esc(curLesson.code) + ')</span>' +
            '<div class="sci-sim-embed-actions">' +
            '<a href="' + simPath + '" target="_blank" class="sim-btn outline" title="在独立新标签页中打开">↗ 独立窗口</a>' +
            '<button class="sim-btn primary" onclick="var f=document.getElementById(\'curSimIframe\');if(f&&f.requestFullscreen){f.requestFullscreen();}else{window.open(\'' + simPath + '\',\'_blank\');}">🔲 全屏探索</button>' +
            '</div></div>' +
            '<iframe id="curSimIframe" src="' + simPath + '" loading="lazy" allowfullscreen></iframe>' +
            '</div>';
        }

        html += '</div>'; // end lesson-body-content

        // 课文底栏 Prev / Next
        html += '<div class="lesson-footer-nav">' +
          '<button class="lesson-footer-btn" id="sciFootPrev"' + (hasPrev ? '' : ' disabled') + '>' +
          '‹ 上一课：' + (hasPrev ? esc(bookLessons[curIdx - 1].title) : '已是本册第一课') + '</button>' +
          '<button class="lesson-footer-btn" id="sciFootToc">📑 本册目录</button>' +
          '<button class="lesson-footer-btn" id="sciFootNext"' + (hasNext ? '' : ' disabled') + '>' +
          '下一课：' + (hasNext ? esc(bookLessons[curIdx + 1].title) : '已是本册最后一课') + ' ›</button>' +
          '</div>';

        html += '</div>'; // end lesson-view
        box.innerHTML = html;

        // 绑定底部导航事件
        var fp = document.getElementById("sciFootPrev");
        if (fp && hasPrev) fp.addEventListener("click", function () {
          state.lessonId = bookLessons[curIdx - 1].id;
          render();
          window.scrollTo({ top: 0, behavior: "smooth" });
        });
        var fn = document.getElementById("sciFootNext");
        if (fn && hasNext) fn.addEventListener("click", function () {
          state.lessonId = bookLessons[curIdx + 1].id;
          render();
          window.scrollTo({ top: 0, behavior: "smooth" });
        });
        var ft = document.getElementById("sciFootToc");
        if (ft) ft.addEventListener("click", function () {
          state.showToc = true;
          var p = document.getElementById("sciTocPanel");
          if (p) p.classList.add("show");
          var tb = document.getElementById("sciTocBtn");
          if (tb) tb.classList.add("on");
          window.scrollTo({ top: 0, behavior: "smooth" });
        });

      } else {
        // 本册全部列表视图 (或搜索视图)
        var filtered = bookLessons;
        if (state.q) {
          filtered = allLessons.filter(function (x) {
            return has(x.title, state.q) || has(x.unit_title, state.q) ||
              has(x.book, state.q) || has(x.domain_cn, state.q) ||
              has(x.raw_text, state.q);
          });
        }

        var html = '<div class="sci-all-wrapper" style="padding:16px 0;">';
        if (state.q) {
          html += '<div style="margin-bottom:16px;font-size:15px;color:#475569;">' +
            '搜索 "<b>' + esc(state.q) + '</b>" 找到 <b>' + filtered.length + '</b> 课：' +
            '<button class="sim-btn outline" id="sciClearSearch" style="margin-left:12px;padding:2px 10px;font-size:12px;">清空搜索</button>' +
            '</div>';
        } else {
          html += '<div style="margin-bottom:16px;font-size:15px;color:#475569;">' +
            '📘 <b>' + esc(state.book) + '</b> 共包含 <b>' + filtered.length + '</b> 课：' +
            '</div>';
        }

        if (!filtered.length) {
          html += '<div class="empty">未找到匹配的科学课文</div>';
        } else {
          var curUnit = "";
          filtered.forEach(function (ls) {
            if (!state.q && ls.unit_title !== curUnit) {
              curUnit = ls.unit_title;
              html += '<h3 class="sci-unit-banner" style="margin:24px 0 12px;padding:8px 12px;background:#f1f5f9;border-left:4px solid #0284c7;border-radius:4px;font-size:16px;color:#0f172a;">' +
                esc(curUnit) + '</h3>';
            }
            var preview = String(ls.raw_text || "").replace(/#[^\n]+/g, "").replace(/\!\[[^\]]+\]\([^\)]+\)/g, "").replace(/\s+/g, " ").trim().slice(0, 110);
            html += '<div class="item" style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 16px;margin-bottom:10px;background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;">' +
              '<div style="flex:1;">' +
              '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">' +
              '<span class="tag d1">' + esc(ls.domain_cn || ls.domain) + '</span>' +
              '<span class="tag d2">' + esc(ls.book) + '</span>' +
              '<span style="font-weight:700;font-size:16px;color:#0f172a;">第' + ls.lesson_no + '课 ' + esc(ls.title) + '</span>' +
              '</div>' +
              '<div style="font-size:13px;color:#64748b;margin-bottom:4px;">' + esc(ls.unit_title) + '</div>' +
              (preview ? '<div style="font-size:13px;color:#475569;line-height:1.5;">' + esc(preview) + '...</div>' : '') +
              '</div>' +
              '<div style="display:flex;gap:8px;align-items:center;">' +
              (ls.sim_file ? '<a href="simulations/' + ls.sim_file + '" target="_blank" class="sim-btn outline" style="font-size:12px;padding:4px 8px;">🧪 实验</a>' : '') +
              '<button class="list-mode-switch-btn" data-lid="' + esc(ls.id) + '" data-bk="' + esc(ls.book) + '" type="button">📖 单课精读</button>' +
              '</div></div>';
          });
        }
        html += '</div>';
        box.innerHTML = html;

        var clr = document.getElementById("sciClearSearch");
        if (clr) clr.addEventListener("click", function () {
          state.q = "";
          var si = document.getElementById("sciSearch");
          if (si) si.value = "";
          render();
        });
      }
    }

    // 事件委托：列表中的单课精读按钮
    box.addEventListener("click", function (e) {
      var btn = e.target.closest(".list-mode-switch-btn");
      if (btn && btn.dataset.lid) {
        state.lessonId = btn.dataset.lid;
        if (btn.dataset.bk) state.book = btn.dataset.bk;
        state.mode = "single";
        state.q = "";
        var si = document.getElementById("sciSearch");
        if (si) si.value = "";
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    });

    render();
  }

  /* ---------------- 科学实验模块 (287个交互仿真与大师探索沙盒) ---------------- */
  function renderScienceSimulations(box) {
    var masterSims = D.master_simulations || [];
    var allLessons = D.lessons || [];
    var books = D.books || [];

    var simList = [];

    masterSims.forEach(function (m, idx) {
      simList.push({
        id: "master_" + idx,
        is_master: true,
        title: m.title,
        file: m.file,
        domain: m.domain,
        domain_cn: m.domain_cn,
        desc: m.desc,
        grade: "大师级探究沙盒",
        lesson_title: "15大科学中心级探究模型",
        code: "MASTER-" + (idx < 9 ? "0" : "") + (idx + 1)
      });
    });

    allLessons.forEach(function (ls) {
      if (ls.sim_file) {
        simList.push({
          id: ls.id,
          is_master: false,
          title: ls.title + " · 仿真实验",
          file: ls.sim_file,
          domain: ls.domain,
          domain_cn: ls.domain_cn,
          desc: "配套第" + ls.lesson_no + "课《" + ls.title + "》课堂探究与实践操作",
          grade: ls.book,
          lesson_title: ls.unit_title + " · 第" + ls.lesson_no + "课",
          code: ls.code,
          lesson_id: ls.id
        });
      }
    });

    var state = {
      domain: "all",
      book: "all",
      q: "",
      activeSim: simList.length ? simList[0] : null
    };

    function render() {
      var filtered = simList.filter(function (s) {
        if (state.domain === "master" && !s.is_master) return false;
        if (state.domain !== "all" && state.domain !== "master") {
          if (s.domain !== state.domain && s.domain_cn !== state.domain) return false;
        }
        if (state.book !== "all" && !s.is_master && s.grade !== state.book) return false;
        if (state.q) {
          return has(s.title, state.q) || has(s.desc, state.q) || has(s.domain_cn, state.q) ||
            has(s.code, state.q) || has(s.lesson_title, state.q);
        }
        return true;
      });

      var html = '<div class="sim-wrapper">';

      // 顶部过滤工具条
      html += '<div class="sim-filter-bar">' +
        '<div class="sim-domain-pills">' +
        '<button class="sim-domain-pill' + (state.domain === 'all' ? ' active' : '') + '" data-dom="all">全部实验 (' + simList.length + ')</button>' +
        '<button class="sim-domain-pill' + (state.domain === 'master' ? ' active' : '') + '" data-dom="master">⭐ 大师级探究沙盒 (15)</button>' +
        '<button class="sim-domain-pill' + (state.domain === 'physics' ? ' active' : '') + '" data-dom="physics">物质科学</button>' +
        '<button class="sim-domain-pill' + (state.domain === 'biology' ? ' active' : '') + '" data-dom="biology">生命科学</button>' +
        '<button class="sim-domain-pill' + (state.domain === 'earth' ? ' active' : '') + '" data-dom="earth">地球与宇宙</button>' +
        '<button class="sim-domain-pill' + (state.domain === 'tech' ? ' active' : '') + '" data-dom="tech">技术与工程</button>' +
        '</div>' +
        '<div class="sim-filter-controls">' +
        '<select class="lnav-select" id="simBookSel">' +
        '<option value="all"' + (state.book === 'all' ? ' selected' : '') + '>全部年级册次</option>';
      books.forEach(function (b) {
        html += '<option value="' + esc(b) + '"' + (state.book === b ? ' selected' : '') + '>' + esc(b) + '</option>';
      });
      html += '</select>' +
        '<input type="search" class="lnav-search" id="simSearch" placeholder="🔍 搜索实验名称/科学现象/仪器..." value="' + esc(state.q) + '">' +
        '</div></div>';

      // 实验台 (Active Simulation Stage)
      if (state.activeSim) {
        var a = state.activeSim;
        var filePath = 'simulations/' + a.file;
        html += '<div class="sim-stage-box" id="simStage">' +
          '<div class="sim-stage-header">' +
          '<div class="sim-stage-title">' +
          '<span>🧪 正在运行：' + esc(a.title) + '</span>' +
          '<span class="tag d1" style="font-size:12px;margin-left:8px;">' + esc(a.domain_cn || a.domain) + '</span>' +
          '<span class="tag d2" style="font-size:12px;margin-left:4px;">' + esc(a.grade) + '</span>' +
          '</div>' +
          '<div class="sim-stage-actions">' +
          (a.lesson_id ? '<a href="index.html#' + encodeURIComponent(a.grade) + '&lesson=' + encodeURIComponent(a.lesson_id) + '" class="sim-btn outline" title="跳转到对应课文文本">📖 配套课文</a>' : '') +
          '<a href="' + filePath + '" target="_blank" class="sim-btn outline" title="在独立新标签页中打开">↗ 独立标签页</a>' +
          '<button class="sim-btn secondary" id="simReloadBtn" title="重新加载仿真">🔄 重置</button>' +
          '<button class="sim-btn primary" id="simFsBtn" title="全屏操作">🔲 全屏实验</button>' +
          '</div></div>' +
          '<iframe id="stageIframe" src="' + filePath + '" style="width:100%;height:680px;border:none;border-radius:10px;background:#000;" allowfullscreen></iframe>' +
          '</div>';
      }

      // 实验卡片列表
      html += '<div class="sim-grid-header" style="margin:24px 0 12px;display:flex;justify-content:space-between;align-items:center;">' +
        '<h3 style="font-size:18px;font-weight:700;color:#0f172a;margin:0;">实验库列表 <span style="font-size:14px;color:#64748b;font-weight:normal;">(共 ' + filtered.length + ' 个仿真模型)</span></h3>' +
        '</div>';

      if (!filtered.length) {
        html += '<div class="empty">未找到符合条件的科学实验，请尝试清除筛选条件</div>';
      } else {
        html += '<div class="sim-grid">';
        filtered.forEach(function (s) {
          var isCur = state.activeSim && state.activeSim.file === s.file;
          html += '<div class="sim-card' + (s.is_master ? ' master' : '') + (isCur ? ' active-playing' : '') + '" data-file="' + esc(s.file) + '">' +
            '<div class="sim-card-top">' +
            '<span class="tag ' + (s.is_master ? 'd2' : 'd1') + '" style="font-size:11px;">' + (s.is_master ? '⭐ 大师沙盒' : esc(s.domain_cn || s.domain)) + '</span>' +
            '<span style="font-size:12px;color:#64748b;">' + esc(s.grade) + '</span>' +
            '</div>' +
            '<div class="sim-card-title">' + esc(s.title) + '</div>' +
            '<div class="sim-card-desc">' + esc(s.desc) + '</div>' +
            '<div class="sim-card-bottom">' +
            '<span style="font-size:12px;color:#94a3b8;">' + esc(s.code) + '</span>' +
            '<button class="sim-btn primary load-sim-btn" data-file="' + esc(s.file) + '">▶ 运行实验</button>' +
            '</div></div>';
        });
        html += '</div>';
      }

      html += '</div>';
      box.innerHTML = html;

      // 绑定筛选
      var domBtns = box.querySelectorAll(".sim-domain-pill");
      domBtns.forEach(function (btn) {
        btn.addEventListener("click", function () {
          state.domain = btn.dataset.dom;
          render();
        });
      });

      var bSel = document.getElementById("simBookSel");
      if (bSel) bSel.addEventListener("change", function () {
        state.book = bSel.value;
        render();
      });

      var sInp = document.getElementById("simSearch");
      if (sInp) sInp.addEventListener("input", function () {
        state.q = sInp.value.trim().toLowerCase();
        render();
      });

      var fsBtn = document.getElementById("simFsBtn");
      if (fsBtn) fsBtn.addEventListener("click", function () {
        var f = document.getElementById("stageIframe");
        if (f && f.requestFullscreen) f.requestFullscreen();
        else if (f && f.webkitRequestFullscreen) f.webkitRequestFullscreen();
        else if (state.activeSim) window.open('simulations/' + state.activeSim.file, '_blank');
      });

      var relBtn = document.getElementById("simReloadBtn");
      if (relBtn) relBtn.addEventListener("click", function () {
        var f = document.getElementById("stageIframe");
        if (f && state.activeSim) f.src = 'simulations/' + state.activeSim.file;
      });

      var cards = box.querySelectorAll(".sim-card");
      cards.forEach(function (card) {
        card.addEventListener("click", function (e) {
          var f = card.dataset.file;
          var found = simList.find(function (x) { return x.file === f; });
          if (found) {
            state.activeSim = found;
            render();
            var stage = document.getElementById("simStage");
            if (stage) stage.scrollIntoView({ behavior: "smooth", block: "start" });
          }
        });
      });
    }

    render();
  }

  function renderScience() {
    var box = listBox();
    if (kind === "simulations") {
      renderScienceSimulations(box);
    } else {
      renderScienceText(box);
    }
  }
'''

def main():
    # 1. Update scripts/custom_runtime.js
    with open('scripts/custom_runtime.js', 'r', encoding='utf-8') as f:
        custom_js = f.read()

    # Replace the existing renderScience block in custom_runtime.js
    marker = '/* ============================================================== 科学模块 (课文文本 & 科学实验) */'
    idx = custom_js.find(marker)
    if idx >= 0:
        custom_js = custom_js[:idx] + SCIENCE_CODE.strip()
    else:
        custom_js = custom_js + '\n' + SCIENCE_CODE

    with open('scripts/custom_runtime.js', 'w', encoding='utf-8') as f:
        f.write(custom_js)
    print("Updated scripts/custom_runtime.js")

    # 2. Patch app.js in both targets
    targets = [
        'src/agent_textbook/site/assets/app.js',
        'pages/assets/app.js'
    ]

    cn_marker = '  function renderChinese() {'
    for target in targets:
        with open(target, 'r', encoding='utf-8') as f:
            app_code = f.read()

        idx = app_code.find(marker)
        cn_idx = app_code.find(cn_marker)
        if idx >= 0 and cn_idx >= 0:
            app_code = app_code[:idx] + SCIENCE_CODE.strip() + '\n\n' + app_code[cn_idx:]
            print(f"Cleanly replaced Science code in {target}")

        with open(target, 'w', encoding='utf-8') as f:
            f.write(app_code)

    print("Finished updating app.js files with full textbook reader!")

if __name__ == '__main__':
    main()
