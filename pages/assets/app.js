/* 小学知识大全 —— 页面渲染
   数据由构建脚本内联（window.DATA），file:// 直接打开即可。
   可视化目标：比纸质书更好用——公式真渲染、结构图可缩放、
   课文中英对照可切换、词汇可自测、语法按范畴汇总。 */

(function () {
  var page = document.body.dataset.page || "index";
  var parts = String(page).split("-"), subject = parts[0], kind = parts[1] || "";
  var D = window.DATA || {};
  var app = document.getElementById("app");

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function has(s, q) { return !q || String(s || "").toLowerCase().indexOf(q) >= 0; }

  /* ---- LaTeX 迷你渲染器：小学范围够用（分数 / 上下标 / 根号 / 常用符号） ---- */
  function tex(s) {
    if (!s) return "";
    var t = esc(s).replace(/\\\\/g, "\\");
    t = t.replace(/\\text\{([^{}]*)\}/g, "$1").replace(/\\mathrm\{([^{}]*)\}/g, "$1");
    for (var i = 0; i < 8 && /\\frac/.test(t); i++) {
      t = t.replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g,
        '<span class="frac"><span class="num">$1</span><span class="den">$2</span></span>');
    }
    t = t.replace(/\\sqrt\{([^{}]*)\}/g,
      '<span class="sqrt">√<span class="rad">$1</span></span>');
    t = t.replace(/\^\{([^{}]*)\}/g, "<sup>$1</sup>")
         .replace(/\^([\w\u4e00-\u9fa5])/g, "<sup>$1</sup>");
    t = t.replace(/_\{([^{}]*)\}/g, "<sub>$1</sub>")
         .replace(/_([\w\u4e00-\u9fa5])/g, "<sub>$1</sub>");
    var sym = { "\\times": "×", "\\div": "÷", "\\cdot": "·", "\\pi": "π",
      "\\leq": "≤", "\\le": "≤", "\\geq": "≥", "\\ge": "≥", "\\neq": "≠",
      "\\approx": "≈", "\\pm": "±", "\\%": "%", "\\degree": "°", "\\circ": "°",
      "\\angle": "∠", "\\triangle": "△", "\\parallel": "∥", "\\perp": "⊥",
      "\\infty": "∞", "\\alpha": "α", "\\beta": "β" };
    Object.keys(sym).forEach(function (k) {
      t = t.split(k).join(sym[k]);
    });
    t = t.replace(/\\[a-zA-Z]+/g, "").replace(/[{}]/g, "");
    return t;
  }

  /* ---- 知识结构图：画成 SVG（可缩放，不像纸质那样印死） ---- */
  function treeSvg(nodes) {
    if (!nodes || !nodes.length) return "";
    var byP = {}, roots = [], i, n;
    nodes.forEach(function (x) { (byP[x.parent || 0] = byP[x.parent || 0] || []).push(x); });
    nodes.forEach(function (x) { if (!x.parent) roots.push(x); });
    if (!roots.length) roots = [nodes[0]];
    var ROW = 30, pos = {}, y = 0;
    function place(nd, depth) {
      var kids = byP[nd.id] || [], ys;
      if (!kids.length) { pos[nd.id] = { y: y, d: depth }; y += ROW; return; }
      kids.forEach(function (c) { place(c, depth + 1); });
      ys = kids.map(function (c) { return pos[c.id].y; })
               .filter(function (v) { return v != null; });
      pos[nd.id] = { y: ys.length ? (Math.min.apply(null, ys) + Math.max.apply(null, ys)) / 2 : y,
                     d: depth };
      if (!ys.length) y += ROW;
    }
    roots.forEach(function (r) { place(r, 0); });
    // 逐层算 x：层宽取该层最长文字
    var W = [], depthMax = 0;
    nodes.forEach(function (x) {
      var p = pos[x.id]; if (!p) return;
      var w = Math.min(220, String(x.text || "").length * 15 + 24);
      W[p.d] = Math.max(W[p.d] || 0, w);
      depthMax = Math.max(depthMax, p.d);
    });
    var X = [], acc = 10;
    for (i = 0; i <= depthMax; i++) { X[i] = acc; acc += (W[i] || 80) + 46; }
    var H = Math.max(y + 20, 60), svgW = acc + 10;
    var out = [];
    nodes.forEach(function (x) {
      var p = pos[x.id]; if (!p) return;
      var w = Math.min(220, String(x.text || "").length * 15 + 24);
      var txt = String(x.text || "");
      if (txt.length > 14) txt = txt.slice(0, 13) + "…";
      var kids = byP[x.id] || [];
      kids.forEach(function (c) {
        var cp = pos[c.id]; if (!cp) return;
        var x1 = X[p.d] + w, y1 = p.y + 13, x2 = X[cp.d], y2 = cp.y + 13;
        out.push('<path d="M' + x1 + " " + y1 + " H" + ((x1 + x2) / 2) +
          " V" + y2 + " H" + x2 + '" fill="none" stroke="#c8bfa8"/>');
      });
      out.push('<rect x="' + X[p.d] + '" y="' + p.y + '" width="' + w +
        '" height="26" rx="6" fill="' + (p.d ? "#fff" : "#fdf3e3") +
        '" stroke="' + (p.d ? "#ddd5c4" : "#c8b26a") + '"/>');
      out.push('<text x="' + (X[p.d] + 10) + '" y="' + (p.y + 18) +
        '" font-size="14" fill="#2f3437">' + esc(txt) + "</text>");
    });
    return '<div class="svgwrap"><svg viewBox="0 0 ' + svgW + " " + H +
      '" width="100%" height="' + H + '">' + out.join("") + "</svg></div>";
  }

  /* ---- 工具条：页签 + 册次 + 搜索（+ 中文对照开关） ---- */
  function tools(domains, onChange, opt) {
    opt = opt || {};
    // view：prog = 按进度（跟着课本走，册次顺序）；topic = 按主题（跨册把同类串起来）
    var st = { tab: "all", book: "all", q: "", extra: "all", view: "prog" };
    var books = D.books || [];
    var wrap = document.createElement("div");
    wrap.className = "tools";
    var html = '<span class="tab on" data-t="all">全部</span>';
    domains.forEach(function (d) {
      html += '<span class="tab" data-t="' + d.key + '">' + esc(d.name) + "</span>";
    });
    html += '<select id="bk"><option value="all">全部册次</option>';
    books.forEach(function (b) { html += '<option>' + esc(b) + "</option>"; });
    html += "</select>";
    if (opt.extra) {
      html += '<select id="ex"><option value="all">' + esc(opt.extra.label) + "</option>";
      opt.extra.opts.forEach(function (o) { html += "<option>" + esc(o) + "</option>"; });
      html += "</select>";
    }
    html += '<input id="q" placeholder="' + (opt.hint || "关键词筛选") + '">';
    if (opt.noView !== true) {
      html += '<span class="views"><span class="vtab on" data-v="prog">按进度</span>' +
        '<span class="vtab" data-v="topic">按主题</span></span>';
    }
    if (opt.zh) html += '<span class="tab" id="zhbtn">中文对照</span>';
    // 常找标签：点一下就等于搜这个词（内容多的时候比翻页快）
    if (opt.tags && opt.tags.length) {
      html += '<div class="tags"><span class="jl">常找</span>' +
        opt.tags.map(function (t) {
          return '<span class="ttag" data-t="' + esc(t) + '">' + esc(t) + "</span>";
        }).join("") + "</div>";
    }
    // 跳到：按当前分组一键定位（分组由 byGroup 回填）
    html += '<div class="jump" id="jump"></div>';
    html += '<span class="count" id="cnt"></span>';
    wrap.innerHTML = html;
    // 列表容器往往先创建：工具条必须插到它前面，否则会被几百条内容压到页底
    var listEl = document.getElementById("list");
    if (listEl && listEl.parentNode === app) app.insertBefore(wrap, listEl);
    else app.appendChild(wrap);

    function fire() { onChange(st, document.getElementById("cnt")); }
    wrap.addEventListener("click", function (e) {
      var v = e.target.closest(".vtab");
      if (v) {
        [].forEach.call(wrap.querySelectorAll(".vtab"),
                        function (x) { x.classList.remove("on"); });
        v.classList.add("on");
        st.view = v.dataset.v;
        fire();
        return;
      }
      var tg = e.target.closest(".ttag");
      if (tg) {
        var qi = document.getElementById("q");
        if (qi) qi.value = tg.dataset.t;
        st.q = (tg.dataset.t || "").toLowerCase();
        [].forEach.call(wrap.querySelectorAll(".ttag"),
                        function (x) { x.classList.remove("on"); });
        tg.classList.add("on");
        fire();
        return;
      }
      var jt = e.target.closest(".jtab");
      if (jt) {
        var g = document.getElementById("g" + jt.dataset.i);
        if (g && g.scrollIntoView) g.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      var t = e.target.closest(".tab");
      if (!t) return;
      if (t.id === "zhbtn") { document.body.classList.toggle("show-zh"); t.classList.toggle("on"); return; }
      [].forEach.call(wrap.querySelectorAll(".tab"), function (x) {
        if (x.id !== "zhbtn") x.classList.remove("on");
      });
      t.classList.add("on");
      st.tab = t.dataset.t;
      fire();
    });
    wrap.addEventListener("change", function (e) {
      if (e.target.id === "bk") st.book = e.target.value;
      if (e.target.id === "ex") st.extra = e.target.value;
      fire();
    });
    var qTimer = null;
    wrap.addEventListener("input", function (e) {
      if (e.target.id !== "q") return;
      st.q = e.target.value.trim().toLowerCase();
      if (qTimer) clearTimeout(qTimer);
      qTimer = setTimeout(fire, 200);   // 课文页数据大，防抖后再过滤
    });
    return { st: st, fire: fire };
  }

  /* 常找标签自动攒：取条目里出现最多的词，不手写、不会过时 */
  function hotTags(rows, field, n) {
    var c = {};
    (rows || []).forEach(function (x) {
      String(x[field] || "").split(/[\s，,、。；;：:（）()【】"“”·0-9]/).forEach(function (w) {
        w = (w || "").trim();
        if (w.length >= 2 && w.length <= 6) c[w] = (c[w] || 0) + 1;
      });
    });
    return Object.keys(c).sort(function (a, b) { return c[b] - c[a]; }).slice(0, n || 16);
  }

  /* 两种学法：按进度（按册分组，课本顺序）／按主题（跨册把同类串起来）。
     数据本身已按 册次→单元→课次 排好，所以分组时不再排序。 */
  function byGroup(rows, st, topicOf, render) {
    var keyOf = (st && st.view === "topic")
      ? function (x) { return topicOf(x) || "其他"; }
      : function (x) { return x.book || "其他"; };
    var g = {}, order = [];
    rows.forEach(function (x) {
      var k = keyOf(x);
      if (!g[k]) { g[k] = []; order.push(k); }
      g[k].push(x);
    });
    var jump = document.getElementById("jump");
    if (jump) {
      jump.innerHTML = order.length > 1 ? '<span class="jl">跳到</span>' +
        order.map(function (k, i) {
          return '<span class="jtab" data-i="' + i + '">' + esc(k) + "</span>";
        }).join("") : "";
    }
    return order.map(function (k, i) {
      return '<h3 class="grp" id="g' + i + '">' + esc(k) + "</h3>" +
        g[k].map(render).join("");
    }).join("");
  }

  function listBox() {
    var d = document.createElement("div");
    d.id = "list";
    app.appendChild(d);
    return d;
  }
  function item(inner) { return '<div class="item">' + inner + "</div>"; }
  function where(x, p) {
    return '<span class="where">' + esc(x.book || "") +
      (x.unit_no ? " · 第" + esc(x.unit_no) + "单元" : "") +
      (x.unit && !x.unit_no ? " · " + esc(x.unit) : "") +
      (p ? " · P" + esc(p) : "") + "</span>";
  }
  function pts(list, label) {
    if (!list || !list.length) return "";
    return '<p class="small">' + (label || "知识点") + "</p><ul class=" + '"pts">' +
      list.map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("") + "</ul>";
  }

  /* ================================================================ 数学 */
  function renderMath() {
    var mh = mathLab(kind);
    if (mh) {
      var el = document.createElement("div");
      el.innerHTML = mh;
      app.appendChild(el);
      bindMathLab(kind);
    }
    var box = listBox();
    // 子页就是领域页，只在"全部单元"页给领域页签
    var t = tools(kind === "all" ? (D.domains || []) : [], function (st, cnt) {
      var rows = (D.units || []).filter(function (u) {
        if (kind !== "all" && u.domain !== kind) return false;
        if (st.tab !== "all" && u.domain !== st.tab) return false;
        if (st.book !== "all" && u.book !== st.book) return false;
        if (st.q && !(has(u.title, st.q) || has(u.points.join(" "), st.q))) return false;
        return true;
      });
      cnt.textContent = rows.length + " 个单元";
      box.innerHTML = byGroup(rows, st, function (u) {
        var d = D.domains.filter(function (x) { return x.key === u.domain; })[0];
        return d ? d.name : "";
      }, mathUnit) || '<div class="empty">没有匹配的单元</div>';
    }, { hint: "如：分数、面积、鸡兔同笼",
         tags: hotTags(D.units, "title", 18) });
    t.fire();
    if (kind === "all") measureTable();
  }

  function mathUnit(u) {
    var dom = D.domains.filter(function (d) { return d.key === u.domain; })[0] || {};
    var lit = (u.literacy || []).map(function (x) {
      return '<span class="tag">' + esc(x) + "</span>";
    }).join("");
    var h = '<div class="top"><span class="name">' + esc(u.title) + "</span>" +
      where(u, u.page_from) + '<span class="tag d' +
      Math.max(0, D.domains.map(function (d) { return d.key; }).indexOf(u.domain)) +
      '">' + esc(dom.name) + "</span>" + lit + "</div>" + pts(u.points);
    // 课本原文：这一单元教材上写的讲解（按进度学时就是"这一课讲了什么"）
    if (u.text && u.text.length) {
      h += "<details><summary>课本原文（" + u.text.length + " 段）</summary>" +
        '<div class="full">' + u.text.map(function (p) {
          return '<p class="para">' + esc(p) + "</p>";
        }).join("") + "</div></details>";
    }
    // 公式：渲染成真公式（分数上下排、指数上标）
    if (u.formulas && u.formulas.length) {
      h += '<p class="small">公式与算式（' + u.formulas.length + "）</p>" +
        '<div class="fboxes">' + u.formulas.map(function (f) {
          return '<span class="fbox"><span class="tex">' + tex(f.latex) + "</span>" +
            '<span class="tag">' + esc(f.kind || "") + "</span>" +
            (f.note ? '<span class="where">' + esc(f.note) + "</span>" : "") + "</span>";
        }).join("") + "</div>";
    }
    // 例题：题干 → 分步 → 答案
    if (u.examples && u.examples.length) {
      h += "<details" + (u.examples.length <= 2 ? " open" : "") +
        "><summary>例题（" + u.examples.length + " 道）</summary>" +
        u.examples.map(function (e) {
          var s = '<div class="ex"><div class="stem">' + esc(e.stem || e.name) + "</div>";
          if (e.given) s += '<div class="given">已知：' + esc(e.given) + "</div>";
          (e.steps || []).forEach(function (stp, i) {
            s += '<div class="step"><b>' + (i + 1) + ".</b> " + esc(stp.text || "") +
              (stp.latex ? ' <span class="tex">' + tex(stp.latex) + "</span>" : "") + "</div>";
          });
          if (e.answer) {
            s += '<div class="ans">答：' + esc(e.answer) +
              (e.answer_latex ? "（" + tex(e.answer_latex) + "）" : "") + "</div>";
          }
          s += (e.difficulty ? '<span class="tag">' + esc(e.difficulty) + "</span>" : "") +
            (e.page ? '<span class="where">' + esc(e.page) + "</span>" : "") + "</div>";
          return s;
        }).join("") + "</details>";
    }
    // 生活里在哪儿用：学这个到底有什么用
    if (u.life && u.life.length) {
      h += '<div class="life">' + u.life.map(function (l) {
        return '<div class="lf"><span class="tag d1">生活里</span>' + esc(l.where) +
          '<span class="ask">算一算：' + esc(l.ask) + "</span></div>";
      }).join("") + "</div>";
    }
    if (u.map && u.map.nodes && u.map.nodes.length) {
      h += "<details><summary>知识结构图（" + u.map.nodes.length + " 节点" +
        (u.map.topic ? "：" + esc(u.map.topic) : "") + "）</summary>" +
        treeSvg(u.map.nodes) + "</details>";
    }
    if (u.measures && u.measures.length) {
      h += '<div class="words">' + u.measures.slice(0, 10).map(function (m) {
        return '<span class="wb">' + esc(m.name || m) +
          (m.rate ? " <i>" + esc(m.rate) + "</i>" : "") + "</span>";
      }).join("") + "</div>";
    }
    return item(h);
  }

  function measureTable() {
    if (!D.measures || !D.measures.length) return;
    var seen = {}, rows = [];
    D.measures.forEach(function (m) {
      var k = (m.name || "") + "|" + (m.rate || "");
      if (!seen[k] && m.name) { seen[k] = 1; rows.push(m); }
    });
    var h = document.createElement("div");
    h.innerHTML = "<h2>计量单位与进率</h2><div class=\"card\"><div class=\"words\">" +
      rows.slice(0, 200).map(function (m) {
        return '<span class="wb">' + esc(m.name) +
          (m.rate ? " <i>" + esc(m.rate) + "</i>" : "") + "</span>";
      }).join("") + '</div><p class="small">共 ' + rows.length +
      " 条（去重），来自各册正文与整理复习页。</p></div>";
    app.appendChild(h);
  }

  /* ================================================================ 语文 */
  function renderChinese() {
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
    var t = tools([], function (st, cnt) {
      var h = "";
      if (kind === "literacy") h = cnLiteracy(st);
      else if (kind === "reading") h = cnReading(st, elems);
      else if (kind === "writing") h = cnWriting(st);
      else if (kind === "poetry") h = cnPoetry(st);
      else h = cnInquiry(st);
      box.innerHTML = h || '<div class="empty">没有匹配的内容</div>';
      var suffix = { reading: " 篇课文", literacy: " 册", writing: " 条",
                     poetry: " 篇" }[kind] || " 组";
      cnt.textContent = box.querySelectorAll(".item").length + suffix;
    }, { noView: true,
         hint: { literacy: "如：春、yī", reading: "如：草原、老舍、比喻",
                 writing: "如：特点、真情实感", poetry: "如：月、山、送别" }[kind] || "关键词",
         tags: kind === "literacy" ? (D.word_kinds || [])
               : kind === "poetry" ? hotTags(D.pieces, "title", 16)
               : hotTags(D.texts, "title", 18) });
    t.fire();
    // 课文目录跳转：点目录里的课文/单元，展开全文并滚到位
    box.addEventListener("click", function (e) {
      var a = e.target.closest("a.tlink, a.ubook");
      if (!a) return;
      var el = document.getElementById((a.getAttribute("href") || "").slice(1));
      if (!el) return;
      e.preventDefault();
      var d = el.querySelector("details.read");
      if (d && !d.open) d.open = true;
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function cnLiteracy(st) {
    if (!D.words) return "";
    var h = "";
    Object.keys(D.words).sort().forEach(function (b) {
      if (st.book !== "all" && st.book !== b) return;
      var kinds = D.words[b] || {};
      h += '<div class="item"><div class="top"><span class="name">' + esc(b) + "</span></div>";
      (D.word_kinds || Object.keys(kinds)).forEach(function (k) {
        var ws = kinds[k] || [];
        if (!ws.length) return;
        var f = st.q ? ws.filter(function (w) {
          return has(w[0], st.q) || has(w[1], st.q);
        }) : ws;
        h += '<p class="small">' + esc(k) + "（" + ws.length + " 条" +
          (st.q ? "，匹配 " + f.length : "") + "）</p>" +
          '<div class="words">' + f.slice(0, 240).map(function (w) {
            return '<span class="wb">' + esc(w[0]) +
              (w[1] ? " <i>" + esc(w[1]) + "</i>" : "") + "</span>";
          }).join("") + (f.length > 240 ? '<span class="wb">…</span>' : "") + "</div>";
      });
      h += "</div>";
    });
    return h;
  }

  /* 课文：课文目录（可跳转/分册）→ 册 → 单元（带语文要素）→ 课文（点开读全文） */
  function cnReading(st, elems) {
    var rows = (D.texts || []).filter(function (x) {
      if (x.domain !== "reading") return false;
      if (st.book !== "all" && x.book !== st.book) return false;
      if (st.q && !(has(x.title, st.q) || has(x.genre, st.q) || has(x.author, st.q) ||
                    has(x.unit_name, st.q) || has((x.paras || []).join(" "), st.q))) return false;
      return true;
    });
    var byUnit = {}, order = [], toc = {};
    rows.forEach(function (x, i) {
      x._i = i;   // 目录跳转用的条目序号
      var k = x.book + "#" + x.unit_no;
      if (!byUnit[k]) {
        byUnit[k] = [];
        order.push(k);
        toc[k] = { i: order.length - 1, book: x.book, no: x.unit_no, items: [] };
      }
      byUnit[k].push(x);
      toc[k].items.push(x);
    });
    // 课文目录：搜索单册时默认展开，其余收起省地方
    var h = '<details class="toc"' + (rows.length && (st.q || st.book !== "all") ? " open" : "") +
      '><summary>课文目录（' + rows.length + " 篇 · 点课文直达）</summary>" +
      '<div class="toc-b">';
    order.forEach(function (k) {
      var u = toc[k];
      h += '<div class="toc-u"><a class="ubook" href="#u' + u.i + '">' +
        esc(u.book) + " · 第" + esc(u.no) + "单元</a>" +
        u.items.map(function (x) {
          return '<a class="tlink" href="#t' + x._i + '">' + esc(x.title) + "</a>";
        }).join("") + "</div>";
    });
    h += "</div></details>";
    order.forEach(function (k, ui) {
      var bk = k.split("#")[0], e = elems[k];
      h += '<div class="unit" id="u' + ui + '"><div class="top"><span class="name">' + esc(bk) +
        " 第" + esc(k.split("#")[1]) + "单元</span>" +
        (e && e.reading ? '<span class="tag d1">阅读要素</span>' : "") + "</div>";
      if (e && e.reading) h += '<div class="elem">' + esc(e.reading) + "</div>";
      h += byUnit[k].map(function (x) { return cnText(x, x._i); }).join("") + "</div>";
    });
    return h;
  }

  function cnText(x, idx) {
    var h = '<div class="item"' + (idx != null ? ' id="t' + idx + '"' : "") +
      '><div class="top"><span class="name">' +
      esc(x.title) + "</span>" +
      (x.genre ? '<span class="tag">' + esc(x.genre) + "</span>" : "") +
      (x.author ? '<span class="who">' + esc(x.author) +
        (x.dynasty ? "（" + esc(x.dynasty) + "）" : "") + "</span>" : "") +
      '<span class="where">' + (x.page ? "P" + esc(x.page) : "") +
      (x.chars ? " · " + esc(x.chars) + "字" : "") + "</span></div>";
    if (x.author && D.authors && D.authors[x.author]) {
      var a = D.authors[x.author];
      h += "<details><summary>作者：" + esc(x.author) + "</summary><p class=\"small\">" +
        (a.dynasty ? "【" + esc(a.dynasty) + "】" : "") + esc(a.intro || "") +
        ((a.works || []).length ? "　代表作：" + esc(a.works.join("、")) : "") +
        "</p></details>";
    }
    if (x.paras && x.paras.length) {
      // 默认收起：384 篇全铺开页面就散架了，从目录或标题点开再读
      h += '<details class="read"><summary>读全文（' + x.paras.length + " 段" +
        (x.chars ? " · " + esc(x.chars) + "字" : "") + "）</summary>" +
        '<div class="full">' + x.paras.map(function (p) {
          return '<p class="para">' + esc(p) + "</p>";
        }).join("") + "</div></details>";
    } else {
      // 语文园地、拼音课这类在教材里没有连续正文，如实说明，别留一片空白
      h += '<p class="small">这一课（多为语文园地、拼音课）在教材里没有连续正文，' +
        "教材原页没抽出课文文本；可以看上面的单元语文要素与本单元字词。</p>";
    }
    if (x.tasks && x.tasks.length) {
      h += '<p class="small">课后题</p><ul class="pts">' + x.tasks.map(function (t) {
        return "<li>" + esc(t) + "</li>";
      }).join("") + "</ul>";
    }
    if (x.newchars && x.newchars.length) {
      h += '<p class="small">本课生字</p><div class="words">' +
        x.newchars.map(function (c) {
          return '<span class="wb">' + esc(c) + "</span>";
        }).join("") + "</div>";
    }
    return h + "</div>";
  }

  function cnWriting(st) {
    var h = "";
    (D.elements || []).forEach(function (e) {
      if (!e.writing || (st.book !== "all" && e.book !== st.book)) return;
      if (st.q && !has(e.writing, st.q)) return;
      h += item('<div class="top"><span class="name">' + esc(e.book) + " 第" +
        esc(e.unit_no) + "单元</span></div><div>" + esc(e.writing) + "</div>");
    });
    var rows = (D.texts || []).filter(function (x) {
      return x.domain === "writing" &&
        (st.book === "all" || x.book === st.book) && (!st.q || has(x.title, st.q));
    });
    var byBook = {};
    rows.forEach(function (x) { (byBook[x.book] = byBook[x.book] || []).push(x); });
    h += "<h3>习作 · 口语交际 · 习作例文（" + rows.length + " 条）</h3>";
    Object.keys(byBook).sort().forEach(function (b) {
      h += '<div class="item"><div class="top"><span class="name">' + esc(b) +
        "</span></div><ul class=" + '"pts">' + byBook[b].map(function (x) {
          return "<li>" + esc(x.title) + ' <span class="tag">' + esc(x.section) + "</span>" +
            (x.page ? ' <span class="where">P' + esc(x.page) + "</span>" : "") +
            (x.stem ? "<div class=\"small\">" + esc(x.stem) + "</div>" : "") + "</li>";
        }).join("") + "</ul></div>";
    });
    return h;
  }

  function cnInquiry(st) {
    var rows = (D.texts || []).filter(function (x) {
      return x.domain === "inquiry" && (st.book === "all" || x.book === st.book) &&
        (!st.q || has(x.title, st.q));
    });
    var h = "";
    if (!rows.length) {
      return h + '<div class="empty">目录里没有单独标出"综合性学习 / 快乐读书吧"' +
        "的条目（这部分通常印在单元末尾的语文园地里）。</div>";
    }
    return h + rows.map(function (x) {
      return item('<div class="top"><span class="name">' + esc(x.title) + "</span>" +
        where(x, x.page) + "</div>" +
        ((x.paras || []).length ? '<div class="full">' + x.paras.map(function (p) {
          return '<p class="para">' + esc(p) + "</p>";
        }).join("") + "</div>" : ""));
    }).join("");
  }

  function cnPoetry(st) {
    var rows = (D.pieces || []).filter(function (x) {
      if (st.book !== "all" && x.book !== st.book) return false;
      return !st.q || has(x.title, st.q) || has(x.author, st.q) || has(x.text, st.q);
    });
    var h = "";
    return h + rows.map(function (x) {
      var s = '<div class="item"><div class="top"><span class="name">' + esc(x.title) +
        "</span>" + (x.dynasty ? '<span class="tag">' + esc(x.dynasty) + "</span>" : "") +
        (x.author ? '<span class="who">' + esc(x.author) + "</span>" : "") +
        (x.kind ? '<span class="tag">' + esc(x.kind) + "</span>" : "") + "</div>";
      s += '<pre class="poem">' + esc(x.text) + "</pre>";
      if (x.glossary && x.glossary.length) {
        s += '<p class="small">注释</p><div class="words">' +
          x.glossary.map(function (g) {
            return '<span class="wb">' + esc(g.word) + " <i>" + esc(g.sense) + "</i></span>";
          }).join("") + "</div>";
      }
      if (x.tr) {
        s += "<details><summary>译文</summary><p class=\"para\">" + esc(x.tr) + "</p>";
        if (x.literal && x.literal.length) {
          s += '<ul class="pts">' + x.literal.map(function (l) {
            return "<li>" + esc(l.src) + " —— " + esc(l.tr) + "</li>";
          }).join("") + "</ul>";
        }
        s += "</details>";
      }
      return s + "</div>";
    }).join("");
  }

  /* ================================================================ 英语 */
  function renderEnglish() {
    if (kind === "vocab") {
      var ql = document.createElement("div");
      ql.innerHTML = quizLab();
      app.appendChild(ql);
      bindQuiz();
    }
    var box = listBox();
    var topics = [];
    (D.vocab || []).forEach(function (v) {
      if (v.topic && topics.indexOf(v.topic) < 0) topics.push(v.topic);
    });
    var t = tools([], function (st, cnt) {
      var h = "";
      if (kind === "discourse") h = enText(st);
      else if (kind === "vocab") h = enVocab(st);
      else if (kind === "grammar") h = enGrammar(st);
      else if (kind === "phonics") h = enPhonics(st);
      else h = enUse(st);
      box.innerHTML = h || '<div class="empty">没有匹配的内容</div>';
      cnt.textContent = box.querySelectorAll(".item").length + " 组";
    }, { hint: { discourse: "如：family、weather", vocab: "如：job、doctor",
                 grammar: "如：can、there be、过去式", phonics: "如：sh、ai",
                 use: "如：song、project" }[kind] || "关键词",
         tags: (function () {
           var m = { discourse: [D.passages, "name"], vocab: [D.vocab, "topic"],
                     grammar: [D.grammar, "category"], phonics: [D.phonics, "letters"],
                     use: [D.songs, "name"] }[kind] || [D.vocab, "topic"];
           return hotTags(m[0], m[1], 16);
         })(),
         zh: kind === "discourse",
         extra: (kind === "vocab" || kind === "discourse")
           ? { label: "按话题", opts: topics } : null });
    t.fire();
    // 词汇卡：点一下才出中文（自测）
    box.addEventListener("click", function (e) {
      var c = e.target.closest(".vcard");
      if (c) c.classList.toggle("open");
    });
  }

  /* 课文：对话（角色分行）+ 语篇（中英对照 + 理解题） */
  function enText(st) {
    var h = "<h2>课文与语篇</h2>" +
      '<p class="lead">点右上角“中文对照”可切换译文显示——纸质书做不到。' +
      "语篇还带教材原题与重点词。</p>";
    var dl = (D.dialogues || []).filter(pass(st, ["scene", "function", "patterns"]));
    if (dl.length) {
      h += "<h3>情景对话（" + dl.length + "）</h3>";
      dl.slice(0, 150).forEach(function (x) {
        var s = '<div class="item"><div class="top"><span class="name">' +
          esc(x.scene) + "</span>" + where(x) +
          (x.function ? '<span class="tag">' + esc(x.function) + "</span>" : "") + "</div>";
        (x.patterns || []).forEach(function (p) {
          s += '<div class="pat">' + hl(String(p)) + "</div>";
        });
        (x.turns || []).forEach(function (t) {
          var who = typeof t === "string" ? "" : (t.speaker || t.role || "");
          var line = typeof t === "string" ? t : (t.text || t.line || t.en || "");
          var zh = typeof t === "string" ? "" : (t.zh || t.translation || "");
          s += '<div class="turn"><b>' + esc(who || "•") + "</b> " + esc(line) +
            (zh ? '<span class="zh">' + esc(zh) + "</span>" : "") + "</div>";
        });
        h += s + "</div>";
      });
    }
    var ps = (D.passages || []).filter(pass(st, ["name", "genre", "text", "topic"]));
    if (ps.length) {
      h += "<h3>短文 / 阅读（" + ps.length + "）</h3>";
      ps.slice(0, 120).forEach(function (x) {
        var s = '<div class="item"><div class="top"><span class="name">' + esc(x.name) +
          "</span>" + where(x) +
          (x.genre ? '<span class="tag">' + esc(x.genre) + "</span>" : "") +
          (x.topic ? '<span class="tag d1">' + esc(x.topic) + "</span>" : "") + "</div>";
        s += '<div class="en para">' + esc(x.text) + "</div>";
        if (x.zh) s += '<div class="zh para">' + esc(x.zh) + "</div>";
        if (x.words && x.words.length) {
          s += '<p class="small">重点词</p><div class="words">' +
            x.words.map(function (w) {
              return '<span class="wb">' + esc(w.word || w) +
                (w.meaning || w.zh ? " <i>" + esc(w.meaning || w.zh) + "</i>" : "") +
                "</span>";
            }).join("") + "</div>";
        }
        if (x.comprehension && x.comprehension.length) {
          s += "<details><summary>理解题（" + x.comprehension.length + "）</summary>" +
            '<ul class="pts">' + x.comprehension.map(function (c) {
              return "<li>" + esc(c.q || c.question) +
                (c.a || c.answer ? " —— " + esc(c.a || c.answer) : "") + "</li>";
            }).join("") + "</ul></details>";
        }
        h += s + "</div>";
      });
    }
    return h;
  }

  function pass(st, fields) {
    return function (x) {
      if (st.book !== "all" && x.book !== st.book) return false;
      if (st.extra && st.extra !== "all" && x.topic !== st.extra) return false;
      if (st.q) {
        var s = fields.map(function (f) { return x[f]; }).join(" ");
        if (!has(s, st.q)) return false;
      }
      return true;
    };
  }

  /* 句式中可替换的部分高亮（... / ___ / 括号里的提示） */
  function hl(s) {
    return esc(s).replace(/\.\.\.+|___+/g, function (m) {
      return '<span class="hl">' + m + "</span>";
    }).replace(/（[^）]*）/g, function (m) {
      return '<span class="hl">' + m + "</span>";
    });
  }

  function enVocab(st) {
    var rows = (D.vocab || []).filter(pass(st, ["word", "meaning", "topic"]));
    var h = "<h2>词汇（" + rows.length + "）</h2>" +
      '<p class="lead">点单词才出中文——可以先自己想一想（自测）。</p>';
    var by = {};
    rows.forEach(function (v) {
      var k = v.topic || v.book || "其他";
      (by[k] = by[k] || []).push(v);
    });
    return h + Object.keys(by).sort().map(function (k) {
      return '<div class="item"><div class="top"><span class="name">' + esc(k) +
        '</span><span class="where">' + by[k].length + " 词</span></div>" +
        '<div class="words">' + by[k].slice(0, 200).map(function (v) {
          return '<span class="vcard"><b>' + esc(v.word) + "</b>" +
            (v.phonetic ? " <i>" + esc(v.phonetic) + "</i>" : "") +
            '<span class="zh">' + esc(v.meaning || "") + "</span>" +
            (v.example ? '<span class="ex-s">' + esc(v.example) + "</span>" : "") +
            "</span>";
        }).join("") + "</div></div>";
    }).join("");
  }

  /* 语法汇总：按范畴分块 + 时态递进条 */
  function enGrammar(st) {
    var rows = (D.grammar || []).filter(pass(st, ["point", "pattern", "rule", "category"]));
    var h = "<h2>语法汇总（" + rows.length + " 条）</h2>";
    // 时态递进：先给一张"什么时候学什么时态"的表
    var byTense = {}, tOrder = [];
    rows.forEach(function (g) {
      if (!g.tense) return;
      if (!byTense[g.tense]) { byTense[g.tense] = {}; tOrder.push(g.tense); }
      byTense[g.tense][g.book] = (byTense[g.tense][g.book] || 0) + 1;
    });
    if (tOrder.length) {
      h += '<div class="card"><h3>时态线：哪一册学了什么</h3><table class="tbl"><tr><th>时态</th>';
      var books = [];
      rows.forEach(function (g) { if (books.indexOf(g.book) < 0) books.push(g.book); });
      books.sort();
      books.forEach(function (b) { h += "<th>" + esc(b.replace("年级", "")) + "</th>"; });
      h += "</tr>";
      tOrder.sort(function (a, b2) {
        return Object.keys(byTense[b2]).length - Object.keys(byTense[a]).length;
      });
      tOrder.forEach(function (t) {
        h += "<tr><td>" + esc(t) + "</td>";
        books.forEach(function (b) {
          h += "<td>" + (byTense[t][b] ? "●" + (byTense[t][b] > 1 ? " " + byTense[t][b] : "") : "") + "</td>";
        });
        h += "</tr>";
      });
      h += "</table></div>";
    }
    // 按范畴分块
    var byCat = {}, cOrder = [];
    rows.forEach(function (g) {
      var k = g.category || "其他";
      if (!byCat[k]) { byCat[k] = []; cOrder.push(k); }
      byCat[k].push(g);
    });
    cOrder.sort(function (a, b2) { return byCat[b2].length - byCat[a].length; });
    h += cOrder.map(function (k) {
      return '<div class="item"><div class="top"><span class="name">' + esc(k) +
        '</span><span class="where">' + byCat[k].length + " 条</span></div>" +
        byCat[k].slice(0, 60).map(function (g) {
          var s = '<div class="step"><b>' + esc(g.point) + "</b>" + where(g) +
            (g.tense ? '<span class="tag">' + esc(g.tense) + "</span>" : "") + "</div>";
          if (g.pattern) s += '<div class="pat">' + hl(g.pattern) + "</div>";
          if (g.rule) s += '<div class="small">' + esc(g.rule) + "</div>";
          var exs = typeof g.examples === "string" ? safeJson(g.examples) : (g.examples || []);
          if (exs.length) {
            s += "<details><summary>例句</summary><ul class=" + '"pts">' +
              exs.slice(0, 6).map(function (e) {
                return "<li>" + esc(typeof e === "string" ? e : (e.en || e.text || e)) +
                  (e && e.zh ? '<span class="zh"> ' + esc(e.zh) + "</span>" : "") + "</li>";
              }).join("") + "</ul></details>";
          }
          return s;
        }).join("") + "</div>";
    }).join("");
    return h;
  }

  function safeJson(s) {
    try { return JSON.parse(s); } catch (e) { return []; }
  }

  function enPhonics(st) {
    var rows = (D.phonics || []).filter(pass(st, ["letters", "sound", "chant"]));
    var h = "<h2>语音与拼读</h2>";
    var by = {};
    rows.forEach(function (x) { (by[x.book] = by[x.book] || []).push(x); });
    return h + Object.keys(by).sort().map(function (b) {
      var s = '<div class="item"><div class="top"><span class="name">' + esc(b) +
        "</span></div>";
      by[b].forEach(function (x) {
        s += '<div class="step"><b>' + esc(x.letters || "") + "</b> <i>" +
          esc(x.sound || "") + "</i>" +
          ((x.examples || []).length ? ' <span class="words">' +
            x.examples.slice(0, 6).map(function (e) {
              return '<span class="wb">' + esc(typeof e === "string" ? e : (e.word || e)) +
                "</span>";
            }).join("") + "</span>" : "") + "</div>";
        if (x.chant) s += '<div class="pat">' + esc(x.chant.slice(0, 140)) + "</div>";
      });
      return s + "</div>";
    }).join("");
  }

  function enUse(st) {
    var h = "<h2>综合运用</h2>";
    var sg = (D.songs || []).filter(pass(st, ["name", "topic"]));
    if (sg.length) {
      h += "<h3>歌谣（" + sg.length + "）</h3>";
      h += sg.slice(0, 80).map(function (x) {
        var lys = (x.lyrics || []).map(function (l) {
          return typeof l === "string" ? l : (l.line || l.text || "");
        });
        return item('<div class="top"><span class="name">' + esc(x.name) + "</span>" +
          where(x) + (x.topic ? '<span class="tag">' + esc(x.topic) + "</span>" : "") +
          '</div><pre class="poem">' + esc(lys.join("\n")) + "</pre>");
      }).join("");
    }
    var pj = (D.projects || []).filter(pass(st, ["name", "goal", "product"]));
    if (pj.length) {
      h += "<h3>项目任务（" + pj.length + "）</h3>";
      h += pj.slice(0, 80).map(function (x) {
        return item('<div class="top"><span class="name">' + esc(x.name) + "</span>" +
          where(x) + (x.type ? '<span class="tag">' + esc(x.type) + "</span>" : "") +
          "</div>" + (x.goal ? '<div class="small">' + esc(x.goal) + "</div>" : "") +
          (x.product ? "<div>产出：" + esc(x.product) + "</div>" : ""));
      }).join("");
    }
    (D.revisions || []).forEach(function (x) {
      if (st.book !== "all" && x.book !== st.book) return;
      h += item('<div class="top"><span class="name">' + esc(x.theme) + "</span>" +
        where(x) + '<span class="tag d3">复习板块</span></div>' +
        ((x.tasks || []).length ? '<ul class="pts">' + x.tasks.map(function (t) {
          return "<li>" + esc(t.name || t) +
            (t.type ? ' <span class="tag">' + esc(t.type) + "</span>" : "") + "</li>";
        }).join("") + "</ul>" : "") +
        (x.outcome ? "<div><b>产出：</b>" + esc(x.outcome) + "</div>" : ""));
    });
    return h;
  }

  /* ======================================================= 互动实验室
     纸质书给不了的：能拖、能点、能自测。数据仍全部来自教材。 */

  var UNITS = {
    "长度": [["千米", 1000000], ["米", 1000], ["分米", 100], ["厘米", 10], ["毫米", 1]],
    "面积": [["平方千米", 100000000], ["公顷", 1000000], ["平方米", 10000],
             ["平方分米", 100], ["平方厘米", 1]],
    "质量": [["吨", 1000000], ["千克", 1000], ["克", 1]],
    "时间": [["日", 86400], ["时", 3600], ["分", 60], ["秒", 1]],
    "人民币": [["元", 100], ["角", 10], ["分", 1]],
    "容积": [["立方米", 1000000], ["立方分米(升)", 1000], ["立方厘米(毫升)", 1]],
  };

  function labBox(title, hint, html) {
    return '<div class="card lab"><h3>' + title + "</h3>" +
      (hint ? '<p class="small">' + hint + "</p>" : "") + html + "</div>";
  }

  function unitLab() {
    var cats = Object.keys(UNITS);
    return labBox("单位换算器",
      "进率取教材正文与整理复习页。换算过程一并写出——不是只给答案。",
      '<div class="row"><select id="uc-c">' +
      cats.map(function (c) { return "<option>" + c + "</option>"; }).join("") +
      '</select><input id="uc-v" type="number" value="3" style="width:80px">' +
      '<select id="uc-f"></select><span class="eq">＝</span>' +
      '<select id="uc-t"></select><span id="uc-o" class="big"></span></div>' +
      '<div id="uc-s" class="small"></div>');
  }

  function bindUnit() {
    var c = document.getElementById("uc-c"), f = document.getElementById("uc-f"),
        t = document.getElementById("uc-t"), v = document.getElementById("uc-v"),
        o = document.getElementById("uc-o"), s = document.getElementById("uc-s");
    if (!c || !f) return;
    function fill() {
      var us = UNITS[c.value] || [];
      var h = us.map(function (u) { return "<option>" + u[0] + "</option>"; }).join("");
      f.innerHTML = h; t.innerHTML = h;
      if (us.length > 1) t.value = us[us.length - 1][0];
      calc();
    }
    function calc() {
      var us = UNITS[c.value] || [], a = 1, b = 1;
      us.forEach(function (u) {
        if (u[0] === f.value) a = u[1];
        if (u[0] === t.value) b = u[1];
      });
      var val = parseFloat(v.value);
      if (isNaN(val)) { o.textContent = ""; return; }
      var r = val * a / b;
      o.innerHTML = tex(String(+(Math.round(r * 1e6) / 1e6)) + " " + t.value);
      s.innerHTML = val + " " + f.value + " × " + a + " ÷ " + b +
        " ＝ " + (+(Math.round(r * 1e6) / 1e6)) + " " + t.value +
        "（都以最小单位为基准）";
    }
    [c, f, t, v].forEach(function (e) {
      e.addEventListener("change", function () { if (e === c) fill(); else calc(); });
      e.addEventListener("input", calc);
    });
    fill();
  }

  /* 分数的意义：拖分母看它到底有多大 */
  function fracLab() {
    return labBox("分数的意义",
      "拖一拖：把一个圆平均分成几份，取其中的几份——分数的分子分母就是这么来的。",
      '<div class="row">分母 <input type="range" id="fr-n" min="2" max="12" value="4">' +
      '<b id="fr-nv">4</b>　分子 <input type="range" id="fr-m" min="0" max="4" value="1">' +
      '<b id="fr-mv">1</b></div>' +
      '<div id="fr-svg" class="svgwrap"></div>');
  }

  function bindFrac() {
    var n = document.getElementById("fr-n"), m = document.getElementById("fr-m"),
        nv = document.getElementById("fr-nv"), mv = document.getElementById("fr-mv"),
        box = document.getElementById("fr-svg");
    if (!n || !box) return;
    function draw() {
      var N = +n.value, M = Math.min(+m.value, N);
      m.max = N; nv.textContent = N; mv.textContent = M;
      var R = 60, cx = 80, cy = 80, i, parts = [];
      parts.push('<circle cx="' + cx + '" cy="' + cy + '" r="' + R +
        '" fill="#fff" stroke="#c8bfa8"/>');
      for (i = 0; i < N; i++) {
        var a0 = -Math.PI / 2 + i * 2 * Math.PI / N;
        var a1 = -Math.PI / 2 + (i + 1) * 2 * Math.PI / N;
        var x0 = cx + R * Math.cos(a0), y0 = cy + R * Math.sin(a0);
        var x1 = cx + R * Math.cos(a1), y1 = cy + R * Math.sin(a1);
        parts.push('<path d="M' + cx + " " + cy + " L" + x0 + " " + y0 +
          " A" + R + " " + R + " 0 0 1 " + x1 + " " + y1 + ' Z" fill="' +
          (i < M ? "#f5c26b" : "#fff") + '" stroke="#c8bfa8"/>');
      }
      // 分数条：整体与所取部分并排，直观对比
      var W = 260;
      parts.push('<rect x="180" y="66" width="' + W + '" height="28" fill="#fff" stroke="#c8bfa8"/>');
      parts.push('<rect x="180" y="66" width="' + (W * M / N) + '" height="28" fill="#f5c26b"/>');
      parts.push('<text x="180" y="118" font-size="14" fill="#6b7280">整体 "1"　取 ' +
        M + " / " + N + "</text>");
      box.innerHTML = '<svg viewBox="0 0 460 150" width="100%" height="150">' +
        parts.join("") + "</svg>" +
        '<p class="small">读作：' + (M === 0 ? "零" : N + "分之" + M) +
        "（分母表示平均分成几份，分子表示取了几份）</p>";
    }
    n.addEventListener("input", draw);
    m.addEventListener("input", draw);
    draw();
  }

  /* 百数表：点一个数字看它的倍数与因数 */
  function hundredLab() {
    return labBox("百数表",
      "点一个数字：高亮它的倍数。这是“因数与倍数”那一单元的看家工具。",
      '<div class="row"><span id="hb-h" class="small">点数字试试</span></div>' +
      '<div id="hb" class="hundred"></div>');
  }

  function bindHundred() {
    var box = document.getElementById("hb"), hh = document.getElementById("hb-h");
    if (!box) return;
    var h = "";
    for (var i = 1; i <= 100; i++) {
      h += '<span class="cell" data-n="' + i + '">' + i + "</span>";
    }
    box.innerHTML = h;
    box.addEventListener("click", function (e) {
      var c = e.target.closest(".cell");
      if (!c) return;
      var n = +c.dataset.n, kids = [];
      for (var k = n; k <= 100; k += n) kids.push(k);
      [].forEach.call(box.querySelectorAll(".cell"), function (x) {
        x.classList.remove("on", "hit");
      });
      c.classList.add("on");
      kids.forEach(function (k) {
        var el = box.querySelector('.cell[data-n="' + k + '"]');
        if (el) el.classList.add("hit");
      });
      hh.innerHTML = n + " 的倍数（含它自己）：" + kids.join("、");
    });
  }

  /* 圆的面积：等分越多，拼出来越像长方形 */
  function circleLab() {
    return labBox("圆的面积是怎么来的",
      "把圆等分成若干份，拼成一个近似的长方形：长是圆周的一半（πr），宽是半径（r），" +
      "所以 S＝πr²。拖一拖，看等分数变化。",
      '<div class="row">等分份数 <input type="range" id="cl-k" min="0" max="3" value="0">' +
      '<b id="cl-kv">4</b></div><div id="cl-svg" class="svgwrap"></div>');
  }

  function bindCircle() {
    var k = document.getElementById("cl-k"), kv = document.getElementById("cl-kv"),
        box = document.getElementById("cl-svg");
    if (!k || !box) return;
    var KS = [4, 8, 16, 32];
    function draw() {
      var N = KS[+k.value], R = 50, cx = 70, cy = 70, i, parts = [];
      kv.textContent = N;
      for (i = 0; i < N; i++) {
        var a0 = i * 2 * Math.PI / N - Math.PI / 2, a1 = (i + 1) * 2 * Math.PI / N - Math.PI / 2;
        var x0 = cx + R * Math.cos(a0), y0 = cy + R * Math.sin(a0);
        var x1 = cx + R * Math.cos(a1), y1 = cy + R * Math.sin(a1);
        parts.push('<path d="M' + cx + " " + cy + " L" + x0 + " " + y0 +
          " A" + R + " " + R + " 0 0 1 " + x1 + " " + y1 + ' Z" fill="' +
          (i % 2 ? "#d9e8f5" : "#f5c26b") + '" stroke="#fff"/>');
      }
      // 拼成的近似长方形：高 r，长 πr
      var L = Math.PI * R, H = R, x = 160, y = 20;
      parts.push('<rect x="' + x + '" y="' + y + '" width="' + L + '" height="' + H +
        '" fill="#fdf3e3" stroke="#c8b26a"/>');
      for (i = 0; i < N; i++) {
        var w = L / N, up = i % 2 === 0;
        parts.push('<rect x="' + (x + i * w) + '" y="' + (up ? y : y + H / 2) +
          '" width="' + (w - 1) + '" height="' + (H / 2 - 1) + '" fill="' +
          (up ? "#f5c26b" : "#d9e8f5") + '"/>');
      }
      parts.push('<text x="' + x + '" y="' + (y + H + 22) + '" font-size="14">长＝πr</text>');
      parts.push('<text x="' + (x + L + 6) + '" y="' + (y + H / 2) +
        '" font-size="14">宽＝r</text>');
      parts.push('<text x="20" y="140" font-size="14" fill="#6b7280">S＝πr×r＝πr²' +
        "（等分 " + N + " 份，份数越多越接近长方形）</text>");
      box.innerHTML = '<svg viewBox="0 0 460 150" width="100%" height="150">' +
        parts.join("") + "</svg>";
    }
    k.addEventListener("input", draw);
    draw();
  }

  /* 线段图：把应用题的数量关系画出来。孩子卡应用题，卡的是"看不出关系"，
     一画线段图，关系就摆在那儿了。三种关系：合与分、相差、倍数。 */
  function segLab() {
    return labBox("线段图：把数量关系画出来",
      "应用题读不懂，多半是“看不出数量关系”。选一种关系，拖一拖，线段自己会变。" +
      "这是解应用题最常用的拐杖。",
      '<div class="row"><span class="segmode on" data-m="sum">合与分</span>' +
      '<span class="segmode" data-m="diff">相差</span>' +
      '<span class="segmode" data-m="times">倍数</span>' +
      '　甲 <input type="range" id="sg-a" min="1" max="60" value="30">' +
      '<b id="sg-av">30</b>　乙 <input type="range" id="sg-b" min="1" max="60" value="18">' +
      '<b id="sg-bv">18</b></div><div id="sg-svg" class="svgwrap"></div>');
  }

  function bindSeg() {
    var a = document.getElementById("sg-a"), b = document.getElementById("sg-b"),
        box = document.getElementById("sg-svg"), av = document.getElementById("sg-av"),
        bv = document.getElementById("sg-bv");
    if (!a || !box) return;
    var mode = "sum";
    var mods = document.querySelectorAll ? document.querySelectorAll(".segmode") : [];
    [].forEach.call(mods, function (m) {
      m.addEventListener("click", function () {
        [].forEach.call(mods, function (x) { x.classList.remove("on"); });
        m.classList.add("on");
        mode = m.dataset.m;
        draw();
      });
    });

    function bar(x, y, w, h, fill, label) {
      var s = '<rect x="' + x + '" y="' + y + '" width="' + Math.max(0, w) +
        '" height="' + h + '" fill="' + fill + '" stroke="#fff"/>';
      if (label) {
        s += '<text x="' + (x + 4) + '" y="' + (y + h - 7) + '" font-size="13" fill="#2f3437">' +
          label + "</text>";
      }
      return s;
    }

    function draw() {
      var A = +a.value, B = +b.value, W = 360, x0 = 30, p = [];
      av.textContent = A;
      bv.textContent = B;
      if (mode === "sum") {
        var tot = A + B, wa = W * A / tot, wb = W * B / tot;
        p.push(bar(x0, 34, wa, 26, "#f5c26b", "甲 " + A));
        p.push(bar(x0 + wa, 34, wb, 26, "#a8d5ba", "乙 " + B));
        p.push('<line x1="' + x0 + '" y1="72" x2="' + (x0 + W) + '" y2="72" stroke="#6b7280"/>');
        p.push('<text x="' + (x0 + W / 2 - 30) + '" y="88" font-size="13" fill="#6b7280">一共 ' +
          tot + "（甲 + 乙）</text>");
      } else if (mode === "diff") {
        var mx = Math.max(A, B), wa = W * A / mx, wb = W * B / mx;
        p.push(bar(x0, 26, wa, 24, "#f5c26b", "甲 " + A));
        p.push(bar(x0, 66, wb, 24, "#a8d5ba", "乙 " + B));
        var lo = Math.min(wa, wb), d = Math.abs(A - B);
        p.push('<rect x="' + (x0 + lo) + '" y="54" width="' + (W * d / mx) +
          '" height="2" fill="#c0392b"/>');
        p.push('<text x="' + (x0 + lo + 4) + '" y="50" font-size="13" fill="#c0392b">相差 ' +
          d + "</text>");
      } else {
        var n = Math.max(1, Math.round(A / Math.max(1, B) * 10) / 10);
        var u = W / (Math.floor(n) + 1.2);
        p.push(bar(x0, 34, u, 24, "#a8d5ba", "乙 " + B));
        p.push('<text x="' + x0 + '" y="74" font-size="13" fill="#6b7280">1 份</text>');
        for (var i = 0; i < Math.floor(n); i++) {
          p.push(bar(x0 + u + i * u, 34, u - 1, 24, "#f5c26b", i === 0 ? "甲 " + A : ""));
        }
        p.push('<text x="' + (x0 + u + 4) + '" y="74" font-size="13" fill="#6b7280">' +
          n + " 份</text>");
      }
      box.innerHTML = '<svg viewBox="0 0 440 100" width="100%" height="100">' +
        p.join("") + "</svg>";
    }
    a.addEventListener("input", draw);
    b.addEventListener("input", draw);
    draw();
  }

  /* 数轴：分数与小数其实是同一个点 */
  function axisLab() {
    return labBox("数轴：分数和小数其实是同一个点",
      "拖分母与分子，看这个分数落在 0 和 1 之间的哪儿——它也就是一个小数。",
      '<div class="row">分母 <input type="range" id="ax-n" min="2" max="10" value="4">' +
      '<b id="ax-nv">4</b>　分子 <input type="range" id="ax-m" min="0" max="4" value="3">' +
      '<b id="ax-mv">3</b></div><div id="ax-svg" class="svgwrap"></div>');
  }

  function bindAxis() {
    var n = document.getElementById("ax-n"), m = document.getElementById("ax-m"),
        box = document.getElementById("ax-svg"), nv = document.getElementById("ax-nv"),
        mv = document.getElementById("ax-mv");
    if (!n || !box) return;
    function draw() {
      var N = +n.value, M = Math.min(+m.value, N), x0 = 30, W = 380, i, p = [];
      m.max = N; nv.textContent = N; mv.textContent = M;
      p.push('<line x1="' + x0 + '" y1="60" x2="' + (x0 + W) + '" y2="60" stroke="#6b7280"/>');
      for (i = 0; i <= N; i++) {
        var x = x0 + W * i / N;
        p.push('<line x1="' + x + '" y1="54" x2="' + x + '" y2="66" stroke="#6b7280"/>');
        p.push('<text x="' + (x - 4) + '" y="82" font-size="12" fill="#6b7280">' +
          (i / N).toFixed(2).replace(/0+$/, "").replace(/\.$/, "") + "</text>");
      }
      var px = x0 + W * M / N;
      p.push('<circle cx="' + px + '" cy="60" r="6" fill="#c0392b"/>');
      p.push('<text x="' + (px - 14) + '" y="42" font-size="15" fill="#c0392b">' +
        M + "/" + N + " ＝ " + (M / N).toFixed(3).replace(/0+$/, "").replace(/\.$/, "") + "</text>");
      box.innerHTML = '<svg viewBox="0 0 440 100" width="100%" height="100">' +
        p.join("") + "</svg>";
    }
    n.addEventListener("input", draw);
    m.addEventListener("input", draw);
    draw();
  }

  /* 割补：面积公式不是背的，是割一刀补一刀看出来的 */
  function cutLab() {
    return labBox("面积公式是怎么来的：割一补一",
      "平行四边形沿高割开、把三角形补到另一边，就是长方形，所以 S＝ah；" +
      "两个全等的三角形（或梯形）能拼成平行四边形，所以三角形 S＝ah÷2、梯形 S＝(a+b)h÷2。" +
      "拖“割补进度”看它怎么变。",
      '<div class="row"><select id="ct-s">' +
      ["平行四边形", "三角形", "梯形"].map(function (s) {
        return "<option>" + s + "</option>";
      }).join("") +
      '</select>　割补进度 <input type="range" id="ct-t" min="0" max="100" value="0">' +
      '<b id="ct-tv">0%</b></div><div id="ct-svg" class="svgwrap"></div>' +
      '<div id="ct-tip" class="small"></div>');
  }

  function bindCut() {
    var s = document.getElementById("ct-s"), t = document.getElementById("ct-t"),
        box = document.getElementById("ct-svg"), tv = document.getElementById("ct-tv"),
        tip = document.getElementById("ct-tip");
    if (!s || !box) return;

    function draw() {
      var A = 150, H = 70, S = 46, X = 40, Y = 30, k = (+t.value) / 100, p = [];
      tv.textContent = t.value + "%";
      var shape = s.value || "平行四边形";
      if (shape === "平行四边形") {
        // 沿高割开，左三角右移 A → 变成长方形（长＝底，宽＝高）
        var tri = (X) + "," + (Y + H) + " " + (X + S) + "," + (Y + H) + " " + (X + S) + "," + Y;
        var rest = (X + S) + "," + (Y + H) + " " + (X + A) + "," + (Y + H) + " " +
          (X + A + S) + "," + Y + " " + (X + S) + "," + Y;
        p.push('<polygon points="' + rest + '" fill="#d9e8f5" stroke="#2f3437"/>');
        p.push('<polygon points="' + tri + '" fill="#f5c26b" stroke="#2f3437" ' +
          'transform="translate(' + (k * A) + ',0)"/>');
        p.push('<line x1="' + (X + S) + '" y1="' + Y + '" x2="' + (X + S) + '" y2="' + (Y + H) +
          '" stroke="#c0392b" stroke-dasharray="4 3"/>');
        p.push('<text x="' + (X + S + 4) + '" y="' + (Y + H + 18) + '" font-size="12" fill="#c0392b">高 h</text>');
        p.push('<text x="' + X + '" y="' + (Y + H + 34) + '" font-size="13">底 a</text>');
        if (k > 0.99) {
          p.push('<text x="' + (X + S + A / 2 - 20) + '" y="' + (Y + H / 2) +
            '" font-size="14" fill="#c0392b">变成长方形了</text>');
        }
        tip.innerHTML = "割补后：长方形的长＝底 a，宽＝高 h，所以 <b>S＝a×h</b>。";
      } else {
        // 三角形／梯形：绕右下角旋转 180°，两个全等的拼成平行四边形
        var pts = shape === "三角形"
          ? X + "," + (Y + H) + " " + (X + A) + "," + (Y + H) + " " + (X + S) + "," + Y
          : X + "," + (Y + H) + " " + (X + A) + "," + (Y + H) + " " + (X + A - 30) + "," + Y +
            " " + (X + 30) + "," + Y;
        var bx = X + A, by = Y + H, off = (1 - k) * 190;
        p.push('<polygon points="' + pts + '" fill="#f5c26b" stroke="#2f3437"/>');
        p.push('<g transform="translate(' + off + ',0)"><polygon points="' + pts +
          '" fill="#a8d5ba" stroke="#2f3437" transform="rotate(180 ' + bx + ' ' + by + ')"/></g>');
        p.push('<text x="' + X + '" y="' + (Y + H + 18) + '" font-size="13">底 a</text>');
        p.push('<text x="' + (bx + 6) + '" y="' + (Y + H / 2) + '" font-size="12" fill="#6b7280">高 h</text>');
        tip.innerHTML = shape === "三角形"
          ? "两个<b>全等</b>的三角形拼成一个平行四边形（底 a、高 h），" +
            "所以一个三角形 <b>S＝a×h÷2</b>。"
          : "两个<b>全等</b>的梯形拼成一个平行四边形（底 a+b、高 h），" +
            "所以一个梯形 <b>S＝(a+b)×h÷2</b>。";
      }
      box.innerHTML = '<svg viewBox="0 0 440 130" width="100%" height="130">' +
        p.join("") + "</svg>";
    }
    s.addEventListener("change", draw);
    t.addEventListener("input", draw);
    draw();
  }

  function mathLab(kind) {
    var h = "";
    if (kind === "all" || kind === "num") {
      h += fracLab() + axisLab() + hundredLab() + unitLab();
    }
    if (kind === "all" || kind === "geo") {
      h += cutLab() + circleLab();
    }
    if (kind === "problem") h += segLab();   // 应用题配线段图，正对"看不出数量关系"
    return h;
  }

  function bindMathLab(kind) {
    if (kind === "all" || kind === "num") {
      bindFrac(); bindAxis(); bindHundred(); bindUnit();
    }
    if (kind === "all" || kind === "geo") { bindCut(); bindCircle(); }
    if (kind === "problem") bindSeg();
  }

  /* 飞花令：按主题字检索诗句（古诗文页） */
  function poetryLab() {
    return labBox("飞花令",
      "输入一个字（如 月、山、春、水），列出教材里含这个字的句子。",
      '<div class="row"><input id="fh-q" placeholder="如：月" style="width:120px">' +
      '<span class="small" id="fh-n"></span></div><div id="fh-o"></div>');
  }

  function bindPoetry() {
    var q = document.getElementById("fh-q"), o = document.getElementById("fh-o"),
        n = document.getElementById("fh-n");
    if (!q || !o) return;
    function run() {
      var w = (q.value || "").trim();
      if (!w) { o.innerHTML = ""; n.textContent = ""; return; }
      var hits = [];
      (D.pieces || []).forEach(function (p) {
        String(p.text || "").split(/[。！？；\n]/).forEach(function (s) {
          if (s.indexOf(w) >= 0) {
            hits.push({ t: p.title, a: p.author, s: s.trim() });
          }
        });
      });
      n.textContent = "命中 " + hits.length + " 句";
      o.innerHTML = hits.length
        ? '<ul class="pts">' + hits.slice(0, 60).map(function (x) {
            return "<li>" + esc(x.s).split(w).join('<span class="hl">' + w + "</span>") +
              ' <span class="where">' + esc(x.t) +
              (x.a ? " · " + esc(x.a) : "") + "</span></li>";
          }).join("") + "</ul>"
        : '<div class="empty">教材里没有含这个字的句子</div>';
    }
    q.addEventListener("input", run);
  }

  /* 识字卡：点一个字，放大看（可盖住拼音自测） */
  function bindCharCard() {
    var mask = document.createElement("div");
    mask.className = "mask";
    mask.innerHTML = '<div class="bigcard"><div class="ch"></div>' +
      '<div class="py"></div><div class="tip">点任意处关闭 · 再点拼音可盖住（自测）</div></div>';
    if (document.body && document.body.appendChild) document.body.appendChild(mask);
    mask.addEventListener("click", function (e) {
      if (e.target.classList && e.target.classList.contains("py")) {
        e.target.classList.toggle("hide");
        return;
      }
      mask.classList.remove("on");
    });
    app.addEventListener("click", function (e) {
      var w = e.target.closest(".wb");
      if (!w) return;
      var zh = w.childNodes[0] ? String(w.childNodes[0].nodeValue || "").trim() : "";
      if (!zh) zh = w.textContent.trim();
      var py = w.querySelector("i");
      mask.querySelector(".ch").textContent = zh.slice(0, 2);
      var p = mask.querySelector(".py");
      p.textContent = py ? py.textContent : "";
      p.classList.remove("hide");
      mask.classList.add("on");
    });
  }

  /* 单词自测：看中文选英文，当场判分 */
  function quizLab() {
    return labBox("单词自测",
      "看中文选英文，10 题一组，当场判分。错的题会留下，方便回头再看。",
      '<div class="row"><button id="qz-go" class="btn">开始自测</button>' +
      '<span id="qz-s" class="small"></span></div><div id="qz"></div>');
  }

  function bindQuiz() {
    var go = document.getElementById("qz-go"), box = document.getElementById("qz"),
        s = document.getElementById("qz-s");
    if (!go || !box) return;
    var pool = (D.vocab || []).filter(function (v) { return v.word && v.meaning; });
    var list = [], idx = 0, right = 0;
    function pick3(ans) {
      var out = [ans], guard = 0;
      while (out.length < 3 && guard++ < 50) {
        var w = pool[Math.floor(Math.random() * pool.length)].word;
        if (out.indexOf(w) < 0) out.push(w);
      }
      return out.sort(function () { return Math.random() - 0.5; });
    }
    function show() {
      if (idx >= list.length) {
        box.innerHTML = '<div class="big">做完了：' + right + " / " + list.length +
          "</div>" + (right < list.length
            ? '<p class="small">再练一组就会更熟。</p>' : '<p class="small">全对。</p>');
        s.textContent = "";
        return;
      }
      var v = list[idx], opts = pick3(v.word);
      s.textContent = "第 " + (idx + 1) + " / " + list.length + " 题　已对 " + right;
      box.innerHTML = '<div class="q"><div class="qw">' + esc(v.meaning) +
        (v.phonetic ? ' <span class="small">' + esc(v.phonetic) + "</span>" : "") +
        "</div>" + opts.map(function (w) {
          return '<span class="opt" data-w="' + esc(w) + '">' + esc(w) + "</span>";
        }).join("") + '<div class="fb"></div></div>';
    }
    go.addEventListener("click", function () {
      list = pool.slice();
      // 洗牌后取 10 题
      list.sort(function () { return Math.random() - 0.5; });
      list = list.slice(0, 10);
      idx = 0; right = 0;
      show();
    });
    box.addEventListener("click", function (e) {
      var o = e.target.closest(".opt");
      if (!o) return;
      var v = list[idx], ok = o.dataset.w === v.word;
      o.classList.add(ok ? "ok" : "no");
      box.querySelector(".fb").innerHTML = ok
        ? '<span class="ok-t">对</span>'
        : '<span class="no-t">正确答案：' + esc(v.word) + "</span>";
      if (ok) right++;
      idx++;
      setTimeout(show, 900);
    });
  }

  /* ================================================== 数学 · 解决问题
     卡应用题的孩子，卡的不是算，是"数量关系"：不知道已知什么、要求什么、
     先算哪一步。所以这里把每道题摊成 已知 → 所求 → 分步 → 答案，
     并且默认把答案折起来——先自己想，再一步步对着看。 */
  function probItem(p) {
    var h = '<div class="item prob"><div class="top"><span class="name">' +
      esc(p.name || p.ask || "") + "</span>" + where(p, "") +
      '<span class="tag d1">' + esc(p.keypoint) + "</span>" +
      '<span class="tag">' + esc(p.difficulty) + "</span>" +
      (p.type ? '<span class="tag">' + esc(p.type) + "</span>" : "") + "</div>";
    if (p.stem) h += '<div class="stem">' + esc(p.stem) + "</div>";
    h += '<div class="qa"><div class="given">已知：' + esc(p.given || "") +
      '</div><div class="ask">要求：' + esc(p.ask || "") + "</div></div>";
    h += '<div class="steps">' + (p.steps || []).map(function (s, i) {
      return '<div class="step hide"><b>' + (i + 1) + ".</b> " + esc(s.text || "") +
        (s.latex ? ' <span class="tex">' + tex(s.latex) + "</span>" : "") + "</div>";
    }).join("") + "</div>";
    h += '<div class="bar">' +
      '<span class="btn next">下一步</span><span class="btn ans">看答案</span>' +
      '<span class="btn reset">重来</span></div>' +
      '<div class="ansbox hide">答：' + esc(p.answer || "") +
      (p.answer_latex ? "（" + tex(p.answer_latex) + "）" : "") + "</div>";
    return h + "</div>";
  }

  function bindProblem(box) {
    box.addEventListener("click", function (e) {
      var b = e.target.closest(".btn"), it = e.target.closest(".item.prob");
      if (!b || !it) return;
      var steps = [].slice.call(it.querySelectorAll(".steps .step"));
      var box2 = it.querySelector(".ansbox");
      if (b.classList.contains("next")) {
        for (var i = 0; i < steps.length; i++) {
          if (steps[i].classList.contains("hide")) {
            steps[i].classList.remove("hide");
            break;
          }
        }
      } else if (b.classList.contains("ans")) {
        if (box2) box2.classList.remove("hide");
      } else if (b.classList.contains("reset")) {
        steps.forEach(function (s) { s.classList.add("hide"); });
        if (box2) box2.classList.add("hide");
      }
    });
  }

  function renderProblem() {
    var mh = mathLab(kind);
    if (mh) {
      var el = document.createElement("div");
      el.innerHTML = mh;
      app.appendChild(el);
      bindMathLab(kind);
    }
    var box = listBox();
    var kps = (D.keypoints || []).map(function (k) { return k.name; });
    var hard = [{ key: "基础", name: "基础" }, { key: "提高", name: "提高" },
                { key: "拓展", name: "拓展" }];
    var t = tools(hard, function (st, cnt) {
      var rows = (D.problems || []).filter(function (p) {
        if (st.tab !== "all" && p.difficulty !== st.tab) return false;
        if (st.book !== "all" && p.book !== st.book) return false;
        if (st.extra !== "all" && p.keypoint !== st.extra) return false;
        if (st.q && !(has(p.stem, st.q) || has(p.given, st.q) || has(p.ask, st.q) ||
                      has(p.keypoint, st.q) || has(p.unit, st.q))) return false;
        return true;
      });
      cnt.textContent = rows.length + " 道题";
      // 考点上千个，只把常见的单独成组，冷门的并进"其他考点"，免得刷出一堆只有一个题的组
      var top = {};
      (D.keypoints || []).forEach(function (k) { top[k.name] = 1; });
      box.innerHTML = byGroup(rows, st, function (p) {
        return top[p.keypoint] ? p.keypoint : "其他考点";
      }, probItem) || '<div class="empty">没有匹配的题目</div>';
    }, { hint: "如：分数、鸡兔同笼、相遇",
         tags: kps.slice(0, 20),
         extra: { label: "全部考点", opts: kps } });
    t.fire();
    bindProblem(box);

    // 教材里单独标出来的"生活中的数学"——学了有什么用，答案就在这儿
    if (D.life && D.life.length) {
      var lf = document.createElement("div");
      lf.innerHTML = "<h2>生活里的数学（教材原文）</h2>" +
        '<p class="lead">教材专门标出来的“生活中的数学”。学这个到底有什么用，' +
        "这些题就是答案——同样先自己想，再看分步。</p>" +
        D.life.slice(0, 80).map(probItem).join("");
      app.appendChild(lf);
      bindProblem(lf);
    }
  }

  /* ==================================================== 语文 · 课文骨架
     "读完了说不出写了什么"——概括这道坎，靠的是把结构看明白。
     教材只印课文，这里给出：全文分几层、每层写什么、主旨是什么。 */
  function structItem(x) {
    var parts = x.parts || [], n = x.n || 0;
    var h = '<div class="item"><div class="top"><span class="name">' + esc(x.title) +
      "</span>" + where(x, x.page) +
      (x.genre ? '<span class="tag d1">' + esc(x.genre) + "</span>" : "") +
      (n ? '<span class="where">共 ' + n + " 段</span>" : "") + "</div>";
    if (x.main) h += '<div class="elem">主旨：' + esc(x.main) + "</div>";
    if (x.why) h += '<p class="small">为什么算这一体裁：' + esc(x.why) + "</p>";
    if (parts.length) {
      var total = Math.max(1, n || parts.reduce(function (a, p) {
        return a + Math.max(1, (p.to || 0) - (p.from || 0) + 1);
      }, 0));
      h += '<div class="skel">' + parts.map(function (p, i) {
        var w = Math.max(1, (p.to || 0) - (p.from || 0) + 1) / total * 100;
        return '<span class="seg s' + (i % 6) + '" style="width:' + w.toFixed(1) +
          '%" title="' + esc(p.gist || "") + '"></span>';
      }).join("") + "</div>";
      h += '<ul class="pts">' + parts.map(function (p) {
        var seg = (p.from === p.to) ? "第" + ((p.from || 0) + 1) + "段"
          : "第" + ((p.from || 0) + 1) + "–" + ((p.to || 0) + 1) + "段";
        return "<li><b>" + seg + "</b>：" + esc(p.gist || "") + "</li>";
      }).join("") + "</ul>";
    }
    return h + "</div>";
  }

  function renderStructure() {
    var box = listBox();
    var gs = (D.genres || []).map(function (g) { return g[0]; });
    var t = tools([], function (st, cnt) {
      var rows = (D.structures || []).filter(function (x) {
        if (st.book !== "all" && x.book !== st.book) return false;
        if (st.extra !== "all" && x.genre !== st.extra) return false;
        if (st.q && !(has(x.title, st.q) || has(x.main, st.q) || has(x.genre, st.q) ||
                      has((x.parts || []).map(function (p) { return p.gist; }).join(" "), st.q)))
          return false;
        return true;
      });
      cnt.textContent = rows.length + " 篇";
      box.innerHTML = byGroup(rows, st, function (x) { return x.genre; }, structItem) ||
        '<div class="empty">没有匹配的课文</div>';
    }, { hint: "如：草原、说明文、借物喻人",
         tags: gs.slice(0, 16),
         extra: { label: "全部体裁", opts: gs } });
    t.fire();
  }

  /* ====================================================== 英语 · 开口说
     "哑巴英语"的根子不是单词量，是没地方说。教材每组对话本来就有角色、场景、
     功能，这里按角色摊开，可以一句一句推进，也可以遮住中文自测。 */
  function dlgItem(d) {
    var h = '<div class="item dlg"><div class="top"><span class="name">' +
      esc(d.title || d.scene || "") + "</span>" + where(d, "") +
      (d.scene ? '<span class="tag">' + esc(d.scene) + "</span>" : "") +
      (d.function ? '<span class="tag d1">' + esc(d.function) + "</span>" : "") + "</div>";
    if (d.patterns && d.patterns.length) {
      h += '<div class="words">' + d.patterns.map(function (p) {
        return '<span class="wb">' + esc(p) + "</span>";
      }).join("") + "</div>";
    }
    h += '<div class="turns">' + (d.turns || []).map(function (t, i) {
      return '<div class="turn r' + (t.s === "B" || (t.s || "").indexOf("B") >= 0 ? 2 : 1) +
        (i ? " hide" : "") + '"><span class="sp">' + esc(t.s || "A") + "</span>" +
        '<span class="en">' + esc(t.en || "") + "</span>" +
        '<span class="zh">' + esc(t.zh || "") + "</span></div>";
    }).join("") + "</div>";
    h += '<div class="bar"><span class="btn next">下一句</span>' +
      '<span class="btn all">全部展开</span>' +
      '<span class="btn zh">遮／显示中文</span></div>';
    return h + "</div>";
  }

  function bindSpeak(box) {
    box.addEventListener("click", function (e) {
      var b = e.target.closest(".btn"), it = e.target.closest(".item.dlg");
      if (!b || !it) return;
      var turns = [].slice.call(it.querySelectorAll(".turn"));
      if (b.classList.contains("next")) {
        for (var i = 0; i < turns.length; i++) {
          if (turns[i].classList.contains("hide")) {
            turns[i].classList.remove("hide");
            break;
          }
        }
      } else if (b.classList.contains("all")) {
        turns.forEach(function (t) { t.classList.remove("hide"); });
      } else if (b.classList.contains("zh")) {
        it.classList.toggle("nozh");
      }
    });
  }

  function projBlock() {
    if (!D.projects || !D.projects.length) return "";
    var h = "<h2>项目任务：做出一样东西</h2>" +
      '<p class="lead">英语的“做中学”：每组任务都写清要做出什么、分几步、' +
      "会用到哪几句话、要准备什么。</p>";
    h += D.projects.slice(0, 60).map(function (p) {
      var s = '<div class="item"><div class="top"><span class="name">' +
        esc(p.name || "") + "</span>" + where(p, "") +
        (p.type ? '<span class="tag">' + esc(p.type) + "</span>" : "") + "</div>";
      if (p.goal) s += '<div class="stem">' + esc(p.goal) + "</div>";
      if (p.steps && p.steps.length) {
        s += '<p class="small">怎么做</p><ul class="pts">' + p.steps.map(function (x) {
          return "<li>" + esc(x) + "</li>";
        }).join("") + "</ul>";
      }
      if (p.language && p.language.length) {
        s += '<p class="small">会用到的话</p><div class="words">' +
          p.language.map(function (x) {
            return '<span class="wb">' + esc(x) + "</span>";
          }).join("") + "</div>";
      }
      if (p.product) s += '<p class="small">做出来是什么：' + esc(p.product) + "</p>";
      if (p.materials && p.materials.length) {
        s += '<p class="small">要准备：' + esc(p.materials.join("、")) + "</p>";
      }
      return s + "</div>";
    }).join("");
    return h;
  }

  function exprBlock() {
    if (!D.exprs || !D.exprs.length) return "";
    return "<h2>常用表达</h2>" +
      '<p class="lead">点一句看中文，再点一下盖回去（自测）。</p>' +
      '<div class="card"><div class="words">' + D.exprs.slice(0, 200).map(function (e) {
        return '<span class="wb ex2"><b>' + esc(e.en) + "</b><i>" + esc(e.zh || "") + "</i></span>";
      }).join("") + "</div></div>";
  }

  function renderSpeak() {
    var box = listBox();
    var fs = (D.functions || []).map(function (f) { return f[0]; });
    var t = tools([], function (st, cnt) {
      var rows = (D.dialogues || []).filter(function (d) {
        if (st.book !== "all" && d.book !== st.book) return false;
        if (st.extra !== "all" && d.function !== st.extra) return false;
        if (st.q && !(has(d.title, st.q) || has(d.scene, st.q) || has(d.function, st.q) ||
                      has((d.turns || []).map(function (x) {
                        return (x.en || "") + " " + (x.zh || "");
                      }).join(" "), st.q))) return false;
        return true;
      });
      cnt.textContent = rows.length + " 组对话";
      box.innerHTML = byGroup(rows, st, function (d) {
        return d.function || d.scene;
      }, dlgItem) || '<div class="empty">没有匹配的对话</div>';
    }, { hint: "如：job、help、community",
         tags: fs.slice(0, 16),
         extra: { label: "全部功能", opts: fs } });
    t.fire();
    bindSpeak(box);

    var tail = document.createElement("div");
    tail.innerHTML = projBlock() + exprBlock();
    app.appendChild(tail);
    tail.addEventListener("click", function (e) {
      var w = e.target.closest(".ex2");
      if (w) w.classList.toggle("hidezh");
    });
  }

  if (kind === "problem") renderProblem();
  else if (kind === "structure") renderStructure();
  else if (kind === "speak") renderSpeak();
  else if (subject === "math") renderMath();
  else if (subject === "chinese") renderChinese();
  else if (subject === "english") renderEnglish();
})();

/* ============================================================== 宿主接口
   这个页面可以被三样东西驱动：人手点、window.AT、外面嵌它的 Agent（postMessage）。
   三条路走同一套 execute(action, params)，所以接 Agent 时不用另写一套逻辑，
   Agent 只需要会发动作名和参数。

   语音只留接口，不绑死实现：
     AT.asr —— 听写。默认用浏览器自带的识别，没有就把请求转给嵌它的父窗口
               （自己的 ASR 服务接在父窗口或宿主里，替换 AT.asr.adapter 即可）。
     AT.tts —— 朗读。默认用浏览器自带的合成，同理可换 adapter。
   识别结果默认写进搜索框（target: "q"），所以"说一句话就搜到"直接能用。

   内嵌协议（iframe）：
     页面 → 父：{source:"agent-textbook", type:"ready"|"event"|"result"|"asr.request"|"tts.request"}
     父 → 页面：{action, params, id} → 回 {type:"result", id, ok, data}
               {action:"asr.result", text, final} / {action:"asr.state",...}
*/
(function () {
  var VER = "1.0";
  var SRC = "agent-textbook";
  var pg = ((document.body && document.body.getAttribute("data-page")) || "").split("-");
  var subject = pg[0] || "";
  var kind = pg[1] || "";
  var D = window.DATA || {};      // 页面内联的数据（构建时写死在 HTML 里）

  function val(id) {
    var e = document.getElementById(id);
    return e ? e.value : "";
  }

  function items() {
    return [].slice.call(document.querySelectorAll("#list .item"));
  }

  // 条目编号：Agent 说"打开第 3 条"，页面得知道第 3 条是哪个
  function markupItems() {
    items().forEach(function (el, i) {
      el.setAttribute("data-agent", "item");
      el.setAttribute("data-idx", i);
    });
  }

  function setCtl(id, value, evt) {
    var el = document.getElementById(id);
    if (!el || value == null) return false;
    el.value = value;
    try {
      el.dispatchEvent(new Event(evt || "input", { bubbles: true }));
    } catch (e) {
      // 老环境没有 Event 构造器：退一步，至少把值写上
      if (el.onchange) el.onchange();
    }
    return true;
  }

  function clickSel(sel, match) {
    var hit = null;
    [].forEach.call(document.querySelectorAll(sel), function (el) {
      if (!hit && (!match || match(el))) hit = el;
    });
    if (hit) { hit.click(); return true; }
    return false;
  }

  /* ---- 事件总线：页面里的变化都往外发，外面的面板可以订阅 ---- */
  var handlers = {};

  function on(ev, fn) {
    (handlers[ev] = handlers[ev] || []).push(fn);
    return fn;
  }

  function off(ev, fn) {
    handlers[ev] = (handlers[ev] || []).filter(function (f) { return f !== fn; });
  }

  function emit(ev, data) {
    [].concat(handlers[ev] || [], handlers["*"] || []).forEach(function (f) {
      try {
        f(ev === "*" ? data : data, ev);
      } catch (e) {}
    });
    if (ev !== "*") post({ type: "event", ev: ev, data: data });
  }

  function post(msg) {
    try {
      if (window.parent && window.parent !== window) {
        msg.source = SRC;
        msg.version = VER;
        window.parent.postMessage(msg, "*");
      }
    } catch (e) {}
  }

  /* ---- 听写（ASR）：接口在这里，实现可以换 ---- */
  var asr = {
    adapter: null,           // 宿主注入：{start(opt), stop()} → 通过 asr.push(text, final) 回传
    lang: "zh-CN",
    running: false,
    target: "q",             // 识别结果默认落到搜索框
    onResult: null,          // function(text, final)

    available: function () {
      return !!asr.adapter ||
        !!(window.SpeechRecognition || window.webkitSpeechRecognition) ||
        !!(window.parent && window.parent !== window);
    },
    push: function (text, final) { asr._recv({ text: text, final: final }); },
    start: function (opt) {
      opt = opt || {};
      asr.target = opt.target || asr.target;
      asr.lang = opt.lang || asr.lang;
      if (asr.adapter && asr.adapter.start) {
        asr.running = true;
        asr.adapter.start(opt);
        emit("asr.state", { running: true });
        return true;
      }
      var R = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (R) {
        try {
          var rec = new R();
          rec.lang = asr.lang;
          rec.interimResults = true;
          rec.continuous = !!opt.continuous;
          rec.onresult = function (ev) {
            var txt = "", fin = true, i;
            for (i = ev.resultIndex; i < ev.results.length; i++) {
              txt += ev.results[i][0].transcript;
              fin = fin && ev.results[i].isFinal;
            }
            asr._recv({ text: txt, final: fin });
          };
          rec.onerror = function (ev) {
            asr.running = false;
            emit("asr.state", { running: false, error: ev && ev.error });
          };
          rec.onend = function () {
            asr.running = false;
            emit("asr.state", { running: false });
          };
          rec.start();
          asr._rec = rec;
          asr.running = true;
          emit("asr.state", { running: true });
          return true;
        } catch (e) {}
      }
      // 页面里没有识别能力：嵌在 iframe 里就请父窗口代劳
      if (window.parent && window.parent !== window) {
        post({ type: "asr.request", action: "asr.start",
               lang: asr.lang, target: asr.target });
        asr.running = true;
        emit("asr.state", { running: true, via: "parent" });
        return true;
      }
      emit("asr.state", { running: false, error: "unavailable" });
      return false;
    },
    stop: function () {
      if (asr._rec) { try { asr._rec.stop(); } catch (e) {} }
      if (asr.adapter && asr.adapter.stop) asr.adapter.stop();
      if (window.parent && window.parent !== window) {
        post({ type: "asr.request", action: "asr.stop" });
      }
      asr.running = false;
      emit("asr.state", { running: false });
      return true;
    },
    _recv: function (d) {
      var t = String((d && d.text) || "").trim();
      if (!t) return;
      var fin = d.final !== false;
      if (fin && asr.target) setCtl(asr.target, t, "input");   // 说一句话就搜到
      if (typeof asr.onResult === "function") asr.onResult(t, fin);
      emit("asr.result", { text: t, final: fin });
    }
  };

  /* ---- 朗读（TTS）：接口在这里，实现可以换 ---- */
  var tts = {
    adapter: null,           // 宿主注入：{speak(text, opt), stop()}
    lang: "zh-CN",
    rate: 1,
    speaking: false,

    available: function () {
      return !!tts.adapter || !!window.speechSynthesis ||
        !!(window.parent && window.parent !== window);
    },
    speak: function (text, opt) {
      opt = opt || {};
      text = String(text || "").trim();
      if (!text) return false;
      if (tts.adapter && tts.adapter.speak) {
        tts.speaking = true;
        tts.adapter.speak(text, opt);
        emit("tts.state", { speaking: true, chars: text.length });
        return true;
      }
      if (window.speechSynthesis && window.SpeechSynthesisUtterance) {
        var u = new window.SpeechSynthesisUtterance(text.slice(0, 500));
        u.lang = opt.lang || tts.lang;
        u.rate = opt.rate || tts.rate;
        u.onend = function () {
          tts.speaking = false;
          emit("tts.state", { speaking: false });
        };
        window.speechSynthesis.speak(u);
        tts.speaking = true;
        emit("tts.state", { speaking: true, chars: text.length });
        return true;
      }
      if (window.parent && window.parent !== window) {
        post({ type: "tts.request", action: "tts.speak",
               text: text, lang: opt.lang || tts.lang });
        emit("tts.state", { speaking: true, via: "parent", chars: text.length });
        return true;
      }
      emit("tts.state", { speaking: false, error: "unavailable" });
      return false;
    },
    stop: function () {
      if (tts.adapter && tts.adapter.stop) tts.adapter.stop();
      if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) {} }
      tts.speaking = false;
      emit("tts.state", { speaking: false });
      return true;
    }
  };

  /* ---- 动作表：Agent 能做的事都写在这儿，参数一眼能看懂 ---- */
  var ACTIONS = [
    { name: "search", params: "{q}", desc: "按关键词筛选（写进搜索框，和人敲字一样）" },
    { name: "filter", params: "{book?, extra?, tab?}", desc: "按册次／附加条件／页签筛选" },
    { name: "set", params: "{id, value, evt?}", desc: "直接给某个控件设值并触发事件" },
    { name: "click", params: "{selector}", desc: "点页面上的东西（页签、标签、跳转）" },
    { name: "query", params: "{q, limit?}", desc: "在本页数据里检索，返回条目与下标" },
    { name: "open", params: "{idx}", desc: "展开第 idx 条里的折叠内容（详解/分步）" },
    { name: "highlight", params: "{idx}", desc: "滚动到第 idx 条并高亮" },
    { name: "read", params: "{idx? | text? | selector?}", desc: "朗读：默认读第 idx 条" },
    { name: "listen", params: "{on, target?}", desc: "听写开关，结果写进 target（默认搜索框）" },
    { name: "speak", params: "{text}", desc: "朗读任意文本（TTS）" },
    { name: "goto", params: "{subject?, slug?}", desc: "跳到某个学科／专题页" },
    { name: "state", params: "{}", desc: "当前页面状态：学科、专题、筛选条件、可见条数" },
    { name: "actions", params: "{}", desc: "列出所有可用动作" }
  ];

  // 本页数据里可供检索的池子（按学科切片，页面上有什么就搜什么）
  var POOLS = ["units", "texts", "pieces", "structures", "elements", "problems",
               "vocab", "grammar", "phonics", "passages", "dialogues", "songs",
               "projects", "exprs", "topics", "measures"];

  function eachRow(k, fn) {
    var v = D[k];
    if (!v) return;
    if (v instanceof Array) { v.forEach(fn); return; }
    Object.keys(v).forEach(function (kk) {
      var vv = v[kk];
      if (vv instanceof Array) vv.forEach(fn);
    });
  }

  function query(opt) {
    opt = opt || {};
    var q = String(opt.q || "").trim().toLowerCase();
    var lim = opt.limit || 20;
    var out = [];
    if (!q) return out;
    POOLS.forEach(function (k) {
      var i = 0;
      eachRow(k, function (x) {
        var n = i++;
        if (out.length >= lim) return;
        var s = JSON.stringify(x);
        if (s.toLowerCase().indexOf(q) < 0) return;
        out.push({
          pool: k, idx: n,
          title: x.title || x.name || x.word || x.text || x.unit || "",
          where: [x.book, x.unit_no ? "第" + x.unit_no + "单元" : "", x.unit]
                 .filter(Boolean).join(" · ")
        });
      });
    });
    return out;
  }

  function state() {
    var tab = document.querySelector(".tab.on");
    return {
      subject: subject, kind: kind,
      page: ((window.location && window.location.pathname) || "").split("/").pop(),
      filters: { q: val("q"), book: val("bk"), extra: val("ex"),
                 tab: tab && tab.dataset ? tab.dataset.t : "" },
      visible: items().length,
      asr: asr.running, tts: tts.speaking
    };
  }

  function textOf(el) {
    return String((el && (el.innerText || el.textContent)) || "")
      .replace(/\s+/g, " ").trim();
  }

  function read(opt) {
    opt = opt || {};
    var t = opt.text;
    if (!t) {
      var el = opt.idx != null ? items()[opt.idx]
        : (opt.selector ? document.querySelector(opt.selector) : null);
      t = textOf(el).slice(0, 400);
    }
    if (!t) return false;
    return tts.speak(t, opt);
  }

  function run(name, p) {
    p = p || {};
    switch (name) {
      case "search": return { ok: setCtl("q", p.q, "input") };
      case "filter":
        var r = {};
        if (p.book != null) r.book = setCtl("bk", p.book, "change");
        if (p.extra != null) r.extra = setCtl("ex", p.extra, "change");
        if (p.tab != null) {
          r.tab = clickSel(".tab", function (el) {
            return el.dataset && el.dataset.t === p.tab;
          });
        }
        return r;
      case "set": return { ok: setCtl(p.id, p.value, p.evt) };
      case "click": return { ok: clickSel(p.selector) };
      case "query": return query(p);
      case "open": {
        var el = items()[p.idx];
        if (!el) return null;
        [].forEach.call(el.querySelectorAll("details"), function (d) { d.open = true; });
        if (el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "center" });
        return { idx: p.idx, title: textOf(el).slice(0, 60) };
      }
      case "highlight": {
        var h = items()[p.idx];
        if (!h) return null;
        items().forEach(function (x) { x.classList.remove("at-hl"); });
        h.classList.add("at-hl");
        if (h.scrollIntoView) h.scrollIntoView({ behavior: "smooth", block: "center" });
        return { idx: p.idx, title: textOf(h).slice(0, 60) };
      }
      case "read": return { ok: read(p) };
      case "speak": return { ok: tts.speak(p.text || "", p) };
      case "listen": return { ok: p.on === false ? asr.stop() : asr.start(p) };
      case "goto": {
        var url = p.url || (p.subject
          ? "../" + p.subject + "/" + (p.slug || "index") + ".html"
          : (p.slug || "index") + ".html");
        if (window.location) window.location.href = url;
        return { url: url };
      }
      case "state": return state();
      case "actions": return ACTIONS;
      default: throw new Error("没有这个动作：" + name);
    }
  }

  function execute(name, params) {
    try {
      var d = run(name, params || {});
      emit("action", { name: name, params: params || {} });
      return { ok: true, data: d };
    } catch (e) {
      return { ok: false, error: String((e && e.message) || e) };
    }
  }

  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!d || typeof d !== "object") return;
    if (d.target && d.target !== SRC) return;
    // 语音结果／状态由父窗口回传（自己的 ASR 服务接在父窗口那一侧）
    if (d.action === "asr.result") { asr._recv(d); return; }
    if (d.action === "asr.state") { emit("asr.state", d); return; }
    if (d.action === "tts.state") { emit("tts.state", d); return; }
    if (!d.action) return;
    var r = execute(d.action, d.params || {});
    post({ type: "result", id: d.id, ok: r.ok, data: r.data, error: r.error });
  });

  function boot() {
    markupItems();
    var app = document.getElementById("app");
    if (window.MutationObserver && app) {
      // 筛选后条目会重排：重新编号，并把最新状态发出来
      new window.MutationObserver(function () {
        markupItems();
        emit("render", state());
      }).observe(app, { childList: true, subtree: true });
    }
    post({ type: "ready", actions: ACTIONS, page: state() });
    emit("ready", { version: VER, page: state() });
  }

  window.AT = {
    version: VER, ready: true,
    subject: subject, kind: kind,
    actions: function () { return ACTIONS; },
    execute: execute,
    query: query,
    state: state,
    items: items,
    data: function () { return D; },
    read: read,
    asr: asr,
    tts: tts,
    on: on, off: off, emit: emit
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
