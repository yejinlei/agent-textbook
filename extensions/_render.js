/* 课外拓展：筛选器 + 书目卡片 + 阅读器（正文按需加载 texts/{id}.js） */
(function () {
  var D = window.DATA || { books: [], pairings: [], roles: {}, facets_labels: {} };
  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  // 兜底美化：taxonomy 没给中文标签的字段（如 topic / cultural_origin / time_period）
  var PRETTY = {
    topic: {
      animal: "动物", "animal.fable": "动物寓言", "family.pets": "家庭宠物",
      "nature.cosmic": "自然·宇宙", "nature.plants": "自然·植物",
      "narrative.hero": "英雄叙事", identity: "身份认同",
      friendship: "友谊", food: "食物", job: "职业", money: "金钱", poverty: "贫困",
    },
    cultural_origin: {
      British: "英国", American: "美国", Danish: "丹麦", Greek: "古希腊",
      "Swiss_German": "瑞士德语区", French: "法国",
      "British_Indian": "英属印度", "British_Scottish": "苏格兰",
      "British_Irish": "爱尔兰", Canadian: "加拿大",
      "British_American": "英美", Kenyan: "肯尼亚", Ethiopian: "埃塞俄比亚",
      Ghanaian: "加纳", "South_African": "南非", "African_Oral": "非洲口传",
      Other: "其他",
    },
    time_period: {
      timeless_fantasy: "无时代/奇幻", medieval: "中世纪",
      "18th_century": "18 世纪", victorian: "维多利亚时代",
      "early_20th": "20 世纪初", modern: "现代",
    },
    lexile_band: {
      elementary_low: "小学低（200–500L）",
      elementary_mid: "小学中（500–800L）",
      elementary_high: "小学高（800–1000L）",
      middle_early: "初中早（1000–1200L）",
      middle_late: "初中晚（1200–1500L）",
    },
    word_bucket: {
      very_short: "极短 <500", short: "短 500–1500",
      medium: "中 1500–3000", long: "长 3000–5000", very_long: "超长 5000+",
    },
    text_type: {
      fable: "寓言", folktale: "民间故事", fantasy: "幻想文学",
      realistic_fiction: "现实虚构", adventure: "冒险",
      detective: "侦探", satire: "讽刺游记",
    },
  };

  function label(k, dict) {
    if (!k) return k;
    var v = (dict || {})[k];
    if (v == null || v === "") {
      // 用 pretty 兜底
      var keys = ["topic","cultural_origin","time_period","lexile_band","word_bucket","text_type"];
      for (var i = 0; i < keys.length; i++) {
        var p = PRETTY[keys[i]] && PRETTY[keys[i]][k];
        if (p) return p;
      }
      return k;
    }
    if (typeof v === "string") return v;
    return v.zh || v.label || k;
  }

  /* 从 books / pairings 聚合筛选选项 + 计数 */
  var allBooks = D.books || [];
  var allPairs = D.pairings || [];
  var labelMap = D.facets_labels || {};
  var roles = D.roles || {};

  // 每本书汇总该书的 pairings
  var pairsByBook = {};
  allPairs.forEach(function (p) {
    (pairsByBook[p.reading_id] = pairsByBook[p.reading_id] || []).push(p);
  });

  /* ---------- 筛选维度定义 ----------
     每个维度: { key, group, label, values: [{value, label, count}] }
     勾选 = AND 组内 OR，组间 AND */
  var GRADE_ORDER = ["1","2","3","4","5","6"];

  function uniqCount(bks, fn) {
    var s = {};
    bks.forEach(function (b) { (fn(b) || []).forEach(function (v) { if (v != null) s[v] = 1; }); });
    return Object.keys(s).length;
  }

  function collectValues(key) {
    var m = {};
    allBooks.forEach(function (b) {
      var vals = b[key] || [];
      if (!Array.isArray(vals)) vals = vals == null ? [] : [vals];
      vals.forEach(function (v) { if (v != null && v !== "") m[v] = (m[v] || 0) + 1; });
    });
    return m;
  }

  var dimensions = [
    { group: "教材单元", key: "unit", label: "教材单元", values: (function () {
        var m = {};
        allPairs.forEach(function (p) {
          if (!m[p.section_id]) {
            m[p.section_id] = {
              value: p.section_id,
              label: (p.unit_name || "") + " " + (p.unit_title || "").slice(0, 24),
              count: 0,
              raw: p
            };
          }
          m[p.section_id].count += 1;
        });
        return Object.keys(m).map(function (k) { return m[k]; });
      })() },
    { group: "题材", key: "primary_topic", label: "题材", values: Object.keys(collectValues("primary_topic")).map(function (v) {
        return { value: v, label: label(v, labelMap.topics), count: collectValues("primary_topic")[v] };
      }) },
    { group: "文本类型", key: "text_type", label: "文本类型", values: Object.keys(collectValues("text_type")).map(function (v) {
        return { value: v, label: label(v, labelMap.text_types), count: collectValues("text_type")[v] };
      }) },
    { group: "主题", key: "themes", label: "主题", values: Object.keys(collectValues("themes")).map(function (v) {
        return { value: v, label: label(v, labelMap.themes), count: collectValues("themes")[v] };
      }) },
    { group: "年级", key: "grade", label: "年级", values: GRADE_ORDER.map(function (g) {
        return { value: g, label: g + " 年级", count: (collectValues("grade") || {})[g] || 0 };
      }).filter(function (v) { return v.count > 0; }) },
    { group: "Lexile 难度", key: "lexile_band", label: "Lexile 难度", values: Object.keys(collectValues("lexile_band")).map(function (v) {
        return { value: v, label: label(v, labelMap.lexile_bands), count: collectValues("lexile_band")[v] };
      }) },
    { group: "词汇量", key: "word_count_bucket", label: "词汇量", values: Object.keys(collectValues("word_count_bucket")).map(function (v) {
        return { value: v, label: label(v, labelMap.word_buckets), count: collectValues("word_count_bucket")[v] };
      }) },
    { group: "文化源", key: "cultural_origin", label: "文化源", values: Object.keys(collectValues("cultural_origin")).map(function (v) {
        return { value: v, label: label(v, labelMap.cultural_origins), count: collectValues("cultural_origin")[v] };
      }) },
    { group: "教学角色", key: "text_role", label: "教学角色", values: Object.keys(roles).map(function (k) {
        return { value: k, label: (roles[k] || {}).label_zh || k, count: 0 };
      }) },
    { group: "技能", key: "target_skills", label: "目标技能", values: Object.keys(collectValues("target_skills")).map(function (v) {
        return { value: v, label: label(v, labelMap.skills), count: collectValues("target_skills")[v] };
      }) },
  ];

  // 教学角色计数
  dimensions.forEach(function (dim) {
    if (dim.key === "text_role") {
      dim.values.forEach(function (v) {
        allBooks.forEach(function (b) {
          if ((b.text_role || []).indexOf(v.value) >= 0) v.count += 1;
        });
      });
    }
  });
  // 过滤 0 值
  dimensions.forEach(function (dim) {
    dim.values = dim.values.filter(function (v) { return v.count > 0; });
  });

  /* ---------- 当前勾选状态 ---------- */
  var state = {
    checked: {},   // key -> Set(value)
    currentBook: null,
    sort: "title",
  };
  dimensions.forEach(function (d) { state.checked[d.key] = {}; });

  function isChecked(dimKey, val) {
    return state.checked[dimKey] && state.checked[dimKey][val];
  }

  /* ---------- 过滤逻辑 ---------- */
  function passes(b, dimKey) {
    var chosen = state.checked[dimKey];
    var n = 0;
    for (var k in chosen) { if (chosen[k]) n++; }
    if (!n) return true;
    var bvals = b[dimKey] || [];
    if (!Array.isArray(bvals)) bvals = bvals == null ? [] : [bvals];
    for (var i = 0; i < bvals.length; i++) {
      if (chosen[bvals[i]]) return true;
    }
    return false;
  }

  // "教材单元" 维度是 pairings 维度，需要走 pairsByBook
  function passesUnit(b) {
    var chosen = state.checked.unit;
    var n = 0;
    for (var k in chosen) { if (chosen[k]) n++; }
    if (!n) return true;
    var ps = pairsByBook[b.id] || [];
    for (var i = 0; i < ps.length; i++) {
      if (chosen[ps[i].section_id]) return true;
    }
    return false;
  }

  function filteredBooks() {
    var bks = allBooks.filter(function (b) {
      if (!passesUnit(b)) return false;
      for (var i = 0; i < dimensions.length; i++) {
        var d = dimensions[i];
        if (d.key === "unit") continue;
        if (!passes(b, d.key)) return false;
      }
      return true;
    });
    // 排序
    var s = state.sort;
    bks.sort(function (a, b) {
      if (s === "title") return (a.title || "").localeCompare(b.title || "");
      if (s === "lexile") {
        var av = a.lexile ? a.lexile.mean : 0;
        var bv = b.lexile ? b.lexile.mean : 0;
        return av - bv;
      }
      if (s === "words") return (a.word_count || 0) - (b.word_count || 0);
      if (s === "grade") {
        var ag = (a.grade || []).slice().sort().join(",");
        var bg = (b.grade || []).slice().sort().join(",");
        return ag.localeCompare(bg);
      }
      return 0;
    });
    return bks;
  }

  /* ---------- 渲染筛选栏 ---------- */
  function renderFilters() {
    var html = "";
    dimensions.forEach(function (d) {
      if (!d.values.length) return;
      html += '<h4>' + esc(d.label) + '</h4>';
      d.values.forEach(function (v) {
        var id = "f_" + d.key + "_" + String(v.value).replace(/[^a-zA-Z0-9_-]/g, "_");
        var ck = isChecked(d.key, v.value) ? "checked" : "";
        html += '<label class="chk"><input type="checkbox" data-dim="' + d.key + '" data-val="' + esc(v.value) + '" ' + ck + '>' +
          '<span>' + esc(v.label) + '</span>' +
          '<span class="hint">' + v.count + '</span></label>';
      });
      html += '<div class="divider"></div>';
    });
    html += '<div class="actions">' +
      '<button id="clearBtn">清空筛选</button>' +
      '<button id="expandAllBtn">全选题材</button>' +
      '</div>';
    $("filterCol").innerHTML = html;

    // 事件委托
    $("filterCol").querySelectorAll('input[type="checkbox"]').forEach(function (el) {
      el.onchange = function () {
        var d = el.dataset.dim, v = el.dataset.val;
        state.checked[d][v] = el.checked;
        // 关闭阅读器视图
        state.currentBook = null;
        renderMain();
      };
    });
    var clear = $("clearBtn");
    if (clear) clear.onclick = function () {
      for (var k in state.checked) { for (var v in state.checked[k]) { delete state.checked[k][v]; } }
      state.currentBook = null;
      renderFilters();
      renderMain();
    };
    var ex = $("expandAllBtn");
    if (ex) ex.onclick = function () {
      var d = dimensions.filter(function (x) { return x.key === "primary_topic"; })[0];
      if (!d) return;
      d.values.forEach(function (v) { state.checked.primary_topic[v.value] = true; });
      state.currentBook = null;
      renderFilters();
      renderMain();
    };
  }

  /* ---------- 渲染书目卡片 ---------- */
  function renderBooks(bks) {
    if (!bks.length) {
      $("app").innerHTML = '<div class="empty-state">' +
        '<div class="big">∅</div>' +
        '<p>当前筛选条件下没有匹配的读物</p>' +
        '<p>试试清空筛选或调整条件</p></div>';
      return;
    }
    var html = '<div class="grid-books">';
    bks.forEach(function (b) {
      var grade = (b.grade || []).join("/");
      var lex = b.lexile ? (b.lexile.min + "–" + b.lexile.max) : "—";
      var tags = [];
      if (b.primary_topic) tags.push('<span class="tag">' + esc(label(b.primary_topic, labelMap.topics)) + '</span>');
      if (b.text_type) tags.push('<span class="tag t">' + esc(label(b.text_type, labelMap.text_types)) + '</span>');
      if (b.grade && b.grade.length) tags.push('<span class="tag g">' + esc(grade) + '年级</span>');
      var nPair = (pairsByBook[b.id] || []).length;
      var rolesOfBook = (b.text_role || []).slice(0, 3).map(function (k) {
        return '<span class="tag" style="background:#f0f8f4;">' + esc((roles[k] || {}).label_zh || k) + '</span>';
      }).join("");
      html += '<div class="book" data-id="' + esc(b.id) + '">' +
        '<span class="arrow">→</span>' +
        '<div class="title">' + esc(b.title) + '</div>' +
        '<div class="author">' + esc(b.author || "") + '</div>' +
        '<div class="meta">' + tags.join("") + '</div>' +
        (rolesOfBook ? '<div class="meta" style="margin-top:4px;">' + rolesOfBook + '</div>' : '') +
        '<div class="stat">' +
          '<span>📖 <b>' + (b.word_count || "—") + '</b> 词</span>' +
          '<span>Lexile <b>' + esc(lex) + '</b></span>' +
          '<span>🎯 <b>' + nPair + '</b> 条挂载</span>' +
        '</div>' +
        '</div>';
    });
    html += '</div>';
    $("app").innerHTML = html;
    $("app").querySelectorAll(".book").forEach(function (el) {
      el.onclick = function () {
        state.currentBook = el.dataset.id;
        renderMain();
      };
    });
  }

  /* ---------- 渲染阅读器 ---------- */
  function renderReader(book) {
    var grade = (book.grade || []).join("/");
    var lex = book.lexile ? (book.lexile.min + "–" + book.lexile.max) : "—";
    var tagOf = function (k, dict) { return '<span class="tag">' + esc(label(k, dict)) + '</span>'; };

    var facets = [];
    if (book.primary_topic) facets.push(tagOf(book.primary_topic, labelMap.topics));
    (book.themes || []).forEach(function (t) { facets.push('<span class="tag k">' + esc(label(t, labelMap.themes)) + '</span>'); });
    if (book.text_type) facets.push('<span class="tag k">' + esc(label(book.text_type, labelMap.text_types)) + '</span>');
    if (book.cultural_origin) facets.push('<span class="tag k">' + esc(label(book.cultural_origin, labelMap.cultural_origins)) + '</span>');
    if (book.time_period) facets.push('<span class="tag k">' + esc(book.time_period) + '</span>');
    if (book.grade && book.grade.length) facets.push('<span class="tag">' + esc(grade) + ' 年级</span>');
    if (book.lexile) facets.push('<span class="tag">Lexile ' + esc(lex) + '</span>');
    if (book.word_count_bucket) facets.push('<span class="tag">' + esc(label(book.word_count_bucket, labelMap.word_buckets)) + '</span>');

    var pairs = pairsByBook[book.id] || [];
    var unitHtml = "";
    if (pairs.length) {
      var parts = [];
      pairs.forEach(function (p) {
        var gradeTerm = (p.grade || "") + (p.term || "");
        var unitLabel = p.unit_name
          ? (p.unit_name + (p.unit_title ? ' ' + p.unit_title.slice(0, 24) : ""))
          : (p.unit_title || "教材单元");
        var roleZh = (roles[p.role] || {}).label_zh || p.role;
        parts.push('<span class="up">' +
          '<span class="gt">' + esc(gradeTerm) + '</span>' +
          '<b>' + esc(unitLabel) + '</b>' +
          '<span class="rl">' + esc(roleZh) + '</span>' +
          '</span>');
      });
      unitHtml = '<div class="unitbox">' +
        '<div class="uh">挂在教材上 · ' + pairs.length + ' 条</div>' +
        '<div class="ul">' + parts.join("") + '</div>' +
        '</div>';
    }

    var html = '<div class="reader">' +
      '<div class="back" id="backBtn">← 返回列表</div>' +
      '<h2 class="title">' + esc(book.title) + '</h2>' +
      '<div class="author">' + esc(book.author || "佚名") + ' · ' + (book.word_count || "—") + ' 词 · ' + (book.reading_time_min || "—") + ' 分钟</div>' +
      '<div class="facets">' + facets.join("") + '</div>' +
      unitHtml +
      '<div class="body" id="bookBody"><div class="loading">加载正文中…</div></div>' +
      '</div>';
    $("app").innerHTML = html;

    $("backBtn").onclick = function () {
      state.currentBook = null;
      renderMain();
    };

    loadText(book.id);
  }

  /* ---------- 动态加载正文 ---------- */
  var textCache = {};
  function loadText(id) {
    var body = $("bookBody");
    if (!body) return;
    if (textCache[id]) {
      body.innerHTML = textCache[id];
      return;
    }
    body.innerHTML = '<div class="loading">加载正文中…</div>';
    var s = document.createElement("script");
    s.src = "texts/" + id + ".js";
    s.onload = function () {
      var data = (window.TEXTS && window.TEXTS[id]) || null;
      if (data && data.html) {
        textCache[id] = data.html;
        body.innerHTML = data.html;
        body.scrollTop = 0;
      } else {
        body.innerHTML = '<div class="error">未找到 ' + esc(id) + ' 的正文文件</div>';
      }
    };
    s.onerror = function () {
      body.innerHTML = '<div class="error">正文文件加载失败：texts/' + esc(id) + '.js<br>请确认已运行 <code>tools/build_extensions_texts.py</code></div>';
    };
    document.head.appendChild(s);
  }

  /* ---------- 主渲染 ---------- */
  function renderMain() {
    if (state.currentBook) {
      var book = allBooks.filter(function (b) { return b.id === state.currentBook; })[0];
      if (book) { renderReader(book); }
      else { state.currentBook = null; }
    }
    var bks = filteredBooks();
    $("cBooks").textContent = bks.length;
    var nPair = 0;
    bks.forEach(function (b) { nPair += (pairsByBook[b.id] || []).length; });
    $("cPairs").innerHTML = '<b>' + nPair + '</b> 条挂载';
    if (!state.currentBook) renderBooks(bks);
  }

  $("sortKey").onchange = function () {
    state.sort = this.value;
    renderMain();
  };

  $("upd").textContent = D.updated || "";
  renderFilters();
  renderMain();
})();
