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


  /* ============================================================== 科学模块 (课文文本 & 科学实验) */

  function formatScienceMd(text) {
    if (!text) return "";
    var s = String(text);
    // Escape HTML first
    s = s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    // Bold: **text**
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // Italic: *text*
    s = s.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    // Code: `code`
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    // Headers: ###, ##, #
    s = s.replace(/^###\s+(.+)$/gm, '<h4 class="sci-subhead">$1</h4>');
    s = s.replace(/^##\s+(.+)$/gm, '<h3 class="sci-sec-title">$1</h3>');
    s = s.replace(/^#\s+(.+)$/gm, '<h2 class="sci-sec-title">$1</h2>');
    // Horizontal rule: ---
    s = s.replace(/^---$/gm, '<hr class="sci-divider">');
    // Lists: - item or * item
    s = s.replace(/^[-*]\s+(.+)$/gm, '<li class="sci-list-item">$1</li>');
    s = s.replace(/((?:<li class="sci-list-item">.*<\/li>\s*)+)/g, '<ul class="sci-list">$1</ul>');
    // Numbered lists: 1. item
    s = s.replace(/^\d+\.\s+(.+)$/gm, '<li class="sci-num-item">$1</li>');
    s = s.replace(/((?:<li class="sci-num-item">.*<\/li>\s*)+)/g, '<ol class="sci-num-list">$1</ol>');
    // Paragraphs
    var paragraphs = s.split(/\n{2,}/);
    var res = [];
    for (var i = 0; i < paragraphs.length; i++) {
      var p = paragraphs[i].trim();
      if (!p) continue;
      if (p.indexOf("<h") === 0 || p.indexOf("<ul") === 0 || p.indexOf("<ol") === 0 || p.indexOf("<hr") === 0) {
        res.push(p);
      } else {
        res.push("<p>" + p.replace(/\n/g, "<br>") + "</p>");
      }
    }
    return res.join("");
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
        var sec = curLesson.sections || {};
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
          '<span style="color:#64748b;font-size:13px;margin-left:auto;">' + esc(curLesson.book) + ' · ' + esc(curLesson.unit_title) + '</span>' +
          '</div>' +
          '<h1 class="lesson-title" style="margin:12px 0 6px;">第' + curLesson.lesson_no + '课 ' + esc(curLesson.title) + '</h1>' +
          '</div>';

        // 核心学习环节卡片
        html += '<div class="lesson-body-content">';

        // 1. 🎯 聚焦 Focus
        if (sec.focus) {
          html += '<div class="sci-sec-card focus">' +
            '<div class="sci-sec-head">🎯 聚焦 · 科学问题与真实情境</div>' +
            '<div class="sci-sec-body">' + formatScienceMd(sec.focus) + '</div>' +
            '</div>';
        }

        // 2. 🔬 探索 Exploration
        if (sec.exploration) {
          html += '<div class="sci-sec-card exploration">' +
            '<div class="sci-sec-head">🔬 探索 · 观察实验与探究过程</div>' +
            '<div class="sci-sec-body">' + formatScienceMd(sec.exploration) + '</div>' +
            '</div>';
        }

        // 3. 🧪 配套交互科学微实验 (Simulation Embed)
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

        // 4. 💬 研讨 Discussion
        if (sec.discussion) {
          html += '<div class="sci-sec-card discussion">' +
            '<div class="sci-sec-head">💬 研讨 · 思维碰撞与事实论证</div>' +
            '<div class="sci-sec-body">' + formatScienceMd(sec.discussion) + '</div>' +
            '</div>';
        }

        // 5. 🚀 拓展 Expansion
        if (sec.expansion) {
          html += '<div class="sci-sec-card expansion">' +
            '<div class="sci-sec-head">🚀 拓展 · 迁移应用与实践探究</div>' +
            '<div class="sci-sec-body">' + formatScienceMd(sec.expansion) + '</div>' +
            '</div>';
        }

        // 6. 🌐 科学家视野与前沿深度卡片 (Frontier, Big Concept, Misconception)
        if (sec.frontier || sec.big_concept || sec.misconception) {
          html += '<div class="sci-frontier-box">' +
            '<div class="sci-frontier-title">🚀 科学家视野 · 深度课外拓展与跨学科思维</div>';

          if (sec.frontier) {
            html += '<div class="sci-frontier-item"><b>🌐 前沿科技链接：</b>' +
              '<div style="margin-top:4px;">' + formatScienceMd(sec.frontier) + '</div></div>';
          }
          if (sec.big_concept) {
            html += '<div class="sci-frontier-item"><b>💡 跨学科大概念：</b>' +
              '<div style="margin-top:4px;">' + formatScienceMd(sec.big_concept) + '</div></div>';
          }
          if (sec.misconception) {
            html += '<div class="sci-frontier-item"><b>⚠️ 前概念迷思纠偏：</b>' +
              '<div style="margin-top:4px;">' + formatScienceMd(sec.misconception) + '</div></div>';
          }
          html += '</div>';
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
              (x.sections && (has(x.sections.focus, state.q) || has(x.sections.exploration, state.q) || has(x.sections.frontier, state.q)));
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
            html += '<div class="item" style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 16px;margin-bottom:8px;background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;">' +
              '<div style="flex:1;">' +
              '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">' +
              '<span class="tag d1">' + esc(ls.domain_cn || ls.domain) + '</span>' +
              '<span class="tag d2">' + esc(ls.book) + '</span>' +
              '<span style="font-weight:700;font-size:16px;color:#0f172a;">第' + ls.lesson_no + '课 ' + esc(ls.title) + '</span>' +
              '</div>' +
              '<div style="font-size:13px;color:#64748b;">' + esc(ls.unit_title) + (ls.sections && ls.sections.focus ? ' · 🎯 ' + esc(ls.sections.focus) : '') + '</div>' +
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

    // 汇总全部 287 个实验 (15 master + 260 lesson sims)
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
      activeSim: simList.length ? simList[0] : null // 默认加载第一个大师沙盒
    };

    function render() {
      // 过滤列表
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

      html += '</div>'; // end sim-wrapper
      box.innerHTML = html;

      // 绑定领域筛选按钮
      var domBtns = box.querySelectorAll(".sim-domain-pill");
      domBtns.forEach(function (btn) {
        btn.addEventListener("click", function () {
          state.domain = btn.dataset.dom;
          render();
        });
      });

      // 绑定年级选择
      var bSel = document.getElementById("simBookSel");
      if (bSel) bSel.addEventListener("change", function () {
        state.book = bSel.value;
        render();
      });

      // 绑定搜索
      var sInp = document.getElementById("simSearch");
      if (sInp) sInp.addEventListener("input", function () {
        state.q = sInp.value.trim().toLowerCase();
        render();
      });

      // 绑定实验台按钮
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

      // 绑定卡片点击运行
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
