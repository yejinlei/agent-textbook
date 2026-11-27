  /* 安全 LocalStorage 读写 */
  function getStorage(k, def) {
    try { return (typeof localStorage !== "undefined" && localStorage.getItem(k)) || def; } catch (e) { return def; }
  }
  function setStorage(k, v) {
    try { if (typeof localStorage !== "undefined") localStorage.setItem(k, v); } catch (e) {}
  }

  /* 安全 DOM 插入 */
  function insertBeforeNode(parent, node, ref) {
    if (parent && parent.insertBefore) parent.insertBefore(node, ref);
    else if (parent) parent.appendChild(node);
  }

  /* ============================================================== 语文单课精读模块 */
  function renderChineseReading(box, elems) {
    var allTexts = (D.texts || []).filter(function (x) { return x.domain === "reading"; });
    var books = D.books || [];
    if (!books.length) {
      allTexts.forEach(function (x) {
        if (x.book && books.indexOf(x.book) < 0) books.push(x.book);
      });
    }

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
      book: hashBook || getStorage("cn_reading_book", books[0] || "一年级上册"),
      lessonId: hashLesson || getStorage("cn_reading_lesson", ""),
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

    function getBookTexts() {
      return allTexts.filter(function (x) { return x.book === state.book; });
    }

    function getUnits(bookTexts) {
      var map = {}, list = [];
      bookTexts.forEach(function (x, i) {
        var k = String(x.unit_no != null ? x.unit_no : (x.unit_name || i));
        if (!map[k]) {
          map[k] = { no: x.unit_no, name: x.unit_name || ("第" + x.unit_no + "单元"), items: [] };
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
      setStorage("cn_reading_book", state.book);
      setStorage("cn_reading_lesson", state.lessonId);
      syncHash();

      var bookTexts = getBookTexts();
      if (!bookTexts.length && books.length) {
        state.book = books[0];
        bookTexts = getBookTexts();
      }

      var curIdx = -1;
      if (state.lessonId) {
        curIdx = bookTexts.findIndex(function (x) { return x.id === state.lessonId; });
      }
      if (curIdx < 0 && bookTexts.length) {
        curIdx = 0;
        state.lessonId = bookTexts[0].id;
      }
      var curText = curIdx >= 0 ? bookTexts[curIdx] : null;
      var units = getUnits(bookTexts);

      var searchMatches = [];
      if (state.q) {
        var ql = state.q.toLowerCase();
        allTexts.forEach(function (x) {
          if (has(x.title, ql) || has(x.author, ql) || has(x.text, ql) || has(x.unit_name, ql)) {
            searchMatches.push(x);
          }
        });
      }

      var navHtml = '<div class="lnav-row">' +
        '<div class="lnav-group"><span class="lnav-label">📚 册次</span>' +
        '<select class="lnav-sel" id="cnBookSel">';
      books.forEach(function (b) {
        navHtml += '<option value="' + esc(b) + '"' + (b === state.book ? ' selected' : '') + '>' + esc(b) + '</option>';
      });
      navHtml += '</select></div>';

      navHtml += '<div class="lnav-group"><span class="lnav-label">📖 单元</span>' +
        '<select class="lnav-sel" id="cnUnitSel">';
      units.forEach(function (u, uIdx) {
        var isCur = curText && (curText.unit_no === u.no || curText.unit_name === u.name);
        var sel = isCur ? ' selected' : '';
        navHtml += '<option value="' + uIdx + '"' + sel + '>' +
          (u.no != null ? '第' + esc(u.no) + '单元 · ' : '') + esc(u.name) + ' (' + u.items.length + '篇)</option>';
      });
      navHtml += '</select></div>';

      navHtml += '<div class="lnav-group"><span class="lnav-label">📝 课文</span>' +
        '<select class="lnav-sel" id="cnLessonSel">';
      bookTexts.forEach(function (x, idx) {
        var sel = x.id === state.lessonId ? ' selected' : '';
        navHtml += '<option value="' + esc(x.id) + '"' + sel + '>' +
          (x.lesson_no ? x.lesson_no + '. ' : '') + esc(x.title) + (x.author ? ' (' + esc(x.author) + ')' : '') + '</option>';
      });
      navHtml += '</select></div>';

      navHtml += '<div class="lnav-group">' +
        '<button class="lnav-btn prev" id="cnPrevBtn"' + (curIdx <= 0 ? ' disabled' : '') + '>《 上一课</button>' +
        '<button class="lnav-btn next" id="cnNextBtn"' + (curIdx >= bookTexts.length - 1 ? ' disabled' : '') + '>下一课 》</button>' +
        '<button class="lnav-btn toc-toggle' + (state.showToc ? ' on' : '') + '" id="cnTocToggle">📋 目录</button>' +
        '<button class="lnav-btn mode-toggle' + (state.mode === 'single' ? ' on' : '') + '" id="cnModeToggle">' +
        (state.mode === 'single' ? '📖 单课精读' : '📑 全册列表') + '</button>' +
        '</div>' +
        '</div>';

      navHtml += '<div class="lnav-search-row">' +
        '<input class="lnav-search" id="cnSearchInput" placeholder="🔍 搜索课文标题、作者、正文、生字..." value="' + esc(state.q) + '">' +
        (state.q ? '<button class="lnav-btn" id="cnSearchClear">清空</button>' : '') +
        (searchMatches.length ? '<div class="lnav-hits"><span>找到 ' + searchMatches.length + ' 篇：</span>' +
          searchMatches.slice(0, 10).map(function (m) {
            return '<span class="lnav-hit-chip" data-book="' + esc(m.book) + '" data-id="' + esc(m.id) + '">' +
              esc(m.book) + ' · ' + esc(m.title) + '</span>';
          }).join('') + (searchMatches.length > 10 ? '<span>...</span>' : '') + '</div>' : (state.q ? '<div class="lnav-hits">未找到匹配的课文</div>' : '')) +
        '</div>';

      navHtml += '<div class="lnav-toc-panel' + (state.showToc ? ' show' : '') + '" id="cnTocPanel">';
      units.forEach(function (u) {
        navHtml += '<div class="lnav-toc-unit">' +
          '<div class="lnav-toc-utitle">' + esc(state.book) + ' · ' + (u.no != null ? '第' + esc(u.no) + '单元 · ' : '') + esc(u.name) + '</div>' +
          '<div class="lnav-toc-items">' +
          u.items.map(function (x) {
            var isAct = x.id === state.lessonId;
            return '<a class="lnav-toc-item' + (isAct ? ' active' : '') + '" data-id="' + esc(x.id) + '">' +
              (x.lesson_no ? x.lesson_no + '. ' : '') + esc(x.title) +
              '</a>';
          }).join('') +
          '</div></div>';
      });
      navHtml += '</div>';

      navWrap.innerHTML = navHtml;

      if (state.mode === "single" && curText) {
        var x = curText;
        var prevText = curIdx > 0 ? bookTexts[curIdx - 1] : null;
        var nextText = curIdx < bookTexts.length - 1 ? bookTexts[curIdx + 1] : null;

        var h = "";
        h += '<div class="unit-banner">' +
          '<div class="unit-banner-top">' +
          '<div class="unit-banner-title">' + esc(state.book) + ' · ' +
          (x.unit_no != null ? '第' + esc(x.unit_no) + '单元 · ' : '') + esc(x.unit_name || '') + '</div>' +
          '<div class="unit-banner-tags">' +
          (x.type ? '<span class="tag d1">' + esc(x.type) + '</span>' : '') +
          (x.page_from ? '<span class="where">P' + esc(x.page_from) + (x.page_to ? '-' + esc(x.page_to) : '') + '</span>' : '') +
          '<span class="tag">第 ' + (curIdx + 1) + ' / ' + bookTexts.length + ' 课</span>' +
          '</div></div></div>';

        h += '<div class="lesson-card" id="t' + esc(x.id) + '">';
        h += '<div class="lesson-header">' +
          '<h2 class="lesson-title-text">' +
          (x.lesson_no ? '<span class="lesson-no">' + esc(x.lesson_no) + '.</span> ' : '') +
          esc(x.title) + '</h2>' +
          (x.author ? '<div class="lesson-author-line">作/译者：' + esc(x.author) + '</div>' : '') +
          '</div>';

        var bodyHtml = esc(x.text || "").replace(/\n/g, "<br>");
        if (x.pinyin) {
          bodyHtml = '<div class="pinyin-block">' + esc(x.pinyin).replace(/\n/g, "<br>") + '</div>' + bodyHtml;
        }

        var kb = x.kb || {};
        (kb.polyphones || []).forEach(function (p) {
          var w = typeof p === "string" ? p : p.char;
          var tip = typeof p === "object" ? (p.pron || []).join(" / ") : "";
          bodyHtml = mark(bodyHtml, w, "poly", tip);
        });
        (kb.typos || []).forEach(function (t) {
          var w = typeof t === "string" ? t : (t.wrong || t.char);
          var tip = typeof t === "object" ? "易错提示：" + (t.reason || t.right || "") : "";
          bodyHtml = mark(bodyHtml, w, "typo", tip);
        });
        (kb.idioms || []).forEach(function (idm) {
          var w = typeof idm === "string" ? idm : (idm.idiom || idm.word);
          var tip = typeof idm === "object" ? (idm.meaning || idm.expl || "") : "";
          bodyHtml = mark(bodyHtml, w, "idiom", tip);
        });

        h += '<div class="lesson-article">' + bodyHtml + '</div>';

        if (x.words && x.words.length) {
          h += '<div class="words-bar"><span class="small">生字词：</span>' +
            x.words.map(function (w) { return '<span class="wb">' + esc(w) + '</span>'; }).join('') +
            '</div>';
        }

        if (x.chars && x.chars.length) {
          h += '<div class="char-cards-wrap">' +
            '<div class="char-cards-title">📖 本课生字表与笔顺结构（' + x.chars.length + ' 字）</div>' +
            '<div class="char-cards-grid">' +
            x.chars.map(function (c) {
              return '<div class="char-card-tile">' +
                '<div class="char-tile-char">' + esc(c.char || c) + '</div>' +
                (c.pinyin ? '<div class="char-tile-py">' + esc(c.pinyin) + '</div>' : '') +
                (c.strokes ? '<div class="char-tile-meta">' + esc(c.strokes) + '画 · ' + esc(c.radical || '') + '</div>' : '') +
                (c.words && c.words.length ? '<div class="char-tile-words">' + c.words.slice(0, 2).map(esc).join('、') + '</div>' : '') +
                '</div>';
            }).join('') +
            '</div></div>';
        }

        if (x.tasks && x.tasks.length) {
          h += '<div class="tasks-box-wrap">' +
            '<div class="tasks-box-title">🤔 课后思考与拓展练习</div>' +
            '<div class="tasks-list">' +
            x.tasks.map(function (t, tIdx) {
              return '<div class="task-item-row">' +
                '<span class="task-num">' + (tIdx + 1) + '</span>' +
                '<div class="task-content">' + esc(typeof t === 'string' ? t : (t.question || t.title || '')) + '</div>' +
                '</div>';
            }).join('') +
            '</div></div>';
        }

        var elem = elems[x.book + "#" + x.unit_no];
        if (elem && elem.elements && elem.elements.length) {
          h += '<div class="unit-elem-block">' +
            '<div class="unit-elem-title">🎯 课标本单元语文要素</div>' +
            '<div class="unit-elem-body">' + elem.elements.map(function (e) {
              return '<span class="elem-badge">' + esc(e) + '</span>';
            }).join('') + '</div></div>';
        }

        if (x.kb) {
          var tabs = EXTRA.filter(function (e) { return kbHas(x.kb, e[0]); });
          if (tabs.length) {
            h += '<div class="kb-box-wrap">' +
              '<div class="kb-tabs-bar"><span class="small">知识库拓展：</span>' +
              tabs.map(function (e) {
                var k = e[0], label = e[1];
                return '<span class="chip kb-tab' + (ON[k] ? " on" : "") + '" data-k="' + k + '">' + esc(label) + '</span>';
              }).join('') + '</div>' +
              tabs.map(function (e) {
                var k = e[0], label = e[1];
                return '<div class="kb' + (ON[k] ? " show" : "") + '" data-kb="' + k + '">' +
                  '<div class="kb-h">' + esc(label) + '</div>' + kbBody(x.kb, k) + '</div>';
              }).join('') +
              '</div>';
          }
        }
        h += '</div>';

        h += '<div class="lesson-footer-nav">' +
          '<button class="lesson-footer-btn" id="cnFootPrev"' + (!prevText ? ' disabled' : '') + '>' +
          (prevText ? '《 上一课：' + esc(prevText.title) : '已是本册第一课') + '</button>' +
          '<button class="lnav-btn" id="cnFootToc">📋 本册目录</button>' +
          '<button class="lesson-footer-btn" id="cnFootNext"' + (!nextText ? ' disabled' : '') + '>' +
          (nextText ? '下一课：' + esc(nextText.title) + ' 》' : '已是本册最后一课') + '</button>' +
          '</div>';

        box.innerHTML = h;
      } else {
        var h = '<div class="single-mode-hint">' +
          '<span>当前为全册列表模式，共 ' + bookTexts.length + ' 课。点任意课文「📖 单课精读」可回到单课页面。</span>' +
          '<button class="lnav-btn primary" id="cnBackToSingle">返回单课精读模式</button>' +
          '</div>';
        h += cnText({ book: state.book, q: state.q });
        box.innerHTML = h;
      }

    }

    navWrap.addEventListener("change", function (e) {
      if (e.target.id === "cnBookSel") {
        state.book = e.target.value;
        state.lessonId = "";
        render();
      } else if (e.target.id === "cnUnitSel") {
        var uIdx = parseInt(e.target.value, 10);
        var bts = getBookTexts();
        var uns = getUnits(bts);
        if (uns[uIdx] && uns[uIdx].items.length) {
          state.lessonId = uns[uIdx].items[0].id;
          render();
        }
      } else if (e.target.id === "cnLessonSel") {
        state.lessonId = e.target.value;
        render();
      }
    });

    navWrap.addEventListener("click", function (e) {
      var prev = e.target.closest("#cnPrevBtn");
      var next = e.target.closest("#cnNextBtn");
      var toc = e.target.closest("#cnTocToggle");
      var mode = e.target.closest("#cnModeToggle");
      var clr = e.target.closest("#cnSearchClear");
      var hitChip = e.target.closest(".lnav-hit-chip");
      var tocItem = e.target.closest(".lnav-toc-item");

      if (prev) {
        var bts = getBookTexts();
        var idx = bts.findIndex(function (x) { return x.id === state.lessonId; });
        if (idx > 0) {
          state.lessonId = bts[idx - 1].id;
          render();
        }
      } else if (next) {
        var bts = getBookTexts();
        var idx = bts.findIndex(function (x) { return x.id === state.lessonId; });
        if (idx >= 0 && idx < bts.length - 1) {
          state.lessonId = bts[idx + 1].id;
          render();
        }
      } else if (toc) {
        state.showToc = !state.showToc;
        var p = document.getElementById("cnTocPanel");
        if (p) p.classList.toggle("show", state.showToc);
        toc.classList.toggle("on", state.showToc);
      } else if (mode) {
        state.mode = state.mode === "single" ? "all" : "single";
        render();
      } else if (clr) {
        state.q = "";
        render();
      } else if (hitChip) {
        state.book = hitChip.dataset.book;
        state.lessonId = hitChip.dataset.id;
        state.mode = "single";
        render();
      } else if (tocItem) {
        state.lessonId = tocItem.dataset.id;
        state.showToc = false;
        render();
      }
    });

    box.addEventListener("click", function (e) {
      // 课文知识库拓展标签点击
      var kbTab = e.target.closest(".kb-tab");
      if (kbTab) {
        var k = kbTab.getAttribute("data-k");
        ON[k] = !ON[k];
        kbTab.classList.toggle("on", !!ON[k]);
        var kbs = box.querySelectorAll('.kb[data-kb="' + k + '"]');
        kbs.forEach(function (d) { d.classList.toggle("show", !!ON[k]); });
        try { localStorage.setItem("cnExtra", JSON.stringify(ON)); } catch (err) {}
      }
      var footNext = e.target.closest("#cnFootNext");
      var footToc = e.target.closest("#cnFootToc");
      var backSingle = e.target.closest("#cnBackToSingle");
      var switchBtn = e.target.closest(".list-mode-switch-btn");

      if (footPrev) {
        var bts = getBookTexts();
        var idx = bts.findIndex(function (x) { return x.id === state.lessonId; });
        if (idx > 0) {
          state.lessonId = bts[idx - 1].id;
          render();
          window.scrollTo({ top: 0, behavior: "smooth" });
        }
      } else if (footNext) {
        var bts = getBookTexts();
        var idx = bts.findIndex(function (x) { return x.id === state.lessonId; });
        if (idx >= 0 && idx < bts.length - 1) {
          state.lessonId = bts[idx + 1].id;
          render();
          window.scrollTo({ top: 0, behavior: "smooth" });
        }
      } else if (footToc) {
        state.showToc = true;
        var p = document.getElementById("cnTocPanel");
        if (p) p.classList.add("show");
        var t = document.getElementById("cnTocToggle");
        if (t) t.classList.add("on");
        window.scrollTo({ top: 0, behavior: "smooth" });
      } else if (backSingle) {
        state.mode = "single";
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      } else if (switchBtn) {
        state.lessonId = switchBtn.dataset.tid;
        state.mode = "single";
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    });

    render();
  }

  /* ============================================================== 英语单课精学模块 */
  function renderEnglishDiscourse(box) {
    var allDialogues = D.dialogues || [];
    var allPassages = D.passages || [];
    var books = D.books || [];
    if (!books.length) {
      allDialogues.concat(allPassages).forEach(function (x) {
        if (x.book && books.indexOf(x.book) < 0) books.push(x.book);
      });
    }

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
      book: hashBook || getStorage("en_discourse_book", books[0] || "三年级上册"),
      lessonKey: hashLesson || getStorage("en_discourse_lesson", ""),
      mode: "single",
      activeTool: "", // "" | "map" | "today" | "wordbook"
      showToc: false,
      q: ""
    };

    if (books.indexOf(state.book) < 0 && books.length) {
      state.book = books[0];
    }

    var navWrap = document.createElement("div");
    navWrap.className = "lnav-bar";
    insertBeforeNode(app, navWrap, box);

    var toolBox = document.createElement("div");
    toolBox.id = "enToolBox";
    insertBeforeNode(app, toolBox, box);

    function getBookLessons() {
      var bdl = allDialogues.filter(function (x) { return x.book === state.book; });
      var bps = allPassages.filter(function (x) { return x.book === state.book; });
      var unitsMap = {}, order = [];
      function slot(x) {
        var k = String(x.unit_no ? "U" + x.unit_no : (x.unit || "0"));
        if (!unitsMap[k]) {
          unitsMap[k] = { unit: x.unit || "", unit_no: x.unit_no || 0, items: [] };
          order.push(k);
        }
        return unitsMap[k];
      }
      bdl.forEach(function (x) { slot(x).items.push({ data: x, type: "dlg" }); });
      bps.forEach(function (x) { slot(x).items.push({ data: x, type: "pas" }); });
      order.sort(function (a, b) {
        var A = unitsMap[a], B = unitsMap[b];
        return ((A.unit_no || 0) - (B.unit_no || 0)) || String(A.unit).localeCompare(String(B.unit), "zh");
      });
      var result = [];
      order.forEach(function (k) {
        var u = unitsMap[k];
        u.items.forEach(function (it) {
          var kx = lessonKey(it.data, it.type);
          var title = it.type === "dlg" ? (it.data.scene || it.data.title || "对话") : (it.data.name || "短文");
          result.push({
            data: it.data,
            type: it.type,
            key: kx,
            unit_no: u.unit_no,
            unit_name: u.unit,
            title: title
          });
        });
      });
      return { list: result, units: order.map(function (k) { return unitsMap[k]; }) };
    }

    function syncHash() {
      try {
        var newHash = "#" + encodeURIComponent(state.book) + "&lesson=" + encodeURIComponent(state.lessonKey);
        if (loc.hash !== newHash) {
          if (hist && hist.replaceState) hist.replaceState(null, "", newHash);
          else if (loc.replace) loc.replace(newHash);
        }
      } catch (e) {}
    }

    function renderTools(bl) {
      if (!state.activeTool) {
        toolBox.innerHTML = "";
        return;
      }
      var th = '<div class="drawer-card">';
      if (state.activeTool === "map") {
        th += '<div class="drawer-card-header"><span>🗺️ 单元通关地图</span><button class="lnav-btn" id="enCloseTool">收起 ✕</button></div>';
        var unitsObj = {}, orderArr = [];
        bl.units.forEach(function (u, i) {
          var k = state.book + "#U" + u.unit_no;
          unitsObj[k] = { book: state.book, unit: u.unit, unit_no: u.unit_no };
          orderArr.push(k);
        });
        th += renderUnitMap(orderArr, unitsObj, function (u) { return esc(u.book) + " · 第" + u.unit_no + "单元 · " + esc(u.unit); }) + renderBadges();
      } else if (state.activeTool === "today") {
        th += '<div class="drawer-card-header"><span>⚡ 每日 3 分钟打卡</span><button class="lnav-btn" id="enCloseTool">收起 ✕</button></div>';
        th += renderToday();
      } else if (state.activeTool === "wordbook") {
        th += '<div class="drawer-card-header"><span>⭐ 生词本</span><button class="lnav-btn" id="enCloseTool">收起 ✕</button></div>';
        th += renderWordBook();
      }
      th += '</div>';
      toolBox.innerHTML = th;
    }

    function render() {
      setStorage("en_discourse_book", state.book);
      setStorage("en_discourse_lesson", state.lessonKey);
      syncHash();

      var bl = getBookLessons();
      var lessons = bl.list;
      var units = bl.units;

      if (!lessons.length && (allDialogues.length || allPassages.length)) {
        state.book = books[0];
        bl = getBookLessons();
        lessons = bl.list;
        units = bl.units;
      }

      var curIdx = -1;
      if (state.lessonKey) {
        curIdx = lessons.findIndex(function (it) { return it.key === state.lessonKey; });
      }
      if (curIdx < 0 && lessons.length) {
        curIdx = 0;
        state.lessonKey = lessons[0].key;
      }
      var curLesson = curIdx >= 0 ? lessons[curIdx] : null;

      var searchMatches = [];
      if (state.q) {
        var ql = state.q.toLowerCase();
        allDialogues.forEach(function (d) {
          if (has(d.scene, ql) || has(d.function, ql) || has((d.patterns || []).join(" "), ql) || has(d.unit, ql)) {
            searchMatches.push({ book: d.book, key: lessonKey(d, "dlg"), title: "对话: " + (d.scene || d.title || "对话") });
          }
        });
        allPassages.forEach(function (p) {
          if (has(p.name, ql) || has(p.topic, ql) || has(p.genre, ql) || has(p.text, ql) || has(p.unit, ql)) {
            searchMatches.push({ book: p.book, key: lessonKey(p, "pas"), title: "短文: " + (p.name || "短文") });
          }
        });
      }

      var navHtml = '<div class="lnav-row">' +
        '<div class="lnav-group"><span class="lnav-label">📚 册次</span>' +
        '<select class="lnav-sel" id="enBookSel">';
      books.forEach(function (b) {
        navHtml += '<option value="' + esc(b) + '"' + (b === state.book ? ' selected' : '') + '>' + esc(b) + '</option>';
      });
      navHtml += '</select></div>';

      navHtml += '<div class="lnav-group"><span class="lnav-label">📖 单元</span>' +
        '<select class="lnav-sel" id="enUnitSel">';
      units.forEach(function (u, uIdx) {
        var isCur = curLesson && (curLesson.unit_name === u.unit || (u.unit_no && curLesson.unit_no === u.unit_no));
        var sel = isCur ? ' selected' : '';
        navHtml += '<option value="' + uIdx + '"' + sel + '>' +
          (u.unit_no ? 'Unit ' + esc(u.unit_no) + ' · ' : '') + esc(u.unit || '未标单元') + ' (' + u.items.length + '课)</option>';
      });
      navHtml += '</select></div>';

      navHtml += '<div class="lnav-group"><span class="lnav-label">📝 课文</span>' +
        '<select class="lnav-sel" id="enLessonSel">';
      lessons.forEach(function (it, idx) {
        var sel = it.key === state.lessonKey ? ' selected' : '';
        navHtml += '<option value="' + esc(it.key) + '"' + sel + '>' +
          (it.unit_no ? 'U' + it.unit_no + ' ' : '') + '[' + (it.type === 'dlg' ? '对话' : '短文') + '] ' + esc(it.title) + '</option>';
      });
      navHtml += '</select></div>';

      navHtml += '<div class="lnav-group">' +
        '<button class="lnav-btn prev" id="enPrevBtn"' + (curIdx <= 0 ? ' disabled' : '') + '>《 上一课</button>' +
        '<button class="lnav-btn next" id="enNextBtn"' + (curIdx >= lessons.length - 1 ? ' disabled' : '') + '>下一课 》</button>' +
        '<button class="lnav-btn toc-toggle' + (state.showToc ? ' on' : '') + '" id="enTocToggle">📋 目录</button>' +
        '<button class="lnav-btn mode-toggle' + (state.mode === 'single' ? ' on' : '') + '" id="enModeToggle">' +
        (state.mode === 'single' ? '📖 单课精学' : '📑 全册列表') + '</button>' +
        '</div>' +
        '</div>';

      navHtml += '<div class="lnav-search-row">' +
        '<div class="lnav-group">' +
        '<button class="lnav-btn' + (state.activeTool === 'map' ? ' on' : '') + '" id="enToolMap">🗺️ 单元地图</button>' +
        '<button class="lnav-btn' + (state.activeTool === 'today' ? ' on' : '') + '" id="enToolToday">⚡ 每日3分钟</button>' +
        '<button class="lnav-btn' + (state.activeTool === 'wordbook' ? ' on' : '') + '" id="enToolWb">⭐ 生词本</button>' +
        '</div>' +
        '<input class="lnav-search" id="enSearchInput" placeholder="🔍 搜索对话、短文、话题、句型..." value="' + esc(state.q) + '">' +
        (state.q ? '<button class="lnav-btn" id="enSearchClear">清空</button>' : '') +
        (searchMatches.length ? '<div class="lnav-hits"><span>找到 ' + searchMatches.length + ' 篇：</span>' +
          searchMatches.slice(0, 10).map(function (m) {
            return '<span class="lnav-hit-chip" data-book="' + esc(m.book) + '" data-key="' + esc(m.key) + '">' +
              esc(m.book) + ' · ' + esc(m.title) + '</span>';
          }).join('') + (searchMatches.length > 10 ? '<span>...</span>' : '') + '</div>' : (state.q ? '<div class="lnav-hits">未找到匹配的课文</div>' : '')) +
        '</div>';

      navHtml += '<div class="lnav-toc-panel' + (state.showToc ? ' show' : '') + '" id="enTocPanel">';
      units.forEach(function (u) {
        navHtml += '<div class="lnav-toc-unit">' +
          '<div class="lnav-toc-utitle">' + esc(state.book) + ' · ' +
          (u.unit_no ? 'Unit ' + esc(u.unit_no) + ' · ' : '') + esc(u.unit || '未标单元') + '</div>' +
          '<div class="lnav-toc-items">' +
          u.items.map(function (it) {
            var kx = lessonKey(it.data, it.type);
            var isAct = kx === state.lessonKey;
            var tit = it.type === "dlg" ? (it.data.scene || it.data.title || "对话") : (it.data.name || "短文");
            return '<a class="lnav-toc-item' + (isAct ? ' active' : '') + '" data-key="' + esc(kx) + '">' +
              '[' + (it.type === 'dlg' ? '对话' : '短文') + '] ' + esc(tit) +
              '</a>';
          }).join('') +
          '</div></div>';
      });
      navHtml += '</div>';

      navWrap.innerHTML = navHtml;
      renderTools(bl);

      if (state.mode === "single" && curLesson) {
        var it = curLesson;
        var prevLesson = curIdx > 0 ? lessons[curIdx - 1] : null;
        var nextLesson = curIdx < lessons.length - 1 ? lessons[curIdx + 1] : null;

        var h = "";
        h += '<div class="unit-banner">' +
          '<div class="unit-banner-top">' +
          '<div class="unit-banner-title">' + esc(state.book) + ' · ' +
          (it.unit_no ? 'Unit ' + esc(it.unit_no) + ' · ' : '') + esc(it.unit_name || '未标单元') + '</div>' +
          '<div class="unit-banner-tags">' +
          '<span class="tag d1">' + (it.type === 'dlg' ? '情境对话' : '阅读短文') + '</span>' +
          '<span class="tag">第 ' + (curIdx + 1) + ' / ' + lessons.length + ' 课</span>' +
          '</div></div></div>';

        // 语音点读与整课朗读控制条
        h += '<div class="en-voice-banner">' +
          '<div class="en-voice-left">' +
          '<span class="en-voice-title">🔊 语音伴读与全课朗读</span>' +
          '<span class="en-voice-hint">点句子或单词发音 · 纯正 Piper 离线语音包 (2.5万+ 词条)</span>' +
          '</div>' +
          '<div class="en-voice-actions">' +
          '<button class="en-play-all-btn" id="enBannerPlayAll">▶ 播放整课朗读</button>' +
          (it.type === 'dlg' ? '<button class="lnav-btn" id="enBannerRecAll">🎙️ 角色跟读打卡</button>' : '') +
          '<div class="lnav-group" style="margin:0">' +
          '<span class="lnav-label" style="font-size:12px">发音人</span>' +
          '<select class="lnav-sel" id="enVoiceSel" style="padding:4px 8px;font-size:12px">' +
          '<option value="alan"' + (currentVoice === 'alan' ? ' selected' : '') + '>Alan (英音男声)</option>' +
          '<option value="jenny"' + (currentVoice === 'jenny' ? ' selected' : '') + '>Jenny (美音女声)</option>' +
          '<option value="amy"' + (currentVoice === 'amy' ? ' selected' : '') + '>Amy (英音女声)</option>' +
          '<option value="cori"' + (currentVoice === 'cori' ? ' selected' : '') + '>Cori (美音男声)</option>' +
          '</select>' +
          '<button class="lnav-btn" id="enVoicePreview" style="padding:4px 10px;font-size:12px">🔊 试听</button>' +
          '</div>' +
          '<button class="lnav-btn" id="enToggleZh">🌐 中英对照</button>' +
          '</div>' +
          '</div>';

        // 注册到全局 LESSONS
        LESSONS[it.key] = { data: it.data, type: it.type };

        h += '<div class="lesson-card item" id="el' + curIdx + '">';
        h += enLesson(it.data, it.type, true);
        h += '</div>';

        h += '<div class="lesson-footer-nav">' +
          '<button class="lesson-footer-btn" id="enFootPrev"' + (!prevLesson ? ' disabled' : '') + '>' +
          (prevLesson ? '《 上一课：' + esc(prevLesson.title) : '已是本册第一课') + '</button>' +
          '<button class="lnav-btn" id="enFootToc">📋 本册目录</button>' +
          '<button class="lesson-footer-btn" id="enFootNext"' + (!nextLesson ? ' disabled' : '') + '>' +
          (nextLesson ? '下一课：' + esc(nextLesson.title) + ' 》' : '已是本册最后一课') + '</button>' +
          '</div>';

        box.innerHTML = h;
      } else {
        var h = '<div class="single-mode-hint">' +
          '<span>当前为全册列表模式，共 ' + lessons.length + ' 课。点任意课文「📖 单课精学」可回到单课页面。</span>' +
          '<button class="lnav-btn primary" id="enBackToSingle">返回单课精学模式</button>' +
          '</div>';
        h += enText({ book: state.book, q: state.q });
        box.innerHTML = h;
      }

      bindLessonHubs(box);
    }

    navWrap.addEventListener("change", function (e) {
      stopReadAll();
      stopTtsAudio();
      if (e.target.id === "enBookSel") {
        state.book = e.target.value;
        state.lessonKey = "";
        render();
      } else if (e.target.id === "enUnitSel") {
        var uIdx = parseInt(e.target.value, 10);
        var bl = getBookLessons();
        if (bl.units[uIdx] && bl.units[uIdx].items.length) {
          var firstItem = bl.units[uIdx].items[0];
          state.lessonKey = lessonKey(firstItem.data, firstItem.type);
          render();
        }
      } else if (e.target.id === "enLessonSel") {
        state.lessonKey = e.target.value;
        render();
      }
    });

    navWrap.addEventListener("click", function (e) {
      var prev = e.target.closest("#enPrevBtn");
      var next = e.target.closest("#enNextBtn");
      var toc = e.target.closest("#enTocToggle");
      var mode = e.target.closest("#enModeToggle");
      var clr = e.target.closest("#enSearchClear");
      var tMap = e.target.closest("#enToolMap");
      var tToday = e.target.closest("#enToolToday");
      var tWb = e.target.closest("#enToolWb");
      var hitChip = e.target.closest(".lnav-hit-chip");
      var tocItem = e.target.closest(".lnav-toc-item");

      if (prev) {
        stopReadAll();
        stopTtsAudio();
        var bl = getBookLessons();
        var idx = bl.list.findIndex(function (it) { return it.key === state.lessonKey; });
        if (idx > 0) {
          state.lessonKey = bl.list[idx - 1].key;
          render();
        }
      } else if (next) {
        stopReadAll();
        stopTtsAudio();
        var bl = getBookLessons();
        var idx = bl.list.findIndex(function (it) { return it.key === state.lessonKey; });
        if (idx >= 0 && idx < bl.list.length - 1) {
          state.lessonKey = bl.list[idx + 1].key;
          render();
        }
      } else if (toc) {
        state.showToc = !state.showToc;
        var p = document.getElementById("enTocPanel");
        if (p) p.classList.toggle("show", state.showToc);
        toc.classList.toggle("on", state.showToc);
      } else if (mode) {
        stopReadAll();
        stopTtsAudio();
        state.mode = state.mode === "single" ? "all" : "single";
        render();
      } else if (clr) {
        state.q = "";
        render();
      } else if (tMap) {
        state.activeTool = state.activeTool === "map" ? "" : "map";
        render();
      } else if (tToday) {
        state.activeTool = state.activeTool === "today" ? "" : "today";
        render();
      } else if (tWb) {
        state.activeTool = state.activeTool === "wordbook" ? "" : "wordbook";
        render();
      } else if (hitChip) {
        stopReadAll();
        stopTtsAudio();
        state.book = hitChip.dataset.book;
        state.lessonKey = hitChip.dataset.key;
        state.mode = "single";
        render();
      } else if (tocItem) {
        stopReadAll();
        stopTtsAudio();
        state.lessonKey = tocItem.dataset.key;
        state.showToc = false;
        render();
      }
    });

    toolBox.addEventListener("click", function (e) {
      if (e.target.closest("#enCloseTool")) {
        state.activeTool = "";
        renderTools(getBookLessons());
        var btns = navWrap.querySelectorAll("#enToolMap, #enToolToday, #enToolWb");
        btns.forEach(function (b) { b.classList.remove("on"); });
      }
    });

    box.addEventListener("click", function (e) {
      var footPrev = e.target.closest("#enFootPrev");
      var footNext = e.target.closest("#enFootNext");
      var footToc = e.target.closest("#enFootToc");
      var backSingle = e.target.closest("#enBackToSingle");
      var switchBtn = e.target.closest(".list-mode-switch-btn");
      var bPlayAll = e.target.closest("#enBannerPlayAll");
      var bRecAll = e.target.closest("#enBannerRecAll");
      var vPreview = e.target.closest("#enVoicePreview");
      var tZh = e.target.closest("#enToggleZh");

      if (bPlayAll) {
        var bl = getBookLessons();
        var curIdx = bl.list.findIndex(function (it) { return it.key === state.lessonKey; });
        var it = curIdx >= 0 ? bl.list[curIdx] : null;
        if (!it) return;

        if (it.type === "dlg") {
          var dlgBtn = box.querySelector(".read-all-dlg");
          if (dlgBtn) {
            readAllDialogue(dlgBtn);
            var isReading = dlgBtn.classList.contains("reading");
            bPlayAll.classList.toggle("reading", isReading);
            bPlayAll.textContent = isReading ? "⏹ 停止朗读" : "▶ 播放整课朗读";
          }
        } else if (it.type === "pas") {
          if (bPlayAll.classList.contains("reading")) {
            stopTtsAudio();
            if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (ex) {} }
            bPlayAll.classList.remove("reading");
            bPlayAll.textContent = "▶ 播放整课朗读";
          } else {
            bPlayAll.classList.add("reading");
            bPlayAll.textContent = "⏹ 停止朗读";
            speech(it.data.text, 0.95);
            if (ttsAudio) {
              var origEnded = ttsAudio.onended;
              ttsAudio.onended = function () {
                if (origEnded) origEnded();
                var b = document.getElementById("enBannerPlayAll");
                if (b) { b.classList.remove("reading"); b.textContent = "▶ 播放整课朗读"; }
              };
            }
          }
        }
      } else if (bRecAll) {
        var recBtn = box.querySelector(".rec-all-btn");
        if (recBtn) recBtn.click();
      } else if (vPreview) {
        ttsPreview(currentVoice);
      } else if (tZh) {
        var zhs = box.querySelectorAll(".zh");
        var isHidden = zhs.length > 0 && zhs[0].style.display === "none";
        zhs.forEach(function (z) { z.style.display = isHidden ? "" : "none"; });
        tZh.classList.toggle("on", !isHidden);
      } else if (footPrev) {
        stopReadAll();
        stopTtsAudio();
        var bl = getBookLessons();
        var idx = bl.list.findIndex(function (it) { return it.key === state.lessonKey; });
        if (idx > 0) {
          state.lessonKey = bl.list[idx - 1].key;
          render();
          window.scrollTo({ top: 0, behavior: "smooth" });
        }
      } else if (footNext) {
        stopReadAll();
        stopTtsAudio();
        var bl = getBookLessons();
        var idx = bl.list.findIndex(function (it) { return it.key === state.lessonKey; });
        if (idx >= 0 && idx < bl.list.length - 1) {
          state.lessonKey = bl.list[idx + 1].key;
          render();
          window.scrollTo({ top: 0, behavior: "smooth" });
        }
      } else if (footToc) {
        state.showToc = true;
        var p = document.getElementById("enTocPanel");
        if (p) p.classList.add("show");
        var t = document.getElementById("enTocToggle");
        if (t) t.classList.add("on");
        window.scrollTo({ top: 0, behavior: "smooth" });
      } else if (backSingle) {
        stopReadAll();
        stopTtsAudio();
        state.mode = "single";
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      } else if (switchBtn) {
        stopReadAll();
        stopTtsAudio();
        state.lessonKey = switchBtn.dataset.lkey;
        state.mode = "single";
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    });

    box.addEventListener("change", function (e) {
      if (e.target.id === "enVoiceSel") {
        currentVoice = e.target.value;
        setStorage("tts_voice", currentVoice);
      }
    });

    render();
  }

  /* ============================================================== 数学配套讲解动画识别 */
  function getMatchedMathLabs(u) {
    if (!u) return [];
    var tit = String(u.title || "");
    var pts = (u.points || []).join(" ");
    var txt = tit + " " + pts;
    var labs = [];

    function add(name, labFn, bindFn) {
      try {
        var h = labFn();
        if (h) labs.push({ name: name, html: h, bind: bindFn });
      } catch (e) {}
    }

    if (/万以上数的认识|大数的认识|亿以内|亿以上|1亿有多大|数位顺序|读数和写数/.test(txt)) {
      add("数位顺序表与多位数拆解", placeLab, bindPlace);
      add("1亿有多大探究动画", bignumLab, bindBignum);
    }
    if (/角的度量|量角器|量角\b|角的分类|线和角/.test(txt) && !/三角形|元角分|角、分/.test(tit)) {
      add("量角器与量角动画", angleLab, bindAngle);
    }
    if (/平行四边形和梯形|平行四边形的高|梯形的高|垂直与平行/.test(txt)) {
      add("平行四边形和梯形的高", heightLab, bindHeight);
    }
    if (/笔算乘法|笔算除法|除数是两位数|三位数乘两位数|竖式计算|多位数乘两位数|有余数的除法|除数是一位数的除法/.test(txt)) {
      add("分步竖式拆解动画", vertLab, bindVert);
    }
    if (/位置与方向|方向与位置|寻找宝藏|罗盘|八个方向|路线图/.test(txt)) {
      add("位置与方向罗盘模拟", dirLab, bindDir);
    }
    if (/三角形/.test(tit) || /三角形的内角和|三角形的三边关系|三角形分类/.test(txt)) {
      add("三角形内角和与三边关系", triLab, bindTri);
      add("三角形三边拼插探究", sideLab, bindSide);
    }
    if (/小数的意义和性质|小数的意义|小数数位顺序|小数的计数单位|小数的加法和减法/.test(txt)) {
      add("小数数位与计数单位", decLab, bindDec);
    }
    if (/小数乘法|小数除法|小数乘整数|小数除以整数/.test(txt)) {
      add("小数乘法与位移变化", decMulLab, bindDecMul);
    }
    if (/简易方程|用字母表示数|方程的意义|等式的性质/.test(txt)) {
      add("字母表示数与天平平衡", letterLab, bindLetter);
    }
    if (/因数与倍数|因数和倍数|质数和合数|2、5、3的倍数|百数表/.test(txt)) {
      add("百数表与倍数质数探究", hundredLab, bindHundred);
    }
    if (/分数的意义和性质|分数的意义|真分数和假分数|分数的基本性质/.test(txt)) {
      add("分数折纸与涂色探究", fracLab, bindFrac);
    }
    if (/分数的加法和减法|异分母分数加减法|同分母分数加减法/.test(txt)) {
      add("异分母分数通分加法", fracAddLab, bindFracAdd);
    }
    if (/分数乘法|分数除法|倒数的认识/.test(txt)) {
      add("分数乘除几何模型", fracMulLab, bindFracMul);
    }
    if (/长方体和正方体|长方体的表面积|正方体的表面积|长方体和正方体的体积|展开图/.test(txt)) {
      add("长方体正方体3D展开与折叠", cubeLab, bindCube);
    }
    if ((/圆的认识|圆的周长|圆的面积|割圆术|圆周率/.test(txt) || tit === "圆") && !/圆柱|圆锥/.test(txt)) {
      add("割圆术求周长与面积动画", circleLab, bindCircle);
    }
    if (/圆柱与圆锥|圆柱和圆锥|圆柱的体积|圆锥的体积/.test(txt)) {
      add("圆柱圆锥等底等高倒水实验", cylinderLab, bindCylinder);
    }
    if (/比例的意义|比例的基本性质|正比例|反比例|正比例和反比例/.test(txt)) {
      add("正反比例动态曲线模拟", propLab, bindProp);
    }
    if (/认识负数|负数的认识|正数和负数|生活中的负数/.test(txt)) {
      add("负数温度计与数轴", negLab, bindNeg);
      add("数轴动点探究", axisLab, bindAxis);
    }
    if (/百分数|百分数的意义|百分率|折扣|成数/.test(txt)) {
      add("百分数与百格图探究", percentLab, bindPercent);
    }
    if (/折线统计图|单式折线|复式折线/.test(txt)) {
      add("折线统计图动态绘制", trendLab, bindTrend);
    } else if (/条形统计图|单式条形|复式条形/.test(txt)) {
      add("条形统计图互动演示", barLab, bindBar);
    }
    if (/平均数|移多补少/.test(txt)) {
      add("平均数移多补少动画", avgLab, bindAvg);
    }
    if (/多边形的面积|平行四边形的面积|梯形的面积|三角形的面积|割补/.test(txt)) {
      add("割补法推导多边形面积", cutLab, bindCut);
    }
    if (/公顷和平方千米|面积单位换算/.test(txt)) {
      add("面积单位进率换算", unitLab, bindUnit);
    }
    if (/相遇问题|行程问题|速度、时间和路程/.test(txt)) {
      add("行程问题动画演示", distLab, bindDist);
    }
    if (/运算律|加法模型|乘法模型|数量关系|解决实际问题|线段图分析/.test(txt)) {
      add("线段图解题动画", segLab, bindSeg);
      add("数量关系模型探究", modelLab, bindModel);
    }

    var seen = {}, unique = [];
    labs.forEach(function (l) {
      if (!seen[l.name]) {
        seen[l.name] = true;
        unique.push(l);
      }
    });
    return unique;
  }

  /* ============================================================== 数学单单元精学模块 */
  function renderMathUnitByUnit(box) {
    var allUnits = D.units || [];
    var books = D.books || [];
    if (!books.length) {
      allUnits.forEach(function (u) {
        if (u.book && books.indexOf(u.book) < 0) books.push(u.book);
      });
    }

    var loc = typeof window !== "undefined" && window.location ? window.location : { hash: "" };
    var hist = typeof window !== "undefined" && window.history ? window.history : null;
    var hashBook = "", hashUnit = -1;
    var m = String(loc.hash || "").match(/#([^#&]+)(?:#|&unit=)(\d+)/);
    if (m) {
      hashBook = decodeURIComponent(m[1]);
      hashUnit = parseInt(m[2], 10) || 0;
    }

    var state = {
      book: hashBook || getStorage("ma_unit_book", books[0] || "一年级上册"),
      domain: kind === "all" ? "all" : kind,
      unitIdx: hashUnit >= 0 ? hashUnit : 0,
      mode: "unit",
      showToc: false,
      showAllLabs: false,
      q: ""
    };

    if (books.indexOf(state.book) < 0 && books.length) {
      state.book = books[0];
    }

    var navWrap = document.createElement("div");
    navWrap.className = "lnav-bar";
    insertBeforeNode(app, navWrap, box);

    var labWrap = document.createElement("div");
    labWrap.id = "maLabWrap";
    insertBeforeNode(app, labWrap, box);

    function getBookUnits() {
      return allUnits.filter(function (u) {
        if (kind !== "all" && u.domain !== kind) return false;
        if (state.domain !== "all" && u.domain !== state.domain) return false;
        if (state.book !== "all" && u.book !== state.book) return false;
        return true;
      });
    }

    function syncHash() {
      try {
        var newHash = "#" + encodeURIComponent(state.book) + "&unit=" + state.unitIdx;
        if (loc.hash !== newHash) {
          if (hist && hist.replaceState) hist.replaceState(null, "", newHash);
          else if (loc.replace) loc.replace(newHash);
        }
      } catch (e) {}
    }

    function render() {
      setStorage("ma_unit_book", state.book);
      syncHash();

      var bookUnits = getBookUnits();
      if (!bookUnits.length && state.book !== "all" && books.length) {
        state.book = books[0];
        bookUnits = getBookUnits();
      }

      if (state.unitIdx >= bookUnits.length) {
        state.unitIdx = Math.max(0, bookUnits.length - 1);
      }
      if (state.unitIdx < 0 && bookUnits.length) {
        state.unitIdx = 0;
      }

      var curUnit = bookUnits.length ? bookUnits[state.unitIdx] : null;

      var searchMatches = [];
      if (state.q) {
        var ql = state.q.toLowerCase();
        allUnits.forEach(function (u, i) {
          if (has(u.title, ql) || has(u.points.join(" "), ql)) {
            searchMatches.push({ book: u.book, unitIdx: i, title: u.title, unit: u });
          }
        });
      }

      var navHtml = '<div class="lnav-row">' +
        '<div class="lnav-group"><span class="lnav-label">📚 册次</span>' +
        '<select class="lnav-sel" id="maBookSel">';
      books.forEach(function (b) {
        navHtml += '<option value="' + esc(b) + '"' + (b === state.book ? ' selected' : '') + '>' + esc(b) + '</option>';
      });
      navHtml += '</select></div>';

      if (kind === "all" && D.domains && D.domains.length) {
        navHtml += '<div class="lnav-group"><span class="lnav-label">📐 领域</span>' +
          '<select class="lnav-sel" id="maDomainSel"><option value="all">全部领域</option>';
        D.domains.forEach(function (d) {
          navHtml += '<option value="' + esc(d.key) + '"' + (d.key === state.domain ? ' selected' : '') + '>' + esc(d.name) + '</option>';
        });
        navHtml += '</select></div>';
      }

      navHtml += '<div class="lnav-group"><span class="lnav-label">💡 单元</span>' +
        '<select class="lnav-sel" id="maUnitSel">';
      bookUnits.forEach(function (u, idx) {
        var sel = idx === state.unitIdx ? ' selected' : '';
        navHtml += '<option value="' + idx + '"' + sel + '>' +
          (u.unit_no ? '第' + esc(u.unit_no) + '单元 · ' : '') + esc(u.title) + '</option>';
      });
      navHtml += '</select></div>';

      navHtml += '<div class="lnav-group">' +
        '<button class="lnav-btn prev" id="maPrevBtn"' + (state.unitIdx <= 0 ? ' disabled' : '') + '>《 上一单元</button>' +
        '<button class="lnav-btn next" id="maNextBtn"' + (state.unitIdx >= bookUnits.length - 1 ? ' disabled' : '') + '>下一单元 》</button>' +
        '<button class="lnav-btn toc-toggle' + (state.showToc ? ' on' : '') + '" id="maTocToggle">📋 目录</button>' +
        '<button class="lnav-btn' + (state.showAllLabs ? ' on' : '') + '" id="maLabsToggle">🎬 讲解动画库 (30个)</button>' +
        '<button class="lnav-btn mode-toggle' + (state.mode === 'unit' ? ' on' : '') + '" id="maModeToggle">' +
        (state.mode === 'unit' ? '📐 单单元精学' : '📑 全册列表') + '</button>' +
        '</div>' +
        '</div>';

      navHtml += '<div class="lnav-search-row">' +
        '<input class="lnav-search" id="maSearchInput" placeholder="🔍 搜索知识点、公式、单元..." value="' + esc(state.q) + '">' +
        (state.q ? '<button class="lnav-btn" id="maSearchClear">清空</button>' : '') +
        (searchMatches.length ? '<div class="lnav-hits"><span>找到 ' + searchMatches.length + ' 个单元：</span>' +
          searchMatches.slice(0, 8).map(function (m) {
            return '<span class="lnav-hit-chip" data-book="' + esc(m.book) + '" data-title="' + esc(m.title) + '">' +
              esc(m.book) + ' · ' + esc(m.title) + '</span>';
          }).join('') + (searchMatches.length > 8 ? '<span>...</span>' : '') + '</div>' : (state.q ? '<div class="lnav-hits">未找到匹配的单元</div>' : '')) +
        '</div>';

      navHtml += '<div class="lnav-toc-panel' + (state.showToc ? ' show' : '') + '" id="maTocPanel">';
      navHtml += '<div class="lnav-toc-items">';
      bookUnits.forEach(function (u, idx) {
        var isAct = idx === state.unitIdx;
        navHtml += '<a class="lnav-toc-item' + (isAct ? ' active' : '') + '" data-idx="' + idx + '">' +
          (u.unit_no ? '第' + esc(u.unit_no) + '单元 · ' : '') + esc(u.title) +
          '</a>';
      });
      navHtml += '</div></div>';

      navWrap.innerHTML = navHtml;

      // 渲染动画库展开抽屉
      if (state.showAllLabs) {
        var dh = '<div class="all-labs-drawer" id="maAllLabsDrawer">' +
          '<div class="drawer-card-header">' +
          '<span>🎬 数学交互讲解动画库与工具箱（共 30 个动画与探究工具）</span>' +
          '<button class="lnav-btn" id="maCloseLabs">收起 ✕</button>' +
          '</div>';
        dh += mathLab(kind);
        dh += practiceLab();
        if (kind === "all") dh += lineLab() + trapLab();
        dh += '</div>';
        labWrap.innerHTML = dh;
        try {
          bindMathLab(kind);
          bindPractice();
          if (kind === "all") { bindLine(); bindTrap(); }
        } catch (e) {}
      } else {
        labWrap.innerHTML = "";
      }

      if (state.mode === "unit" && curUnit) {
        var u = curUnit;
        var prevUnit = state.unitIdx > 0 ? bookUnits[state.unitIdx - 1] : null;
        var nextUnit = state.unitIdx < bookUnits.length - 1 ? bookUnits[state.unitIdx + 1] : null;
        var dom = (D.domains || []).find(function (d) { return d.key === u.domain; }) || {};

        var h = "";
        h += '<div class="unit-banner">' +
          '<div class="unit-banner-top">' +
          '<div class="unit-banner-title">' + esc(u.book) + ' · ' +
          (u.unit_no ? '第' + esc(u.unit_no) + '单元 · ' : '') + esc(u.title) + '</div>' +
          '<div class="unit-banner-tags">' +
          '<span class="tag d' + Math.max(0, (D.domains || []).findIndex(function (d) { return d.key === u.domain; })) + '">' + esc(dom.name || '') + '</span>' +
          (u.page_from ? '<span class="where">P' + esc(u.page_from) + (u.page_to ? '-' + esc(u.page_to) : '') + '</span>' : '') +
          '<span class="tag">第 ' + (state.unitIdx + 1) + ' / ' + bookUnits.length + ' 单元</span>' +
          '</div></div></div>';

        // 插入本单元配套讲解动画
        var matched = getMatchedMathLabs(u);
        if (matched.length > 0) {
          h += '<div class="unit-lab-matched">' +
            '<div class="unit-lab-title">' +
            '<span>🎬 本单元配套讲解动画（' + matched.length + ' 个互动探究实验）</span>' +
            '<span class="unit-lab-badge">课本配套动态演示</span>' +
            '</div>';
          matched.forEach(function (ml) {
            h += ml.html;
          });
          h += '</div>';
        }

        h += '<div class="lesson-card">';
        h += mathUnit(u, state.unitIdx);
        h += '</div>';

        h += '<div class="lesson-footer-nav">' +
          '<button class="lesson-footer-btn" id="maFootPrev"' + (!prevUnit ? ' disabled' : '') + '>' +
          (prevUnit ? '《 上一单元：' + esc(prevUnit.title) : '已是本册第一单元') + '</button>' +
          '<button class="lnav-btn" id="maFootToc">📋 本册单元目录</button>' +
          '<button class="lesson-footer-btn" id="maFootNext"' + (!nextUnit ? ' disabled' : '') + '>' +
          (nextUnit ? '下一单元：' + esc(nextUnit.title) + ' 》' : '已是本册最后一单元') + '</button>' +
          '</div>';

        box.innerHTML = h;

        // 绑定配套动画交互事件
        matched.forEach(function (ml) {
          if (ml.bind) {
            try { ml.bind(); } catch (err) {}
          }
        });
      } else {
        var h = '<div class="single-mode-hint">' +
          '<span>当前为全册列表模式，共 ' + bookUnits.length + ' 个单元。点任意单元「📐 单单元精学」可回到单单元页面。</span>' +
          '<button class="lnav-btn primary" id="maBackToSingle">返回单单元精学模式</button>' +
          '</div>';
        h += unitToc(bookUnits) + (byGroup(bookUnits, { book: state.book, tab: state.domain }, function (u) {
          var d = (D.domains || []).find(function (x) { return x.key === u.domain; });
          return d ? d.name : "";
        }, function (u) {
          return mathUnit(u, bookUnits.indexOf(u));
        }) || '<div class="empty">没有匹配的单元</div>');
        box.innerHTML = h;
      }
    }

    navWrap.addEventListener("change", function (e) {
      if (e.target.id === "maBookSel") {
        state.book = e.target.value;
        state.unitIdx = 0;
        render();
      } else if (e.target.id === "maDomainSel") {
        state.domain = e.target.value;
        state.unitIdx = 0;
        render();
      } else if (e.target.id === "maUnitSel") {
        state.unitIdx = parseInt(e.target.value, 10) || 0;
        render();
      }
    });

    navWrap.addEventListener("click", function (e) {
      var prev = e.target.closest("#maPrevBtn");
      var next = e.target.closest("#maNextBtn");
      var toc = e.target.closest("#maTocToggle");
      var labsToggle = e.target.closest("#maLabsToggle");
      var mode = e.target.closest("#maModeToggle");
      var clr = e.target.closest("#maSearchClear");
      var hitChip = e.target.closest(".lnav-hit-chip");
      var tocItem = e.target.closest(".lnav-toc-item");

      if (prev) {
        if (state.unitIdx > 0) {
          state.unitIdx--;
          render();
        }
      } else if (next) {
        var bu = getBookUnits();
        if (state.unitIdx < bu.length - 1) {
          state.unitIdx++;
          render();
        }
      } else if (toc) {
        state.showToc = !state.showToc;
        var p = document.getElementById("maTocPanel");
        if (p) p.classList.toggle("show", state.showToc);
        toc.classList.toggle("on", state.showToc);
      } else if (labsToggle) {
        state.showAllLabs = !state.showAllLabs;
        render();
      } else if (mode) {
        state.mode = state.mode === "unit" ? "all" : "unit";
        render();
      } else if (clr) {
        state.q = "";
        render();
      } else if (hitChip) {
        var b = hitChip.dataset.book;
        var tit = hitChip.dataset.title;
        state.book = b;
        var bu = getBookUnits();
        var hitIdx = bu.findIndex(function (u) { return u.title === tit; });
        state.unitIdx = hitIdx >= 0 ? hitIdx : 0;
        state.mode = "unit";
        render();
      } else if (tocItem) {
        state.unitIdx = parseInt(tocItem.dataset.idx, 10) || 0;
        state.showToc = false;
        render();
      }
    });

    labWrap.addEventListener("click", function (e) {
      if (e.target.closest("#maCloseLabs")) {
        state.showAllLabs = false;
        render();
      }
    });

    box.addEventListener("click", function (e) {
      var footPrev = e.target.closest("#maFootPrev");
      var footNext = e.target.closest("#maFootNext");
      var footToc = e.target.closest("#maFootToc");
      var backSingle = e.target.closest("#maBackToSingle");
      var switchBtn = e.target.closest(".list-mode-switch-btn");

      if (footPrev) {
        if (state.unitIdx > 0) {
          state.unitIdx--;
          render();
          window.scrollTo({ top: 0, behavior: "smooth" });
        }
      } else if (footNext) {
        var bu = getBookUnits();
        if (state.unitIdx < bu.length - 1) {
          state.unitIdx++;
          render();
          window.scrollTo({ top: 0, behavior: "smooth" });
        }
      } else if (footToc) {
        state.showToc = true;
        var p = document.getElementById("maTocPanel");
        if (p) p.classList.add("show");
        var t = document.getElementById("maTocToggle");
        if (t) t.classList.add("on");
        window.scrollTo({ top: 0, behavior: "smooth" });
      } else if (backSingle) {
        state.mode = "unit";
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      } else if (switchBtn) {
        state.unitIdx = parseInt(switchBtn.dataset.mid, 10) || 0;
        state.mode = "unit";
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    });

    render();
  }

  /* 全局键盘翻页支持（左箭头/右箭头） */
  document.addEventListener("keydown", function (e) {
    if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT")) return;
    if (e.key === "ArrowLeft") {
      var btn = document.querySelector(".lnav-btn.prev:not(:disabled)") || document.querySelector(".lesson-footer-btn:first-child:not(:disabled)");
      if (btn) { e.preventDefault(); btn.click(); }
    } else if (e.key === "ArrowRight") {
      var btn = document.querySelector(".lnav-btn.next:not(:disabled)") || document.querySelector(".lesson-footer-btn:last-child:not(:disabled)");
      if (btn) { e.preventDefault(); btn.click(); }
    }
  });
