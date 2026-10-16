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

  /* ---- 点读：单词/句子/段落一键朗读。
        优先级：
          1) 本地 Piper MP3（英语页有 ../tts/map.json，命中率取决于该词/句是否在
             教材里出现过；命中就用 selectedVoice 播放，音质保准）
          2) 宿主注入的 window.ttsSpeak（iframe 里被父窗口拦截的情况）
          3) 浏览器原生 speechSynthesis（离线可用，音质因平台而异）
          4) Google Translate TTS（在线兜底）
        音色选择器：英语页顶部挂一个下拉框，选后写进 localStorage("ttsVoice")。 */
  var speechCurrent = null;
  var currentVoice = (function () {
    try { return localStorage.getItem("ttsVoice") || "alan"; } catch (e) { return "alan"; }
  })();
  function setVoice(v) {
    if (!v || v === currentVoice) return;
    currentVoice = v;
    try { localStorage.setItem("ttsVoice", v); } catch (e) {}
  }
  /* 音色元数据：fallback 到浏览器 speechSynthesis 时用来区分英美、调整音高 */
  var VOICE_META = {
    alan:  { lang: "en-GB", pitch: 1.0 },
    jenny: { lang: "en-GB", pitch: 1.15 },
    amy:   { lang: "en-US", pitch: 1.2 },
    cori:  { lang: "en-GB", pitch: 1.1 }
  };
  function currentVoiceMeta() { return VOICE_META[currentVoice] || VOICE_META.alan; }
  /* 从浏览器 speechSynthesis 的 voice 列表里按目标语言挑一个：
     优先完全匹配的 lang（en-GB / en-US），再退化到任意 en-* 音色。 */
  function pickBrowserVoice(targetLang) {
    if (!window.speechSynthesis || typeof window.speechSynthesis.getVoices !== "function") return null;
    try {
      var vs = window.speechSynthesis.getVoices() || [];
      var want = (targetLang || "en-GB").toLowerCase();
      var picked = null;
      for (var i = 0; i < vs.length; i++) {
        var lang = (vs[i].lang || "").toLowerCase();
        if (lang === want) { picked = vs[i]; break; }
        if (!picked && lang.indexOf("en-") === 0) picked = vs[i];
      }
      return picked;
    } catch (e) { return null; }
  }
  var TTS_MAP = null;       // {cleaned_text: {voice: "voice/hash.mp3"}}
  var TTS_MAP_FAILED = false; // 首次 404 后不再重试
  var TTS_MAP_LOADED = false;
  var TTS_PREVIEW = null;    // {voice: "voice/hash.mp3"}
  var TTS_PREVIEW_LOADED = false;
  var TTS_BASE = "../tts/"; // 静态站点根目录下的 tts/ 目录

  function loadTtsMap() {
    if (TTS_MAP) return Promise.resolve(TTS_MAP);
    if (TTS_MAP_LOADED) return Promise.resolve(TTS_MAP || {});
    TTS_MAP_LOADED = true;
    return new Promise(function (resolve) {
      try {
        var x = new XMLHttpRequest();
        x.open("GET", TTS_BASE + "map.json", true);
        x.onload = function () {
          if (x.status === 200 || x.status === 0) {
            try { TTS_MAP = JSON.parse(x.responseText || "{}"); } catch (e) { TTS_MAP = {}; }
          } else {
            TTS_MAP_FAILED = true;
            TTS_MAP = {};
          }
          resolve(TTS_MAP);
        };
        x.onerror = function () { TTS_MAP_LOADED = false; resolve(TTS_MAP || {}); };
        x.send(null);
      } catch (e) { TTS_MAP_LOADED = false; resolve(TTS_MAP || {}); }
    });
  }
  function loadTtsPreview() {
    if (TTS_PREVIEW) return Promise.resolve(TTS_PREVIEW);
    if (TTS_PREVIEW_LOADED) return Promise.resolve(TTS_PREVIEW || {});
    TTS_PREVIEW_LOADED = true;
    return new Promise(function (resolve) {
      try {
        var x = new XMLHttpRequest();
        x.open("GET", TTS_BASE + "preview.json", true);
        x.onload = function () {
          if (x.status === 200 || x.status === 0) {
            try { TTS_PREVIEW = JSON.parse(x.responseText || "{}"); } catch (e) { TTS_PREVIEW = {}; }
          } else { TTS_PREVIEW = {}; }
          resolve(TTS_PREVIEW);
        };
        x.onerror = function () { TTS_PREVIEW_LOADED = false; resolve(TTS_PREVIEW || {}); };
        x.send(null);
      } catch (e) { TTS_PREVIEW_LOADED = false; resolve(TTS_PREVIEW || {}); }
    });
  }
  /* 播放某个音色的一段固定试听音频；不走 speech() 的降级链，直接 new Audio() */
  function ttsPreview(voice) {
    stopTtsAudio();
    if (window.speechSynthesis) try { window.speechSynthesis.cancel(); } catch (e) {}
    if (googleAudio) { try { googleAudio.pause(); } catch (e) {} googleAudio = null; }
    function doPlay(file) {
      if (!file) { speakText("Hello! This is your TTS voice.", voice); return; }
      try {
        var a = new Audio(TTS_BASE + file);
        ttsAudio = a;
        a.onended = function () { ttsAudio = null; };
        var p = a.play();
        if (p && typeof p.then === "function") p.catch(function () {});
      } catch (e) { speakText("Hello! This is your TTS voice.", voice); }
    }
    if (TTS_PREVIEW && TTS_PREVIEW[voice]) { doPlay(TTS_PREVIEW[voice]); return; }
    loadTtsPreview().then(function () {
      if (TTS_PREVIEW && TTS_PREVIEW[voice]) doPlay(TTS_PREVIEW[voice]);
      else speakText("Hello! This is your TTS voice.", voice);
    });
  }
  /* 无本地 MP3 时用浏览器/宿主接口兜底朗读（试听按钮专用） */
  function speakText(text, voice) {
    if (window.speechSynthesis) {
      try {
        var meta = VOICE_META[voice] || VOICE_META.alan;
        var u = new SpeechSynthesisUtterance(text);
        u.lang = meta.lang;
        u.rate = 0.95;
        u.pitch = meta.pitch;
        var picked = pickBrowserVoice(meta.lang);
        if (picked) u.voice = picked;
        window.speechSynthesis.speak(u);
        return;
      } catch (e) {}
    }
    if (typeof window.ttsSpeak === "function") {
      try { window.ttsSpeak(text, { lang: "en-GB" }); } catch (e) {}
    }
  }
  /* 与 Python 端 _clean() 保持一致：只保留 ASCII 字母数字与常见英文标点，
     折叠空白。前端拿同一份规则就能命中本地缓存。 */
  function ttsClean(s) {
    s = String(s == null ? "" : s)
      .replace(/\u2018|\u2019/g, "'").replace(/\u201c|\u201d/g, '"')
      .replace(/\u2013|\u2014/g, "-").replace(/\u2026/g, "...");
    var o = "";
    for (var i = 0; i < s.length; i++) {
      var c = s.charAt(i), cc = s.charCodeAt(i);
      if (cc < 128 && ((/[a-z0-9]/i.test(c) || " .,!?;:'\"-()/-_\n%".indexOf(c) >= 0))) o += c;
      else o += " ";
    }
    o = o.replace(/\n/g, " ").replace(/\s+/g, " ").trim();
    return o;
  }
  function clearSpeechOn() {
    if (speechCurrent) { speechCurrent.classList.remove("tts-on"); speechCurrent = null; }
  }
  function setSpeechOn(el) {
    if (!el) return;
    if (speechCurrent && speechCurrent !== el) speechCurrent.classList.remove("tts-on");
    el.classList.add("tts-on");
    speechCurrent = el;
  }
  function speechOf(el) {
    if (!el) return "";
    if (el.__text) return el.__text;
    var t = (el.getAttribute("data-spk") || "").trim();
    if (!t) {
      var clone = el.cloneNode(true);
      clone.querySelectorAll(".spkbtn, .zh").forEach(function (n) { n.remove(); });
      t = (clone.textContent || "").replace(/\s+/g, " ").trim();
    }
    el.__text = t;
    return t;
  }
  var ttsAudio = null;      // 正在播放的本地 MP3 Audio 元素
  var googleAudio = null;   // Google 兜底音源
  function stopTtsAudio() {
    if (ttsAudio) {
      try { ttsAudio.pause(); ttsAudio.currentTime = 0; } catch (e) {}
      ttsAudio = null;
    }
  }
  function speechViaLocal(text, rate, el) {
    if (!TTS_MAP) return false;
    var key = ttsClean(text);
    if (!key) return false;
    var entry = TTS_MAP[key];
    if (!entry) return false;
    // 优先用当前音色；缺失时降级到 Alan，并给用户提示"该词没有 XX 音色的音频"
    var file = entry[currentVoice] || entry.alan;
    if (!file) return false;
    if (!entry[currentVoice] && currentVoice !== "alan") {
      showVoiceMissingHint(currentVoice);
    }
    try {
      stopTtsAudio();
      var a = new Audio(TTS_BASE + file);
      ttsAudio = a;
      a.playbackRate = Math.max(0.3, Math.min(2, rate || 0.95));
      a.onended = function () { clearSpeechOn(); ttsAudio = null; };
      a.onerror = function () { ttsAudio = null; };
      var p = a.play();
      if (p && typeof p.then === "function") p.catch(function () { ttsAudio = null; });
      setSpeechOn(el);
      return true;
    } catch (e) { return false; }
  }
  function speech(text, rate, el) {
    text = String(text || "").trim();
    if (!text) return;
    // 不再弹右上角朗读 toast：朗读中的高亮由 .tts-on CSS 承担；
    // 失败时才由 doFallbackSpeech → speechUnavailableHint 弹右上角警告。
    // 停止上一次朗读（本地 audio / 浏览器原生）
    stopTtsAudio();
    if (window.speechSynthesis && window.speechSynthesis.speaking) {
      try { window.speechSynthesis.cancel(); } catch (e) {}
    }
    // 1) 本地 MP3 优先（命中就用）；未加载过就先拉一次再决定
    if (TTS_MAP_LOADED && !TTS_MAP_FAILED) {
      if (speechViaLocal(text, rate, el)) return;
    } else if (subject === "english") {
      loadTtsMap().then(function () {
        if (!TTS_MAP_FAILED && speechViaLocal(text, rate, el)) return;
        doFallbackSpeech(text, rate, el);
      });
      return;
    }
    // 2~4) 老降级链
    doFallbackSpeech(text, rate, el);
  }
  function doFallbackSpeech(text, rate, el) {
    var ok = false;
    // 2) 宿主注入的自定义朗读接口
    if (typeof window.ttsSpeak === "function") {
      try { ok = window.ttsSpeak(text, { lang: "en-GB", rate: rate || 0.95 }) !== false; }
      catch (e) { ok = false; }
    }
    // 3) 浏览器原生 speechSynthesis：按当前音色挑英/美音色 + 音高微调
    if (!ok && window.speechSynthesis && window.SpeechSynthesisUtterance) {
      try {
        if (window.speechSynthesis.speaking) window.speechSynthesis.cancel();
        var meta = currentVoiceMeta();
        var u = new window.SpeechSynthesisUtterance(text);
        u.lang = meta.lang;
        u.rate = rate || 0.95;
        u.pitch = meta.pitch;
        var picked = pickBrowserVoice(meta.lang);
        if (picked) u.voice = picked;
        var done = false;
        var clear = function () { if (!done) { done = true; clearSpeechOn(); } };
        u.onend = clear;
        u.onerror = clear;
        u.onpause = clear;
        window.speechSynthesis.speak(u);
        ok = true;
      } catch (e) { ok = false; }
    }
    // 4) iframe 场景：转发给父窗口
    if (!ok && window.parent && window.parent !== window) {
      try {
        window.parent.postMessage({
          type: "tts.request", action: "tts.speak",
          text: text, lang: "en-GB", rate: rate || 0.95
        }, "*");
        ok = true;
      } catch (e) { ok = false; }
    }
    // 5) 兜底：Google Translate TTS
    if (!ok) ok = speechViaGoogle(text, rate, el);
    if (ok) setSpeechOn(el);
    else if (el) speechUnavailableHint(el);
  }
  function speechViaGoogle(text, rate, el) {
    var clean = text.replace(/[^A-Za-z0-9\?\.\!\,\;\:\'\"\ \-\(\)\/]+/g, "")
      .replace(/\s+/g, " ").trim();
    if (!clean) return false;
    var url = "https://translate.google.com/translate_tts?ie=UTF-8&q=" +
      encodeURIComponent(clean.slice(0, 200)) + "&tl=en&client=tw-ob";
    try {
      var a = new Audio();
      googleAudio = a;
      a.src = url;
      a.volume = 1;
      a.playbackRate = rate || 0.95;
      a.onend = function () { clearSpeechOn(); googleAudio = null; };
      a.onerror = function () {
        googleAudio = null;
        if (el) speechUnavailableHint(el); else clearSpeechOn();
      };
      var p = a.play();
      if (p && typeof p.then === "function") {
        p.then(function () { setSpeechOn(el); }).catch(function () {
          googleAudio = null;
          if (el) speechUnavailableHint(el); else clearSpeechOn();
        });
      }
      return true;
    } catch (e) { return false; }
  }
  function speechUnavailableHint(el) {
    setSpeechOn(el);
    var tip = ensureTip();
    tip.innerHTML = buildToastHTML();
    tip.classList.add("show");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      tip.classList.remove("show");
      tip.innerHTML = "";
    }, 60000); // 有重试按钮时保留久一点
  }
  /* Toast HTML 模板：仅失败提示 + [重试] + [外部浏览器] + [×] */
  function buildToastHTML() {
    var here = (window.location.href || "").replace(/&/g, "&amp;");
    var html = "⚠️ 当前环境可能不支持朗读。";
    html += '<span style="display:flex;gap:6px;margin-top:6px;align-items:center;">' +
      '<button class="spk-act" data-act="retry" ' +
      'style="background:#2c6bb3;color:#fff;border:none;border-radius:6px;' +
      'padding:3px 10px;font-size:12px;cursor:pointer;">重试</button>' +
      '<a href="' + here + '" target="_blank" rel="noreferrer" class="spk-act" ' +
      'style="color:#ffd07a;text-decoration:underline;font-size:12px;">外部浏览器</a>' +
      '<button class="spk-act" data-act="close" ' +
      'style="background:#444;color:#ddd;border:none;border-radius:6px;' +
      'padding:3px 10px;font-size:12px;cursor:pointer;">关闭</button>' +
      "</span>";
    return html;
  }
  /* Toast 交互委托：重试 / 关闭 */
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("#spk-tip .spk-act[data-act]");
    if (!b) return;
    var tip = b.parentNode.parentNode;
    var act = b.getAttribute("data-act");
    if (act === "close") {
      if (window.speechSynthesis) try { window.speechSynthesis.cancel(); } catch (e) {}
      if (googleAudio) { try { googleAudio.pause(); } catch (e) {} }
      tip.classList.remove("show");
      tip.innerHTML = "";
      clearSpeechOn();
      if (toastTimer) { clearTimeout(toastTimer); toastTimer = null; }
      return;
    }
    if (act === "retry" && speechCurrent) {
      var text = speechOf(speechCurrent) || (speechCurrent.getAttribute("data-spk") || "");
      speech(text, 0.95, speechCurrent);
    }
  });
  function ensureTip() {
    var tip = document.getElementById("spk-tip");
    if (!tip) {
      tip = document.createElement("div");
      tip.id = "spk-tip";
      tip.className = "spk-tip";
      document.body.appendChild(tip);
    }
    return tip;
  }
  /* 失败提示的自动消失计时器：朗读失败时才使用 */
  var toastTimer = null;
  /* 缺当前音色音频时的提示：短小悬浮条，不覆盖失败警告 */
  var VOICE_LABELS = {
    alan: "Alan · 英音男",
    jenny: "Jenny · 英音女",
    amy: "Amy · 美音女",
    cori: "Cori · 高质量英音"
  };
  var voiceHintEl = null;
  var voiceHintTimer = null;
  function showVoiceMissingHint(voice) {
    var label = VOICE_LABELS[voice] || voice;
    if (!voiceHintEl) {
      voiceHintEl = document.createElement("div");
      voiceHintEl.id = "voice-missing-hint";
      voiceHintEl.style.cssText =
        "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);" +
        "background:rgba(50,50,50,.92);color:#ffd07a;border:1px solid #665;" +
        "padding:6px 14px;border-radius:20px;font-size:12px;z-index:9999;" +
        "pointer-events:none;opacity:0;transition:opacity .25s;" +
        "box-shadow:0 4px 12px rgba(0,0,0,.25);";
      document.body.appendChild(voiceHintEl);
    }
    voiceHintEl.textContent = "⚠ 该词没有 " + label + " 的音频，已用 Alan 兜底";
    voiceHintEl.style.opacity = "1";
    if (voiceHintTimer) clearTimeout(voiceHintTimer);
    voiceHintTimer = setTimeout(function () {
      voiceHintEl.style.opacity = "0";
      voiceHintTimer = null;
    }, 2500);
  }
  function spkBtn(text) {
    return '<span class="spkbtn" data-spk="' +
      String(text || "").replace(/"/g, "&quot;") + '" title="点击朗读，双击慢速">🔊</span>';
  }
  /* 点读事件委托：挂一次，任何位置的 .spk / .spkbtn 都会响应
        文本（.spk）：单击正常语速，双击慢速
        按钮（.spkbtn）：单击正常语速；不拦截冒泡，父容器的自测开合等交互照常触发 */
  document.addEventListener("click", function (e) {
    var b = e.target.closest(".spkbtn");
    if (b) { speech(b.getAttribute("data-spk") || "", 0.95, b); return; }
    var s = e.target.closest("[data-spk]");
    if (s) { speech(s.getAttribute("data-spk") || "", 0.95, s); return; }
    var el = e.target.closest(".spk");
    if (!el) return;
    var slow = (e.detail || 1) >= 2;
    speech(speechOf(el), slow ? 0.65 : 0.95, el);
  });
  /* Chrome/Safari 的 speechSynthesis.getVoices() 在页面首次访问时可能还是空的，
        必须先调一次才会开始加载语音列表。挂个一次性预热。 */
  (function warmUpVoices() {
    if (!window.speechSynthesis) return;
    try {
      if (!window.speechSynthesis.getVoices() || !window.speechSynthesis.getVoices().length) {
        window.speechSynthesis.onvoiceschanged = function () {};
        window.speechSynthesis.getVoices();
      }
    } catch (e) {}
  })();

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
    var html = '<span class="nav"><span class="tab on" data-t="all">全部</span>';
    domains.forEach(function (d) {
      html += '<span class="tab" data-t="' + d.key + '">' + esc(d.name) + "</span>";
    });
    html += "</span>";
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
    html += '<span class="count" id="cnt"></span>';
    // 常找标签：点一下就等于搜这个词（内容多的时候比翻页快）
    if (opt.tags && opt.tags.length) {
      html += '<div class="tags"><span class="jl">常找</span>' +
        opt.tags.map(function (t) {
          return '<span class="ttag" data-t="' + esc(t) + '">' + esc(t) + "</span>";
        }).join("") + "</div>";
    }
    // 跳到：按当前分组一键定位（分组由 byGroup 回填）
    html += '<div class="jump" id="jump"></div>';
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

  /* 常找标签自动攒：取条目里出现最多的词，不手写、不会过时。
     过滤掉年级/册次/单元/第/课这类通用词，否则数学头部会挤出一长串。 */
  var TAG_STOP = /年级|上册|下册|册|单元|练习|复习|总复习|^第|^课$|^的$|^和$|^与$|^是$|^在$|^有$|^了$/;
  function hotTags(rows, field, n) {
    var c = {};
    (rows || []).forEach(function (x) {
      String(x[field] || "").split(/[\s，,、。；;：:（）()【】"“”·0-9]/).forEach(function (w) {
        w = (w || "").trim();
        if (w.length >= 2 && w.length <= 6 && !TAG_STOP.test(w)) c[w] = (c[w] || 0) + 1;
      });
    });
    return Object.keys(c).sort(function (a, b) { return c[b] - c[a]; }).slice(0, n || 12);
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
      box.innerHTML = unitToc(rows) + (byGroup(rows, st, function (u) {
        var d = D.domains.filter(function (x) { return x.key === u.domain; })[0];
        return d ? d.name : "";
      }, function (u) {
        return mathUnit(u, rows.indexOf(u));
      }) || '<div class="empty">没有匹配的单元</div>');
    }, { hint: "如：分数、面积、鸡兔同笼",
         tags: hotTags(D.units, "title", 18) });
    box.addEventListener("click", function (e) {
      var chip = e.target.closest(".chip");
      if (!chip) return;
      var k = chip.dataset.ex;
      ON[k] = !ON[k];
      chip.classList.toggle("on", !!ON[k]);
      [].forEach.call(box.querySelectorAll('.kb[data-kb="' + k + '"]'),
                      function (d) { d.classList.toggle("show", !!ON[k]); });
      try { localStorage.setItem("cnExtra", JSON.stringify(ON)); } catch (err) { }
    });
    t.fire();
    if (kind === "all") measureTable();
  }

  /* 单元目录：按册 → 单元列出，点单元直达（课本翻目录那一页） */
  function unitToc(rows) {
    if (!rows || rows.length < 2) return "";
    return '<details class="toc"><summary>单元目录（' + rows.length +
      ' 个单元 · 点单元直达）</summary><div class="toc-b">' +
      rows.map(function (u, i) {
        var head = (i === 0 || rows[i - 1].book !== u.book)
          ? '<div class="toc-u">' + esc(u.book) + "</div>" : "";
        return head + '<a class="tlink" href="#mu' + i + '">' +
          (u.unit_no ? "第" + esc(u.unit_no) + "单元 · " : "") + esc(u.title) + "</a>";
      }).join("") + "</div></details>";
  }

  /* 数学单元的外延（算理／算法／易错／思想／联系）：同样默认收起，勾了才显示 */
  var M_EXTRA = [["why", "算理"], ["how", "算法步骤"], ["traps", "易错"],
                 ["ideas", "数学思想"], ["links", "前后联系"]];

  function mBody(kb, k) {
    var v = kb[k], h = "";
    if (k === "how") {
      h = (v || []).map(function (s, i) {
        return '<p class="kbp"><b>' + (i + 1) + ".</b> " + esc(s.s || "") +
          (s.note ? '<span class="std">　' + esc(s.note) + "</span>" : "") + "</p>";
      }).join("");
    } else if (k === "traps") {
      h = (v || []).map(function (t) {
        return '<p class="kbp"><span class="kbtag">' + esc(t.type || "") +
          "</span>" + esc(t.text || "") + "</p>";
      }).join("");
    } else if (k === "ideas") {
      h = '<p class="kbp">' + (v || []).map(function (m) {
        return '<span class="kbtag g">' + esc(m) + "</span>";
      }).join("") + "</p>";
    } else if (k === "links") {
      h = '<p class="kbp"><span class="kbtag">先要会</span>' +
        esc(v.before || "") + "</p>" +
        '<p class="kbp"><span class="kbtag">接着学</span>' +
        esc(v.after || "") + "</p>";
    } else {
      h = '<p class="kbp">' + esc(String(v || "")) + "</p>";
    }
    var std = (kb.standard || {})[k];
    return h + (std ? '<p class="std">课标依据：' + esc(std) + "</p>" : "");
  }

  function mathUnit(u, idx) {
    var dom = D.domains.filter(function (d) { return d.key === u.domain; })[0] || {};
    var lit = (u.literacy || []).map(function (x) {
      return '<span class="tag">' + esc(x) + "</span>";
    }).join("");
    var h = '<div class="item"' + (idx != null ? ' id="mu' + idx + '"' : "") +
      '><div class="top"><span class="name">' + esc(u.title) + "</span>" +
      where(u, u.page_from) + '<span class="tag d' +
      Math.max(0, D.domains.map(function (d) { return d.key; }).indexOf(u.domain)) +
      '">' + esc(dom.name) + "</span>" + lit + "</div>" + pts(u.points);
    if (u.kb) {
      h += '<div class="chips">' + M_EXTRA.map(function (e) {
        return kbHas(u.kb, e[0])
          ? '<span class="chip' + (ON[e[0]] ? " on" : "") + '" data-ex="' +
            e[0] + '">' + e[1] + "</span>" : "";
      }).join("") + "</div>";
      h += M_EXTRA.map(function (e) {
        return kbHas(u.kb, e[0])
          ? '<div class="kb' + (ON[e[0]] ? " show" : "") + '" data-kb="' +
            e[0] + '">' + mBody(u.kb, e[0]) + "</div>" : "";
      }).join("");
    }
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
    return h + "</div>";
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
      var chip = e.target.closest(".chip");
      if (chip) {
        var k = chip.dataset.ex;
        ON[k] = !ON[k];
        chip.classList.toggle("on", !!ON[k]);
        [].forEach.call(box.querySelectorAll('.kb[data-kb="' + k + '"]'),
                        function (d) { d.classList.toggle("show", !!ON[k]); });
        // 正文里的着色也跟着走：只切 class，不重绘，免得刚展开的全文又合上
        [].forEach.call(box.querySelectorAll(".item"), function (it) {
          it.classList.toggle("on-" + k, !!ON[k]);
        });
        try { localStorage.setItem("cnExtra", JSON.stringify(ON)); } catch (err) { }
        return;
      }
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
        " 第" + esc(k.split("#")[1]) + "单元" +
        (e && e.unit_title ? " · " + esc(e.unit_title) : "") + "</span>" +
        (e && e.reading ? '<span class="tag d1">阅读要素</span>' : "") +
        (e && e.writing ? '<span class="tag">习作要素</span>' : "") + "</div>";
      if (e && e.theme) h += '<div class="elem"><b>人文主题</b>' + esc(e.theme) + "</div>";
      if (e && e.reading) h += '<div class="elem">' + esc(e.reading) + "</div>";
      if (e && e.writing) h += '<div class="elem"><b>习作要素</b>' + esc(e.writing) + "</div>";
      h += byUnit[k].map(function (x) { return cnText(x, x._i); }).join("") + "</div>";
    });
    return h;
  }

  /* 教材之外的东西（背景、考点、易错、批注……）一律默认收起：
     先只给教材里印着的内容，家长勾哪个才显示哪个。勾一次记下来，全站通用。 */
  var EXTRA = [
    ["recite", "读背要求"], ["words", "词语理解"], ["sentences", "品读句子"],
    ["methods", "写法"], ["questions", "答题思路"], ["polyphone", "多音字"],
    ["notes", "段内批注"], ["background", "背景资料"], ["center", "中心与启示"],
    ["exam", "考点"], ["traps", "易错"], ["accumulate", "积累"],
    ["extend", "拓展"], ["transfer", "说到写"]
  ];
  var ON = {};
  try { ON = JSON.parse(localStorage.getItem("cnExtra") || "{}"); } catch (e) { ON = {}; }

  function kbHas(kb, k) {
    var v = kb[k];
    if (v == null) return false;
    if (typeof v === "string") return !!v;
    if (Array.isArray(v)) return v.length > 0;
    if (typeof v === "object") return Object.keys(v).length > 0;
    return !!v;
  }

  function kbBody(kb, k) {
    var v = kb[k], h = "";
    if (k === "notes") {
      h = (v || []).map(function (n) {
        return '<p class="kbp"><span class="kbtag">第' + (n.para + 1) + "段 · " +
          esc(n.kind || "") + "</span>" + (n.tags || []).map(function (t) {
            return '<span class="kbtag g">' + esc(t) + "</span>";
          }).join("") + esc(n.text || "") + "</p>";
      }).join("");
    } else if (k === "words") {
      h = (v || []).map(function (w) {
        return '<p class="kbp"><b>' + esc(w.w) + "</b>：" + esc(w.mean || "") + "</p>";
      }).join("");
    } else if (k === "sentences") {
      h = (v || []).map(function (s) {
        return '<p class="kbp">“' + esc(s.src || "") + "”<br><span class=\"std\">" +
          esc(s.why || "") + "</span></p>";
      }).join("");
    } else if (k === "questions") {
      h = (v || []).map(function (q) {
        return '<p class="kbp"><b>' + esc(q.q || "") + "</b><br><span class=\"std\">" +
          esc(q.hint || "") + "</span></p>";
      }).join("");
    } else if (k === "polyphone") {
      h = (v || []).map(function (p) {
        return '<p class="kbp"><b>' + esc(p.zi) + "</b>：" +
          (p.items || []).map(function (i) {
            return esc(i.py || "") + "（" + esc(i.ci || "") + "）";
          }).join("　") + "</p>";
      }).join("");
    } else if (k === "methods") {
      h = '<p class="kbp">' + (v || []).map(function (m) {
        return '<span class="kbtag g">' + esc(m) + "</span>";
      }).join("") + "</p>";
    } else if (k === "exam") {
      h = (v || []).map(function (e) {
        return '<p class="kbp"><span class="kbtag">' + esc(e.point || "") +
          "</span>" + esc(e.how || "") + "</p>";
      }).join("");
    } else if (k === "traps") {
      h = (v || []).map(function (t) {
        return '<p class="kbp"><span class="kbtag">' + esc(t.type || "") +
          "</span>" + esc(t.text || "") + "</p>";
      }).join("");
    } else if (k === "accumulate") {
      h = (v || []).map(function (a) {
        return '<p class="kbp">“' + esc(a.t || "") + "”" +
          (a.why ? '<span class="std">　' + esc(a.why) + "</span>" : "") + "</p>";
      }).join("");
    } else if (k === "center") {
      h = '<p class="kbp">' + esc(v.idea || "") + "</p>" +
        (v.virtue ? '<p class="kbp"><span class="kbtag">启示</span>' +
          esc(v.virtue) + "</p>" : "");
    } else if (k === "extend") {
      h = '<p class="kbp">' + esc(v.life || "") + "</p>" +
        ((v.links || []).length ? '<p class="kbp"><span class="std">连着看：' +
          esc(v.links.join("　")) + "</span></p>" : "");
    } else {
      h = '<p class="kbp">' + esc(String(v)) + "</p>";
    }
    var std = (kb.standard || {})[k];       // 这一块依据课标哪一条，一并写清楚
    return h + (std ? '<p class="std">课标依据：' + esc(std) + "</p>" : "");
  }

  // 段内批注按 kind 上不同的颜色，一眼能分清"这段是讲词义还是讲写法"
  var KIND_CLS = {"段意": "idea", "字词": "word", "朗读": "read", "提问": "ask",
                  "写法": "method", "积累": "acc", "背诵": "recite"};

  function mark(html, w, cls, tip) {
    var s = esc(w);
    if (!s || html.indexOf(s) < 0) return html;
    // 单字（多音字、易错字）到处都是，只标第一次，不然满屏都是色块
    if (s.length <= 2) {
      return html.replace(s, '<mark class="' + cls + '"' +
        (tip ? ' title="' + esc(tip) + '"' : "") + ">" + s + "</mark>");
    }
    return html.split(s).join('<mark class="' + cls + '"' +
      (tip ? ' title="' + esc(tip) + '"' : "") + ">" + s + "</mark>");
  }

  // 一段课文：先贴批注，再按勾的选项把词、句、多音字、积累句着上色
  function paraHtml(x, p, i) {
    var kb = x.kb || {}, t = esc(p), notes = [];
    (kb.notes || []).forEach(function (n) {
      if (n.para === i) notes.push(n);
    });
    (kb.words || []).forEach(function (w) {
      t = mark(t, w.w, "k-word", w.mean);
    });
    (kb.polyphone || []).forEach(function (q) {
      t = mark(t, q.zi, "k-poly", (q.items || []).map(function (z) {
        return (z.py || "") + "（" + (z.ci || "") + "）";
      }).join(" "));
    });
    (kb.sentences || []).forEach(function (s) {
      t = mark(t, s.src, "k-sent", s.why);
    });
    (kb.accumulate || []).forEach(function (a) {
      t = mark(t, a.t, "k-acc", a.why);
    });
    var head = notes.map(function (n) {
      return '<span class="pnote"><span class="kbtag k-' +
        (KIND_CLS[n.kind] || "idea") + '">' + esc(n.kind || "") + "</span>" +
        (n.tags || []).map(function (g) {
          return '<span class="kbtag g">' + esc(g) + "</span>";
        }).join("") + esc(n.text || "") + "</span>";
    }).join("");
    return '<p class="para' + (notes.length ? " hl k-" +
      (KIND_CLS[notes[0].kind] || "idea") : "") + '">' + head + t + "</p>";
  }

  function cnText(x, idx) {
    var onCls = Object.keys(ON).filter(function (k) { return ON[k]; })
      .map(function (k) { return " on-" + k; }).join("");
    var h = '<div class="item' + onCls + '"' +
      (idx != null ? ' id="t' + idx + '"' : "") +
      '><div class="top">' +
      (x.no ? '<span class="tag d1">第' + esc(x.no) + "课</span>" : "") +
      '<span class="name">' + esc(x.title) + "</span>" +
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
        '<div class="full">' + x.paras.map(function (p, i) {
          return paraHtml(x, p, i);
        }).join("") +
        // 注解（教材脚注）照原样放在正文下面，不挪到课后题后面
        (x.notes && x.notes.length
          ? '<p class="small">注解</p><ul class="pts">' + x.notes.map(function (n) {
            return "<li>" + esc(n) + "</li>";
          }).join("") + "</ul>" : "") + "</div></details>";
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
    if (x.kb) {
      // 这课没有的块就不给标签，免得点了个空标签
      h += '<div class="chips">' + EXTRA.map(function (e) {
        return kbHas(x.kb, e[0])
          ? '<span class="chip' + (ON[e[0]] ? " on" : "") + '" data-ex="' +
            e[0] + '">' + e[1] + "</span>" : "";
      }).join("") + "</div>";
      h += EXTRA.map(function (e) {
        return kbHas(x.kb, e[0])
          ? '<div class="kb' + (ON[e[0]] ? " show" : "") + '" data-kb="' +
            e[0] + '">' + kbBody(x.kb, e[0]) + "</div>" : "";
      }).join("");
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
    // 篇目汇总表：一页看清这一册有哪些古诗文，点篇名直达原文
    if (rows.length > 1) {
      h += '<details class="toc"><summary>篇目汇总表（' + rows.length +
        ' 篇 · 点篇名直达）</summary><div class="toc-b">' +
        '<table class="tbl"><thead><tr><th>册次</th><th>篇名</th>' +
        "<th>朝代 / 作者</th><th>类别</th></tr></thead><tbody>" +
        rows.map(function (x, i) {
          return "<tr><td>" + esc(x.book) + '</td><td><a href="#p' + i + '">' +
            esc(x.title) + "</a></td><td>" +
            esc([x.dynasty, x.author].filter(Boolean).join(" · ")) + "</td><td>" +
            esc(x.kind || "") + "</td></tr>";
        }).join("") + "</tbody></table></div></details>";
    }
    return h + rows.map(function (x, i) {
      var s = '<div class="item" id="p' + i + '"><div class="top"><span class="name">' +
        esc(x.title) +
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
    function addTopic(t) {
      if (t && topics.indexOf(t) < 0) topics.push(t);
    }
    (D.vocab || []).forEach(function (v) { addTopic(v.topic); });
    if (kind === "discourse") {
      (D.passages || []).forEach(function (x) { addTopic(x.topic); });
      (D.dialogues || []).forEach(function (x) { addTopic(x.topic); });
    }
    var t = tools([], function (st, cnt) {
      var h = "";
      if (kind === "discourse") h = enText(st);
      else if (kind === "vocab") h = enVocab(st);
      else if (kind === "grammar") h = enGrammar(st);
      else if (kind === "phonics") h = enPhonics(st);
      else if (kind === "extra") h = enExtra(st);
      else if (kind === "writing") h = enWriting(st);
      else h = enUse(st);
      box.innerHTML = h || '<div class="empty">没有匹配的内容</div>';
      cnt.textContent = box.querySelectorAll(kind === "grammar" ? ".dk-sec" : ".item").length + " 组";
      if (kind === "grammar") dkReveal(box);
    }, { hint: { discourse: "如：family、weather", vocab: "如：job、doctor",
                 grammar: "如：can、there be、过去式", phonics: "如：sh、ai",
                 use: "如：song、project", extra: "如：family、weather、school",
                 writing: "如：narrative、描写、看图写话" }[kind] || "关键词",
         tags: (function () {
           var m = { discourse: [D.passages, "name"], vocab: [D.vocab, "topic"],
                     grammar: [D.grammar, "category"], phonics: [D.phonics, "letters"],
                     use: [D.songs, "name"], extra: [D.passages, "topic"],
                     writing: [(D.writing && D.writing.genres) || [], "zh"] }[kind] || [D.vocab, "topic"];
           var m1 = m[0] || [], m2 = m[1] || "zh";
           if (kind === "writing") return (m[0] || []).map(function (g) { return g.zh; });
           return hotTags(m1, m2, 16);
         })(),
         zh: kind === "discourse",
         extra: (kind === "vocab" || kind === "discourse" || kind === "extra")
           ? { label: "按话题", opts: topics } : null });
    t.fire();
    // 词汇卡：点一下才出中文（自测），点发音/生词本按钮不触发展开
    box.addEventListener("click", function (e) {
      var c = e.target.closest(".vcard");
      if (c && !e.target.closest(".spkbtn") && !e.target.closest(".wb-toggle")) c.classList.toggle("open");
    });
    // 课文页：每课学习中心的 tab/练习/游戏/打星都走这一套委托
    if (kind === "discourse") bindLessonHubs(box);
    /* 从课外拓展卡片跳来：#<册名>#U{n} → 展开该单元全部课并滚到单元顶部 */
    function applyUnitHash() {
      if (kind !== "discourse") return;
      var m = String(location.hash || "").match(/^#([^#]+)#U(\d+)$/);
      if (!m) return;
      var book = decodeURIComponent(m[1]);
      var uno = parseInt(m[2], 10);
      if (!book || !uno) return;
      // 一课 = book|unit_no|type|scene；展开该单元所有课（对话+短文）
      var dets = box.querySelectorAll(
        '.lesson[data-lkey^="' + book + '|' + uno + '|"]');
      if (!dets.length) return;
      var par = null;
      for (var i = 0; i < dets.length; i++) {
        dets[i].open = true;
        if (!par) par = dets[i].closest(".unit");
      }
      if (par) par.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    setTimeout(applyUnitHash, 80);
    // 课外拓展页：ReadWorks 风格筛选
    if (kind === "extra") {
      box.addEventListener("change", function (e) {
        var cb = e.target.closest('input[type="checkbox"]');
        if (!cb) return;
        exToggle(cb.dataset.fcat, cb.dataset.fval);
        cb.closest(".rw-ck").classList.toggle("checked", cb.checked);
        t.fire();
      });
      box.addEventListener("click", function (e) {
        var clr = e.target.closest(".rw-clear");
        if (!clr) return;
        EX_FILTER = {};
        try { localStorage.setItem("enExtraFilter", "{}"); } catch (err) {}
        t.fire();
      });
      /* 课外拓展：分段精读交互 */
      box.addEventListener("click", function (e) {
        /* 词汇高亮点击 → 朗读 */
        var vw = e.target.closest(".rw-vocab");
        if (vw) { speech(vw.getAttribute("data-word") || vw.textContent); return; }
        /* 词汇条目点击 → 朗读 */
        var vi = e.target.closest(".rw-vocab-item");
        if (vi) { speech(vi.getAttribute("data-word") || vi.textContent); return; }
        /* 绘本单页翻译 */
        var pgTr = e.target.closest(".rw-pg-tr");
        if (pgTr) {
          var zhSpan = pgTr.parentNode.querySelector(".rw-pg-zh");
          if (!zhSpan) return;
          if (zhSpan.getAttribute("data-loaded") === "1") {
            zhSpan.classList.toggle("hide");
            return;
          }
          var bkId = pgTr.getAttribute("data-book") || "";
          var pgN = parseInt(pgTr.getAttribute("data-pg") || "0", 10);
          var pgTxt = "";
          (D.picturebooks || []).forEach(function (pb) {
            if (pb.id === bkId && pb.pages) {
              pb.pages.forEach(function (pp) {
                if ((pp.n || 0) === pgN) pgTxt = pp.text || "";
              });
            }
          });
          if (!pgTxt) return;
          zhSpan.textContent = "翻译中…";
          zhSpan.classList.remove("hide");
          loadTranslation(pgTxt, function (zh) {
            zhSpan.textContent = zh;
            zhSpan.setAttribute("data-loaded", "1");
            pgTr.textContent = "译✓";
          }, function () {
            zhSpan.textContent = "翻译加载失败";
            zhSpan.setAttribute("data-loaded", "1");
          });
          return;
        }
        /* 词汇表开关 */
        var vb = e.target.closest(".rw-vocab-btn");
        if (vb) {
          var vbb = vb.closest(".rw-para-body");
          var vbl = vbb ? vbb.querySelector(".rw-vocab-list") : null;
          if (vbl) vbl.classList.toggle("hide");
          vb.classList.toggle("on");
          return;
        }
      });
      /* 段落展开 → 更新进度 */
      box.addEventListener("toggle", function (e) {
        var para = e.target.closest(".rw-para");
        if (!para) return;
        var read = para.closest(".rw-read");
        if (!read) return;
        var opened = read.querySelectorAll(".rw-para[open]").length;
        var total = parseInt(read.getAttribute("data-total") || "0", 10);
        var cnt = read.querySelector(".rw-read-count");
        if (cnt) cnt.textContent = opened + "/" + total + " 段";
        var fill = read.querySelector(".rw-read-fill");
        if (fill) fill.style.width = (total ? (opened / total * 100) : 0) + "%";
      }, true);
    }
  }

  /* 译文加载：先查预生成库（window.ZH_TRANS，课外拓展页随 zh_trans.js 加载），
     本地没有再走 Google Translate API。 */
  function loadTranslation(text, onOk, onErr) {
    var T = window.ZH_TRANS || null;
    if (T && T[text]) { onOk(T[text]); return; }
    var url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=" +
              encodeURIComponent(text);
    fetch(url).then(function (r) { return r.json(); }).then(function (d) {
      if (d && d[0]) {
        var zh = d[0].map(function (s) { return s[0] || ""; }).join("");
        onOk(zh);
      } else { onErr(); }
    }).catch(onErr);
  }

  /* 课文：按册 → 单元（教材顺序）→ 对话 / 短文。
     每课默认折叠，点开是一个「学习中心」：
     课文 / 预习 / 音标 / 拼读 / 语法 / 练习 / 游戏 / 复习 / 拓展 九个板块。
     @CONSTRAINT 除课文板块外全部惰性渲染——708 课一次性铺开会卡，
     依赖 LESSONS 注册表在 tab 第一次点开时才生成内容。 */
  var LESSONS = {};   // lkey → {data, type}，惰性板块的数源（每次重渲染重建）
  var HUBS = D.hubs || { units: {}, songs: {}, extra: {} };

  function lessonKey(x, type) {
    return [x.book || "", x.unit_no || x.unit || "", type,
            x.scene || x.name || ""].join("|");
  }
  function unitHubOf(x) {
    return HUBS.units[(x.book || "") + "#" +
      (x.unit_no ? "U" + x.unit_no : x.unit || "")] || null;
  }
  /* 本单元配套的课外书（pairs_with_unit 反向索引） */
  function unitExtraOf(x) {
    var k = (x.book || "") + "#U" + (x.unit_no || 0);
    return (HUBS.extra || {})[k] || [];
  }
  /* 课外拓展页：从单元索引跳到教材课文页（课文页读 hash 定位并展开该课） */
  function unitLink(u) {
    var key = "#" + encodeURIComponent(u.book || "") + "#U" + (u.unit_no || 0);
    return '<a class="rw-ulink" href="index.html' + key + '" title="' +
      esc((u.grade || "") + " " + (u.term || "") + " " +
          (u.unit_name || "") + " " + (u.unit_title || "")) + '">' +
      esc(u.unit_name || "单元") +
      (u.unit_title ? '<span class="rw-ut">' + esc(u.unit_title) + "</span>" : "") +
      (u.grade ? '<span class="rw-ug">' + esc(u.grade) + "</span>" : "") + "</a>";
  }
  /* 星星：localStorage 持久化。键 lessonKey，值 {fill,scramble,order,match,rate} */
  var STARS = {};
  try { STARS = JSON.parse(localStorage.getItem("enStars") || "{}"); } catch (e) { STARS = {}; }
  function starSave() { try { localStorage.setItem("enStars", JSON.stringify(STARS)); } catch (e) {} }
  function starCount(key) {
    var s = STARS[key] || {};
    return (s.fill ? 1 : 0) + (s.scramble ? 1 : 0) + (s.order ? 1 : 0) + (s.match ? 1 : 0);
  }
  function starStr(n) { return n > 0 ? "★" + n : ""; }
  function awardStar(key, game) {
    if (!STARS[key]) STARS[key] = {};
    var isNew = !STARS[key][game];
    STARS[key][game] = 1;
    starSave();
    [].forEach.call(document.querySelectorAll(".lstars"), function (el) {
      if (el.getAttribute("data-stars") === key) el.textContent = starStr(starCount(key));
    });
    // 星星同时也是"闯关进度"：练习与游戏分别点亮 练习/游戏 两关，
    // 预习/跟读两关由用户手动点亮（在预习板块勾选目标、在音标板块点过录音）。
    if (isNew) {
      var stage = (game === "fill" || game === "order" || game === "match" ||
                   game === "scramble") ? "exercise" : "game";
      markUnitMap(key, stage);
    }
  }
  function shuffle(a) { a.sort(function () { return Math.random() - 0.5; }); return a; }
  function sample(arr, n) { return shuffle(arr.slice()).slice(0, n); }

  /* ---- 生词本 / 单元地图 / 每日打卡：三份 localStorage 数据 ---- */
  /* 生词本：key = book#word，value = {word, ipa, zh, added, last, right, wrong} */
  var WORDBOOK = {};
  try { WORDBOOK = JSON.parse(localStorage.getItem("enWordBook") || "{}"); } catch (e) { WORDBOOK = {}; }
  function wordBookSave() { try { localStorage.setItem("enWordBook", JSON.stringify(WORDBOOK)); } catch (e) {} }
  function wbKey(book, word) { return (book || "") + "#" + String(word || "").toLowerCase(); }
  function wbHas(book, word) { return !!WORDBOOK[wbKey(book, word)]; }
  function wbAdd(book, word, meta) {
    var k = wbKey(book, word);
    if (!WORDBOOK[k]) {
      WORDBOOK[k] = { word: String(word || ""), ipa: (meta && meta.ipa) || "",
                      zh: (meta && meta.zh) || "", book: book || "",
                      added: Date.now(), last: 0, right: 0, wrong: 0 };
      wordBookSave();
    }
    refreshWordBookUI();
    return WORDBOOK[k];
  }
  function wbRemove(book, word) {
    delete WORDBOOK[wbKey(book, word)];
    wordBookSave();
    refreshWordBookUI();
  }
  function wbList() { return Object.keys(WORDBOOK).map(function (k) { return WORDBOOK[k]; }); }
  function refreshWordBookUI() {
    var box = document.querySelector(".wordbook .wb-list");
    if (box) box.outerHTML = wordBookListInner();
    [].forEach.call(document.querySelectorAll(".wb-count"), function (el) {
      el.textContent = wbList().length;
    });
    [].forEach.call(document.querySelectorAll(".wb-badge"), function (el) {
      el.textContent = "📖 " + wbList().length;
    });
    // 单词收藏按钮的选中态同步
    [].forEach.call(document.querySelectorAll(".wb-toggle"), function (el) {
      var k = el.getAttribute("data-wbkey");
      if (k) el.classList.toggle("on", !!WORDBOOK[k]);
    });
  }

  /* 单元进度：{unitKey: {preview,read,exercise,game}}
     unitKey 与 HUBS.units 的键同格式："book#U3" 或 "book#Unit name" */
  var UNITMAP = {};
  try { UNITMAP = JSON.parse(localStorage.getItem("enUnitMap") || "{}"); } catch (e) { UNITMAP = {}; }
  function unitMapSave() { try { localStorage.setItem("enUnitMap", JSON.stringify(UNITMAP)); } catch (e) {} }
  /* lessonKey = book|unitKey|type|scene，其中 unitKey 已是 "U3" 或 "Unit name" 形式 */
  function lessonUnitKey(lessonKey) {
    var p = String(lessonKey).split("|");
    return (p[0] || "") + "#" + (p[1] || "");
  }
  function markUnitMap(lessonKey, stage) {
    var ukey = lessonUnitKey(lessonKey);
    if (!UNITMAP[ukey]) UNITMAP[ukey] = {};
    if (!UNITMAP[ukey][stage]) {
      UNITMAP[ukey][stage] = 1;
      unitMapSave();
      refreshUnitMapUI();
    }
  }
  function unitDoneCount(uk) {
    var u = UNITMAP[uk] || {};
    return (u.preview ? 1 : 0) + (u.read ? 1 : 0) +
           (u.exercise ? 1 : 0) + (u.game ? 1 : 0);
  }
  function refreshUnitMapUI() {
    refreshUnitMapStages();
  }

  /* 每日 3 分钟打卡：{ "YYYY-MM-DD": {items:[lessonKey], done:n} } */
  var CHECKIN = {};
  try { CHECKIN = JSON.parse(localStorage.getItem("enCheckin") || "{}"); } catch (e) { CHECKIN = {}; }
  function checkinSave() { try { localStorage.setItem("enCheckin", JSON.stringify(CHECKIN)); } catch (e) {} }
  function todayStr() {
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
           "-" + String(d.getDate()).padStart(2, "0");
  }
  function checkinStreak() {
    // 连续打卡天数（含今天）
    var n = 0, d = new Date();
    while (true) {
      var s = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
              "-" + String(d.getDate()).padStart(2, "0");
      if (CHECKIN[s] && CHECKIN[s].done >= 3) n++;
      else break;
      d.setDate(d.getDate() - 1);
      if (n > 365) break;
    }
    return n;
  }

  /* ── 错题本 ── */
  var ERRBOOK = {};
  try { ERRBOOK = JSON.parse(localStorage.getItem("enErrBook") || "{}"); } catch (e) { ERRBOOK = {}; }
  function errBookSave() { try { localStorage.setItem("enErrBook", JSON.stringify(ERRBOOK)); } catch (e) {} }
  function errAdd(lessonKey, q, a, kind) {
    var k = lessonKey + "|" + kind + "|" + q;
    if (!ERRBOOK[k]) ERRBOOK[k] = { q: q, a: a, kind: kind, lkey: lessonKey, wrong: 0, last: 0 };
    ERRBOOK[k].wrong++;
    ERRBOOK[k].last = Date.now();
    errBookSave();
  }
  function errRemove(k) { delete ERRBOOK[k]; errBookSave(); }
  function errList() {
    return Object.keys(ERRBOOK).sort(function (a, b) {
      return (ERRBOOK[b].last || 0) - (ERRBOOK[a].last || 0);
    }).map(function (k) { return ERRBOOK[k]; });
  }
  function errCount() { return Object.keys(ERRBOOK).length; }

  /* ── 成就勋章 ── */
  var BADGES = [
    { id: "firstStar",   icon: "⭐", name: "初露锋芒",   desc: "获得第一颗星", test: function () { return starTotal() >= 1; } },
    { id: "firstUnit",  icon: "🏁", name: "首战告捷",   desc: "完成第一个单元全部四关", test: function () { return unitFullCount() >= 1; } },
    { id: "threeUnits", icon: "🗺", name: "渐入佳境",   desc: "完成 3 个单元", test: function () { return unitFullCount() >= 3; } },
    { id: "word10",     icon: "📖", name: "积少成多",   desc: "生词本收藏 10 个词", test: function () { return Object.keys(WORDBOOK).length >= 10; } },
    { id: "word50",     icon: "📚", name: "词汇大师",   desc: "生词本收藏 50 个词", test: function () { return Object.keys(WORDBOOK).length >= 50; } },
    { id: "streak3",    icon: "🔥", name: "三天打鱼",   desc: "连续打卡 3 天", test: function () { return checkinStreak() >= 3; } },
    { id: "streak7",    icon: "🏅", name: "一周不落",   desc: "连续打卡 7 天", test: function () { return checkinStreak() >= 7; } },
    { id: "streak30",   icon: "👑", name: "月度全勤",   desc: "连续打卡 30 天", test: function () { return checkinStreak() >= 30; } },
    { id: "err10",      icon: "🔧", name: "错题收割机", desc: "错题本积累 10 题", test: function () { return errCount() >= 10; } },
    { id: "halfMap",    icon: "🚀", name: "半程勇士",   desc: "单元地图点亮过半", test: function () {
      var nodes = document.querySelectorAll(".umap-node");
      if (!nodes.length) return false;
      var done = 0; [].forEach.call(nodes, function (n) { if (n.classList.contains("done")) done++; });
      return done >= nodes.length / 2;
    } },
    { id: "allDone",    icon: "🏆", name: "全部通关",   desc: "单元地图全部完成", test: function () {
      var nodes = document.querySelectorAll(".umap-node");
      if (!nodes.length) return false;
      return [].every.call(nodes, function (n) { return n.classList.contains("done"); });
    } },
  ];
  function starTotal() {
    var n = 0;
    for (var k in STARS) { for (var g in STARS[k]) { if (STARS[k][g]) n++; } }
    return n;
  }
  function unitFullCount() {
    var n = 0;
    for (var k in UNITMAP) {
      var u = UNITMAP[k];
      if (u.preview && u.read && u.exercise && u.game) n++;
    }
    return n;
  }
  function earnedBadges() { return BADGES.filter(function (b) { return b.test(); }); }
  function renderBadges() {
    var earned = earnedBadges();
    var h = '<div class="badges"><span class="badges-h">🎖 勋章 (' + earned.length + '/' + BADGES.length + ')</span>';
    h += '<div class="badges-row">';
    BADGES.forEach(function (b) {
      var has = b.test();
      h += '<span class="badge' + (has ? " on" : "") + '" title="' + esc(b.desc) + '" data-bid="' + esc(b.id) + '">' +
           '<span class="badge-ic">' + (has ? b.icon : "🔒") + '</span>' +
           '<span class="badge-n">' + esc(b.name) + '</span></span>';
    });
    h += '</div></div>';
    return h;
  }
  /* ── 勋章解锁动画 ── */
  var BADGE_UNLOCKED = {};
  try { BADGE_UNLOCKED = JSON.parse(localStorage.getItem("enBadges") || "{}"); } catch (e) { BADGE_UNLOCKED = {}; }
  function badgeSave() { try { localStorage.setItem("enBadges", JSON.stringify(BADGE_UNLOCKED)); } catch (e) {} }
  function checkBadgeUnlock() {
    var newly = [];
    BADGES.forEach(function (b) {
      if (b.test() && !BADGE_UNLOCKED[b.id]) {
        BADGE_UNLOCKED[b.id] = Date.now();
        newly.push(b);
      }
    });
    if (newly.length) {
      badgeSave();
      newly.forEach(function (b, i) {
        setTimeout(function () { showBadgePopup(b); }, i * 1600);
      });
    }
  }
  function showBadgePopup(b) {
    /* 遮罩 + 弹窗 */
    var overlay = document.createElement("div");
    overlay.className = "badge-overlay";
    overlay.innerHTML =
      '<div class="badge-popup">' +
        '<div class="badge-rays"></div>' +
        '<div class="badge-pop-icon">' + b.icon + '</div>' +
        '<div class="badge-pop-title">🏆 勋章解锁！</div>' +
        '<div class="badge-pop-name">' + esc(b.name) + '</div>' +
        '<div class="badge-pop-desc">' + esc(b.desc) + '</div>' +
        '<button class="badge-pop-ok">太棒了</button>' +
      '</div>';
    document.body.appendChild(overlay);
    /* 点按钮或遮罩关闭 */
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay || e.target.closest(".badge-pop-ok")) {
        overlay.classList.add("bye");
        setTimeout(function () { overlay.remove(); }, 400);
      }
    });
    /* 自动关闭（5 秒） */
    setTimeout(function () {
      if (overlay.parentNode) {
        overlay.classList.add("bye");
        setTimeout(function () { overlay.remove(); }, 400);
      }
    }, 5000);
    /* 刷新勋章行：点亮新勋章 */
    var node = document.querySelector('.badge[data-bid="' + b.id + '"]');
    if (node) {
      node.classList.add("on");
      node.querySelector(".badge-ic").textContent = b.icon;
      node.classList.add("badge-flash");
      setTimeout(function () { node.classList.remove("badge-flash"); }, 2000);
    }
    /* 更新计数 */
    var h = document.querySelector(".badges-h");
    if (h) {
      var n = earnedBadges().length;
      h.textContent = "🎖 勋章 (" + n + "/" + BADGES.length + ")";
    }
  }

  /* ---- 单元地图 / 每日 3 分钟 / 生词本：三个页面级组件 ---- */

  /* 单元地图：册 → 单元卡片，每卡显示四关灯（预习/跟读/练习/游戏）
     order/units/nameOf 由 enText 传入，与目录/正文同源，保证进度条对应得上。 */
  /* ── 单元地图（游戏棋盘式蛇形路径）── */
  var UMAP_COLS = 4;                       /* 每行节点数，蛇形折回 */
  function unitUnlocked(order, i) {
    if (i <= 0) return true;               /* 第一单元永远开 */
    var prevDone = unitDoneCount(order[i - 1]);
    return prevDone >= 2;                  /* 前一单元 ≥2 关即解锁 */
  }
  function currentUnitIndex(order) {
    for (var i = 0; i < order.length; i++) {
      if (unitUnlocked(order, i) && unitDoneCount(order[i]) < 4) return i;
    }
    return -1;                              /* 全部完成 */
  }
  function renderUnitMap(order, units, nameOf) {
    var totalUnits = order.length;
    var totalStages = totalUnits * 4;
    var doneStages = 0;
    order.forEach(function (k) { doneStages += unitDoneCount(k); });
    var pct = totalStages ? Math.round(doneStages / totalStages * 100) : 0;
    var curIdx = currentUnitIndex(order);

    var h = '<div class="umap">';
    h += '<div class="umap-h"><b>🗺 单元闯关地图</b>' +
         '<span class="small">每单元四关：预习 · 跟读 · 练习 · 游戏 · 前单元过 2 关解锁</span>' +
         '<span class="umap-progress small">已点亮 <b>' + doneStages +
         '</b> / ' + totalStages + ' 关 (' + pct + '%)</span></div>';
    /* 总进度条 */
    h += '<div class="umap-total"><div class="umap-total-bar" style="width:' + pct + '%"></div></div>';

    /* 蛇形路径 */
    h += '<div class="umap-path">';
    order.forEach(function (k, i) {
      var u = units[k];
      var nLessons = u.dlg.length + u.pas.length;
      var name = nameOf(u);
      var n = unitDoneCount(k);
      var unlocked = unitUnlocked(order, i);
      var isCurrent = (i === curIdx);
      var isDone = (n >= 4);
      var row = Math.floor(i / UMAP_COLS);
      var col = i % UMAP_COLS;
      var reverse = (row % 2 === 1);         /* 奇数行从右到左 */

      h += '<a class="umap-node' +
           (unlocked ? "" : " locked") +
           (isCurrent ? " current" : "") +
           (isDone ? " done" : "") +
           (reverse ? " rev" : "") +
           '" href="#eu' + i + '" data-uk="' + esc(k) + '" data-idx="' + i + '">';

      /* 节点编号圆牌 */
      h += '<div class="umap-badge">' + (i + 1) + '</div>';

      /* 勋章 / 锁 / 当前位置标记 */
      if (isDone) h += '<div class="umap-medal">🏅</div>';
      else if (!unlocked) h += '<div class="umap-lock">🔒</div>';
      else if (isCurrent) h += '<div class="umap-here">📍</div>';

      /* 单元名 */
      h += '<div class="umap-t">' + esc(name) + '</div>';

      /* 四关灯 */
      h += '<div class="umap-stages">' +
           '<span class="umap-s" data-s="preview" title="预习">预</span>' +
           '<span class="umap-s" data-s="read" title="跟读">读</span>' +
           '<span class="umap-s" data-s="exercise" title="练习">练</span>' +
           '<span class="umap-s" data-s="game" title="游戏">游</span>' +
           '</div>';

      /* 进度文字 */
      h += '<div class="umap-n">' + n + '/4 · ' + nLessons + '课</div>';

      h += '</a>';

      /* 连接线（非行末且非最后一个节点） */
      if (i < totalUnits - 1) {
        var nextCol = (i + 1) % UMAP_COLS;
        if (nextCol === 0) {
          h += '<div class="umap-turn ' + (reverse ? "tl" : "tr") + '"></div>';
        } else {
          h += '<div class="umap-link ' + (reverse ? "lr" : "rl") + '"></div>';
        }
      }
    });
    h += '</div>';

    /* 起点 / 终点标记 */
    h += '<div class="umap-endpoints"><span class="umap-start">🏁 起点</span>';
    if (curIdx < 0) h += '<span class="umap-finish done">🏆 全部通关！</span>';
    else h += '<span class="umap-finish">🎯 目标：全部通关</span>';
    h += '</div>';

    h += '</div>';
    return h;
  }
  function refreshUnitMapStages() {
    var doneStages = 0, totalUnits = 0;
    var nodes = document.querySelectorAll(".umap-node");
    var order = [];
    [].forEach.call(nodes, function (el) {
      var uk = el.getAttribute("data-uk");
      order.push(uk);
    });
    [].forEach.call(nodes, function (el, i) {
      totalUnits++;
      var uk = el.getAttribute("data-uk");
      var u = UNITMAP[uk] || {};
      [].forEach.call(el.querySelectorAll(".umap-s"), function (s) {
        var st = s.getAttribute("data-s");
        s.classList.toggle("on", !!u[st]);
      });
      var n = unitDoneCount(uk);
      doneStages += n;
      el.classList.toggle("done", n >= 4);
      var unlocked = unitUnlocked(order, i);
      el.classList.toggle("locked", !unlocked);
      /* 勋章 / 锁标记随状态切换 */
      var medal = el.querySelector(".umap-medal");
      var lock = el.querySelector(".umap-lock");
      var here = el.querySelector(".umap-here");
      if (n >= 4 && !medal) {
        el.insertAdjacentHTML("afterbegin", '<div class="umap-medal">🏅</div>');
        if (lock) lock.remove();
        if (here) here.remove();
      }
      if (n < 4 && !unlocked && !lock) {
        el.insertAdjacentHTML("afterbegin", '<div class="umap-lock">🔒</div>');
        if (medal) medal.remove();
        if (here) here.remove();
      }
    });
    /* 刷新当前位置 */
    var curIdx = currentUnitIndex(order);
    [].forEach.call(nodes, function (el, i) {
      var isCur = (i === curIdx);
      el.classList.toggle("current", isCur);
      var here = el.querySelector(".umap-here");
      if (isCur && !here && !el.classList.contains("done")) {
        el.insertAdjacentHTML("afterbegin", '<div class="umap-here">📍</div>');
      } else if (!isCur && here) {
        here.remove();
      }
    });
    /* 总进度 */
    var total = totalUnits * 4;
    var pct = total ? Math.round(doneStages / total * 100) : 0;
    [].forEach.call(document.querySelectorAll(".umap-progress b"), function (el) {
      el.textContent = doneStages;
    });
    [].forEach.call(document.querySelectorAll(".umap-progress"), function (el) {
      el.textContent = '已点亮 ' + doneStages + ' / ' + total + ' 关 (' + pct + '%)';
      el.insertAdjacentHTML("afterbegin", "<b></b>");
      el.querySelector("b").textContent = doneStages;
    });
    var bar = document.querySelector(".umap-total-bar");
    if (bar) bar.style.width = pct + "%";
    /* 终点状态 */
    var fin = document.querySelector(".umap-finish");
    if (fin) {
      if (curIdx < 0) {
        fin.textContent = "🏆 全部通关！";
        fin.classList.add("done");
      } else {
        fin.textContent = "🎯 目标：全部通关";
        fin.classList.remove("done");
      }
    }
  }

  /* 每日 3 分钟：从"错题本 + 生词本 + 未复习的课"里抽 3 张卡
     错题本暂缺，用生词本 + 已打过星但未自评的课作候选池。 */
  function renderToday() {
    var today = todayStr();
    var day = CHECKIN[today] || { items: [], done: 0 };
    if (!day.items || day.items.length === 0) {
      day.items = pickTodayItems();
      CHECKIN[today] = day;
      checkinSave();
    }
    var streak = checkinStreak();
    var done = day.done || 0;
    var h = '<details class="today"' + (done >= 3 ? "" : " open") + '>' +
            '<summary><b>📅 每日 3 分钟</b>' +
            '<span class="small">' + esc(today) + ' · 已完成 ' + done + '/3</span>' +
            '<span class="today-streak small">🔥 连击 ' + streak + ' 天</span>' +
            '<span class="wb-badge">📖 <span class="wb-count">' + wbList().length + '</span></span>' +
            '<span class="small today-repick">换一批</span></summary>';
    h += '<div class="today-body">';
    h += '<p class="small">每天三张卡：先自己说，再点 <b>✅ 已记住</b> 打勾。</p>';
    if (day.items.length === 0) {
      h += '<p class="small">先把生词收藏进词本，明天就有卡可抽。</p>';
    } else {
      h += '<div class="today-items">';
      day.items.forEach(function (it, i) {
        var done_i = day.done >= i + 1;
        var card = "";
        if (it.kind === "error") {
          card = '<div class="today-card' + (done_i ? " done" : "") + '" data-i="' + i + '">' +
                 '<span class="tag d1">错题</span>' +
                 '<b>' + esc(it.q) + '</b>' +
                 '<span class="small">正确：' + esc(it.a) + '</span>' +
                 '<span class="small">类型：' + esc(it.errKind || "") + '</span>' +
                 '<button class="btn today-ok">✅ 已搞懂</button>' +
                 '<button class="btn today-wrong">❌ 还是不会</button></div>';
        } else if (it.kind === "word") {
          card = '<div class="today-card' + (done_i ? " done" : "") + '" data-i="' + i + '">' +
                 '<span class="tag d1">生词</span>' +
                 '<b>' + esc(it.word) + '</b>' +
                 (it.ipa ? ' <i>' + esc(it.ipa) + '</i>' : "") +
                 (it.zh ? ' <em class="wzh">' + esc(it.zh) + '</em>' : "") +
                 '<button class="btn today-ok">✅ 已记住</button>' +
                 '<button class="btn today-wrong">❌ 再来</button></div>';
        } else if (it.kind === "lesson") {
          card = '<div class="today-card' + (done_i ? " done" : "") + '" data-i="' + i +
                 '" data-lkey="' + esc(it.key) + '">' +
                 '<span class="tag">复习</span>' +
                 '<b>' + esc(it.title) + '</b>' +
                 '<span class="small">' + esc(it.book) + '</span>' +
                 '<button class="btn today-go">去复习</button>' +
                 '<button class="btn today-ok">✅ 已复习</button></div>';
        }
        h += card;
      });
      h += '</div>';
    }
    h += '</div></details>';
    return h;
  }
  /* 抽 3 张今日卡：生词本按 last 最久未复习优先，其次补未自评的课 */
  function pickTodayItems() {
    var items = [];
    // 错题：最近的错题优先（取 1 条）
    var errs = errList();
    if (errs.length) {
      var e0 = errs[0];
      items.push({ kind: "error", q: e0.q, a: e0.a, errKind: e0.kind, lkey: e0.lkey });
    }
    // 生词：按 last 升序（越久没复习越靠前）
    var wb = wbList().slice().sort(function (a, b) { return (a.last || 0) - (b.last || 0); });
    wb.forEach(function (w) {
      if (items.length >= 3) return;
      items.push({ kind: "word", word: w.word, ipa: w.ipa, zh: w.zh,
                   key: wbKey(w.book, w.word) });
    });
    // 补未自评（rate === 0）的课，随机挑
    var less = [];
    Object.keys(LESSONS).forEach(function (key) {
      var s = STARS[key] || {};
      if (!s.rate) {
        var x = LESSONS[key].data;
        less.push({ key: key, book: x.book || "",
                    title: LESSONS[key].type === "dlg"
                      ? (x.scene || x.title || "对话")
                      : (x.name || "短文") });
      }
    });
    shuffle(less);
    less.forEach(function (l) {
      if (items.length >= 3) return;
      items.push({ kind: "lesson", key: l.key, book: l.book, title: l.title });
    });
    return items.slice(0, 3);
  }

  /* 生词本：按遗忘曲线（1 天 / 3 天 / 7 天）挑该复习的词，其余词列后面 */
  function renderWordBook() {
    var items = wbList();
    var now = Date.now();
    var DAY = 86400000;
    items.sort(function (a, b) {
      // 到复习时点越早越靠前；从未复习按 last 排
      var da = nextReview(a), db = nextReview(b);
      return da - db;
    });
    var due = [], rest = [];
    items.forEach(function (w) {
      (nextReview(w) <= now ? due : rest).push(w);
    });
    var h = '<details class="wordbook">' +
            '<summary><b>📖 我的生词本</b>' +
            '<span class="small">收藏 ' + items.length + ' 词</span>' +
            '<span class="small">待复习 <b>' + due.length + '</b> 词</span>' +
            '</summary>';
    h += '<div class="wb-list">';
    if (items.length === 0) {
      h += '<p class="small">还没有生词。去「预习」或「音标」板块，点生词旁的 <b>+ 收藏</b> 加入。</p>';
    } else {
      h += '<p class="small">🔔 待复习（1/3/7 天间隔）</p>';
      h += wbListInnerRow(due.length ? due : items.slice(0, 3), true);
      if (rest.length) {
        h += '<p class="small">📚 其他生词</p>' + wbListInnerRow(rest);
      }
    }
    h += '</div></details>';
    return h;
  }
  function nextReview(w) {
    // 忘了就提前回来；对了就拉长间隔（1 → 3 → 7 → 14 → 30）
    if (!w.last) return w.added || 0;
    var wrong = w.wrong > w.right;
    var gap = 1;
    var n = (w.right || 0);
    if (n === 0) gap = 1;
    else if (n === 1) gap = 3;
    else if (n === 2) gap = 7;
    else if (n === 3) gap = 14;
    else gap = 30;
    if (wrong) gap = Math.max(1, gap - 1);
    return w.last + gap * 86400000;
  }
  function wordBookListInner() { return renderWordBook().replace(/^<details[^>]*>|<\/details>$/g, ""); }
  function wbListInnerRow(items, isDue) {
    return '<div class="wb-grid">' + items.map(function (w) {
      var k = wbKey(w.book, w.word);
      return '<div class="wb-card' + (isDue ? " due" : "") + '" data-k="' + esc(k) + '">' +
             '<b>' + esc(w.word) + '</b>' +
             (w.ipa ? ' <i>' + esc(w.ipa) + '</i>' : "") +
             (w.zh ? '<br><span class="wzh">' + esc(w.zh) + '</span>' : "") +
             '<span class="wb-meta small">' +
             (w.right || 0) + '✓ / ' + (w.wrong || 0) + '✗</span>' +
             '<span class="wb-act">' +
             '<button class="btn wb-right">记住了</button>' +
             '<button class="btn wb-wrong">忘了</button>' +
             '<button class="btn wb-del">移除</button>' +
             '</span></div>';
    }).join("") + '</div>';
  }

  /* 本课生词：对话取 vocab_cards（带 IPA/词性），短文取 words 并回查词汇表补音标。
     本课标注不足 3 个时用单元词汇表兜底，音标/游戏板块才不至于空转。 */
  var VIDX = null;
  function vlookup(book, word) {
    if (!VIDX) {
      VIDX = {};
      (D.vocab || []).forEach(function (v) {
        var k = (v.book || "") + "#" + String(v.word || "").toLowerCase();
        if (!VIDX[k]) VIDX[k] = v;
      });
    }
    return VIDX[(book || "") + "#" + String(word || "").toLowerCase()] || null;
  }
  function lessonWords(x, type) {
    var out = [], seen = {};
    function add(w, ipa, zh, pos) {
      w = String(w || "").trim();
      if (!w || seen[w.toLowerCase()]) return;
      seen[w.toLowerCase()] = 1;
      if (ipa && ipa.charAt(0) !== "/") ipa = "/" + ipa + "/";
      out.push({ word: w, ipa: ipa || "", zh: zh || "", pos: pos || "" });
    }
    if (type === "dlg") {
      (x.vocab_cards || []).forEach(function (c) { add(c.word, c.ipa, c.zh, c.pos); });
    }
    (x.words || []).forEach(function (w) {
      var ww = w.word || w, v = vlookup(x.book, ww);
      add(ww, (v && v.phonetic) || "", w.zh || w.meaning || (v && v.meaning) || "", "");
    });
    out.own = out.length >= 3;
    if (out.length < 3) {
      (D.vocab || []).forEach(function (v) {
        if (out.length >= 10) return;
        if (v.book === x.book && (v.unit_no || 0) === (x.unit_no || 0)) {
          add(v.word, v.phonetic, v.meaning, "");
        }
      });
    }
    return out;
  }
  /* 本课句子：对话按轮次，短文按行。游戏与听读共用。 */
  function lessonLines(x, type) {
    if (type === "dlg") {
      return (x.turns || []).map(function (t) {
        return typeof t === "string" ? t : (t.text || t.line || t.en || "");
      }).filter(function (s) { return s && s.trim().length > 3; });
    }
    return String(x.text || "").split(/\n+/)
      .map(function (s) { return s.trim(); })
      .filter(function (s) { return s.length > 3; });
  }

  /* 课外拓展：本体论 + ReadWorks 风格
     数据来源：D.readings（长文库 catalog.json）+ D.picturebooks（绘本 books.json）
     筛选维度来自 taxonomy.json 的本体分面 */
  var EX_FACETS = [
    ["grade_band", "年级段"], ["text_type", "体裁"], ["themes", "主题"],
    ["settings", "背景"], ["word_count_bucket", "篇幅"],
    ["lexile", "难度"], ["cultural_origin", "文化"], ["time_period", "时代"],
    ["target_skills", "技能"], ["text_role", "挂载角色"],
  ];
  var EX_FACET_LABELS = {
    grade_band: { early_primary: "低段(1-2)", mid_primary: "中段(3-4)",
                  late_primary: "高段(5-6)", middle_school: "初中(7-8)" },
    text_type: { fable: "寓言", folktale: "民间故事", fantasy: "幻想",
                 realistic_fiction: "现实主义", adventure: "冒险",
                 detective: "侦探", satire: "讽刺", memoir: "回忆录", essay: "散文" },
    themes: { courage: "勇气", kindness: "善良", honesty: "诚实", friendship: "友谊",
              perseverance: "坚持", self_acceptance: "自我接纳", belonging: "归属感",
              growing_up: "成长", imagination: "想象力", justice: "正义",
              loyalty: "忠诚", resilience: "韧性", survival: "生存", homecoming: "归家",
              generosity: "慷慨", humility: "谦逊", curiosity: "好奇",
              love_loss: "爱与失去", disobedience: "违纪/后果", reason: "理性",
              family: "家庭亲情", trade_sharing: "交易与分享", money_wealth: "金钱财富" },
    settings: { countryside: "乡村", rural_village: "村庄", city_urban: "城市",
                school: "学校", forest_wild: "森林", mountain: "山地",
                sea_nautical: "海上", jungle: "丛林", arctic: "极地", farm: "农场",
                garden_park: "花园", magical_world: "奇幻世界", space_outer: "太空",
                medieval: "中世纪", nature_outdoor: "自然户外" },
    word_count_bucket: { very_short: "极短(<500)", short: "短(500-1500)",
                         medium: "中(1500-3000)", long: "长(3000-5000)",
                         very_long: "很长(>5000)" },
    lexile: { elementary_low: "200-500L", elementary_mid: "500-800L",
              elementary_high: "800-1000L", middle_early: "1000-1200L",
              middle_late: "1200-1500L" },
    cultural_origin: { British: "英国", American: "美国", Danish: "丹麦",
                       Greek: "希腊", Swiss_German: "瑞士/德国", French: "法国",
                       British_Indian: "英印", British_Scottish: "苏格兰",
                       British_Irish: "爱尔兰", Canadian: "加拿大",
                       British_American: "英美", Kenyan: "肯尼亚",
                       Ethiopian: "埃塞俄比亚", Ghanaian: "加纳",
                       South_African: "南非", African_Oral: "非洲口传", Other: "其他" },
    time_period: { timeless_fantasy: "奇幻/无时代", medieval: "中世纪",
                   "18th_century": "18世纪", victorian: "维多利亚",
                   early_20th: "20世纪初", modern: "现代" },
    target_skills: { reading_comprehension: "阅读理解", vocabulary_extension: "词汇拓展",
                     retelling: "复述", grammar_practice: "语法练习",
                     writing_inspiration: "写作启发", cultural_awareness: "文化意识",
                     critical_thinking: "批判思维" },
    text_role: { pre_reading: "预热文", bridge_text: "桥梁文", consolidation: "巩固文",
                 extension: "拓展文", compare_contrast: "对比文",
                 writing_trigger: "写作触发", culture_window: "文化窗口" },
  };
  function exFacetLabel(cat, val) {
    var m = EX_FACET_LABELS[cat];
    return m && m[val] ? m[val] : val;
  }
  var EX_FILTER = {};
  try { EX_FILTER = JSON.parse(localStorage.getItem("enExtraFilter") || "{}"); } catch (e) { EX_FILTER = {}; }
  function exChecked(cat, val) {
    return EX_FILTER[cat] && EX_FILTER[cat].indexOf(val) >= 0;
  }
  function exToggle(cat, val) {
    if (!EX_FILTER[cat]) EX_FILTER[cat] = [];
    var i = EX_FILTER[cat].indexOf(val);
    if (i >= 0) EX_FILTER[cat].splice(i, 1);
    else EX_FILTER[cat].push(val);
    if (!EX_FILTER[cat].length) delete EX_FILTER[cat];
    try { localStorage.setItem("enExtraFilter", JSON.stringify(EX_FILTER)); } catch (e) {}
  }
  /* 从一本书的 facets 里取某个维度的值（数组或单值统一返回数组） */
  function exFacetVals(book, cat) {
    var f = book.facets || {};
    var v = f[cat];
    if (!v) return [];
    if (cat === "lexile") return f.lexile && f.lexile.band ? [f.lexile.band] : [];
    if (Array.isArray(v)) return v;
    return [v];
  }
  function exMatch(book) {
    for (var i = 0; i < EX_FACETS.length; i++) {
      var cat = EX_FACETS[i][0];
      if (!EX_FILTER[cat] || !EX_FILTER[cat].length) continue;
      var vals = exFacetVals(book, cat);
      var hit = false;
      for (var j = 0; j < vals.length; j++) {
        if (EX_FILTER[cat].indexOf(vals[j]) >= 0) { hit = true; break; }
      }
      if (!hit) return false;
    }
    /* 话题筛选（primary_topic + secondary_topics） */
    if (EX_FILTER.topic && EX_FILTER.topic.length) {
      var ts = [book.primary_topic || ""].concat(book.secondary_topics || []);
      var th = false;
      for (var k = 0; k < ts.length; k++) {
        if (EX_FILTER.topic.indexOf(ts[k]) >= 0) { th = true; break; }
      }
      if (!th) return false;
    }
    /* 类型筛选：readings vs picturebooks */
    if (EX_FILTER.source && EX_FILTER.source.length) {
      if (EX_FILTER.source.indexOf(book._source) < 0) return false;
    }
    return true;
  }
  function enExtra(st) {
    var readings = D.readings || [];
    var pbs = D.picturebooks || [];
    var all = [];
    readings.forEach(function (b) { all.push(Object.assign({_source: "reading"}, b)); });
    pbs.forEach(function (b) { all.push(Object.assign({_source: "picturebook"}, b)); });
    if (!all.length) return '<div class="empty">课外拓展库暂无内容</div>';

    /* 收集每个维度的可用值 + 计数 */
    var facetCounts = {};
    EX_FACETS.forEach(function (f) { facetCounts[f[0]] = {}; });
    facetCounts.topic = {};
    facetCounts.source = {};
    all.forEach(function (b) {
      EX_FACETS.forEach(function (f) {
        exFacetVals(b, f[0]).forEach(function (v) {
          facetCounts[f[0]][v] = (facetCounts[f[0]][v] || 0) + 1;
        });
      });
      [b.primary_topic || ""].concat(b.secondary_topics || []).forEach(function (t) {
        if (t) facetCounts.topic[t] = (facetCounts.topic[t] || 0) + 1;
      });
      facetCounts.source[b._source] = (facetCounts.source[b._source] || 0) + 1;
    });

    /* 渲染筛选组 */
    function filterGroup(cat, label, vals, counts) {
      /* 从 counts 取可用值（vals 只提供 label 映射） */
      var keys = Object.keys(counts).sort(function (a, b) {
        return (counts[b] || 0) - (counts[a] || 0);
      }).filter(function (v) { return counts[v]; });
      if (!keys.length) return "";
      var h = '<div class="rw-fgrp"><div class="rw-fh">' + label + '</div>';
      keys.forEach(function (v) {
        var ck = exChecked(cat, v);
        var lbl = typeof vals === "object" && !Array.isArray(vals) ? (vals[v] || v) : v;
        h += '<label class="rw-ck' + (ck ? " checked" : "") + '">' +
             '<input type="checkbox" data-fcat="' + esc(cat) + '" data-fval="' + esc(v) + '"' +
             (ck ? " checked" : "") + '>' +
             '<span>' + esc(lbl) + '</span>' +
             '<span class="rw-cnt">' + (counts[v] || 0) + '</span></label>';
      });
      return h + '</div>';
    }
    var tx = D.taxonomy || {};
    /* 筛选栏 */
    var sidebar = '<div class="rw-sidebar">' +
      '<div class="rw-fhd">筛选 <button class="rw-clear">清除全部</button></div>' +
      filterGroup("source", "来源", {reading: "长文", picturebook: "绘本"}, facetCounts.source) +
      filterGroup("grade_band", "年级段", EX_FACET_LABELS.grade_band, facetCounts.grade_band) +
      filterGroup("text_type", "体裁", EX_FACET_LABELS.text_type, facetCounts.text_type) +
      filterGroup("themes", "主题", EX_FACET_LABELS.themes, facetCounts.themes) +
      filterGroup("settings", "背景", EX_FACET_LABELS.settings, facetCounts.settings) +
      filterGroup("word_count_bucket", "篇幅", EX_FACET_LABELS.word_count_bucket, facetCounts.word_count_bucket) +
      filterGroup("lexile", "难度", EX_FACET_LABELS.lexile, facetCounts.lexile) +
      filterGroup("cultural_origin", "文化", EX_FACET_LABELS.cultural_origin, facetCounts.cultural_origin) +
      filterGroup("time_period", "时代", EX_FACET_LABELS.time_period, facetCounts.time_period) +
      filterGroup("target_skills", "技能", EX_FACET_LABELS.target_skills, facetCounts.target_skills) +
      filterGroup("text_role", "挂载角色", EX_FACET_LABELS.text_role, facetCounts.text_role) +
      filterGroup("topic", "话题", {}, facetCounts.topic) +
      '</div>';

    /* 卡片列表 */
    var shown = all.filter(exMatch);
    var main = '<div class="rw-main"><div class="rw-count">共 ' + shown.length + ' 本' +
      (all.length !== shown.length ? '（已筛选，总共 ' + all.length + ' 本）' : '') + '</div>';
    if (!shown.length) main += '<div class="empty">没有匹配的内容，试试清除部分筛选</div>';

    shown.forEach(function (b) {
      var f = b.facets || {};
      var tags = [];
      if (b._source === "picturebook" && b.level) tags.push(["d1", b.level]);
      if (f.text_type) tags.push(["", exFacetLabel("text_type", f.text_type)]);
      if (f.grade_band) tags.push(["d2", exFacetLabel("grade_band", f.grade_band)]);
      if (f.word_count_bucket) tags.push(["d3", exFacetLabel("word_count_bucket", f.word_count_bucket)]);
      if (f.lexile && f.lexile.band) tags.push(["d3", exFacetLabel("lexile", f.lexile.band)]);
      if (b.primary_topic) tags.push(["d1", b.primary_topic]);
      (f.themes || []).slice(0, 3).forEach(function (t) { tags.push(["d2", exFacetLabel("themes", t)]); });
      (f.target_skills || []).slice(0, 2).forEach(function (t) { tags.push(["", exFacetLabel("target_skills", t)]); });

      main += '<details class="rw-card" id="rw-' + esc(b.id) + '"><summary>' +
        '<span class="rw-card-title">' + esc(b.title) + '</span>' +
        '<span class="rw-card-author">' + esc(b.author || "") + '</span>' +
        '<span class="rw-card-tags">' +
        tags.map(function (t) {
          return '<span class="tag' + (t[0] ? " " + t[0] : "") + '">' + esc(t[1]) + '</span>';
        }).join("") + '</span></summary>';

      /* 元信息 */
      main += '<div class="rw-meta">';
      if (b._source === "picturebook") {
        if (b.word_count) main += '<span>词数 ' + b.word_count + '</span>';
        if (b.reading_time_min) main += '<span>约 ' + b.reading_time_min + ' 分钟</span>';
      }
      if (f.cultural_origin) main += '<span>' + exFacetLabel("cultural_origin", f.cultural_origin) + '</span>';
      if (f.time_period) main += '<span>' + exFacetLabel("time_period", f.time_period) + '</span>';
      (f.settings || []).forEach(function (s) {
        main += '<span>📍' + exFacetLabel("settings", s) + '</span>';
      });
      (f.text_role || []).forEach(function (r) {
        main += '<span>📎' + exFacetLabel("text_role", r) + '</span>';
      });
      main += '</div>';

      /* 话题 */
      var topics = [b.primary_topic || ""].concat(b.secondary_topics || []).filter(Boolean);
      if (topics.length) {
        main += '<div class="rw-topics">话题：' +
          topics.map(function (t) { return '<span class="tag d1">' + esc(t) + '</span>'; }).join("") +
          '</div>';
      }

      /* 绘本：展示页面文本 */
      if (b._source === "picturebook" && b.pages && b.pages.length) {
        main += '<div class="rw-pages">';
        b.pages.forEach(function (p) {
          if (p.text) {
            main += '<p class="rw-pg"><span class="rw-pgn">P' + (p.n || "") + '</span>' +
                    esc(p.text) + spkBtn(p.text) +
                    ' <button class="btn rw-pg-tr" type="button" data-book="' + esc(b.id) +
                    '" data-pg="' + (p.n || 0) + '">译</button>' +
                    '<span class="rw-pg-zh hide"></span></p>';
          }
        });
        main += '</div>';
      }

      /* 长文：分段精读 + 词汇聚焦 + 翻译对照 + 朗读 + 进度 */
      if (b._source === "reading") {
        if (b.text) {
          main += renderReadingText(b.text, b.id);
        }
        /* 配套教材单元：b.units 是解析后的对象（带 book/unit_no/unit_name/grade），
           b.pairs_with_unit 是裸 id 列表（无定位信息），只信任前者 */
        if (b.units && b.units.length) {
          var uls = b.units.map(function (u) { return unitLink(u); }).join("");
          main += '<p class="small rw-ulinks">🔗 配套教材单元：' + uls + '</p>';
        }
      }

      main += '</details>';
    });
    main += '</div>';

    /* 从教材单元页跳来：#read=<id> → 打开并展开对应书籍卡片 */
    function applyReadHash() {
      var m = String(location.hash || "").match(/^#read=(.+)$/);
      if (!m) return;
      var el = document.getElementById("rw-" + decodeURIComponent(m[1]));
      if (!el) return;
      el.open = true;
      setTimeout(function () {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    }
    setTimeout(applyReadHash, 60);
    window.addEventListener("hashchange", applyReadHash);
    var html = '<div class="rw-layout" id="rw-layout-root">' + sidebar + main + '</div>';
    setTimeout(function () {
      var root = document.getElementById("rw-layout-root");
      if (root) _bindRead(root);
    }, 0);
    return html;
  }

  /* ---- 课外拓展：分段精读引擎 ---- */
  var COMMON_WORDS = "the a an is was are were be been being have has had do does did will would could should may might must can shall to of in on at by for with from into onto upon about above below between through during before after since until as like than that this these those it its his her their our your my me him them us you they we i he she who whom whose what which where when why how not no nor so too very just only also but and or yet if then else when while because although though unless since until once more most many much few less least several both either neither each every all none some such own same other another here there everywhere nowhere somewhere anywhere now then always never often sometimes usually rarely soon later already still yet again ago away back down up off out over under around across along past behind beside beyond within without against toward towards amidst among amongst amidst".split(" ");
  var _commonSet = {};
  COMMON_WORDS.forEach(function (w) { _commonSet[w.toLowerCase()] = 1; });

  function extractVocab(text) {
    var words = text.toLowerCase().match(/[a-z]+/g) || [];
    var freq = {}, seen = {};
    words.forEach(function (w) {
      if (w.length >= 4 && !_commonSet[w]) {
        freq[w] = (freq[w] || 0) + 1;
      }
    });
    return Object.keys(freq).sort(function (a, b) {
      return freq[b] - freq[a];
    }).slice(0, 8);
  }

  /* 简易音标生成器：基于英语拼读规则，覆盖常见模式 */
  var _ipaCache = {};
  function simpleIPA(word) {
    word = word.toLowerCase().trim();
    if (!word) return "";
    if (_ipaCache[word]) return _ipaCache[word];
    var w = word, ipa = "";

    /* 不规则常见词速查表 */
    var IRREG = {
      said: "/sed/", were: "/wɜː/", been: "/bɪn/", done: "/dʌn/", does: "/dʌz/",
      would: "/wʊd/", should: "/ʃʊd/", could: "/kʊd/", come: "/kʌm/", some: "/sʌm/",
      have: "/hæv/", give: "/ɡɪv/", live: "/lɪv/", love: "/lʌv/", move: "/muːv/",
      water: "/ˈwɔːtə/", again: "/əˈɡen/", every: "/ˈevri/", woman: "/ˈwʊmən/",
      women: "/ˈwɪmɪn/", child: "/tʃaɪld/", children: "/ˈtʃɪldrən/", people: "/ˈpiːpl/",
      through: "/θruː/", although: "/ɔːlˈðoʊ/", enough: "/ɪˈnʌf/", though: "/ðoʊ/",
      thought: "/θɔːt/", brought: "/brɔːt/", daughter: "/ˈdɔːtə/", laugh: "/læf/",
      heart: "/hɑːt/", hear: "/hɪə/", heard: "/hɜːd/", earth: "/ɜːθ/",
      beauty: "/ˈbjuːti/", build: "/bɪld/", guide: "/ɡaɪd/", guard: "/ɡɑːd/",
      blood: "/blʌd/", floor: "/flɔː/", door: "/dɔː/", poor: "/pʊə/",
      sure: "/ʃʊə/", sugar: "/ˈʃʊɡə/", ocean: "/ˈoʊʃn/", special: "/ˈspeʃl/",
      machine: "/məˈʃiːn/", police: "/pəˈliːs/", nature: "/ˈneɪtʃə/", picture: "/ˈpɪktʃə/",
      answer: "/ˈænsə/", often: "/ˈɒfn/", listen: "/ˈlɪsn/", castle: "/ˈkɑːsl/",
      whole: "/hoʊl/", whose: "/huːz/", who: "/huː/", whom: "/huːm/"
    };
    if (IRREG[w]) { _ipaCache[w] = IRREG[w]; return IRREG[w]; }

    /* 静音字母 */
    w = w.replace(/^kn/, "n").replace(/^wr/, "r").replace(/^wh/, "w")
         .replace(/^ps/, "s").replace(/^gn/, "n").replace(/^mn/, "n")
         .replace(/mb$/, "m").replace(/bt$/, "t").replace(/ght/, "t");

    /* 辅音组合 */
    w = w.replace(/sh/g, "ʃ").replace(/ch/g, "tʃ").replace(/th/g, "θ")
         .replace(/ph/g, "f").replace(/ng/g, "ŋ").replace(/ck/g, "k")
         .replace(/qu/g, "kw").replace(/wh/g, "w").replace(/zh/g, "ʒ");

    /* c/g 软化 */
    w = w.replace(/c([ei])/g, "s$1").replace(/g([ei])/g, "dʒ$1");

    /* 元音组合 */
    w = w.replace(/ee/g, "iː").replace(/ea/g, "e")
         .replace(/oo/g, "uː").replace(/ou/g, "aʊ").replace(/ow/g, "oʊ")
         .replace(/ai/g, "eɪ").replace(/ay/g, "eɪ")
         .replace(/oi/g, "ɔɪ").replace(/oy/g, "ɔɪ")
         .replace(/au/g, "ɔː").replace(/aw/g, "ɔː")
         .replace(/igh/g, "aɪ").replace(/ie/g, "aɪ")
         .replace(/oa/g, "oʊ").replace(/ew/g, "juː")
         .replace(/ar/g, "ɑː").replace(/er/g, "ə").replace(/ir/g, "ɜː")
         .replace(/or/g, "ɔː").replace(/ur/g, "ɜː")
         .replace(/air/g, "eə").replace(/ear/g, "ɪə");

    /* a_e / i_e / o_e / u_e（magic e） */
    w = w.replace(/a([^aeiou])e/g, "eɪ$1")
         .replace(/i([^aeiou])e/g, "aɪ$1")
         .replace(/o([^aeiou])e/g, "oʊ$1")
         .replace(/u([^aeiou])e/g, "juː$1");

    /* 剩余单元音 */
    w = w.replace(/a/g, "æ").replace(/e/g, "e").replace(/i/g, "ɪ")
         .replace(/o/g, "ɒ").replace(/u/g, "ʌ").replace(/y/g, "i");

    /* 清理 */
    w = w.replace(/e$/, "").replace(/ɪː/g, "iː");
    ipa = "/" + w.replace(/[^a-zɪæɒʌəɔːˈˌʃʒŋθðβː]/g, "") + "/";

    /* 简单音节切分：每个元音核一个音节，加重音符号 */
    var vowels = ipa.match(/[æeɪɒʌəɔːiːuːʊaɪeɪɔɪaʊoʊeəɪə]/g);
    if (vowels && vowels.length > 1) {
      ipa = ipa.replace(/^\/([^/])/, "/ˈ$1");
    }

    _ipaCache[word] = ipa;
    return ipa;
  }

  function highlightVocab(text, vocab) {
    var html = esc(text);
    vocab.forEach(function (w) {
      var ipa = simpleIPA(w);
      var re = new RegExp("\\b(" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")\\b", "gi");
      html = html.replace(re, '<span class="rw-vocab" data-word="$1" title="' +
              esc(ipa) + '">$1<i class="rw-vocab-tip">' + esc(ipa) + '</i></span>');
    });
    return html;
  }

  function renderReadingText(text, bookId) {
    /* 连续段落版：按 \n\n 分自然段，保留原文排版，不打断阅读 */
    var paras = text.split(/\n\n+/).filter(function (p) { return p.trim(); });
    if (!paras.length) return '<p class="small">暂无正文</p>';
    var totalWords = (text.match(/[A-Za-z']+/g) || []).length;

    /* 逐词切分：先把每段拆成 token（词 / 非词），标出词在"干净文本"
       中的起点偏移，供播放时按 speechSynthesis.onboundary 的 charIndex 高亮。 */
    var TOKEN_RE = /[A-Za-z']+(?:['-][A-Za-z']+)*|[^A-Za-z']+/g;
    var clean = "";              // 与播放文本一致：段落内词用单空格，段落间用句号+换行
    var wordOffsets = [];        // [[startOfs, wordText], ...]

    function flatten(p) {
      return p.replace(/\s+/g, " ").trim();
    }
    var segs = paras.map(flatten);
    // 第一遍：构建 clean + wordOffsets（段落间用 ". " 分隔）
    segs.forEach(function (seg, si) {
      var re = new RegExp(TOKEN_RE.source, "g"), m;
      var segStart = clean.length;
      var cursor = 0;
      while ((m = re.exec(seg)) !== null) {
        var tok = m[0];
        if (/[A-Za-z']/.test(tok.charAt(0))) {
          wordOffsets.push([segStart + m.index, tok]);
        }
        cursor = m.index + tok.length;
      }
      clean += seg;
      if (si < segs.length - 1) clean += ". ";
    });

    /* 按句切分且完整保留字符（含分隔空白），保证正文文本与词偏移不变；
       每句包一层 .rw-sent，供全文翻译时把中文插到该句正下方。 */
    function splitSentKeep(seg) {
      var re = /[^.!?。！？\n]+[.!?。！？]?\s*/g, m, out = [];
      while ((m = re.exec(seg)) !== null) { if (m[0]) out.push(m[0]); }
      return out;
    }
    var h = '<div class="rw-read2" data-book="' + esc(bookId || "") + '">';
    h += '<div class="rw-read2-bar">';
    h += '<button class="btn rw-read-all" type="button">🔊 全文朗读</button>';
    h += '<button class="btn rw-tr-all" type="button">全文翻译</button>';
    h += '<span class="rw-read2-hint">选中单词或句子可查询含义</span>';
    h += '<span class="rw-read2-meta">' + totalWords + ' 词</span>';
    h += '</div>';
    h += '<div class="rw-read2-body">';
    for (var s = 0; s < segs.length; s++) {
      var sentChunks = splitSentKeep(segs[s]);
      h += '<p class="rw-para-plain">';
      for (var c = 0; c < sentChunks.length; c++) {
        h += '<span class="rw-sent">';
        var re2 = new RegExp(TOKEN_RE.source, "g"), m2;
        while ((m2 = re2.exec(sentChunks[c])) !== null) {
          var tok2 = m2[0];
          if (/[A-Za-z']/.test(tok2.charAt(0))) {
            h += '<span class="rw-w" data-word="' + esc(tok2) + '">' + esc(tok2) + '</span>';
          } else {
            h += esc(tok2);
          }
        }
        h += '</span>';
      }
      h += '</p>';
    }
    h += '</div>';
    h += '<div class="lookup-card" style="display:none"></div>';
    h += '</div>';

    /* 把干净文本与词偏移挂到根节点属性，供 _bindRead 播放时高亮。
       属性用双引号包裹，JSON 里的 " 需转义成 &quot; 以免破坏属性边界。 */
    var cleanAttr = esc(clean).replace(/"/g, "&quot;");
    var offsAttr = esc(JSON.stringify(wordOffsets)).replace(/"/g, "&quot;");
    h = h.replace('data-book="' + esc(bookId || "") + '"',
                  'data-book="' + esc(bookId || "") + '" data-clean="' + cleanAttr +
                  '" data-offs="' + offsAttr + '"');
    return h;
  }

  /* 从原文本中定位划词区间的起点，返回所属句子 */
  function _sentenceAt(raw, idx) {
    if (!raw || idx < 0) return "";
    var re = /[^.!?。！？\n]+[.!?。！？]?/g, m, s0 = 0, s1 = 0;
    while ((m = re.exec(raw)) !== null) {
      if (idx >= m.index && idx < m.index + m[0].length) { s0 = m.index; s1 = m.index + m[0].length; break; }
    }
    return raw.slice(s0, s1).trim();
  }
  /* 单词原形还原（简易去 s/es/d/ed） */
  function _normWord(w) {
    w = w.toLowerCase();
    if (w.length > 4 && /ing$/.test(w)) w = w.slice(0, -3);
    else if (w.length > 4 && /ed$/.test(w)) w = w.slice(0, -2);
    else if (w.length > 4 && w !== "is" && /s$/.test(w) && !/(ss|us|x|ch|sh)$/.test(w)) w = w.slice(0, -1);
    return w;
  }

  /* ---- 本地语法提示（离线规则，不依赖网络） ----
     单词：后缀/词法猜词性 + 常用搭配；
     短语/句子：时态词检测 + 疑问/否定/存在句句型提示。 */
  var _AUX = { is: true, am: true, are: true, was: true, were: true, be: true, been: true,
               do: true, does: true, did: true, have: true, has: true, had: true,
               will: true, would: true, can: true, could: true, shall: true, should: true,
               may: true, might: true, must: true, need: true, dare: true, used: true };
  var _PREP = { in:true, on:true, at:true, of:true, to:true, for:true, with:true, by:true,
                from:true, into:true, under:true, over:true, about:true, without:true };
  var _DET = { a:true, an:true, the:true, this:true, that:true, these:true, those:true,
               my:true, your:true, his:true, her:true, its:true, our:true, their:true,
               some:true, any:true, no:true, every:true, each:true };
  var _CONJ = { and:true, or:true, but:true, because:true, when:true, if:true, so:true,
                after:true, before:true, while:true, that:true, than:true, as:true };
  var _PRON = { i:true, me:true, we:true, us:true, you:true, he:true, she:true, it:true,
                they:true, them:true, who:true, whom:true, which:true, what:true,
                my:true, mine:true, your:true, yours:true, our:true, their:true };
  var _WH = [ /^wh[a-z]/, /^how/ ];
  function _posGuess(w) {
    w = w.toLowerCase();
    if (_AUX[w]) return "助动词 / 情态动词";
    if (_DET[w]) return "冠词 / 限定词";
    if (_PREP[w]) return "介词";
    if (_CONJ[w]) return "连词";
    if (_PRON[w]) return "代词";
    if (/ingly$/.test(w) || /ly$/.test(w)) return "副词";
    if (/(tion|sion|ness|ment|ity|er|or|age|ance|ence|th)$/.test(w)) return "名词";
    if (/ing$/.test(w)) return "动词（现在分词）";
    if (/ed$/.test(w)) return "动词（过去式/过去分词）";
    if (/(ful|ous|ive|able|ible|less|ic|ical)$/.test(w)) return "形容词";
    if (/(ate|ize|ise|en)$/.test(w)) return "动词";
    return "单词";
  }
  /* 迷你词典：给常见词配 词性解释 + 例句 + 派生/同反义词 + 儿童化小贴士 */
  var _WDICT = {
    "run":      { pos: "动词", ex: "I can run fast. 我能跑得很快。", derive: "running / runner（跑步的人）", syn: "jog / dash" },
    "dog":      { pos: "名词", ex: "The dog is my friend. 小狗是我的朋友。", derive: "doggy（小狗）", syn: "puppy" },
    "wild":     { pos: "形容词", ex: "Wild animals live in the forest. 野生动物住在森林里。", derive: "wildlife（野生动物）/ wilderness（荒野）", ant: "tame（驯养的）" },
    "cold":     { pos: "形容词", ex: "The ice is cold. 冰是凉的。", derive: "coldly（冷漠地）/ coldness（寒冷）", syn: "cool / chilly", ant: "hot" },
    "snow":     { pos: "名词/动词", ex: "Snow is white. 雪是白色的。", derive: "snowy（下雪的）/ snowman（雪人）" },
    "come":     { pos: "动词", ex: "Come here, please. 请到这里来。", derive: "coming / came（过去式）", syn: "arrive", ant: "go / leave" },
    "give":     { pos: "动词", ex: "Give me a hand. 帮我一把。", derive: "giving / gave / given", syn: "hand / offer" },
    "love":     { pos: "动词/名词", ex: "I love my family. 我爱我的家人。", derive: "loving（爱的）/ lovely（可爱的）", syn: "like / enjoy", ant: "hate" },
    "make":     { pos: "动词", ex: "Let's make a snowman. 我们来堆雪人吧。", derive: "making / made / maker（制作者）", syn: "build / create" },
    "beautiful":{ pos: "形容词", ex: "The flowers are beautiful. 这些花真漂亮。", derive: "beauty（美丽）/ beautifully（美丽地）", syn: "pretty / lovely", ant: "ugly" },
    "water":    { pos: "名词/动词", ex: "I drink water every day. 我每天喝水。", derive: "watery（水汪汪的）/ watermelon（西瓜）", syn: "liquid" },
    "sleep":    { pos: "动词/名词", ex: "I sleep at night. 我晚上睡觉。", derive: "sleeping / sleepy（困的）/ slept（过去式）", ant: "wake" },
    "night":    { pos: "名词", ex: "The moon shines at night. 月亮在夜里发光。", derive: "tonight（今晚）/ goodnight（晚安）", ant: "day" },
    "day":      { pos: "名词", ex: "The sun is bright in the day. 白天太阳很亮。", derive: "today / daytime / daily（每日的）" },
    "long":     { pos: "形容词", ex: "I have a long rope. 我有一根长绳子。", derive: "length（长度）/ lengthen（加长）", syn: "big in length", ant: "short" },
    "fast":     { pos: "形容词/副词", ex: "The horse runs fast. 马跑得很快。", derive: "fastness", syn: "quick / quickly", ant: "slow" },
    "big":      { pos: "形容词", ex: "An elephant is big. 大象很大。", derive: "bigness", syn: "large / huge", ant: "small / little" },
    "small":    { pos: "形容词", ex: "A mouse is small. 老鼠很小。", derive: "smallness", syn: "little / tiny", ant: "big" },
    "house":    { pos: "名词", ex: "We live in a house. 我们住在一栋房子里。", derive: "housework（家务）/ greenhouse（温室）", syn: "home" },
    "world":    { pos: "名词", ex: "We live in this world together. 我们一同生活在这个世界上。", derive: "worldwide（全世界的）/ world-famous（闻名世界的）" },
    "walk":     { pos: "动词/名词", ex: "I walk to school. 我走路去上学。", derive: "walking / walker（行人）", syn: "step", ant: "run" },
    "angry":    { pos: "形容词", ex: "Don't be angry. 别生气。", derive: "angrily（生气地）/ anger（愤怒）", syn: "mad", ant: "happy" },
    "happy":    { pos: "形容词", ex: "I am happy today. 我今天很开心。", derive: "happily（开心地）/ happiness（幸福）", syn: "glad / joyful", ant: "sad" },
    "help":     { pos: "动词/名词", ex: "Can you help me? 你能帮我吗？", derive: "helpful（有用的）/ helping", syn: "aid" },
    "friend":   { pos: "名词", ex: "She is my good friend. 她是我的好朋友。", derive: "friendly（友好的）/ friendship（友谊）" },
    "brave":    { pos: "形容词", ex: "The brave boy saved the cat. 勇敢的男孩救了猫。", derive: "bravely（勇敢地）/ bravery（勇敢）", ant: "cowardly" },
    "know":     { pos: "动词", ex: "I know the answer. 我知道答案。", derive: "knowing / known", syn: "understand" },
    "see":      { pos: "动词", ex: "I can see the stars. 我能看见星星。", derive: "seeing / saw / seen", syn: "look at / watch" },
    "want":     { pos: "动词", ex: "I want an apple. 我想要一个苹果。", derive: "wanting / wanted", syn: "wish / would like" }
  };
  function _wordCard(base) {
    var d = _WDICT[base];
    if (!d) return "";
    var h = '<div class="lk-gram">';
    h += '<span class="g-t">' + esc(d.pos) + "</span> 看看例句就懂了 ↓";
    h += '<div class="g-ex">' + esc(d.ex) + "</div>";
    if (d.derive) h += '<div class="g-more">🧩 派生：' + esc(d.derive) + "</div>";
    if (d.syn) h += '<div class="g-more">🔄 近义：' + esc(d.syn) + "</div>";
    if (d.ant) h += '<div class="g-more">⚖️ 反义：' + esc(d.ant) + "</div>";
    h += "</div>";
    return h;
  }
  function _grammarHint(text, isWord) {
    if (isWord) {
      var single = text.split(/\s+/).length === 1;
      if (!single) return '<div class="lk-gram"><span class="g-t">短语</span> 两个词搭配在一起用，注意中间的介词哦，像 "look at"、"get up"。</div>';
      var pos = _posGuess(text);
      var card = _wordCard(_normWord(text).toLowerCase());
      if (card) return card;
      var ex = {
        "名词": '用来叫出人、动物或东西的名字，比如 "a book"（一本书）。',
        "动词": "表示做的动作，比如 run（跑）、eat（吃）。",
        "形容词": "用来形容人或东西是什么样，比如 big（大的）、beautiful（漂亮的）。",
        "副词": "说明动作怎么发生，比如 quickly（快速地）。",
        "介词": "表示位置关系的小词，比如 in（在…里）、on（在…上）。",
        "助动词 / 情态动词": "帮助主要动词组成句子的小帮手，比如 can、will。",
        "冠词 / 限定词": "放在名词前的小词，比如 a、the。",
        "连词": "用来把两个部分连起来，比如 and（和）、but（但是）。",
        "代词": "代替名字的词，比如 I、you、he。",
        "动词（现在分词）": "动词加了 -ing，表示正在做，比如 running（正在跑）。",
        "动词（过去式/过去分词）": "动词加了 -ed，表示过去发生，比如 walked（走过了）。"
      }[pos] || "这是个有意思的单词，查一查它什么意思吧！";
      return '<div class="lk-gram"><span class="g-t">' + esc(pos) + "</span> " + esc(ex) + "</div>";
    }
    /* 句子：时态 + 句型 */
    var words = (text.match(/[A-Za-z']+/g) || []).map(function (w) { return w.toLowerCase(); });
    var tense = "";
    var hasAux = words.some(function (w) { return _AUX[w]; });
    var hasBe = words.some(function (w) { return _AUX[w] && w !== "do" && w !== "does" && w !== "did"; });
    var hasHave = words.some(function (w) { return w === "have" || w === "has" || w === "had"; });
    var hasWill = words.some(function (w) { return w === "will" || w === "would" || w === "shall"; });
    var baseS = words.filter(function (w) { return /ing$/.test(w); }).length;
    if (hasWill) tense = "一般将来";
    else if (hasHave && baseS) tense = "现在完成";
    else if (words.some(function (w) { return /ed$/.test(w); })) tense = "一般过去";
    else if (hasBe || hasHave) tense = "一般现在";
    else tense = (words.length ? "一般现在" : "");
    var type = "陈述句";
    var first = words[0];
    if (first && (_WH.some(function (r) { return r.test(first); }))) type = "特殊疑问句";
    else if (first === "do" || first === "does" || first === "did" || (_AUX[first] && !/ed$/.test(words[1] || ""))) type = "一般疑问句";
    else if (words.indexOf("not") >= 0 && hasAux) type = "否定句";
    else if (first === "there") type = "there be 存在句";
    var parts = [];
    if (tense) parts.push("时态：" + tense);
    if (type) parts.push("句型：" + type);
    if (hasAux) parts.push("含助动词");
    return '<div class="lk-gram"><span class="g-t">语法</span> ' + esc(parts.join(" · ")) + "</div>";
  }

  /* 划词查询浮层：单词 → 音标 + 中文；短语/句子 → 中文翻译 */
  var _lookupTransCache = {};
  function _lookupShow(text, anchorRect, isWord, wordForm, ipa) {
    var root = document.querySelector(".rw-read2 .lookup-card");
    if (!root) return;
    if (_lookupTransCache[text]) {
      _lookupRender(text, anchorRect, isWord, wordForm, ipa, _lookupTransCache[text]);
    } else {
      root.innerHTML = '<div class="lk-tip">查询中…</div>';
      root.style.display = "block";
      var x = anchorRect ? Math.min(anchorRect.left + window.scrollX, window.innerWidth - 300) : 100;
      root.style.left = Math.max(0, x) + "px";
      root.style.top = (anchorRect ? (anchorRect.bottom + window.scrollY + 8) : 200) + "px";
      loadTranslation(text, function (zh) {
        _lookupTransCache[text] = zh;
        _lookupRender(text, anchorRect, isWord, wordForm, ipa, zh);
      }, function () {
        root.innerHTML = '<div class="lk-tip">翻译失败，请重试</div>';
      });
    }
  }
  function _lookupRender(text, rect, isWord, wordForm, ipa, zh) {
    var root = document.querySelector(".rw-read2 .lookup-card");
    if (!root) return;
    var h = '<div class="lk-hd">';
    if (isWord) {
      h += '<span class="lk-wd">' + esc(wordForm) + '</span>';
      if (ipa) h += '<span class="lk-ipa">' + esc(ipa) + '</span>';
    } else {
      h += '<span class="lk-sentence">' + esc(text.length > 80 ? text.slice(0, 80) + "…" : text) + '</span>';
    }
    h += '<span class="lk-close" title="关闭">✕</span>';
    h += '</div>';
    h += '<div class="lk-trans">' + esc(zh) + '</div>';
    h += _grammarHint(text, isWord);
    h += '<div class="lk-acts">';
    h += spkBtn(text);
    if (isWord) h += '<button class="btn lk-add" type="button">📌 收藏</button>';
    h += '</div>';
    root.innerHTML = h;
    root.style.display = "block";
    var y = (rect ? (rect.bottom + window.scrollY + 8) : (window.scrollY + 100));
    var x = (rect ? Math.min(rect.left + window.scrollX, window.innerWidth - 280) : 100);
    root.style.left = Math.max(0, x) + "px";
    root.style.top = Math.max(window.scrollY + 20, y) + "px";
    var close = root.querySelector(".lk-close");
    if (close) close.onclick = function () { root.style.display = "none"; };
    var add = root.querySelector(".lk-add");
    if (add) add.onclick = function () {
      add.textContent = "✓ 已收藏";
      add.classList.add("ok");
    };
  }

  /* 全文翻译 + 划词查询：一次性绑定到当前 root 内的 .rw-read2 元素 */
  function _bindRead(root) {
    root.querySelectorAll(".rw-read2").forEach(function (rd) {
      if (rd._bound) return;
      rd._bound = 1;
      var raw = rd.querySelector(".rw-read2-body").textContent || "";
      /* 全文朗读 + 逐词高亮 */
      var rdClean = rd.getAttribute("data-clean") || "";
      var rdOffs = null;
      try { rdOffs = JSON.parse(rd.getAttribute("data-offs") || "[]"); } catch (e) { rdOffs = null; }
      var wordSpans = null;
      function gatherSpans() {
        if (wordSpans) return wordSpans;
        wordSpans = Array.prototype.slice.call(rd.querySelectorAll(".rw-w"));
        return wordSpans;
      }
      function highlightWord(idx) {
        if (!rdOffs || !rdOffs.length) return;
        var span = null;
        for (var k = rdOffs.length - 1; k >= 0; k--) {
          if (rdOffs[k][0] <= idx) { span = gatherSpans()[k]; break; }
        }
        gatherSpans().forEach(function (s) { s.classList.remove("hl"); });
        if (span) span.classList.add("hl");
      }
      function clearHighlight() {
        if (wordSpans) wordSpans.forEach(function (s) { s.classList.remove("hl"); });
      }
      rd.addEventListener("click", function (e) {
        var rb = e.target.closest(".rw-read-all");
        if (rb) {
          if (rb.classList.contains("reading")) {
            /* 再点一次停止 */
            try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch (err) {}
            rb.classList.remove("reading");
            rb.textContent = "🔊 全文朗读";
            clearHighlight();
            return;
          }
          var voiceKey = currentVoice || "alan";
          rb.classList.add("reading");
          rb.textContent = "🔊 朗读中…";
          speakWithVoice(rdClean || raw, voiceKey, function () {
            rb.classList.remove("reading");
            rb.textContent = "🔊 全文朗读";
            clearHighlight();
          }, function (ci) {
            highlightWord(ci);
          });
          return;
        }
        var b = e.target.closest(".rw-tr-all");
        if (!b) return;
        /* 已加载：切换中文显隐 */
        if (rd.getAttribute("data-tr-loaded") === "1") {
          rd.classList.toggle("rw-tr-off");
          b.textContent = rd.classList.contains("rw-tr-off") ? "显示翻译" : "隐藏翻译";
          return;
        }
        /* 首次：逐句把中文插到英文句子的正下方（句内联，不集中在结尾）。
           zh 作为 .rw-sent 的兄弟节点插入，sp.textContent 不受污染。 */
        var sentEls = rd.querySelectorAll(".rw-sent");
        var queue = [];
        for (var si2 = 0; si2 < sentEls.length; si2++) {
          var sp = sentEls[si2];
          var en = sp.textContent.replace(/\s+/g, " ").trim();
          if (!en || !/[A-Za-z]/.test(en)) continue;
          var zh = document.createElement("span");
          zh.className = "rw-tr-zh";
          zh.textContent = "翻译中…";
          sp.parentNode.insertBefore(zh, sp.nextSibling);
          queue.push([en, zh]);
        }
        if (!queue.length) return;
        rd.setAttribute("data-tr-loaded", "1");
        b.textContent = "隐藏翻译";
        /* 串行逐句翻译，保持上下对应；失败置占位 */
        var qi = 0;
        (function nextSent() {
          if (qi >= queue.length) return;
          var item = queue[qi];
          loadTranslation(item[0], function (zhText) {
            item[1].textContent = zhText;
            qi++; nextSent();
          }, function () {
            item[1].innerHTML = '<span class="rw-tr-err">翻译失败</span>';
            qi++; nextSent();
          });
        })();
      });
      /* 划词：mouseup 检测选区 */
      rd.addEventListener("mouseup", function () {
        var sel = window.getSelection();
        if (!sel || sel.isCollapsed) return;
        var text = sel.toString().trim();
        if (!text) return;
        if (text.length > 300) return;
        var range = sel.getRangeAt(0);
        var rect = range.getBoundingClientRect();
        if (rect.width < 3 && rect.height < 3) return;
        /* 判断是单词还是句子 */
        var isWord = /^[A-Za-z][A-Za-z' -]{0,30}$/.test(text) && text.split(/\s+/).length <= 3;
        var ipa = "", wordForm = text;
        if (isWord && text.split(/\s+/).length === 1) {
          wordForm = _normWord(text);
          ipa = simpleIPA(wordForm);
        } else if (isWord) {
          /* 短词组：拼合成完整音节的每个词 IPA */
          wordForm = text;
          ipa = text.split(/\s+/).map(function (w) { return simpleIPA(_normWord(w)); }).join(" ");
        } else {
          /* 句子：从原文中定位所属句子，用于显示上下文 */
          var preLen = "";
          try {
            var p = range.cloneRange();
            p.selectNodeContents(rd.querySelector(".rw-read2-body"));
            p.setEnd(range.startContainer, range.startOffset);
            preLen = p.toString();
          } catch (err) {}
          var idx = preLen.length;
          var sent = _sentenceAt(raw, idx);
          if (sent && sent.length > text.length + 5 && sent.indexOf(text) >= 0) text = sent;
        }
        _lookupShow(text, rect, isWord, wordForm, ipa);
      });
    });
    /* 点击页外关闭浮层 */
    document.addEventListener("click", function (e) {
      var card = document.querySelector(".rw-read2 .lookup-card");
      if (!card || card.style.display === "none") return;
      if (card.contains(e.target)) return;
      if (e.target.closest(".rw-read2")) return;
      card.style.display = "none";
    }, true);
  }

  function enText(st) {
    LESSONS = {};
    var dl = (D.dialogues || []).filter(pass(st, ["scene", "function", "patterns"]));
    var ps = (D.passages || []).filter(pass(st, ["name", "genre", "text", "topic"]));
    var bidx = {};
    (D.books || []).forEach(function (b, i) { bidx[b] = i; });
    var units = {}, order = [];
    // 单元主键用 unit_no（占位的 "Unit 3" 已换成真实名，同单元不会再散成两组）
    function slot(x) {
      var k = (x.book || "") + "#" + (x.unit_no ? "U" + x.unit_no : x.unit || "");
      if (!units[k]) {
        units[k] = { book: x.book || "", unit: x.unit || "",
                     unit_no: x.unit_no || 0, dlg: [], pas: [] };
        order.push(k);
      }
      return units[k];
    }
    dl.forEach(function (x) { slot(x).dlg.push(x); });
    ps.forEach(function (x) { slot(x).pas.push(x); });
    order.sort(function (a, b) {
      var A = units[a], B = units[b];
      return ((bidx[A.book] || 0) - (bidx[B.book] || 0)) ||
        ((A.unit_no ? 0 : 1) - (B.unit_no ? 0 : 1)) ||
        ((A.unit_no || 0) - (B.unit_no || 0)) ||
        String(A.unit).localeCompare(String(B.unit), "zh");
    });
    function uname(u) {
      return esc(u.book) + " · " +
        (u.unit_no ? "第" + u.unit_no + "单元 · " : "") +
        esc(u.unit || "（未标单元）");
    }
    // 搜索/筛选时自动展开各课，否则默认折叠（课太多，全铺开找不到北）
    var filtering = !!(st.q || st.book !== "all" || (st.extra && st.extra !== "all"));
    // 生词本（顶部固定位）：不依赖 LESSONS 顺序
    var h = renderWordBook();
    // 课文目录：按册 → 单元列出，点单元直达
    h += '<details class="toc"' +
      (order.length && filtering ? " open" : "") +
      '><summary>课文目录（' + (dl.length + ps.length) + " 课 · " + order.length +
      " 个单元 · 点单元直达）</summary><div class=\"toc-b\">" +
      order.map(function (k, i) {
        return '<div class="toc-u"><a class="ubook" href="#eu' + i + '">' +
          uname(units[k]) + "</a></div>";
      }).join("") + "</div></details>";
    order.forEach(function (k, i) {
      var u = units[k];
      h += '<div class="unit" id="eu' + i + '"><div class="top"><span class="name">' +
        uname(u) + "</span>" +
        '<span class="tag d1">对话 ' + u.dlg.length + " · 短文 " + u.pas.length + "</span>" +
        '<span class="u-fold">全部展开</span></div>';
      u.dlg.forEach(function (x) { h += enLesson(x, "dlg", filtering); });
      u.pas.forEach(function (x) { h += enLesson(x, "pas", filtering); });
      h += "</div>";
    });
    // 单元地图四关灯状态（进度条已由 renderUnitMap 算过，这里刷一次确保与 UNITMAP 一致）
    setTimeout(function () { refreshUnitMapStages(); checkBadgeUnlock(); }, 0);
    // 单元地图 + 每日 3 分钟：这两块要 LESSONS 全部注册后才能算候选
    // 放在末尾再插到顶部，保证 renderToday/pickTodayItems 拿到完整 LESSONS
    var top = renderToday() + renderUnitMap(order, units, uname) + renderBadges();
    return top + h;
  }

  /* 一课 = 一个折叠的学习中心 */
  function enLesson(x, type, filtering) {
    var key = lessonKey(x, type);
    LESSONS[key] = { data: x, type: type };
    var name = type === "dlg" ? (x.scene || x.title || "对话") : (x.name || "短文");
    var lines = lessonLines(x, type);
    var peek = lines.length ? lines[0] : "";
    if (peek.length > 40) peek = peek.slice(0, 40) + "…";
    var s = '<details class="lesson" data-lkey="' + esc(key) + '"' +
      (filtering ? " open" : "") + "><summary>" +
      '<span class="tag d1">' + (type === "dlg" ? "对话" : "短文") + "</span>" +
      '<span class="name">' + esc(name) + "</span>" +
      (x.function ? '<span class="tag">' + esc(x.function) + "</span>" : "") +
      (x.genre ? '<span class="tag">' + esc(x.genre) + "</span>" : "") +
      '<span class="peek">' + esc(peek) + "</span>" +
      '<span class="lstars" data-stars="' + esc(key) + '">' +
        starStr(starCount(key)) + "</span>" +
      "</summary>";
    s += '<div class="lbody">' +
      '<div class="htabs">' +
      [["text", "📖 课文"], ["preview", "🎯 预习"], ["vocab", "📗 词汇"],
       ["ipa", "🔤 音标"], ["phonics", "🧩 拼读"], ["grammar", "📐 语法"],
       ["exercise", "✏️ 练习"], ["game", "🎮 游戏"], ["review", "🔁 复习"],
       ["extend", "🌱 拓展"]]
        .map(function (t, i) {
          return '<span class="htab' + (i === 0 ? " on" : "") + '" data-p="' +
            t[0] + '">' + t[1] + "</span>";
        }).join("") + "</div>" +
      '<div class="hpanel on" data-p="text">' +
        '<div class="tl-bar"><button class="btn zh-toggle" type="button" ' +
        'title="显示/隐藏中文对照">🌐 中英对照</button></div>' +
        (type === "dlg" ? enDialogue(x) : enPassage(x)) + "</div>";
    ["preview", "vocab", "ipa", "phonics", "grammar", "exercise", "game", "review", "extend"]
      .forEach(function (p) {
        s += '<div class="hpanel" data-p="' + p + '"></div>';
      });
    return s + "</div></details>";
  }

  /* 惰性板块：第一次切到该 tab 才生成 */
  function buildPanel(el, p, x, type) {
    var h = "";
    if (p === "preview") h = hubPreview(x, type);
    else if (p === "vocab") h = hubVocab(x, type);
    else if (p === "ipa") h = hubIpa(x, type);
    else if (p === "phonics") h = hubPhonics(x);
    else if (p === "grammar") h = hubGrammar(x, type);
    else if (p === "exercise") h = hubExercise(x, type);
    else if (p === "game") h = hubGame(x, type);
    else if (p === "review") h = hubReview(x, type);
    else if (p === "extend") h = hubExtend(x);
    el.innerHTML = h;
    el._built = true;
  }

  /* 预习：目标 + 生词 + 句型 + 带着问题读 */
  function hubPreview(x, type) {
    var words = lessonWords(x, type);
    var goals = [];
    if (type === "dlg") {
      if (x.function) goals.push("会用英语" + x.function);
      if ((x.patterns || []).length) goals.push("掌握 " + x.patterns.length + " 个句型");
      goals.push("能分角色朗读、表演这段对话");
    } else {
      goals.push("读懂这篇" + (x.genre || "短文") + "，能回答理解题");
      if ((x.keypoints || []).length) goals.push("留意：" + x.keypoints.slice(0, 2).join("、"));
    }
    var step = 1;
    var h = '<p class="small">上课前花 5 分钟：听一听、看一看、想一想。</p>';
    h += '<div class="pstep"><b>' + ["①", "②", "③", "④"][0] + " 学习目标</b><ul class=\"pts\">" +
      goals.map(function (g) { return "<li>" + esc(g) + "</li>"; }).join("") + "</ul></div>";
    step++;
    if (words.length) {
      h += '<div class="pstep"><b>② 生词先认识（点 🔊 听发音，点 ⭐ 收进生词本）</b>' +
        (words.own ? "" : '<span class="small">（本课未标注生词，先学本单元这些词）</span>') +
        '<div class="words">' + words.map(function (w) {
          var k = wbKey(x.book, w.word);
          return '<span class="wb">' + spkBtn(w.word) + esc(w.word) +
            (w.ipa ? ' <i>' + esc(w.ipa) + "</i>" : "") +
            (w.zh ? ' <em class="wzh">' + esc(w.zh) + "</em>" : "") +
            '<button class="btn wb-toggle' + (WORDBOOK[k] ? " on" : "") +
              '" data-wbkey="' + esc(k) + '" data-book="' + esc(x.book || "") +
              '" data-word="' + esc(w.word) + '" data-ipa="' + esc(w.ipa || "") +
              '" data-zh="' + esc(w.zh || "") +
              '" title="收进生词本">' + (WORDBOOK[k] ? "★" : "⭐") + '</button></span>';
        }).join("") + "</div></div>";
      step++;
    }
    var pats = type === "dlg" ? (x.patterns || []) : [];
    if (pats.length) {
      h += '<div class="pstep"><b>' + ["①", "②", "③", "④"][step - 1] + " 句型先睹为快</b>" +
        pats.map(function (p) { return '<div class="pat">' + hl(String(p)) + "</div>"; }).join("") +
        "</div>";
      step++;
    }
    var qs = type === "dlg"
      ? ["谁在说话？", "他们在说什么事？", "找出打招呼或提问的句子。"]
      : ["这篇" + (x.genre || "短文") + "讲了谁、什么事？", "事情是按什么顺序写的？",
         "把不认识的词圈出来。"];
    h += '<div class="pstep"><b>' + ["①", "②", "③", "④"][step - 1] + " 带着问题读</b>" +
      '<ul class="pts">' + qs.map(function (q) { return "<li>" + esc(q) + "</li>"; }).join("") +
      "</ul></div>";
    return h;
  }

  /* ---- 全文朗读（多角色多音色）----
     将不同角色映射到不同 TTS 音色，逐句播放，高亮当前句。 */
  var VOICE_ROSTER = ["alan", "jenny", "amy", "cori"];
  var _readAllTimer = null;
  function readAllDialogue(btn) {
    var panel = btn.closest(".hpanel") || btn.closest(".les-item") || btn.parentElement;
    if (!panel) return;
    var turns = panel.querySelectorAll(".turn[data-speaker]");
    if (!turns.length) return;
    /* 正在朗读 → 停止 */
    if (btn.classList.contains("reading")) {
      stopReadAll();
      return;
    }
    /* 角色映射到音色 */
    var speakerMap = {}, next = 0;
    turns.forEach(function (t) {
      var sp = t.getAttribute("data-speaker") || "";
      if (!(sp in speakerMap)) {
        speakerMap[sp] = VOICE_ROSTER[next % VOICE_ROSTER.length];
        next++;
      }
    });
    btn.classList.add("reading");
    btn.textContent = "⏹ 停止朗读";
    var i = 0;
    function playNext() {
      if (i >= turns.length) { stopReadAll(); return; }
      var turn = turns[i];
      [].forEach.call(turns, function (t) { t.classList.remove("reading"); });
      turn.classList.add("reading");
      turn.scrollIntoView({ block: "nearest", behavior: "smooth" });
      var line = turn.querySelector(".spk");
      var text = line ? line.textContent : "";
      var sp = turn.getAttribute("data-speaker") || "";
      var voiceKey = speakerMap[sp] || "alan";
      /* 逐词高亮：将 .spk 内容拆成 <span class="tw"> 词 */
      var wordSpans = [];
      if (line) {
        var orig = line.textContent;
        var html = "";
        var idx = 0;
        orig.replace(/(\S+)/g, function (m) {
          var off = orig.indexOf(m, idx);
          /* 空格/标点保留 */
          if (off > idx) html += esc(orig.slice(idx, off));
          html += '<span class="tw" data-i="' + idx + '">' + esc(m) + '</span>';
          idx = off + m.length;
          return m;
        });
        if (idx < orig.length) html += esc(orig.slice(idx));
        line.innerHTML = html;
        wordSpans = [].slice.call(line.querySelectorAll(".tw"));
      }
      speakWithVoice(text, voiceKey, function () {
        /* 恢复原文 */
        if (line) line.textContent = text;
        i++;
        _readAllTimer = setTimeout(playNext, 400);
      }, function (charIdx, charLen) {
        /* 逐词高亮：找到 charIndex 对应的 .tw */
        wordSpans.forEach(function (s) { s.classList.remove("on"); });
        var wi = parseInt(wordSpans[0] ? wordSpans[0].getAttribute("data-i") : "0", 10);
        for (var j = 0; j < wordSpans.length; j++) {
          var si = parseInt(wordSpans[j].getAttribute("data-i"), 10);
          if (si <= charIdx) wi = j;
        }
        if (wordSpans[wi]) {
          wordSpans[wi].classList.add("on");
          /* 滚动到可见 */
          var rect = wordSpans[wi].getBoundingClientRect();
          if (rect.top < 60 || rect.bottom > window.innerHeight - 20) {
            wordSpans[wi].scrollIntoView({ block: "nearest", behavior: "smooth" });
          }
        }
      });
    }
    playNext();
  }
  function stopReadAll() {
    if (_readAllTimer) { clearTimeout(_readAllTimer); _readAllTimer = null; }
    if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) {} }
    stopTtsAudio();
    var btn = document.querySelector(".read-all-dlg.reading");
    if (btn) { btn.classList.remove("reading"); btn.textContent = "🔊 全文朗读（分角色音色）"; }
    [].forEach.call(document.querySelectorAll(".turn.reading"), function (t) {
      t.classList.remove("reading");
      /* 恢复原文（去掉 .tw 词span） */
      var spk = t.querySelector(".spk");
      if (spk && spk.querySelector(".tw")) spk.textContent = spk.textContent;
    });
    [].forEach.call(document.querySelectorAll(".tw.on"), function (s) {
      s.classList.remove("on");
    });
  }
  /* 用指定音色朗读一段文本（浏览器 speechSynthesis，支持回调） */
  function speakWithVoice(text, voiceKey, onEnd, onWord) {
    text = String(text || "").trim();
    if (!text) { if (onEnd) onEnd(); return; }
    var meta = VOICE_META[voiceKey] || VOICE_META.alan;
    if (window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel();
        var u = new SpeechSynthesisUtterance(text);
        u.lang = meta.lang;
        u.rate = 0.95;
        u.pitch = meta.pitch;
        var picked = pickBrowserVoice(meta.lang);
        if (picked) u.voice = picked;
        if (onEnd) u.onend = onEnd;
        if (onWord) u.onboundary = function (e) {
          if (e.name === "word") onWord(e.charIndex, e.charLength || 0);
        };
        window.speechSynthesis.speak(u);
        return;
      } catch (e) {}
    }
    /* 降级：Google Translate 或无 TTS */
    if (typeof window.ttsSpeak === "function") {
      try { window.ttsSpeak(text, { lang: meta.lang }); } catch (e) {}
    }
    /* 无回调支持时模拟延时 */
    if (onEnd) setTimeout(onEnd, Math.max(1500, text.length * 60));
  }

  /* ---- 录音跟读打分：用浏览器原生 SpeechRecognition（Chrome/Edge）----
     识别英文，去掉标点/空格后与目标词比对；对得上 → 得 ★ 点亮"跟读"关。 */
  function hasSpeechRecognition() {
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  }
  var recSR = null, recState = null;
  function startRecognition(target, onResult) {
    if (!hasSpeechRecognition()) {
      onResult({ ok: false, text: "", why: "不支持语音识别" });
      return;
    }
    var C = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (recSR) { try { recSR.abort(); } catch (e) {} }
    var sr = new C();
    recSR = sr;
    sr.lang = "en-US";
    sr.interimResults = false;
    sr.maxAlternatives = 3;
    var done = false;
    function finish(res) {
      if (done) return;
      done = true;
      onResult(res);
    }
    sr.onresult = function (e) {
      var alt = [];
      try {
        for (var i = 0; i < e.results[0].length; i++) alt.push(e.results[0][i].transcript);
      } catch (err) {}
      var txt = alt.join(" ").toLowerCase().replace(/[^a-z\s'-]/g, "");
      var want = String(target).toLowerCase().replace(/[^a-z\s'-]/g, "");
      var ok = alt.some(function (a) {
        return a.toLowerCase().replace(/[^a-z\s'-]/g, "") === want;
      });
      finish({ ok: ok, text: alt[0] || "", target: target });
    };
    sr.onerror = function (e) {
      finish({ ok: false, text: "", why: e.error === "no-speech"
        ? "没听清，再大声说一次" : ("识别失败：" + e.error) });
    };
    sr.onend = function () {
      finish({ ok: false, text: "", why: "请说一次单词" });
    };
    try { sr.start(); } catch (e) { finish({ ok: false, text: "", why: "开始失败" }); }
  }

  /* 音标：本课生词 IPA 对照表；每行带 🔊 跟读打分（浏览器支持时） */
  function hubIpa(x, type) {
    var words = lessonWords(x, type);
    if (!words.length) return '<div class="empty">这一课没有生词</div>';
    var sr = hasSpeechRecognition();
    return '<p class="small">三步跟读：先看音标拼一拼，再点 🔊 听，最后自己读三遍。</p>' +
      '<p class="small rec-tip">' +
        (sr ? '点 <b>🎤 打分</b> 让浏览器听你说，说对了得一颗 ★。' :
               '浏览器不支持语音识别（换 Chrome/Edge），只能听示范。') + '</p>' +
      (words.own ? "" : '<p class="small">（本课未标注生词，列出本单元词汇）</p>') +
      '<table class="tbl ipa-t"><tr><th>单词</th><th>音标</th><th>词性</th><th>中文</th><th>读</th><th>跟读</th></tr>' +
      words.map(function (w) {
        return "<tr><td><b>" + esc(w.word) + "</b></td><td>" + esc(w.ipa || "—") +
          "</td><td>" + esc(w.pos || "—") + "</td><td>" + esc(w.zh || "—") +
          "</td><td>" + spkBtn(w.word) + "</td><td>" +
          (sr
            ? '<button class="btn rec-btn" data-rec="' + esc(w.word) + '">🎤 打分</button>'
              + '<span class="rec-res"></span>'
            : '<span class="small muted">—</span>') +
          "</td></tr>";
      }).join("") + "</table>" +
      '<p class="small rec-all"><button class="btn rec-all-btn" data-recall="1">🎤 全部跟读一遍</button>' +
      '<span class="small">（逐个念，全对得 ★ 跟读关）</span></p>';
  }

  /* 自然拼读：本单元的字母组合发音（构建期按单元切片） */
  function hubPhonics(x) {
    var hub = unitHubOf(x);
    var rows = hub ? hub.phonics : [];
    if (!rows.length) return '<div class="empty">本单元没有安排自然拼读内容</div>';
    return '<p class="small">见词能读、听音能写：先听例词，再自己拼。</p>' +
      rows.map(function (p) {
        var h = '<div class="ph-row"><span class="ph-l">' + esc(p.letters) + "</span>" +
          '<span class="ph-s">' + esc(p.sound) + "</span>" +
          '<span class="words">' + (p.examples || []).map(function (w) {
            return '<span class="wb">' + spkBtn(w) + esc(w) + "</span>";
          }).join("") + "</span></div>";
        if (p.chant) {
          h += '<div class="chant">' + spkBtn(p.chant) +
            '<span class="spk">' + esc(p.chant) + "</span></div>";
        }
        return h;
      }).join("");
  }

  /* 语法：本课语言点 + 本单元语法条目（句型/规则/例句） */
  function hubGrammar(x, type) {
    var own = type === "dlg" ? (x.grammar_points || []) : (x.keypoints || []);
    var hub = unitHubOf(x);
    var rows = hub ? hub.grammar : [];
    var h = "";
    if (own.length) h += pts(own, "本课语言点");
    if (rows.length) {
      h += '<p class="small">本单元语法</p>' + rows.map(function (g) {
        var s = '<div class="g-card"><div class="g-head"><b>' + esc(g.point) + "</b></div>";
        if (g.pattern) s += '<div class="pat">' + hl(g.pattern) + "</div>";
        if (g.rule) s += '<p class="grule">' + esc(g.rule) + "</p>";
        if (g.examples && g.examples.length) {
          s += '<ul class="pts">' + g.examples.map(function (e) {
            return "<li>" + spkBtn(e.en) + '<span class="spk">' + esc(e.en) + "</span>" +
              (e.zh ? ' <span class="gzh">' + esc(e.zh) + "</span>" : "") + "</li>";
          }).join("") + "</ul>";
        }
        return s + "</div>";
      }).join("");
    }
    return h || '<div class="empty">本单元暂无语法条目</div>';
  }

  /* 练习：选词填空（从课文原句抠词）+ 理解题 / 句型替换说。
     @CONSTRAINT 题目全部由教材原文机械生成，不编新内容。 */
  function hubExercise(x, type) {
    var words = lessonWords(x, type);
    var lines = lessonLines(x, type);
    var h = "";
    var items = [];
    lines.forEach(function (line) {
      words.forEach(function (w) {
        if (items.length >= 5) return;
        var re = new RegExp("\\b" + w.word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i");
        if (re.test(line) && items.every(function (it) { return it.word !== w.word; })) {
          items.push({ line: line, word: w.word });
        }
      });
    });
    if (items.length >= 2) {
      var pool = words.map(function (w) { return w.word; });
      if (pool.length < 3) {
        (D.vocab || []).forEach(function (v) {
          if (v.book === x.book && (v.unit_no || 0) === (x.unit_no || 0) &&
              pool.indexOf(v.word) < 0) pool.push(v.word);
        });
      }
      h += '<p class="small">练习一 · 选词填空（全对得 ★）</p><div class="ex-fill">';
      items.forEach(function (it) {
        var opts = [it.word], guard = 0;
        while (opts.length < 3 && guard++ < 40) {
          var w = pool[Math.floor(Math.random() * pool.length)];
          if (opts.map(function (o) { return o.toLowerCase(); })
              .indexOf(w.toLowerCase()) < 0) opts.push(w);
        }
        shuffle(opts);
        var blanked = it.line.replace(
          new RegExp("\\b" + it.word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i"),
          "＿＿＿");
        h += '<div class="fq" data-a="' + esc(it.word) + '">' +
          '<div class="fl">' + spkBtn(it.line) + esc(blanked) + "</div>" +
          opts.map(function (o) {
            return '<span class="opt" data-w="' + esc(o) + '">' + esc(o) + "</span>";
          }).join("") + '<span class="fb"></span></div>';
      });
      h += "</div>";
    }
    if (type === "pas" && x.comprehension && x.comprehension.length) {
      h += '<p class="small">练习二 · 理解题（先自己想，再点开对答案）</p>' +
        x.comprehension.map(function (c) {
          return '<details class="aq"><summary>' + esc(c.q || c.question) + "</summary>" +
            '<div class="aa">' + esc(c.a || c.answer || "（回课文里找一找）") + "</div></details>";
        }).join("");
    } else if (type === "dlg" && (x.patterns || []).length) {
      h += '<p class="small">练习二 · 句型替换说：把高亮处换成自己想到的词，大声说 3 遍</p>' +
        x.patterns.slice(0, 4).map(function (p) {
          return '<div class="pat">' + spkBtn(String(p)) + hl(String(p)) + "</div>";
        }).join("");
    }
    h += hubCloze(x, type);
    return h || '<div class="empty">这一课暂时没有可自动生成的练习</div>';
  }

  /* 听力填词：把课文里的词挖空，点 🔊 听整句，从 3 个候选里选。
     与"练习一"的区别：练习一显示整句挖空 + 3 选 1；这里是听句子 → 填空，
     不看文字。全对得 ★（与练习一共用 fill 关，取一次即可）。 */
  function hubCloze(x, type) {
    var words = lessonWords(x, type);
    var lines = lessonLines(x, type);
    if (words.length < 2 || lines.length < 1) return "";
    // 挑 3 条句子，每条挖一个词
    var picks = [];
    var used = {};
    var pool = lines.slice();
    shuffle(pool);
    pool.forEach(function (line) {
      if (picks.length >= 3) return;
      words.forEach(function (w) {
        if (picks.length >= 3) return;
        if (used[w.word]) return;
        var re = new RegExp("\\b" + w.word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i");
        if (re.test(line) && line.length <= 90) {
          picks.push({ line: line, word: w.word, ipa: w.ipa });
          used[w.word] = 1;
        }
      });
    });
    if (picks.length < 2) return "";
    var other = words.map(function (w) { return w.word; });
    var h = '<p class="small">练习三 · 听力填词（先看挖空句，听一遍再选）</p>' +
            '<div class="ex-cloze">';
    picks.forEach(function (it) {
      var opts = [it.word];
      var guard = 0;
      while (opts.length < 3 && guard++ < 40) {
        var w = other[Math.floor(Math.random() * other.length)];
        if (opts.map(function (o) { return o.toLowerCase(); })
              .indexOf(w.toLowerCase()) < 0) opts.push(w);
      }
      shuffle(opts);
      var blanked = it.line.replace(
        new RegExp("\\b" + it.word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i"),
        "＿＿＿");
      h += '<div class="fq cloze" data-a="' + esc(it.word) + '">' +
        '<div class="fl"><span class="small">' + esc(blanked) + '</span></div>' +
        '<div class="cloze-ctl">' +
        '<button class="btn cloze-play" data-line="' + esc(it.line) +
          '" data-slow="0">🔊 正常</button>' +
        '<button class="btn cloze-play" data-line="' + esc(it.line) +
          '" data-slow="1">🐢 慢速</button>' +
        '</div>' +
        opts.map(function (o) {
          return '<span class="opt" data-w="' + esc(o) + '">' + esc(o) + "</span>";
        }).join("") + '<span class="fb"></span></div>';
    });
    h += "</div>";
    return h;
  }

  /* 游戏：拼词 / 句子排排队 / 中英对对碰，各得一颗 ★ */
  function hubGame(x, type) {
    var words = lessonWords(x, type);
    var lines = lessonLines(x, type);
    var singles = words.filter(function (w) { return /^[A-Za-z'-]{2,}$/.test(w.word); });
    var pairs = words.filter(function (w) { return w.zh; });
    var h = '<p class="small">每通关一个游戏得一颗 ★，星星存在这台设备上。</p>';
    if (singles.length >= 3) {
      h += gameShell("scramble", "🔤 拼词游戏", "看中文听发音，把字母排成单词");
    }
    if (lines.length >= 3) {
      h += gameShell("order", "🚂 句子排排队", "句子打乱了，按课文顺序点出来");
    }
    if (pairs.length >= 3) {
      h += gameShell("match", "🃏 中英对对碰", "英文和中文配成一对");
    }
    return h || '<div class="empty">这一课的内容还不够开局游戏</div>';
  }
  function gameShell(g, title, desc) {
    return '<div class="game" data-g="' + g + '"><div class="g-head"><b>' + title +
      '</b><span class="small">' + desc + '</span>' +
      '<button class="btn g-start">开始</button></div><div class="g-body"></div></div>';
  }

  /* 复习：会读 / 会说 / 会写 + 自评打星 */
  function hubReview(x, type) {
    var key = lessonKey(x, type);
    var rate = (STARS[key] && STARS[key].rate) || 0;
    var lines = lessonLines(x, type);
    var words = lessonWords(x, type);
    var h = '<p class="small">学完回头过一遍：会读、会说、会写，做到了就给自己打星。</p>';
    h += '<ul class="pts rv">' +
      "<li>🔊 我会读：" + spkBtn(lines.join(" ")) + "点这里把整课再听一遍，跟读 2 遍</li>" +
      '<li>🎭 我会说：打开右上角「中文对照」再关掉，遮住中文说英文；' +
        '也可以去「<a href="speak.html">开口说</a>」分角色演一演</li>' +
      '<li>✍️ 我会写：去「<a href="dictation.html">听写练习</a>」选 ' +
        esc(x.book || "") + "，听写本课 " + words.length + " 个生词</li>" +
      "</ul>";
    h += '<div class="rate" data-lkey="' + esc(key) + '"><span>我给自己打星：</span>' +
      [1, 2, 3].map(function (i) {
        return '<span class="rstar' + (rate >= i ? " on" : "") + '" data-r="' + i + '">★</span>';
      }).join("") + "</div>";
    h += '<p class="small">本课已得星星：练习与游戏共 ' + starCount(key) + " 颗" +
      (rate ? "，自评 " + rate + " 星" : "") + "。</p>";
    return h;
  }

  /* 单元词汇：从 en_vocab 取本单元所有词，自测卡 + 发音 + 生词本 */
  function hubVocab(x, type) {
    var rows = (D.vocab || []).filter(function (v) {
      return v.book === x.book && (v.unit_no || 0) === (x.unit_no || 0);
    });
    var h = "";
    if (!rows.length) {
      h = '<div class="empty">本单元教材词表尚未录入（数据补充中）。' +
        '可先在「📖 课文」点单词查发音，或去「<a href="vocab.html">词汇总表</a>」浏览已收录词汇。</div>';
      return h;
    }
    h = '<p class="small">本单元共 ' + rows.length +
      ' 个词 · 点卡片显示中文（自测）· 点 🔊 朗读 · 点 ⭐ 收进生词本</p>';
    h += '<div class="words">' + rows.map(function (v) {
      var k = wbKey(x.book, v.word);
      var ph = v.phonetic || "";
      if (ph && ph.charAt(0) !== "/") ph = "/" + ph + "/";
      return '<span class="vcard"><b>' + esc(v.word) + "</b>" +
        (ph ? " <i>" + esc(ph) + "</i>" : "") +
        spkBtn(String(v.word || "")) +
        '<button class="btn wb-toggle' + (WORDBOOK[k] ? " on" : "") +
          '" data-wbkey="' + esc(k) + '" data-book="' + esc(x.book || "") +
          '" data-word="' + esc(v.word || "") + '" data-ipa="' + esc(v.phonetic || "") +
          '" data-zh="' + esc(v.meaning || "") +
          '" title="收进生词本">' + (WORDBOOK[k] ? "★" : "⭐") + '</button>' +
        '<span class="zh">' + esc(v.meaning || "") + "</span>" +
        (v.example ? '<span class="ex-s">' + spkBtn(String(v.example || "")) +
          esc(v.example) + "</span>" : "") +
        "</span>";
    }).join("") + "</div>";
    return h;
  }

  /* 拓展：项目任务 / 歌谣 / 同主题短文 + 本单元配套的课外书 */
  function hubExtend(x) {
    var hub = unitHubOf(x);
    var projs = hub ? hub.projects : [];
    var songs = (HUBS.songs || {})[x.book || ""] || [];
    var exbooks = unitExtraOf(x);
    var h = "";
    if (projs.length) {
      h += '<p class="small">动手做一做（教材里的项目任务）</p>' + projs.map(function (p) {
        var s = '<div class="g-card"><div class="g-head"><b>' + esc(p.name) + "</b>" +
          (p.type ? '<span class="tag">' + esc(p.type) + "</span>" : "") + "</div>";
        if (p.goal) s += '<p class="grule">' + esc(p.goal) + "</p>";
        if (p.steps && p.steps.length) {
          s += '<ol class="pts">' + p.steps.map(function (st) {
            return "<li>" + spkBtn(st) + '<span class="spk">' + esc(st) + "</span></li>";
          }).join("") + "</ol>";
        }
        if (p.language && p.language.length) {
          s += '<p class="small">要用的英语</p><div class="words">' +
            p.language.map(function (l) {
              return '<span class="wb">' + spkBtn(l) + esc(l) + "</span>";
            }).join("") + "</div>";
        }
        if (p.product) s += '<p class="small">成果：' + esc(p.product) + "</p>";
        return s + "</div>";
      }).join("");
    }
    if (songs.length) {
      h += '<p class="small">唱一唱（本册歌谣）</p>' + songs.slice(0, 3).map(function (s2) {
        return '<details class="aq"><summary>🎵 ' + esc(s2.name) +
          (s2.topic ? " · " + esc(s2.topic) : "") + "</summary>" +
          s2.lyrics.map(function (l) {
            return '<div class="lyr">' + spkBtn(l) + '<span class="spk">' + esc(l) + "</span></div>";
          }).join("") + "</details>";
      }).join("");
    }
    /* 配套课外书：本单元在课外拓展库里挑好的书（双向挂载的反向入口） */
    if (exbooks.length) {
      h += '<p class="small">📚 本单元配套的课外书（课外拓展库里按这单元挑的）</p>' +
        '<div class="exbooks">' + exbooks.map(function (b) {
          var s = '<a class="exbook" href="extra.html#read=' + esc(b.id) + '">';
          s += '<b>' + esc(b.title || "课外阅读") + "</b>";
          if (b.author) s += '<span class="small">' + esc(b.author) + "</span>";
          if (b.topic) s += '<span class="tag d1">' + esc(b.topic) + "</span>";
          s += '</a>';
          return s;
        }).join("") + "</div>";
    }
    /* 同主题课外短文：从 D.passages 里找同 topic 但不在本课的短文 */
    var topic = x.topic || "";
    var extras = [];
    if (topic) {
      var myKey = lessonKey(x, "pas");
      (D.passages || []).forEach(function (p) {
        if (p.topic === topic && lessonKey(p, "pas") !== myKey) {
          extras.push(p);
        }
      });
    }
    if (extras.length) {
      h += '<p class="small">📖 同主题课外短文（' + esc(topic) + '）</p>';
      extras.slice(0, 3).forEach(function (p) {
        var peek = (p.text || "").slice(0, 80);
        h += '<details class="aq"><summary>' + esc(p.name || "短文") +
          (p.genre ? ' <span class="tag">' + esc(p.genre) + '</span>' : '') +
          (p.book ? ' <span class="small">' + esc(p.book) + '</span>' : '') +
          '</summary>' +
          (p.zh ? '<p class="small">' + esc(p.zh.slice(0, 120)) + '</p>' : '') +
          '<p class="spk">' + esc(peek) + (p.text && p.text.length > 80 ? '…' : '') + '</p>' +
          spkBtn(peek) + '</details>';
      });
    }
    /* 同主题课外对话 */
    var extraDlg = [];
    if (topic) {
      (D.dialogues || []).forEach(function (d) {
        if (d.topic === topic && lessonKey(d, "dlg") !== lessonKey(x, "dlg")) {
          extraDlg.push(d);
        }
      });
    }
    if (extraDlg.length) {
      h += '<p class="small">💬 同主题课外对话</p>';
      extraDlg.slice(0, 2).forEach(function (d) {
        h += '<details class="aq"><summary>' + esc(d.scene || d.title || "对话") +
          (d.book ? ' <span class="small">' + esc(d.book) + '</span>' : '') +
          '</summary></details>';
      });
    }
    if (!extras.length && !extraDlg.length) {
      h += '<p class="small">暂无同主题课外拓展内容。</p>';
    }
    return h;
  }

  /* ---- 游戏局内逻辑：状态挂在 .game 元素的 _st 上 ---- */
  function startGame(g, x, type) {
    var words = lessonWords(x, type);
    var lines = lessonLines(x, type);
    var kind = g.getAttribute("data-g");
    var body = g.querySelector(".g-body");
    if (kind === "scramble") {
      var ws = sample(words.filter(function (w) {
        return /^[A-Za-z'-]{2,}$/.test(w.word);
      }), 5);
      g._st = { kind: "scramble", ws: ws, i: 0 };
      body.innerHTML = scrHtml(g._st);
    } else if (kind === "order") {
      // 取一段连续原文（对话/短文节选），打乱后按原序点回
      var n = Math.min(5, lines.length);
      var at = Math.floor(Math.random() * (lines.length - n + 1));
      var seq = lines.slice(at, at + n);
      var disp = seq.map(function (t, i) { return { t: t, i: i }; });
      shuffle(disp);
      g._st = { kind: "order", seq: seq, disp: disp, next: 0 };
      body.innerHTML = '<div class="od">' +
        '<div class="od-h">' + spkBtn(seq.join(" ")) + "先听整段，再按顺序点句子</div>" +
        disp.map(function (d, i) {
          return '<div class="oline" data-i="' + i + '">' + esc(d.t) + "</div>";
        }).join("") + '<div class="g-fb"></div></div>';
    } else if (kind === "match") {
      var ps = sample(words.filter(function (w) { return w.zh; }), 5);
      var cards = [];
      ps.forEach(function (w, i) {
        cards.push({ t: "en", txt: w.word, id: i });
        cards.push({ t: "zh", txt: w.zh, id: i });
      });
      shuffle(cards);
      g._st = { kind: "match", left: ps.length, pick: null };
      body.innerHTML = '<div class="mt">' + cards.map(function (c) {
        return '<span class="mcard" data-id="' + c.id + '" data-t="' + c.t + '">' +
          esc(c.txt) + "</span>";
      }).join("") + '</div><div class="g-fb"></div>';
    }
    g.querySelector(".g-start").textContent = "重来";
  }
  function scrHtml(st) {
    var w = st.ws[st.i];
    st.letters = w.word.split("");
    st.tiles = shuffle(w.word.split("").map(function (t, i) { return { t: t, i: i }; }));
    st.ans = [];
    return '<div class="scr"><div class="sc-h">' + spkBtn(w.word) + "<b>" +
      esc(w.zh || "听音拼词") + "</b>" + (w.ipa ? " <i>" + esc(w.ipa) + "</i>" : "") +
      "</div>" +
      '<div class="sc-ans">' + st.letters.map(function () {
        return '<span class="slot"></span>';
      }).join("") + "</div>" +
      '<div class="sc-tiles">' + st.tiles.map(function (t, i) {
        return '<span class="lt" data-i="' + i + '">' + esc(t.t) + "</span>";
      }).join("") + "</div>" +
      '<div class="g-fb"></div>' +
      '<div class="sc-prog small">第 ' + (st.i + 1) + " / " + st.ws.length + " 个</div></div>";
  }
  function gameWin(g, key, game) {
    g.querySelector(".g-fb").innerHTML = '<span class="ok-t">通关！得一颗 ★</span>';
    awardStar(key, game);
  }

  /* 学习中心事件委托：tab 切换 / 单元展开 / 练习作答 / 游戏 / 打星 */
  function bindLessonHubs(box) {
    box.addEventListener("click", function (e) {
      /* 中英对照：就近开关，只切换本课的 .lbody，不影响全局 */
      var zt = e.target.closest(".zh-toggle");
      if (zt) {
        zt.closest(".lbody").classList.toggle("show-zh");
        zt.classList.toggle("on");
        return;
      }
      var uf = e.target.closest(".u-fold");
      if (uf) {
        var unit = uf.closest(".unit");
        var dets = unit.querySelectorAll("details.lesson");
        var anyClosed = [].some.call(dets, function (d) { return !d.open; });
        [].forEach.call(dets, function (d) { d.open = anyClosed; });
        uf.textContent = anyClosed ? "全部收起" : "全部展开";
        return;
      }
      var tab = e.target.closest(".htab");
      if (tab) {
        var body2 = tab.closest(".lbody");
        var p = tab.getAttribute("data-p");
        [].forEach.call(body2.querySelectorAll(".htab"), function (x) {
          x.classList.remove("on");
        });
        tab.classList.add("on");
        [].forEach.call(body2.querySelectorAll(".hpanel"), function (x) {
          x.classList.toggle("on", x.getAttribute("data-p") === p);
        });
        var panel = body2.querySelector('.hpanel[data-p="' + p + '"]');
        /* text 板块在生成课时就内联渲染好了，切回来不该再走 buildPanel，否则会被清空 */
        if (panel && !panel._built && p !== "text") {
          var det0 = tab.closest("details.lesson");
          var lx = LESSONS[det0.getAttribute("data-lkey")];
          buildPanel(panel, p, lx.data, lx.type);
        }
        return;
      }
      var opt = e.target.closest(".fq .opt");
      if (opt) {
        var fq = opt.closest(".fq");
        if (fq._done) return;
        fq._done = true;
        var ok = opt.getAttribute("data-w") === fq.getAttribute("data-a");
        opt.classList.add(ok ? "ok" : "no");
        fq.querySelector(".fb").innerHTML = ok ? '<span class="ok-t">对</span>'
          : '<span class="no-t">答案：' + esc(fq.getAttribute("data-a") || "") + "</span>";
        if (!ok) {
          var detE = opt.closest("details.lesson");
          var lkeyE = detE ? detE.getAttribute("data-lkey") : "";
          errAdd(lkeyE, fq.getAttribute("data-q") || opt.textContent, fq.getAttribute("data-a") || "", "fill");
        }
        var wrap = opt.closest(".ex-fill") || opt.closest(".ex-cloze");
        if (wrap) {
          var qs = wrap.querySelectorAll(".fq"), done = 0, right = 0;
          [].forEach.call(qs, function (q) {
            if (q._done) { done++; if (q.querySelector(".opt.ok")) right++; }
          });
          if (done === qs.length) {
            var det1 = opt.closest("details.lesson");
            if (right === qs.length) {
              awardStar(det1.getAttribute("data-lkey"), "fill");
              wrap.insertAdjacentHTML("beforeend",
                '<div class="g-fb"><span class="ok-t">全对！得一颗 ★</span></div>');
            } else {
              wrap.insertAdjacentHTML("beforeend",
                '<div class="g-fb"><span class="no-t">对 ' + right + " / " + qs.length +
                ' 题</span> <span class="opt fq-reset">再做一次</span></div>');
            }
          }
        }
        return;
      }
      if (e.target.closest(".fq-reset")) {
        var wrap2 = e.target.closest(".ex-fill") || e.target.closest(".ex-cloze");
        if (!wrap2) return;
        [].forEach.call(wrap2.querySelectorAll(".fq"), function (q) {
          q._done = false;
          q.querySelector(".fb").innerHTML = "";
          [].forEach.call(q.querySelectorAll(".opt"), function (o) {
            o.classList.remove("ok"); o.classList.remove("no");
          });
        });
        var fb2 = wrap2.querySelector(".g-fb");
        if (fb2) fb2.parentNode.removeChild(fb2);
        return;
      }
      /* 听力填词：点 🔊 播放整句（慢速 rate = 0.7） */
      var cp = e.target.closest(".cloze-play");
      if (cp) {
        var line = cp.getAttribute("data-line") || "";
        var slow = cp.getAttribute("data-slow") === "1";
        if (line) speech(line, slow ? 0.7 : 1.0);
        return;
      }
      /* 生词收藏按钮（预习板块每个词后面） */
      var wbT = e.target.closest(".wb-toggle");
      if (wbT) {
        var k = wbT.getAttribute("data-wbkey");
        var book = wbT.getAttribute("data-book") || "";
        var word = wbT.getAttribute("data-word") || "";
        if (WORDBOOK[k]) wbRemove(book, word);
        else wbAdd(book, word, { ipa: wbT.getAttribute("data-ipa") || "",
                                 zh: wbT.getAttribute("data-zh") || "" });
        checkBadgeUnlock();
        return;
      }
      /* 每日 3 分钟：换一批 / 打卡 / 复习 */
      if (e.target.closest(".today-repick")) {
        var today = todayStr();
        var day2 = CHECKIN[today] || { items: [], done: 0 };
        day2.items = pickTodayItems();
        day2.done = 0;
        CHECKIN[today] = day2;
        checkinSave();
        var todayBox = document.querySelector("details.today");
        if (todayBox) todayBox.outerHTML = renderToday();
        return;
      }
      var tOk = e.target.closest(".today-ok");
      if (tOk) {
        var card = tOk.closest(".today-card");
        if (!card || card.classList.contains("done")) return;
        var i = +card.getAttribute("data-i");
        var day3 = CHECKIN[todayStr()] || { items: [], done: 0 };
        if (i + 1 > day3.done) day3.done = i + 1;
        CHECKIN[todayStr()] = day3;
        checkinSave();
        card.classList.add("done");
        [].forEach.call(document.querySelectorAll(".today summary .small"), function (el) {
          if (el.textContent.indexOf("已完成") >= 0) {
            el.textContent = todayStr() + " · 已完成 " + day3.done + "/3";
          }
        });
        var str2 = checkinStreak();
        [].forEach.call(document.querySelectorAll(".today-streak"), function (el) {
          el.textContent = "🔥 连击 " + str2 + " 天";
        });
        checkBadgeUnlock();
        return;
      }
      var tWrong = e.target.closest(".today-wrong");
      if (tWrong) {
        /* 生词本里记一次错误：把 last 更新到当下，wrong++，下次优先抽它 */
        var card2 = tWrong.closest(".today-card");
        var today2 = todayStr();
        var day4 = CHECKIN[today2];
        var idx = +card2.getAttribute("data-i");
        var it = day4.items[idx];
        if (it && it.kind === "word") {
          var wk = wbKey(it.book, it.word);
          if (!WORDBOOK[wk]) {
            /* 从今日 items 里补一下 meta */
            WORDBOOK[wk] = { word: it.word, ipa: it.ipa || "", zh: it.zh || "",
                             book: it.book || "", added: Date.now(),
                             last: 0, right: 0, wrong: 0 };
          }
          WORDBOOK[wk].wrong = (WORDBOOK[wk].wrong || 0) + 1;
          WORDBOOK[wk].last = Date.now();
          wordBookSave();
          refreshWordBookUI();
        }
        return;
      }
      var tGo = e.target.closest(".today-go");
      if (tGo) {
        var card3 = tGo.closest(".today-card");
        var lkey = card3.getAttribute("data-lkey");
        var detG = document.querySelector('details.lesson[data-lkey="' + lkey + '"]');
        if (detG) {
          detG.open = true;
          detG.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        /* 打卡：复习完记得点右边的 ✅ 已复习 */
        return;
      }
      /* 生词本：记住了 / 忘了 / 移除 */
      var wRight = e.target.closest(".wb-right");
      if (wRight) {
        var cb = wRight.closest(".wb-card");
        var wk2 = cb.getAttribute("data-k");
        if (WORDBOOK[wk2]) {
          WORDBOOK[wk2].right = (WORDBOOK[wk2].right || 0) + 1;
          WORDBOOK[wk2].last = Date.now();
          wordBookSave();
          refreshWordBookUI();
        }
        return;
      }
      var wWrong = e.target.closest(".wb-wrong");
      if (wWrong) {
        var cb2 = wWrong.closest(".wb-card");
        var wk3 = cb2.getAttribute("data-k");
        if (WORDBOOK[wk3]) {
          WORDBOOK[wk3].wrong = (WORDBOOK[wk3].wrong || 0) + 1;
          WORDBOOK[wk3].last = Date.now();
          wordBookSave();
          refreshWordBookUI();
        }
        return;
      }
      var wDel = e.target.closest(".wb-del");
      if (wDel) {
        var cb3 = wDel.closest(".wb-card");
        var wk4 = cb3.getAttribute("data-k");
        var parts2 = String(wk4).split("#");
        wbRemove(parts2[0], parts2.slice(1).join("#"));
        return;
      }
      /* 跟读打分：点 🎤 触发浏览器语音识别 */
      var recB = e.target.closest(".rec-btn");
      if (recB) {
        var rec = recB.getAttribute("data-rec");
        var res = recB.parentElement.querySelector(".rec-res");
        if (res) res.innerHTML = '<span class="small">… 正在听</span>';
        recB.disabled = true;
        recB.classList.add("rec-busy");
        startRecognition(rec, function (r) {
          recB.disabled = false;
          recB.classList.remove("rec-busy");
          if (res) {
            if (r.ok) {
              res.innerHTML = '<span class="ok-t">说对了 ✓</span>';
              var detR = recB.closest("details.lesson");
              if (detR) markUnitMap(detR.getAttribute("data-lkey"), "read");
            } else {
              var why = r.why || "";
              var tip = r.text ? "（识别到：" + esc(r.text) + "）" : "";
              res.innerHTML = '<span class="no-t">' + esc(why) + tip + "</span>";
            }
          }
        });
        return;
      }
      /* 全文朗读（多角色多音色） */
      var readAll = e.target.closest(".read-all-dlg");
      if (readAll) { readAllDialogue(readAll); return; }
      var recAll = e.target.closest(".rec-all-btn");
      if (recAll) {
        /* 全部跟读：逐个念，全部说对才点亮"跟读"关 */
        var panel = recAll.closest(".hpanel");
        if (!panel) return;
        var btns = panel.querySelectorAll(".rec-btn");
        if (!btns.length) return;
        var n = btns.length, ok = 0, i = 0;
        recAll.disabled = true;
        [].forEach.call(btns, function (b) { b.disabled = true; });
        function step() {
          if (i >= n) {
            [].forEach.call(btns, function (b) { b.disabled = false; });
            recAll.disabled = false;
            if (ok === n) {
              var detA = recAll.closest("details.lesson");
              if (detA) markUnitMap(detA.getAttribute("data-lkey"), "read");
              var hint = recAll.parentElement.querySelector(".rec-all .small");
              if (hint) hint.innerHTML = '<span class="ok-t">全对！跟读关已点亮 ✓</span>';
            } else {
              var hint2 = recAll.parentElement.querySelector(".rec-all .small");
              if (hint2) hint2.innerHTML = '对了 ' + ok + " / " + n + " 个，再练一次";
            }
            return;
          }
          var b = btns[i];
          b.classList.add("rec-cur");
          var r = b.parentElement.querySelector(".rec-res");
          if (r) r.innerHTML = '<span class="small">👂 现在说：' + esc(b.getAttribute("data-rec")) + "</span>";
          startRecognition(b.getAttribute("data-rec"), function (res2) {
            b.classList.remove("rec-cur");
            if (res2.ok) {
              ok++;
              if (r) r.innerHTML = '<span class="ok-t">✓</span>';
            } else {
              if (r) r.innerHTML = '<span class="no-t">再来</span>';
            }
            i++;
            setTimeout(step, 250);
          });
        }
        step();
        return;
      }
      var gs = e.target.closest(".g-start");
      if (gs) {
        var g0 = gs.closest(".game");
        var det2 = gs.closest("details.lesson");
        var lx2 = LESSONS[det2.getAttribute("data-lkey")];
        startGame(g0, lx2.data, lx2.type);
        return;
      }
      var lt = e.target.closest(".lt");
      if (lt && !lt.classList.contains("used")) {
        var g1 = lt.closest(".game"), st1 = g1._st;
        if (!st1 || st1.kind !== "scramble") return;
        var tile = st1.tiles[+lt.getAttribute("data-i")];
        lt.classList.add("used");
        st1.ans.push(tile);
        var slots = g1.querySelectorAll(".slot");
        slots[st1.ans.length - 1].textContent = tile.t;
        slots[st1.ans.length - 1].classList.add("filled");
        if (st1.ans.length === st1.letters.length) {
          var got = st1.ans.map(function (t) { return t.t; }).join("");
          var want = st1.letters.join("");
          var fb3 = g1.querySelector(".g-fb");
          if (got.toLowerCase() === want.toLowerCase()) {
            fb3.innerHTML = '<span class="ok-t">对！</span>';
            st1.i++;
            if (st1.i >= st1.ws.length) {
              gameWin(g1, g1.closest("details.lesson").getAttribute("data-lkey"), "scramble");
            } else {
              setTimeout(function () {
                g1.querySelector(".g-body").innerHTML = scrHtml(st1);
              }, 700);
            }
          } else {
            fb3.innerHTML = '<span class="no-t">再试试</span>';
            var detS = g1.closest("details.lesson");
            errAdd(detS ? detS.getAttribute("data-lkey") : "", want, got, "scramble");
            setTimeout(function () {
              st1.ans = [];
              [].forEach.call(g1.querySelectorAll(".slot"), function (s) {
                s.textContent = ""; s.classList.remove("filled");
              });
              [].forEach.call(g1.querySelectorAll(".lt"), function (s) {
                s.classList.remove("used");
              });
              fb3.innerHTML = "";
            }, 700);
          }
        }
        return;
      }
      var ol = e.target.closest(".oline");
      if (ol && !ol.classList.contains("done")) {
        var g2 = ol.closest(".game"), st2 = g2._st;
        if (!st2 || st2.kind !== "order") return;
        var d2 = st2.disp[+ol.getAttribute("data-i")];
        if (d2.t === st2.seq[st2.next]) {
          st2.next++;
          ol.classList.add("done");
          ol.insertAdjacentHTML("beforeend",
            '<span class="obadge">' + st2.next + "</span>");
          if (st2.next === st2.seq.length) {
            gameWin(g2, g2.closest("details.lesson").getAttribute("data-lkey"), "order");
          }
        } else {
          ol.classList.add("no");
          var detO = g2.closest("details.lesson");
          errAdd(detO ? detO.getAttribute("data-lkey") : "", st2.seq[st2.next], d2.t, "order");
          setTimeout(function () { ol.classList.remove("no"); }, 450);
        }
        return;
      }
      var mc = e.target.closest(".mcard");
      if (mc && !mc.classList.contains("done")) {
        var g3 = mc.closest(".game"), st3 = g3._st;
        if (!st3 || st3.kind !== "match") return;
        if (!st3.pick) {
          st3.pick = mc;
          mc.classList.add("on");
        } else if (st3.pick === mc) {
          mc.classList.remove("on");
          st3.pick = null;
        } else {
          var a = st3.pick, b = mc;
          var pair = a.getAttribute("data-id") === b.getAttribute("data-id") &&
                     a.getAttribute("data-t") !== b.getAttribute("data-t");
          if (pair) {
            a.classList.remove("on");
            a.classList.add("done"); b.classList.add("done");
            st3.pick = null;
            st3.left--;
            if (!st3.left) {
              gameWin(g3, g3.closest("details.lesson").getAttribute("data-lkey"), "match");
            }
          } else {
            b.classList.add("no");
            var detM = g3.closest("details.lesson");
            errAdd(detM ? detM.getAttribute("data-lkey") : "", a.textContent, b.textContent, "match");
            setTimeout(function () {
              a.classList.remove("on"); b.classList.remove("no");
            }, 500);
            st3.pick = null;
          }
        }
        return;
      }
      var rs = e.target.closest(".rstar");
      if (rs) {
        var rate = rs.closest(".rate");
        var key = rate.getAttribute("data-lkey");
        var r = +rs.getAttribute("data-r");
        if (!STARS[key]) STARS[key] = {};
        STARS[key].rate = r;
        starSave();
        [].forEach.call(rate.querySelectorAll(".rstar"), function (s) {
          s.classList.toggle("on", +s.getAttribute("data-r") <= r);
        });
      }
    });
  }

  /* 一课对话：句型 + 逐句（角色 / 原文 / 中文） */
  function enDialogue(x) {
    var s = '<div class="item les-item">';
    (x.patterns || []).forEach(function (p) {
      s += '<div class="pat">' + hl(String(p)) + "</div>";
    });
    var turns = (x.turns || []).map(function (t) {
      var who = typeof t === "string" ? "" : (t.speaker || t.role || "");
      var line = typeof t === "string" ? t : (t.text || t.line || t.en || "");
      var zh = typeof t === "string" ? "" : (t.zh || t.translation || "");
      return { who: who, line: line, zh: zh };
    }).filter(function (t) { return t.line; });
    /* 全文朗读按钮（多角色多音色） */
    if (turns.length > 1) {
      s += '<p class="small read-all-row"><button class="btn read-all-dlg" type="button">' +
           '🔊 全文朗读（分角色音色）</button></p>';
    }
    turns.forEach(function (t) {
      s += '<div class="turn" data-speaker="' + esc(t.who) + '">' +
           '<b>' + esc(t.who || "•") + "</b> " +
           spkBtn(String(t.line)) + ' <span class="spk">' + esc(t.line) + "</span>" +
           (t.zh ? '<span class="zh">' + esc(t.zh) + "</span>" : "") + "</div>";
    });
    return s + "</div>";
  }

  /* 一课短文：原文 + 译文 + 重点词 + 写作任务（理解题挪到练习板块） */
  function enPassage(x) {
    var s = '<div class="item les-item">';
    if (x.source) s += '<p class="small">来源：' + esc(x.source) + "</p>";
    s += '<div class="en para">' + spkBtn(String(x.text || "")) +
      '<span class="spk">' + esc(x.text) + "</span></div>";
    if (x.zh) s += '<div class="zh para">' + esc(x.zh) + "</div>";
    if (x.words && x.words.length) {
      s += '<p class="small">重点词</p><div class="words">' +
        x.words.map(function (w) {
          var wword = w.word || w;
          return '<span class="wb">' + spkBtn(String(wword || "")) +
            esc(wword) +
            (w.meaning || w.zh ? " <i>" + esc(w.meaning || w.zh) + "</i>" : "") +
            "</span>";
        }).join("") + "</div>";
    }
    if (x.writing) {
      s += '<div class="life"><div class="lf"><span class="tag d1">写一写</span>' +
        esc(x.writing) + "</div></div>";
    }
    return s + "</div>";
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
            spkBtn(String(v.word || "")) +
            '<span class="zh">' + esc(v.meaning || "") + "</span>" +
            (v.example ? '<span class="ex-s">' + spkBtn(String(v.example || "")) +
              esc(v.example) + "</span>" : "") +
            "</span>";
        }).join("") + "</div></div>";
    }).join("");
  }

  /* ================= DK 风语法图解：积木句构 + 例句着色 + 时态轴 ================= */
  var DK_TENSES = ["一般现在时", "现在进行时", "一般将来时", "be going to", "一般过去时"];

  function enGrammar(st) {
    var rows = (D.grammar || []).filter(pass(st, ["point", "pattern", "rule", "category"]));
    var h = "<h2>语法图解（" + rows.length + " 条）<span class=\"small\">" +
      " 彩色积木句构 · 例句重点词着色 · 时态时间轴</span></h2>";
    if (!rows.length) return h;
    h += dkLegend() + dkTenseMap(rows);
    // 按范畴分块
    var byCat = {}, cOrder = [];
    rows.forEach(function (g) {
      var k = g.category || "其他";
      if (!byCat[k]) { byCat[k] = []; cOrder.push(k); }
      byCat[k].push(g);
    });
    cOrder.sort(function (a, b) { return byCat[b].length - byCat[a].length; });
    h += '<div class="dk-nav">' + cOrder.map(function (k, i) {
      return '<a href="#dkc' + i + '">' + esc(k) + " <b>" + byCat[k].length + "</b></a>";
    }).join("") + "</div>";
    h += cOrder.map(function (k, ci) {
      var inner = (k === "时态") ? dkTenseGroups(byCat[k]) :
        byCat[k].map(function (g, i) { return dkCard(g, i + 1); }).join("");
      return '<details class="dk-sec" id="dkc' + ci + '"' + (ci < 2 ? " open" : "") +
        '><summary><span>' + esc(k) + '</span><span class="dk-sec-n">' +
        byCat[k].length + " 条</span></summary>" + inner + "</details>";
    }).join("");
    return h;
  }

  function dkLegend() {
    var items = [["q", "疑问词"], ["subj", "主语"], ["aux", "助动词"], ["verb", "谓语动词"],
                 ["det", "冠词/限定"], ["obj", "宾语·表语"], ["prep", "介词"],
                 ["neg", "否定"], ["time", "状语"], ["misc", "其他成分"]];
    return '<div class="dk-legend">' + items.map(function (x) {
      return '<span><i class="dk-i dk-i-' + x[0] + '"></i>' + x[1] + "</span>";
    }).join("") + "</div>";
  }

  /* 时态全景条：每个时态一张小卡，标注条数与覆盖册数 */
  function dkTenseMap(rows) {
    var st = {}, order = [];
    rows.forEach(function (g) {
      if (!g.tense) return;
      if (!st[g.tense]) { st[g.tense] = { n: 0, books: {} }; order.push(g.tense); }
      st[g.tense].n++; st[g.tense].books[g.book] = 1;
    });
    if (!order.length) return "";
    order.sort(function (a, b) {
      var ia = DK_TENSES.indexOf(a), ib = DK_TENSES.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    return '<div class="dk-tmap">' + order.map(function (t) {
      return '<div class="dk-tm"><div class="dk-tm-h">' + dkTlSvg(t) + "</div>" +
        '<div class="dk-tm-name">' + esc(t) + '</div><div class="dk-tm-meta">' +
        st[t].n + " 条 · " + Object.keys(st[t].books).length + " 册</div></div>";
    }).join("") + "</div>";
  }

  /* 小时态轴：过去 —— 现在 —— 将来，高亮本时态位置 */
  function dkTlSvg(tense) {
    var x = { "一般过去时": 46, "一般现在时": 150, "现在进行时": 150,
              "一般将来时": 254, "be going to": 254 }[tense] || 150;
    var s = '<svg class="dk-tl" viewBox="0 0 300 60" width="210" height="42" aria-hidden="true">';
    s += '<line x1="20" y1="26" x2="280" y2="26" stroke="#ddd5c2" stroke-width="3" stroke-linecap="round"/>';
    [[46, "过去"], [150, "现在"], [254, "将来"]].forEach(function (m) {
      var on = m[0] === x;
      s += '<line x1="' + m[0] + '" y1="19" x2="' + m[0] + '" y2="33" stroke="' +
        (on ? "#e5534b" : "#c9c0aa") + '" stroke-width="3" stroke-linecap="round"/>';
      s += '<text x="' + m[0] + '" y="50" text-anchor="middle" class="dk-tl-lab' +
        (on ? " on" : "") + '">' + m[1] + "</text>";
      if (on) s += '<circle cx="' + m[0] + '" cy="26" r="7" fill="#e5534b"/>';
    });
    return s + "</svg>";
  }

  /* 时态范畴：按时态分组，组头配小时态轴，卡片编号连续 */
  function dkTenseGroups(list) {
    var by = {}, order = [];
    list.forEach(function (g) {
      var k = g.tense || "其他";
      if (!by[k]) { by[k] = []; order.push(k); }
      by[k].push(g);
    });
    order.sort(function (a, b) {
      var ia = DK_TENSES.indexOf(a), ib = DK_TENSES.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    var n = 0;
    return order.map(function (t) {
      var cards = by[t].map(function (g) { n++; return dkCard(g, n); }).join("");
      return '<div class="dk-tg"><div class="dk-tg-h">' + dkTlSvg(t) + "<b>" + esc(t) +
        '</b><span class="dk-tg-n">' + by[t].length + " 条</span></div>" + cards + "</div>";
    }).join("");
  }

  function dkCard(g, n) {
    var s = '<div class="dk-card"><div class="dk-ch"><span class="dk-num">' + n + "</span>" +
      "<h3>" + esc(g.point || "") + "</h3>" + where(g) + "</div>";
    if (g.rule) s += '<div class="dk-rule">' + esc(g.rule) + "</div>";
    s += dkTiles(g.pattern);
    var exs = typeof g.examples === "string" ? safeJson(g.examples) : (g.examples || []);
    if (exs.length) {
      s += '<ul class="dk-ex">' + exs.slice(0, 6).map(function (e) {
        var en = String(typeof e === "string" ? e : (e.en || e.text || e) || "");
        return "<li>" + spkBtn(en) + '<span class="dk-en">' + dkColorEx(en, g) + "</span>" +
          (e && e.zh ? '<span class="dk-zh">' + esc(e.zh) + "</span>" : "") + "</li>";
      }).join("") + "</ul>";
    }
    return s + "</div>";
  }

  /* 把 pattern 拆成彩色积木：先按 + 拆，整句模式按空格拆；拆不动就退回原文行 */
  function dkTiles(pat) {
    pat = String(pat || "").trim();
    if (!pat) return "";
    var segs = pat.split(/\s*\+\s*/).map(function (x) { return x.trim(); }).filter(Boolean);
    if (segs.length < 2 && !/[?？!！。]/.test(pat)) {
      var toks = pat.split(/\s+/);
      if (toks.length >= 2 && toks.length <= 6) segs = toks;
    }
    if (segs.length < 2 || segs.length > 9) return '<div class="pat">' + hl(pat) + "</div>";
    var h = '<div class="dk-blocks">';
    segs.forEach(function (seg, i) {
      if (i) h += '<span class="dk-conn" style="--i:' + (i * 2 - 1) + '">❯</span>';
      var r = dkRole(seg), m = dkMorph(seg);
      h += '<div class="dk-tile ' + r.cls + '" style="--i:' + (i * 2) + '">' +
        '<span class="dk-t-en">' + esc(seg) + (m ? '<em class="dk-morph">' + m[0] + "</em>" : "") +
        "</span>" + '<span class="dk-tag">' + r.tag + "</span>" +
        (m ? '<span class="dk-mnote">' + m[1] + "</span>" : "") + "</div>";
    });
    return h + "</div>";
  }

  function dkRole(seg) {
    var s = seg.toLowerCase();
    if (!/[一-鿿]/.test(seg) && seg.length > 16) return { cls: "misc", tag: "句型" };
    if (/^(who|what|where|when|why|whose|which|how)\b|疑问词/.test(s)) return { cls: "q", tag: "疑问词" };
    if (/^(do|does|did|can|could|will|would|shall|should|may|might|must|won)n't$|\bnot\b|\bno\b|never|否定/.test(s))
      return { cls: "neg", tag: "否定" };
    if (/^(do|does|did|can|could|will|would|shall|should|may|might|must)\b|助动词|情态|have to|has to/.test(s))
      return { cls: "aux", tag: "助动词" };
    if (/^there (is|are|was|were)\b/.test(s)) return { cls: "verb", tag: "There be" };
    if (/^(am|is|are|was|were|be)\b|系动词|be ?动词/.test(s)) return { cls: "verb", tag: "系动词" };
    if (/过去式/.test(seg)) return { cls: "verb", tag: "谓语·过去式" };
    if (/进行时|动名词|ing$/.test(s)) return { cls: "verb", tag: "谓语·ing" };
    if (/动词|谓语/.test(seg)) return { cls: "verb", tag: "谓语" };
    if (/主语/.test(seg)) return { cls: "subj", tag: "主语" };
    if (/^(i|you|he|she|it|we|they|this|that|these|those|there)\b/.test(s)) return { cls: "subj", tag: "主语" };
    if (/冠词|限定词|指示词|物主|所有格/.test(seg)) return { cls: "det", tag: "限定词" };
    if (/^(a|an|the|my|your|his|her|its|our|their|some|any)\b/.test(s)) return { cls: "det", tag: "限定词" };
    if (/宾语|表语|名词/.test(seg)) return { cls: "obj", tag: "宾/表语" };
    if (/介词/.test(seg)) return { cls: "prep", tag: "介词" };
    if (/^(in|on|under|at|to|from|with|of|for|by|near|behind|between|after|before|about)\b/.test(s))
      return { cls: "prep", tag: "介词" };
    if (/时间|地点|状语|频率/.test(seg)) return { cls: "time", tag: "状语" };
    if (/^(\.+|…)$/.test(seg)) return { cls: "misc", tag: "其他成分" };
    return { cls: "misc", tag: "成分" };
  }

  /* 词尾形态小片：三单+s / 过去式+ed / 进行+ing / 复数+s */
  function dkMorph(seg) {
    if (/加 ?s|s\/es|三单|第三人称/.test(seg)) return ["s", "三单+s"];
    if (/过去式/.test(seg)) return ["ed", "过去式"];
    if (/进行时|动词 ?ing|动名词/.test(seg)) return ["ing", "加ing"];
    if (/复数/.test(seg)) return ["s", "复数+s"];
    return null;
  }

  /* 例句重点词着色：助动词橙 / be动词红 / 否定紫 / 疑问词粉 / 人称蓝；按条目时态补 -ed/-ing */
  function dkColorEx(s, g) {
    var t = esc(s);
    t = t.replace(/\b(do|does|did|can|could|will|would|shall|should|may|might|must|won)(n't| not)\b/gi,
      '<span class="hl-a">$1</span><span class="hl-n">$2</span>');
    t = t.replace(/\b(am|is|are|was|were)(n't| not)\b/gi,
      '<span class="hl-v">$1</span><span class="hl-n">$2</span>');
    t = t.replace(/\b(do|does|did|can|could|will|would|shall|should|may|might|must)\b/gi,
      '<span class="hl-a">$1</span>');
    t = t.replace(/\b(am|is|are|was|were)\b/gi, '<span class="hl-v">$1</span>');
    t = t.replace(/\b(going to)\b/gi, '<span class="hl-a">$1</span>');
    t = t.replace(/^(who|what|where|when|why|whose|which|how)\b/i, '<span class="hl-q">$1</span>');
    t = t.replace(/\b(i|you|he|she|it|we|they|this|that|these|those|there)\b/gi,
      '<span class="hl-s">$1</span>');
    t = t.replace(/\b(not|no|never)\b/gi, '<span class="hl-n">$1</span>');
    var tn = g && g.tense;
    if (tn === "一般过去时") t = t.replace(/\b([A-Za-z]+ed)\b/g, '<span class="hl-v">$1</span>');
    else if (tn === "现在进行时") t = t.replace(/\b([A-Za-z]+ing)\b/g, '<span class="hl-v">$1</span>');
    return t;
  }

  /* 卡片滚入视口时触发级联动画（details 折叠的卡片在展开时才会触发） */
  function dkReveal(root) {
    if (!("IntersectionObserver" in window)) {
      root.querySelectorAll(".dk-card").forEach(function (c) { c.classList.add("on"); });
      return;
    }
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("on"); io.unobserve(e.target); }
      });
    }, { threshold: 0.1 });
    root.querySelectorAll(".dk-card").forEach(function (c) { io.observe(c); });
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
              var ew = typeof e === "string" ? e : (e.word || e);
              return '<span class="wb">' + spkBtn(String(ew || "")) +
                esc(ew) + "</span>";
            }).join("") + "</span>" : "") + "</div>";
        if (x.chant) s += '<div class="pat">' + spkBtn(String(x.chant || "")) +
          esc(x.chant.slice(0, 140)) + "</div>";
      });
      return s + "</div>";
    }).join("");
  }

  /* 英语写作教学页：Writing Process / 6+1 Traits / 5 文体 / 句型+过渡词 / 检查表+练习 */
  function enWriting(st) {
    var W = D.writing || {};
    var q = (st.q || "").trim().toLowerCase();
    function match(s) { return !q || String(s).toLowerCase().indexOf(q) >= 0; }
    var h = '<h2>英语写作 <span class="small">从构思到发表的完整写作流程</span></h2>';

    /* 1. 写作流程 */
    var proc = (W.process || []).filter(function (p) { return match(p.en + " " + p.zh); });
    if (proc.length) {
      h += '<details class="wrt-sec" open><summary>① 写作流程 <span class="small">Writing Process · 五步走</span></summary>';
      h += '<div class="wrt-flow">';
      proc.forEach(function (p, i) {
        h += '<div class="wrt-step">';
        h += '<div class="wrt-step-num">' + p.step + '</div>';
        h += '<div class="wrt-step-en">' + esc(p.en) + '</div>';
        h += '<div class="wrt-step-zh">' + esc(p.zh) + '</div>';
        h += '<div class="wrt-step-desc">' + esc(p.desc) + '</div>';
        if (p.tips && p.tips.length) {
          h += '<ul class="wrt-tips">';
          p.tips.forEach(function (t) { h += '<li>' + esc(t) + '</li>'; });
          h += '</ul>';
        }
        h += '</div>';
        if (i < proc.length - 1) h += '<div class="wrt-arrow">→</div>';
      });
      h += '</div></details>';
    }

    /* 2. 六要素 */
    var traits = (W.traits || []).filter(function (t) { return match(t.en + " " + t.zh); });
    if (traits.length) {
      h += '<details class="wrt-sec" open><summary>② 写作七要素 <span class="small">6+1 Traits of Writing</span></summary>';
      h += '<div class="wrt-trait-grid">';
      traits.forEach(function (t) {
        h += '<div class="wrt-trait">';
        h += '<div class="wrt-trait-ic">' + (t.icon || "") + '</div>';
        h += '<div class="wrt-trait-en">' + esc(t.en) + '</div>';
        h += '<div class="wrt-trait-zh">' + esc(t.zh) + '</div>';
        h += '<div class="wrt-trait-desc">' + esc(t.desc) + '</div>';
        if (t.check && t.check.length) {
          h += '<ul class="wrt-tips">';
          t.check.forEach(function (c) { h += '<li>✓ ' + esc(c) + '</li>'; });
          h += '</ul>';
        }
        h += '</div>';
      });
      h += '</div></details>';
    }

    /* 3. 文体分类 */
    var genres = (W.genres || []).filter(function (g) { return match(g.en + " " + g.zh); });
    if (genres.length) {
      h += '<details class="wrt-sec" open><summary>③ 五种文体 <span class="small">Genre Approach</span></summary>';
      h += '<div class="wrt-genre-list">';
      genres.forEach(function (g) {
        h += '<details class="wrt-genre">';
        h += '<summary><span class="wrt-genre-ic">' + (g.icon || "") + '</span>' +
             '<span class="wrt-genre-en">' + esc(g.en) + '</span>' +
             '<span class="wrt-genre-zh">' + esc(g.zh) + '</span></summary>';
        h += '<div class="wrt-genre-body">';
        if (g.structure && g.structure.length) {
          h += '<div class="wrt-sub">结构</div>';
          h += '<ol class="wrt-steps">';
          g.structure.forEach(function (s) { h += '<li>' + esc(s) + '</li>'; });
          h += '</ol>';
        }
        if (g.frames && g.frames.length) {
          h += '<div class="wrt-sub">句型支架</div>';
          h += '<div class="wrt-frames">';
          g.frames.forEach(function (f) {
            h += '<span class="wrt-frame-item">' + spkBtn(f) + esc(f) + '</span>';
          });
          h += '</div>';
        }
        if (g.sample) {
          h += '<div class="wrt-sub">完整范文</div>';
          h += '<div class="wrt-eg-full">' + esc(g.sample) + spkBtn(g.sample) + '</div>';
        }
        else if (g.example) {
          h += '<div class="wrt-sub">范例</div>';
          h += '<div class="wrt-eg">' + esc(g.example) + spkBtn(g.example) + '</div>';
        }
        h += '</div></details>';
      });
      h += '</div></details>';
    }

    /* 4. 句型支架 + 过渡词 */
    var frames = (W.sentence_frames || []).filter(function (f) { return match(f.level + " " + f.en); });
    var trans = (W.transitions || []).filter(function (t) { return match(t.cat + " " + t.zh); });
    h += '<details class="wrt-sec" open><summary>④ 句型支架 + 过渡词 <span class="small">Sentence Frames & Transitions</span></summary>';
    h += '<div class="wrt-frames-cols">';
    /* 左：句型支架 */
    h += '<div class="wrt-col"><div class="wrt-col-hd">句型（由简到难）</div>';
    frames.forEach(function (f) {
      h += '<div class="wrt-frame-level" style="background:' + f.color + '">';
      h += '<div class="wrt-frame-lv">' + esc(f.level) + ' <span class="small">' + esc(f.en) + '</span></div>';
      h += '<div class="wrt-frames">';
      (f.frames || []).forEach(function (fr) {
        h += '<span class="wrt-frame-item">' + spkBtn(fr) + esc(fr) + '</span>';
      });
      h += '</div></div>';
    });
    h += '</div>';
    /* 右：过渡词 */
    h += '<div class="wrt-col"><div class="wrt-col-hd">过渡词（6 类）</div>';
    trans.forEach(function (t) {
      h += '<div class="wrt-tr-row">';
      h += '<span class="wrt-tr-cat">' + esc(t.cat) + '<span class="small">' + esc(t.zh) + '</span></span>';
      h += '<div class="wrt-tr-words">';
      (t.words || []).forEach(function (w) {
        h += '<span class="wrt-tr-w">' + esc(w) + '</span>';
      });
      h += '</div></div>';
    });
    h += '</div></div></details>';

    /* 5. 检查表 + 练习提示 */
    var chk = (W.checklist || []).filter(function (c) { return match(c.item + " " + c.cat); });
    var prompts = (W.prompts || []).filter(function (p) { return match(p.type + " " + p.en + " " + p.zh); });
    h += '<details class="wrt-sec" open><summary>⑤ 写作检查表 + 练习提示</summary>';
    h += '<div class="wrt-check-cols">';
    h += '<div class="wrt-col"><div class="wrt-col-hd">检查表（写完自查）</div>';
    h += '<div class="wrt-check-list">';
    chk.forEach(function (c) {
      h += '<label class="wrt-check-item"><input type="checkbox"> ' +
           '<span>' + esc(c.item) + '</span> <span class="wrt-check-cat">' + esc(c.cat) + '</span></label>';
    });
    h += '</div></div>';
    h += '<div class="wrt-col"><div class="wrt-col-hd">练习提示（选一个开始写）</div>';
    h += '<div class="wrt-prompt-list">';
    prompts.forEach(function (p) {
      h += '<div class="wrt-prompt">';
      h += '<div class="wrt-prompt-type">' + esc(p.type) + ' <span class="small">' + esc(p.en) + '</span>' +
           ' <span class="wrt-prompt-min">≥' + (p.min_words || 0) + ' 词</span></div>';
      h += '<div class="wrt-prompt-text">' + esc(p.zh) + '</div>';
      h += '</div>';
    });
    h += '</div></div></div></details>';

    /* 6. 写作规范专项 */
    var conv = (W.conventions || []).filter(function (c) { return match(c.topic); });
    if (conv.length) {
      h += '<details class="wrt-sec" open><summary>⑥ 写作规范专项 <span class="small">Conventions & Mechanics</span></summary>';
      h += '<div class="wrt-conv-grid">';
      conv.forEach(function (c) {
        h += '<div class="wrt-conv">';
        h += '<div class="wrt-conv-hd"><span>' + (c.icon || "") + '</span> ' + esc(c.topic) + '</div>';
        if (c.rules && c.rules.length) {
          h += '<ul class="wrt-tips">';
          c.rules.forEach(function (r) { h += '<li>' + esc(r) + '</li>'; });
          h += '</ul>';
        }
        if (c.example) h += '<div class="wrt-conv-ex">' + esc(c.example) + '</div>';
        h += '</div>';
      });
      h += '</div></details>';
    }

    /* 7. 分年级写作指导 */
    var grades = (W.grade_guide || []).filter(function (g) { return match(g.grade + " " + g.focus); });
    if (grades.length) {
      h += '<details class="wrt-sec" open><summary>⑦ 分年级写作指导 <span class="small">Grade-by-Grade Guide</span></summary>';
      h += '<div class="wrt-grade-list">';
      grades.forEach(function (g) {
        h += '<div class="wrt-grade">';
        h += '<div class="wrt-grade-hd"><span class="wrt-grade-ic">' + (g.icon || "") + '</span>' +
             '<span class="wrt-grade-name">' + esc(g.grade) + '</span>' +
             '<span class="wrt-grade-focus">' + esc(g.focus) + '</span></div>';
        h += '<div class="wrt-grade-goal">目标：' + esc(g.goal) + '</div>';
        h += '<div class="wrt-grade-len">篇幅：' + esc(g.length) + '</div>';
        if (g.tips && g.tips.length) {
          h += '<ul class="wrt-tips">';
          g.tips.forEach(function (t) { h += '<li>' + esc(t) + '</li>'; });
          h += '</ul>';
        }
        h += '</div>';
      });
      h += '</div></details>';
    }

    /* 8. 创意写作 */
    var creatives = (W.creative || []).filter(function (c) { return match(c.cat); });
    if (creatives.length) {
      h += '<details class="wrt-sec" open><summary>⑧ 创意写作 <span class="small">Creative Writing · 工坊/游戏/诗歌/话题</span></summary>';
      h += '<div class="wrt-creative">';
      creatives.forEach(function (c) {
        h += '<div class="wrt-creative-cat">';
        h += '<div class="wrt-cat-hd"><span>' + (c.icon || "") + '</span> ' + esc(c.cat) + '</div>';
        h += '<div class="wrt-creative-grid">';
        (c.items || []).forEach(function (it) {
          h += '<div class="wrt-creative-item">';
          h += '<div class="wrt-cret-hd"><span class="wrt-cret-name">' + esc(it.name) + '</span>' +
               '<span class="wrt-cret-en">' + esc(it.en) + '</span></div>';
          h += '<div class="wrt-cret-desc">' + esc(it.desc) + '</div>';
          if (it.frames && it.frames.length) {
            h += '<div class="wrt-sub">句式支架</div>';
            h += '<div class="wrt-frames">';
            it.frames.forEach(function (f) {
              h += '<span class="wrt-frame-item">' + esc(f) + '</span>';
            });
            h += '</div>';
          }
          if (it.example) {
            h += '<div class="wrt-sub">范例</div>';
            h += '<div class="wrt-eg">' + spkBtn(it.example) + esc(it.example) + '</div>';
          }
          h += '</div>';
        });
        h += '</div></div>';
      });
      h += '</div></details>';
    }

    return h;
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
        var lang = (x.language || []).length ?
          '<p class="small">会用到的话</p><div class="words">' +
          x.language.map(function (s) {
            return '<span class="wb">' + spkBtn(String(s || "")) + esc(s) + "</span>";
          }).join("") + "</div>" : "";
        return item('<div class="top"><span class="name">' + esc(x.name) + "</span>" +
          where(x) + (x.type ? '<span class="tag">' + esc(x.type) + "</span>" : "") +
          "</div>" + (x.goal ? '<div class="small">' + esc(x.goal) + "</div>" : "") +
          lang +
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
  function highlightSent(en, words) {
    if (!en) return "";
    if (!words || !words.length) return esc(en);
    // 按出现位置排序，逐个高亮，避免重叠
    var ranges = [];
    words.forEach(function (w) {
      var re = new RegExp("\\b" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "gi");
      var m;
      while ((m = re.exec(en)) !== null) {
        ranges.push({ s: m.index, e: m.index + m[0].length });
      }
    });
    ranges.sort(function (a, b) { return a.s - b.s; });
    // 去重叠（保留最长/最先）
    var out = [], cur = 0;
    ranges.forEach(function (r) {
      if (r.s < cur) return;
      out.push({ s: r.s, e: r.e });
      cur = r.e;
    });
    var html = "", i = 0;
    out.forEach(function (r) {
      html += esc(en.slice(i, r.s)) + '<mark>' + esc(en.slice(r.s, r.e)) + "</mark>";
      i = r.e;
    });
    html += esc(en.slice(i));
    return html;
  }

  function dlgItem(d) {
    var rich = !!(d.vocab_cards && d.vocab_cards.length) ||
               !!(d.sentence_patterns && d.sentence_patterns.length);
    var h = '<div class="item dlg' + (rich ? " rich" : "") + '"><div class="top"><span class="name">' +
      esc(d.title || d.scene || "") + "</span>" + where(d, "") +
      (d.scene ? '<span class="tag">' + esc(d.scene) + "</span>" : "") +
      (d.function ? '<span class="tag d1">' + esc(d.function) + "</span>" : "") + "</div>";

    // 情境图 + 情境旁白
    if (d.scene_desc) {
      var iconMap = { hello: "👋", family: "🏠", weather: "☀️", food: "🍎", numbers: "🔢", school: "🎒" };
      var icon = iconMap[d.scene_icon] || "🎬";
      h += '<div class="scene">' +
        '<div class="scenec">' + icon + '</div>' +
        '<div class="scenet">' + esc(d.scene_desc) + '</div>' +
        '</div>';
      if (d.usage_tags && d.usage_tags.length) {
        h += '<div class="words">' + d.usage_tags.map(function (t) {
          return '<span class="tag k">' + esc(t) + "</span>";
        }).join("") + "</div>";
      }
    }

    if (d.patterns && d.patterns.length) {
      h += '<div class="words">' + d.patterns.map(function (p) {
        return '<span class="wb">' + spkBtn(String(p || "")) + esc(p) + "</span>";
      }).join("") + "</div>";
    }

    var turnsHtml = '<div class="turns">' + (d.turns || []).map(function (t, i) {
      var sent = String(t.en || "");
      var side = t.s === "B" || (t.s || "").indexOf("B") >= 0 ? 2 : 1;
      var emo = t.emo ? '<span class="emo">' + esc(t.emo) + "</span>" : "";
      var rlabel = t.role_label ? '<span class="rlabel">' + esc(t.role_label) + "</span>" : "";
      var enHtml = t.highlights ? highlightSent(sent, t.highlights) : esc(sent);
      return '<div class="turn r' + side + (i ? " hide" : "") + '">' +
        '<div class="turnhead">' +
          '<span class="sp">' + esc(t.s || "A") + "</span>" +
          rlabel + emo +
        '</div>' +
        '<div class="turnline">' + spkBtn(sent) +
          '<span class="en spk">' + enHtml + "</span></div>" +
        '<div class="zh">' + esc(t.zh || "") + "</div>" +
        '</div>';
    }).join("") + "</div>";

    // 词汇 + 句型 + 语法侧栏
    var sideHtml = "";
    if (rich) {
      var sideParts = [];
      if (d.vocab_cards && d.vocab_cards.length) {
        sideParts.push('<div class="sg"><div class="sh">📖 生词</div>' +
          d.vocab_cards.map(function (c) {
            return '<div class="vc">' +
              '<b>' + esc(c.word) + '</b>' +
              (c.ipa ? '<i>' + esc(c.ipa) + '</i>' : "") +
              (c.pos ? '<em>' + esc(c.pos) + '</em>' : "") +
              '<span class="vzh">' + esc(c.zh || "") + '</span>' +
              (c.note ? '<p class="vnote">' + esc(c.note) + '</p>' : "") +
              '</div>';
          }).join("") + '</div>');
      }
      if (d.sentence_patterns && d.sentence_patterns.length) {
        sideParts.push('<div class="sg"><div class="sh">✏️ 句型</div>' +
          d.sentence_patterns.map(function (p) {
            var fill = p.fill ? '<span class="fillbox">' + esc(p.fill) + '</span>' : "";
            var variants = (p.variants || []).map(function (v) {
              return '<span class="var">' + esc(v) + '</span>';
            }).join("");
            var full = p.en.indexOf("__") >= 0
              ? p.en.replace(/_{2,}/g, "<span class='blank'></span>")
              : esc(p.en);
            return '<div class="sp">' +
              '<div class="sptext">' + full + '</div>' +
              '<div class="spzh">' + esc(p.zh || "") + '</div>' +
              (variants ? '<div class="spsp">' + variants + '</div>' : "") +
              '</div>';
          }).join("") + '</div>');
      }
      if (d.grammar_points && d.grammar_points.length) {
        sideParts.push('<div class="sg"><div class="sh">📚 语法</div>' +
          '<ul class="pts">' + d.grammar_points.map(function (g) {
            return "<li>" + esc(g) + "</li>";
          }).join("") + '</ul></div>');
      }
      sideHtml = '<aside class="ds">' + sideParts.join("") + '</aside>';
    }

    var turnsBar = '<div class="bar"><span class="btn next">下一句</span>' +
      '<span class="btn all">全部展开</span>' +
      '<span class="btn zh">遮／显示中文</span></div>';

    if (rich) {
      h += '<div class="dt"><div class="dl">' + turnsHtml + turnsBar + '</div>' + sideHtml + '</div>';
    } else {
      h += turnsHtml + turnsBar;
    }
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
            return '<span class="wb">' + spkBtn(String(x || "")) + esc(x) + "</span>";
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
        return '<span class="wb ex2">' + spkBtn(String(e.en || "")) +
          '<b>' + esc(e.en) + "</b><i>" + esc(e.zh || "") + "</i></span>";
      }).join("") + "</div></div>";
  }

  /* ================================================== 英语 · 听写练习
     三种模式：拼写听写（vocab）/ 句子听写（对话&常用表达）/ 短文填空（passage）。
     10 题一组，右侧错题本，localStorage 记当日进度。 */
  var DICT_KEY = "en-dictation";
  var DICT_ROUND = 10;

  function dictPool(st) {
    // 按 st 抽题池；返回 [{type, answer, hint, ...}]
    var arr = [];
    var vocab = D.vocab || [];
    var dialogues = D.dialogues || [];
    var passages = D.passages || [];
    var exprs = D.exprs || [];
    function ok(x) {
      if (st.book !== "all" && x.book !== st.book) return false;
      if (st.unit !== "all" && String(x.unit_no || "") !== st.unit) return false;
      if (st.topic !== "all" && x.topic !== st.topic) return false;
      if (st.q) {
        var hay = [x.word, x.meaning, x.en, x.zh, x.text, x.name, x.scene, x.function]
          .join(" ").toLowerCase();
        if (hay.indexOf(st.q.toLowerCase()) < 0) return false;
      }
      return true;
    }
    function add(o) { if (o && o.answer && String(o.answer).length >= 2) arr.push(o); }
    if (st.mode === "word") {
      vocab.forEach(function (v) {
        if (!ok(v) || !v.word || !v.meaning) return;
        // 挑战：只给中文；提高：给音标+中文；基础：给音标+中文+例句
        var hint = v.meaning;
        if (st.level !== "hard" && v.phonetic) hint = "/" + v.phonetic.replace(/^\//, "").replace(/\/$/, "") + "/ " + v.meaning;
        add({ type: "word", answer: v.word, hint: hint, phonetic: v.phonetic,
              meaning: v.meaning, example: v.example, book: v.book,
              unit: v.unit, topic: v.topic, tag: v.theme });
      });
    } else if (st.mode === "sentence") {
      var maxLen = st.level === "basic" ? 6 : (st.level === "mid" ? 12 : 99);
      function push(en, zh, meta) {
        if (!en || !zh) return;
        var wc = String(en).split(/\s+/).filter(Boolean).length;
        if (wc < 3 || wc > maxLen) return;
        add({ type: "sentence", answer: en, hint: zh, book: meta.book,
              unit: meta.unit, topic: meta.topic,
              meta: (meta.scene || meta.function || meta.name || "") });
      }
      if (st.level === "basic") {
        exprs.forEach(function (e) { if (ok(e)) push(e.en, e.zh, e); });
      } else if (st.level === "mid") {
        exprs.forEach(function (e) { if (ok(e)) push(e.en, e.zh, e); });
        dialogues.forEach(function (d) {
          if (!ok(d)) return;
          (d.turns || []).forEach(function (t) { push(t.en, t.zh, d); });
        });
      } else {
        dialogues.forEach(function (d) {
          if (!ok(d)) return;
          (d.turns || []).forEach(function (t) { push(t.en, t.zh, d); });
        });
        passages.forEach(function (p) {
          if (!ok(p)) return;
          var first = String(p.text || "").split(/[.!?]/)[0].trim();
          if (first.length >= 20) push(first, String(p.zh || "").split(/[。！？]/)[0], p);
        });
      }
    } else {
      // 短文填空：从 passage 挖 3-5 个 3-8 长度英文词
      passages.forEach(function (p) {
        if (!ok(p)) return;
        var text = String(p.text || "");
        if (text.length < 60) return;
        var words = text.match(/([A-Za-z][A-Za-z']{2,8})/g) || [];
        if (words.length < 3) return;
        var idxs = [], seen = {}, guard = 0;
        var n = Math.min(words.length, 3 + Math.floor(Math.random() * 3));
        while (idxs.length < n && guard++ < 60) {
          var i = Math.floor(Math.random() * words.length);
          var w = words[i];
          if (!seen[w]) { seen[w] = 1; idxs.push(i); }
        }
        if (idxs.length < 2) return;
        var answers = idxs.map(function (i) { return words[i]; });
        add({ type: "passage", passage: text, answers: answers,
              hint: String(p.zh || "").slice(0, 120), name: p.name,
              book: p.book, unit: p.unit, topic: p.topic });
      });
    }
    return arr;
  }

  function dictShell(st) {
    var modeBtns = [
      { id: "word",     label: "拼写听写", icon: "🔤" },
      { id: "sentence", label: "句子听写", icon: "📝" },
      { id: "passage",  label: "短文填空", icon: "📄" }
    ].map(function (m) {
      return '<button class="d-mode' + (m.id === st.mode ? " on" : "") +
        '" data-m="' + m.id + '">' + m.icon + " " + m.label + "</button>";
    }).join("");
    var levels = [
      { id: "basic", label: "基础" },
      { id: "mid",   label: "提高" },
      { id: "hard",  label: "挑战" }
    ];
    var lvOpts = levels.map(function (l) {
      return '<option value="' + l.id + '"' + (l.id === st.level ? " selected" : "") +
        ">" + l.label + "</option>";
    }).join("");
    var books = D.books || [];
    var bkOpts = '<option value="all">全部册次</option>' +
      books.map(function (b) {
        return '<option value="' + esc(b) + '"' + (b === st.book ? " selected" : "") + ">" + esc(b) + "</option>";
      }).join("");
    // 单元/话题动态渲染，见 populateDictFilters
    return '<div class="d-ctl">' +
      '<div class="d-modes">' + modeBtns + "</div>" +
      '<div class="d-filters">' +
      '<select id="d-book">' + bkOpts + "</select>" +
      '<select id="d-unit"><option value="all">全部单元</option></select>' +
      '<select id="d-topic"><option value="all">全部话题</option></select>' +
      '<select id="d-level">' + lvOpts + "</select>" +
      '<input id="d-q" placeholder="关键词（如：dog、family）">' +
      "</div></div>" +
      '<div class="d-body">' +
      '<div class="d-main">' +
      '<div class="d-hdr">' +
      '<span class="d-title">第 <span id="d-idx">1</span> / <span id="d-total">' + DICT_ROUND +
      "</span> 题</span>" +
      '<span class="d-score">已对 <b id="d-right">0</b></span>' +
      '<span class="d-prog"><span id="d-prog" style="width:0%"></span></span>' +
      "</div>" +
      '<div id="d-card" class="d-card"></div>' +
      '<div class="d-nav">' +
      '<button id="d-prev" class="btn-ghost">← 上一题</button>' +
      '<button id="d-skip" class="btn-ghost">跳过</button>' +
      '<button id="d-check" class="btn">判分 →</button>' +
      "</div></div>" +
      '<aside class="d-side">' +
      '<h4>错题本 · <span id="d-wrong-n">0</span></h4>' +
      '<div id="d-wrong" class="d-wrong"><p class="small">做错的题会留在这里，方便回头重做。</p></div>' +
      '<button id="d-redo" class="btn-ghost">重做错题</button>' +
      '<button id="d-new" class="btn">新一组</button>' +
      "</aside></div>";
  }

  function populateDictFilters(st) {
    function unique(arr, key) {
      var s = {}, o = [];
      arr.forEach(function (x) {
        var k = x[key];
        if (k && !s[k]) { s[k] = 1; o.push(k); }
      });
      return o.sort();
    }
    var unitSel = document.getElementById("d-unit");
    var topicSel = document.getElementById("d-topic");
    if (!unitSel || !topicSel) return;
    // 单元：只列当前书（或全部）里的单元
    var units = {};
    (D.vocab || []).concat(D.passages || []).concat(D.dialogues || []).forEach(function (x) {
      if (st.book !== "all" && x.book !== st.book) return;
      if (x.unit_no) units[x.unit_no] = x.unit;
    });
    var uKeys = Object.keys(units).sort(function (a, b) { return +a - +b; });
    unitSel.innerHTML = '<option value="all">全部单元</option>' +
      uKeys.map(function (k) {
        return '<option value="' + k + '"' + (String(st.unit) === String(k) ? " selected" : "") + ">" +
          "U" + k + " · " + esc(units[k] || "") + "</option>";
      }).join("");
    var topics = unique((D.vocab || []).concat(D.passages || []).concat(D.dialogues || []), "topic");
    topicSel.innerHTML = '<option value="all">全部话题</option>' +
      topics.map(function (t) {
        return '<option value="' + esc(t) + '"' + (t === st.topic ? " selected" : "") + ">" + esc(t) + "</option>";
      }).join("");
  }

  function dictCard(item, userAns) {
    var h = "";
    if (item.type === "word") {
      h += '<div class="d-hint"><p class="d-q">听发音，拼出这个单词：</p>' +
        '<p class="d-hint-text"><b>' + esc(item.meaning || "") + "</b>";
      if (item.phonetic && String(st_level()).level !== "hard") {
        h += ' <i>/' + esc(item.phonetic.replace(/^\/|\/$/g, "")) + "/</i>";
      }
      h += "</p>";
      if (item.example) h += '<p class="small">例句：' + esc(item.example) + "</p>";
      h += spkBtn(item.answer);
      h += "</div>";
      h += '<div class="d-input">' +
        '<input id="d-ans" type="text" autocomplete="off" placeholder="输入拼写…" ' +
        'value="' + esc(userAns || "") + '" data-key="0">' +
        "</div>";
    } else if (item.type === "sentence") {
      h += '<div class="d-hint"><p class="d-q">听发音，写出英文原句：</p>' +
        '<p class="d-hint-text">' + esc(item.hint || "") + "</p>";
      if (item.meta) h += '<p class="small">场景：' + esc(item.meta) + "</p>";
      h += spkBtn(item.answer);
      h += "</div>";
      h += '<div class="d-input"><textarea id="d-ans" rows="3" ' +
        'placeholder="写整句…" data-key="0">' + esc(userAns || "") + "</textarea></div>";
    } else if (item.type === "passage") {
      h += '<div class="d-hint"><p class="d-q">听整篇短文，把挖空的关键词按顺序填上：</p>' +
        (item.name ? '<p class="small">' + esc(item.name) + "</p>" : "") +
        "</div>";
      h += '<div class="d-passage">' + paintBlanks(item.passage, item.answers) + "</div>";
      h += '<div class="d-input">' + item.answers.map(function (a, i) {
        return '<div class="d-blank"><span>' + (i + 1) + '.</span>' +
          '<input type="text" placeholder="填空 ' + (i + 1) + '" data-key="' + i + '" ' +
          'value="' + esc((userAns || [])[i] || "") + '" autocomplete="off">' +
          "</div>";
      }).join("") + "</div>";
    }
    return h;
  }

  function st_level() { return DICT_STATE.st; }

  var DICT_STATE = { st: null, round: [], idx: 0, ans: {}, right: 0, wrong: [] };

  function paintBlanks(text, answers) {
    // 把 answers 中每个词的首次出现替换成 ______
    var out = text;
    answers.forEach(function (w) {
      out = out.replace(new RegExp("\\b" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i"),
                        "_______");
    });
    return esc(out);
  }

  function dictFb(item, ok) {
    var h = '<div class="d-fb ' + (ok ? "ok" : "no") + '">';
    if (item.type === "word") {
      h += '<div class="big">' + (ok ? "✅ 正确" : "❌ 不对") + "</div>";
      if (!ok) {
        h += '<div class="d-ans">正确答案：<b>' + esc(item.answer) + "</b>";
        if (item.phonetic) h += " <i>/" + esc(item.phonetic.replace(/^\/|\/$/g, "")) + "/</i>";
        h += "</div>";
      }
    } else if (item.type === "sentence") {
      h += '<div class="big">' + (ok ? "✅ 基本正确" : "对照原句") + "</div>" +
        '<div class="d-ans"><b>' + esc(item.answer) + "</b></div>";
    } else if (item.type === "passage") {
      var user = DICT_STATE.ans[DICT_STATE.idx] || [];
      var per = item.answers.map(function (a, i) {
        var u = (user[i] || "").toLowerCase().trim();
        var ok2 = u === a.toLowerCase();
        return '<span class="' + (ok2 ? "ok" : "no") + '">' + (i + 1) + " · " +
          "你：" + esc(user[i] || "（空）") + " ／ 对：<b>" + esc(a) + "</b></span>";
      });
      h += '<div class="big">' + (ok ? "✅ 全部正确" : "对照答案") + "</div>" +
        '<div class="d-ans-list">' + per.join("") + "</div>";
    }
    return h + "</div>";
  }

  function dictNorm(s) {
    // 判分归一：小写、去首尾空格、把多余空白折叠成单个空格
    return String(s || "").toLowerCase().replace(/[.,;:!?"'()]/g, "").replace(/\s+/g, " ").trim();
  }

  function dictScore(item, ans) {
    // 拼写：严格等
    // 句子：整句归一后相等
    // 短文：所有空都对
    if (item.type === "word") {
      return dictNorm(ans) === dictNorm(item.answer);
    }
    if (item.type === "sentence") {
      return dictNorm(ans) === dictNorm(item.answer);
    }
    if (item.type === "passage") {
      var a = ans || [];
      return item.answers.every(function (x, i) {
        return dictNorm(a[i]) === dictNorm(x);
      });
    }
    return false;
  }

  function renderDictation() {
    var st = { mode: "word", book: "all", unit: "all", topic: "all", level: "basic", q: "" };
    DICT_STATE.st = st;
    var root = document.createElement("div");
    root.className = "dictation";
    root.innerHTML = dictShell(st);
    app.appendChild(root);
    loadTtsMap();   // 预热 TTS

    function rebuild() {
      populateDictFilters(st);
      var pool = dictPool(st);
      // 洗牌取 10 题；如果池子不足就有多少用多少
      pool.sort(function () { return Math.random() - 0.5; });
      DICT_STATE.round = pool.slice(0, DICT_ROUND);
      DICT_STATE.idx = 0;
      DICT_STATE.ans = {};
      DICT_STATE.right = 0;
      DICT_STATE.wrong = [];
      paintCard();
    }
    function paintCard() {
      var total = DICT_STATE.round.length;
      var idx = DICT_STATE.idx;
      var item = DICT_STATE.round[idx];
      var card = document.getElementById("d-card");
      var totalEl = document.getElementById("d-total");
      var idxEl = document.getElementById("d-idx");
      var rightEl = document.getElementById("d-right");
      var progEl = document.getElementById("d-prog");
      var prevBtn = document.getElementById("d-prev");
      var checkBtn = document.getElementById("d-check");
      if (!card) return;
      totalEl.textContent = total;
      idxEl.textContent = idx + 1;
      rightEl.textContent = DICT_STATE.right;
      progEl.style.width = (idx / Math.max(1, total) * 100) + "%";
      prevBtn.disabled = idx === 0;
      checkBtn.textContent = (idx === total - 1) ? "判分并结束" : "判分 →";
      if (!item) {
        card.innerHTML = '<div class="big">🎉 完成</div>' +
          '<p class="small">本轮共 ' + total + " 题，答对 " + DICT_STATE.right + " 题（" +
          (total ? Math.round(DICT_STATE.right / total * 100) : 0) + "%）</p>";
        paintWrong();
        return;
      }
      card.innerHTML = dictCard(item, DICT_STATE.ans[idx]) +
        (DICT_STATE.ans[idx + "_ok"] != null
          ? dictFb(item, DICT_STATE.ans[idx + "_ok"]) : "");
      var inp = card.querySelector('[data-key="0"]');
      if (inp) {
        inp.focus();
        inp.addEventListener("keydown", function (e) {
          if (e.key === "Enter") { e.preventDefault(); doCheck(); }
        });
      } else {
        // 短文：最后一个输入框回车触发
        var inputs = card.querySelectorAll('input[data-key]');
        inputs.forEach(function (inp, i) {
          inp.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
              e.preventDefault();
              if (i === inputs.length - 1) doCheck();
            }
          });
        });
      }
    }
    function paintWrong() {
      var box = document.getElementById("d-wrong");
      var n = document.getElementById("d-wrong-n");
      var redoBtn = document.getElementById("d-redo");
      if (!box) return;
      n.textContent = DICT_STATE.wrong.length;
      redoBtn.style.display = DICT_STATE.wrong.length ? "" : "none";
      if (!DICT_STATE.wrong.length) {
        box.innerHTML = '<p class="small">做错的题会留在这里，方便回头重做。</p>';
        return;
      }
      box.innerHTML = DICT_STATE.wrong.slice(0, 30).map(function (w, i) {
        var label = w.item.type === "word" ? "词" : (w.item.type === "sentence" ? "句" : "文");
        return '<div class="w-item"><b>' + label + "</b> " +
          esc(w.item.answer || w.item.answers.join(" / ")) + "</div>";
      }).join("");
    }
    function collectAns() {
      var card = document.getElementById("d-card");
      if (!card) return null;
      var item = DICT_STATE.round[DICT_STATE.idx];
      if (!item) return null;
      if (item.type === "passage") {
        var inputs = card.querySelectorAll('input[data-key]');
        var a = [];
        inputs.forEach(function (inp) { a.push(inp.value); });
        return a;
      }
      var inp = card.querySelector('[data-key="0"]');
      return inp ? inp.value : "";
    }
    function doCheck() {
      var ans = collectAns();
      if (ans == null) return;
      var item = DICT_STATE.round[DICT_STATE.idx];
      DICT_STATE.ans[DICT_STATE.idx] = ans;
      var ok = dictScore(item, ans);
      DICT_STATE.ans[DICT_STATE.idx + "_ok"] = ok;
      if (ok) DICT_STATE.right++;
      else DICT_STATE.wrong.push({ item: item, userAns: ans });
      paintCard();
      paintWrong();
      // 稍后自动跳到下一题
      setTimeout(function () {
        if (DICT_STATE.idx < DICT_STATE.round.length - 1) {
          DICT_STATE.idx++;
          paintCard();
        }
      }, 900);
    }
    // 事件绑定
    root.addEventListener("click", function (e) {
      var m = e.target.closest(".d-mode");
      if (m) {
        st.mode = m.dataset.m;
        [].forEach.call(root.querySelectorAll(".d-mode"), function (b) {
          b.classList.toggle("on", b === m);
        });
        rebuild();
        return;
      }
      if (e.target.id === "d-check") { doCheck(); return; }
      if (e.target.id === "d-prev") {
        if (DICT_STATE.idx > 0) { DICT_STATE.idx--; paintCard(); }
        return;
      }
      if (e.target.id === "d-skip") {
        DICT_STATE.ans[DICT_STATE.idx] = null;
        DICT_STATE.ans[DICT_STATE.idx + "_ok"] = false;
        DICT_STATE.wrong.push({ item: DICT_STATE.round[DICT_STATE.idx], userAns: null });
        DICT_STATE.idx = Math.min(DICT_STATE.round.length, DICT_STATE.idx + 1);
        paintCard(); paintWrong();
        return;
      }
      if (e.target.id === "d-new") { rebuild(); return; }
      if (e.target.id === "d-redo") {
        // 用错题组一轮新的
        var items = DICT_STATE.wrong.map(function (w) { return w.item; });
        items.sort(function () { return Math.random() - 0.5; });
        DICT_STATE.round = items.slice(0, DICT_ROUND);
        DICT_STATE.idx = 0;
        DICT_STATE.ans = {};
        DICT_STATE.right = 0;
        DICT_STATE.wrong = [];
        paintCard(); paintWrong();
        return;
      }
    });
    root.addEventListener("change", function (e) {
      var t = e.target;
      if (t.id === "d-book") st.book = t.value;
      else if (t.id === "d-unit") st.unit = t.value;
      else if (t.id === "d-topic") st.topic = t.value;
      else if (t.id === "d-level") st.level = t.value;
      else return;
      rebuild();
    });
    root.addEventListener("input", function (e) {
      if (e.target.id === "d-q") {
        st.q = e.target.value.trim();
        clearTimeout(root._t);
        root._t = setTimeout(rebuild, 250);
      }
    });
    rebuild();
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

  /* ---- 音色选择器：只挂在英语页顶部。选后写 localStorage，点按钮试听当前音色 ---- */
  var VOICE_LIST = [
    { id: "alan",  label: "Alan · 英音男",  emoji: "🎤" },
    { id: "jenny", label: "Jenny · 英音女", emoji: "🎤" },
    { id: "amy",   label: "Amy · 美音女",   emoji: "🎤" },
    { id: "cori",  label: "Cori · 高质量英音", emoji: "🎤" }
  ];
  if (subject === "english") {
    // 提前加载一次，别等第一次点才拉（避免第一下点读无声音）
    loadTtsMap();
    var bar = document.createElement("div");
    bar.className = "tools tts-voice-bar";
    var opts = VOICE_LIST.map(function (v) {
      var sel = (v.id === currentVoice) ? " selected" : "";
      return '<option value="' + v.id + '"' + sel + '>' +
             esc(v.emoji + " " + v.label) + "</option>";
    }).join("");
    bar.innerHTML =
      '<span class="tv-label">朗读音色</span>' +
      '<select id="ttsVoiceSel">' + opts + '</select>' +
      '<button id="ttsVoiceTry" title="试听当前音色">▶ 试听</button>' +
      '<span class="tv-note" id="ttsVoiceNote"></span>';
    if (app.firstChild) app.insertBefore(bar, app.firstChild);
    else app.appendChild(bar);
    var sel = document.getElementById("ttsVoiceSel");
    var btn = document.getElementById("ttsVoiceTry");
    var note = document.getElementById("ttsVoiceNote");
    function updateNote() {
      var v = VOICE_LIST.filter(function (x) { return x.id === currentVoice; })[0];
      if (note) note.textContent = v ? ("当前：" + v.label) : "";
    }
    sel.addEventListener("change", function () {
      setVoice(sel.value);
      updateNote();
    });
    btn.addEventListener("click", function () {
      ttsPreview(currentVoice);
    });
    updateNote();
  }

  if (kind === "problem") renderProblem();
  else if (kind === "structure") renderStructure();
  else if (kind === "speak") renderSpeak();
  else if (kind === "dictation") renderDictation();
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
