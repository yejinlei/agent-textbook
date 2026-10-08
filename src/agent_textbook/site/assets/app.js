/* 小学知识大全 —— 页面渲染
   数据由构建脚本内联（window.DATA），这里只做筛选与排版，
   没有网络请求，file:// 直接打开即可。 */

(function () {
  var page = document.body.dataset.page || "index";
  var D = window.DATA || {};
  var app = document.getElementById("app");

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function has(s, q) { return !q || String(s || "").toLowerCase().indexOf(q) >= 0; }

  /* 工具条：领域页签 + 册次下拉 + 搜索框 */
  function tools(domains, onChange, extra) {
    var st = { tab: "all", book: "all", q: "", extra: "" };
    var books = [];
    (D.units || D.texts || D.vocab || []).forEach(function (x) {
      if (x.book && books.indexOf(x.book) < 0) books.push(x.book);
    });
    var wrap = document.createElement("div");
    wrap.className = "tools";
    var html = '<span class="tab on" data-t="all">全部</span>';
    domains.forEach(function (d, i) {
      html += '<span class="tab" data-t="' + d.key + '">' + esc(d.name) + "</span>";
    });
    html += '<select id="bk"><option value="all">全部册次</option>';
    books.forEach(function (b) { html += '<option value="' + esc(b) + '">' + esc(b) + "</option>"; });
    html += "</select>";
    if (extra) {
      html += '<select id="ex"><option value="all">' + esc(extra.label) + "</option>";
      extra.opts.forEach(function (o) { html += '<option value="' + esc(o) + '">' + esc(o) + "</option>"; });
      html += "</select>";
    }
    html += '<input id="q" placeholder="输入关键词筛选（如 分数、比喻、can）">';
    html += '<span class="count" id="cnt"></span>';
    wrap.innerHTML = html;
    app.appendChild(wrap);

    function fire() { onChange(st, document.getElementById("cnt")); }
    wrap.addEventListener("click", function (e) {
      var t = e.target.closest(".tab");
      if (!t) return;
      [].forEach.call(wrap.querySelectorAll(".tab"), function (x) { x.classList.remove("on"); });
      t.classList.add("on");
      st.tab = t.dataset.t;
      fire();
    });
    wrap.addEventListener("change", function (e) {
      if (e.target.id === "bk") st.book = e.target.value;
      if (e.target.id === "ex") st.extra = e.target.value;
      fire();
    });
    wrap.addEventListener("input", function (e) {
      if (e.target.id === "q") st.q = e.target.value.trim().toLowerCase(), fire();
    });
    return { st: st, fire: fire };
  }

  function listBox() {
    var d = document.createElement("div");
    d.id = "list";
    app.appendChild(d);
    return d;
  }

  function item(inner) {
    return '<div class="item">' + inner + "</div>";
  }
  function where(x, page) {
    return '<span class="where">' + esc(x.book || "") +
      (x.unit_no ? " · 第" + esc(x.unit_no) + "单元" : "") +
      (x.unit && x.unit_no == null ? " · " + esc(x.unit) : "") +
      (page ? " · P" + esc(page) : "") + "</span>";
  }
  function points(x, label) {
    if (!x.points || !x.points.length) return "";
    return '<p class="small" style="margin:8px 0 2px">' + (label || "知识点") +
      "</p>" + '<ul class="pts">' + x.points.map(function (p) {
      return "<li>" + esc(p) + "</li>";
    }).join("") + "</ul>";
  }

  /* ------------------------------------------------------------ 数学 */
  function renderMath() {
    var box = listBox();
    var t = tools(D.domains, function (st, cnt) {
      var rows = D.units.filter(function (u) {
        if (st.tab !== "all" && u.domain !== st.tab) return false;
        if (st.book !== "all" && u.book !== st.book) return false;
        if (st.q && !(has(u.title, st.q) || has(u.points.join(" "), st.q))) return false;
        return true;
      });
      cnt.textContent = rows.length + " 个单元";
      box.innerHTML = rows.map(function (u) {
        var lit = (u.literacy || []).map(function (x) {
          return '<span class="tag">' + esc(x) + "</span>";
        }).join("");
        var h = '<div class="top"><span class="name">' + esc(u.title) + "</span>" +
          where(u, u.page_from) + '<span class="tag d' +
          (D.domains.findIndex(function (d) { return d.key === u.domain; })) + '">' +
          esc((D.domains.find(function (d) { return d.key === u.domain; }) || {}).name) +
          "</span>" + lit + "</div>" + points(u);
        if (u.measures && u.measures.length) {
          h += '<div class="words">' + u.measures.slice(0, 10).map(function (m) {
            return '<span class="wb">' + esc(m.name || m) +
              (m.rate ? " <i>" + esc(m.rate) + "</i>" : "") + "</span>";
          }).join("") + "</div>";
        }
        if (u.map && u.map.nodes && u.map.nodes.length) {
          h += "<details><summary>知识结构图（" + u.map.nodes.length + " 节点" +
            (u.map.topic ? "：" + esc(u.map.topic) : "") + "）</summary>" +
            tree(u.map.nodes) + "</details>";
        }
        return item(h);
      }).join("") || '<div class="empty">没有匹配的单元</div>';
    });
    t.fire();
    measureTable();
  }

  function tree(nodes) {
    var byParent = {}, root = [];
    nodes.forEach(function (n) {
      var p = n.parent || 0;
      (byParent[p] = byParent[p] || []).push(n);
    });
    nodes.forEach(function (n) { if (!n.parent) root.push(n); });
    var out = [];
    function walk(n, depth) {
      out.push('<li><span class="node" style="--d:' + (depth * 18) + 'px' +
        (depth ? "" : ";font-weight:600") + '">' +
        (depth ? "└ " : "") + esc(n.text) + "</span></li>");
      (byParent[n.id] || []).forEach(function (c) { walk(c, depth + 1); });
    }
    (root.length ? root : nodes).forEach(function (n) { walk(n, 0); });
    return '<ul class="tree">' + out.join("") + "</ul>";
  }

  function measureTable() {
    if (!D.measures || !D.measures.length) return;
    var seen = {}, rows = [];
    D.measures.forEach(function (m) {
      var k = (m.name || "") + "|" + (m.rate || "");
      if (!seen[k] && m.name) { seen[k] = 1; rows.push(m); }
    });
    var h = document.createElement("div");
    h.innerHTML = "<h2>计量单位与进率</h2>" +
      '<div class="card"><div class="words">' + rows.slice(0, 160).map(function (m) {
        return '<span class="wb">' + esc(m.name) +
          (m.rate ? " <i>" + esc(m.rate) + "</i>" : "") + "</span>";
      }).join("") + "</div>" +
      '<p class="small" style="margin-top:8px">共 ' + rows.length +
      " 条单位（去重后），来自各册正文与整理复习页。</p></div>";
    app.appendChild(h);
  }

  /* ------------------------------------------------------------ 语文 */
  function renderChinese() {
    var box = listBox();
    var t = tools(D.domains, function (st, cnt) {
      var h = "";
      if (st.tab === "all" || st.tab === "literacy") h += literacy(st);
      if (st.tab === "all" || st.tab === "reading") h += reading(st);
      if (st.tab === "all" || st.tab === "writing") h += writing(st);
      if (st.tab === "all" || st.tab === "inquiry") h += inquiry(st);
      cnt.textContent = (box.querySelectorAll(".item,.wb").length || 0) + " 条";
      box.innerHTML = h || '<div class="empty">没有匹配的内容</div>';
      var n = box.querySelectorAll(".item,.wb").length;
      cnt.textContent = n + " 条";
    });
    t.fire();
  }

  function booksOf() {
    var bs = Object.keys(D.words || {});
    (D.texts || []).forEach(function (x) { if (x.book && bs.indexOf(x.book) < 0) bs.push(x.book); });
    return bs.sort();
  }

  function literacy(st) {
    if (!D.words) return "";
    var h = "<h2>识字与写字</h2>";
    booksOf().forEach(function (b) {
      if (st.book !== "all" && st.book !== b) return;
      var kinds = D.words[b] || {};
      h += '<div class="item"><div class="top"><span class="name">' + esc(b) +
        "</span></div>";
      (D.word_kinds || Object.keys(kinds)).forEach(function (k) {
        var ws = kinds[k] || [];
        if (!ws.length) return;
        if (st.q) {
          var f = ws.filter(function (w) { return has(w[0], st.q) || has(w[1], st.q); });
        } else f = ws;
        h += '<p class="small" style="margin:8px 0 2px">' + esc(k) + "（" +
          ws.length + " 条" + (st.q ? "，匹配 " + f.length : "") + "）</p>";
        h += '<div class="words">' + f.slice(0, 240).map(function (w) {
          return '<span class="wb">' + esc(w[0]) +
            (w[1] ? " <i>" + esc(w[1]) + "</i>" : "") + "</span>";
        }).join("") + (f.length > 240 ? '<span class="wb">…</span>' : "") + "</div>";
      });
      h += "</div>";
    });
    return h;
  }

  function reading(st) {
    var h = "<h2>阅读与鉴赏</h2>";
    h += '<p class="lead">单元语文要素就是这一单元要练的阅读本领，教材印在单元导语页上。' +
      "下面按册次列出，后面的课文就是练它的材料。</p>";
    (D.elements || []).forEach(function (e) {
      if (st.book !== "all" && e.book !== st.book) return;
      if (st.q && !(has(e.reading, st.q) || has(e.theme, st.q) || has(e.unit_title, st.q))) return;
      if (!e.reading && !e.theme) return;
      h += item('<div class="top"><span class="name">' +
        esc(e.unit_title || ("第" + e.unit_no + "单元")) + "</span>" +
        where(e, e.page) + "</div>" +
        (e.theme ? '<p class="small">' + esc(e.theme) + "</p>" : "") +
        (e.reading ? "<div><b>阅读要素：</b>" + esc(e.reading) + "</div>" : "") +
        (e.writing ? '<div style="color:#196f3d"><b>习作要素：</b>' + esc(e.writing) + "</div>" : "") +
        points(e, "要素要点"));
    });
    var texts = (D.texts || []).filter(function (x) {
      return x.domain === "reading" || (!x.domain && x.section === "阅读");
    }).filter(function (x) {
      if (st.book !== "all" && x.book !== st.book) return false;
      if (st.q && !(has(x.title, st.q) || has(x.genre, st.q) || has(x.author, st.q))) return false;
      return true;
    });
    h += '<h2>课文（' + texts.length + " 篇）</h2>";
    var byBook = {};
    texts.forEach(function (x) { (byBook[x.book] = byBook[x.book] || []).push(x); });
    Object.keys(byBook).sort().forEach(function (b) {
      h += '<div class="item"><div class="top"><span class="name">' + esc(b) +
        "</span><span class=\"where\">" + byBook[b].length + " 篇</span></div>";
      h += '<div class="words">' + byBook[b].map(function (x) {
        return '<span class="wb">' + esc(x.title) +
          (x.genre ? " <i>" + esc(x.genre) + "</i>" : "") + "</span>";
      }).join("") + "</div></div>";
    });
    return h;
  }

  function writing(st) {
    var h = "<h2>表达与交流</h2>";
    h += '<p class="lead">习作要素即习作量规：要求来自教材，写完可以逐条对着看。</p>';
    (D.elements || []).forEach(function (e) {
      if (!e.writing) return;
      if (st.book !== "all" && e.book !== st.book) return;
      if (st.q && !has(e.writing, st.q)) return;
      h += item('<div class="top"><span class="name">' + esc(e.book) + " 第" +
        esc(e.unit_no) + "单元</span></div><div>" + esc(e.writing) + "</div>");
    });
    var texts = (D.texts || []).filter(function (x) {
      return x.domain === "writing";
    }).filter(function (x) {
      if (st.book !== "all" && x.book !== st.book) return false;
      if (st.q && !has(x.title, st.q)) return false;
      return true;
    });
    h += '<h2>习作 · 口语交际 · 习作例文（' + texts.length + " 条）</h2>";
    var byBook = {};
    texts.forEach(function (x) { (byBook[x.book] = byBook[x.book] || []).push(x); });
    Object.keys(byBook).sort().forEach(function (b) {
      h += '<div class="item"><div class="top"><span class="name">' + esc(b) +
        "</span></div>" + '<ul class="pts">' +
        byBook[b].map(function (x) {
          return "<li>" + esc(x.title) + ' <span class="tag">' + esc(x.section) + "</span>" +
            (x.page ? ' <span class="where">P' + esc(x.page) + "</span>" : "") + "</li>";
        }).join("") + "</ul></div>";
    });
    return h;
  }

  function inquiry(st) {
    var texts = (D.texts || []).filter(function (x) { return x.domain === "inquiry"; });
    var h = "<h2>梳理与探究</h2>";
    if (!texts.length) {
      h += '<div class="empty">教材目录里没有单独标出"综合性学习 / 快乐读书吧"的条目' +
        "（这部分通常印在单元末尾的语文园地里）。</div>";
      return h;
    }
    h += '<ul class="pts">' + texts.filter(function (x) {
      if (st.book !== "all" && x.book !== st.book) return false;
      return !st.q || has(x.title, st.q);
    }).map(function (x) {
      return "<li>" + esc(x.book) + " · " + esc(x.title) + "</li>";
    }).join("") + "</ul>";
    return h;
  }

  /* ------------------------------------------------------------ 英语 */
  function renderEnglish() {
    var box = listBox();
    var t = tools(D.domains, function (st, cnt) {
      var h = "", n = 0;
      function count(s) { n += (s.match(/class="(item|wb)"/g) || []).length; return s; }
      if (st.tab === "all" || st.tab === "phonics") h += count(phonics(st));
      if (st.tab === "all" || st.tab === "vocab") h += count(evocab(st));
      if (st.tab === "all" || st.tab === "grammar") h += count(egrammar(st));
      if (st.tab === "all" || st.tab === "discourse") h += count(discourse(st));
      if (st.tab === "all" || st.tab === "use") h += count(use(st));
      box.innerHTML = h || '<div class="empty">没有匹配的内容</div>';
      cnt.textContent = box.querySelectorAll(".item,.wb").length + " 条";
    }, { label: "按主题范畴", opts: D.themes || [] });
    t.fire();
  }

  function filterBy(lst, st, fields) {
    return (lst || []).filter(function (x) {
      if (st.book !== "all" && x.book !== st.book) return false;
      if (st.extra && st.extra !== "all" && x.theme !== st.extra) return false;
      if (st.q) {
        var s = fields.map(function (f) { return x[f]; }).join(" ");
        if (!has(s, st.q)) return false;
      }
      return true;
    }).filter(function (x) {
      return !st.extra || st.extra === "all" || !x.theme || x.theme === st.extra;
    });
  }

  function groupByBook(lst) {
    var m = {};
    lst.forEach(function (x) { (m[x.book] = m[x.book] || []).push(x); });
    return m;
  }

  function phonics(st) {
    var rows = filterBy(D.phonics, st, ["letters", "sound", "examples", "chant"]);
    var h = "<h2>语音与拼读</h2>";
    var m = groupByBook(rows);
    Object.keys(m).sort().forEach(function (b) {
      h += '<div class="item"><div class="top"><span class="name">' + esc(b) +
        "</span></div>" + '<div class="words">' + m[b].map(function (x) {
          return '<span class="wb">' + esc(x.letters || x.sound) +
            (x.sound ? " <i>" + esc(x.sound) + "</i>" : "") + "</span>";
        }).join("") + "</div>";
      m[b].slice(0, 3).forEach(function (x) {
        if (x.chant) h += '<p class="small">' + esc(x.chant.slice(0, 120)) + "</p>";
      });
      h += "</div>";
    });
    return h;
  }

  function evocab(st) {
    var rows = filterBy(D.vocab, st, ["word", "meaning", "topic"]);
    var h = "<h2>词汇</h2>";
    var m = groupByBook(rows);
    Object.keys(m).sort().forEach(function (b) {
      h += '<div class="item"><div class="top"><span class="name">' + esc(b) +
        '</span><span class="where">' + m[b].length + " 词</span></div>" +
        '<div class="words">' + m[b].slice(0, 300).map(function (x) {
          return '<span class="wb">' + esc(x.word) + " <i>" + esc(x.meaning || "") +
            "</i></span>";
        }).join("") + "</div></div>";
    });
    return h;
  }

  function egrammar(st) {
    var rows = filterBy(D.grammar, st, ["point", "pattern", "rule", "category"]);
    var h = "<h2>语法与句型</h2>";
    rows.forEach(function (x) {
      h += item('<div class="top"><span class="name">' + esc(x.point) + "</span>" +
        where(x) + (x.category ? '<span class="tag">' + esc(x.category) + "</span>" : "") +
        "</div>" + (x.pattern ? '<div><b>句型：</b><code>' + esc(x.pattern) + "</code></div>" : "") +
        (x.rule ? '<p class="small">' + esc(x.rule) + "</p>" : ""));
    });
    return h;
  }

  function discourse(st) {
    var ps = filterBy(D.passages, st, ["name", "genre", "text", "topic"]);
    var dl = filterBy(D.dialogues, st, ["scene", "function", "turns"]);
    var h = "<h2>语篇与对话</h2>";
    ps.slice(0, 120).forEach(function (x) {
      h += item('<div class="top"><span class="name">' + esc(x.name) + "</span>" +
        where(x) + (x.genre ? '<span class="tag">' + esc(x.genre) + "</span>" : "") +
        '</div><details><summary>看原文</summary><pre class="lyric">' +
        esc(x.text) + "</pre></details>");
    });
    h += "<h2>情景对话</h2>";
    dl.slice(0, 120).forEach(function (x) {
      var turns = (x.turns || []).map(function (t) {
        return typeof t === "string" ? t : (t.speaker ? t.speaker + "：" : "") + (t.text || t.line || "");
      });
      h += item('<div class="top"><span class="name">' + esc(x.scene) + "</span>" +
        where(x) + (x.function ? '<span class="tag">' + esc(x.function) + "</span>" : "") +
        "</div>" + (turns.length ? '<ul class="pts">' + turns.map(function (t) {
          return "<li>" + esc(t) + "</li>";
        }).join("") + "</ul>" : ""));
    });
    return h;
  }

  function use(st) {
    var h = "<h2>综合运用</h2>";
    var sg = filterBy(D.songs, st, ["name", "topic", "lyrics"]);
    if (sg.length) {
      h += "<h3>歌谣</h3>";
      sg.slice(0, 60).forEach(function (x) {
        h += item('<div class="top"><span class="name">' + esc(x.name) + "</span>" +
          where(x) + (x.topic ? '<span class="tag">' + esc(x.topic) + "</span>" : "") +
          '</div><pre class="lyric">' + esc((x.lyrics || []).join("\n")) + "</pre>");
      });
    }
    var pj = filterBy(D.projects, st, ["name", "goal", "product", "type"]);
    if (pj.length) {
      h += "<h3>项目任务</h3>";
      pj.slice(0, 80).forEach(function (x) {
        h += item('<div class="top"><span class="name">' + esc(x.name) + "</span>" +
          where(x) + (x.type ? '<span class="tag">' + esc(x.type) + "</span>" : "") +
          "</div>" + (x.goal ? '<p class="small">' + esc(x.goal) + "</p>" : "") +
          (x.product ? '<div>产出：' + esc(x.product) + "</div>" : ""));
      });
    }
    (D.revisions || []).forEach(function (x) {
      if (st.book !== "all" && x.book !== st.book) return;
      h += item('<div class="top"><span class="name">' + esc(x.theme) + "</span>" +
        where(x) + '<span class="tag d3">复习板块</span></div>' +
        ((x.tasks || []).length ? '<ul class="pts">' + x.tasks.map(function (t) {
          return "<li>" + esc(t.name || t) + (t.type ? ' <span class="tag">' + esc(t.type) + "</span>" : "") + "</li>";
        }).join("") + "</ul>" : "") +
        (x.outcome ? "<div><b>产出：</b>" + esc(x.outcome) + "</div>" : ""));
    });
    return h;
  }

  if (page === "math") renderMath();
  else if (page === "chinese") renderChinese();
  else if (page === "english") renderEnglish();
})();
