/* 冒烟：逐个页面跑一遍 app.js（用页面里内联的真实数据），确认渲染出内容、不抛异常。
   用法：node _smoke.js [文件 ...]，不给参数就遍历 pages/**\/*.html */

const fs = require("fs");
const path = require("path");

class El {
  constructor(tag) {
    this.tag = tag; this.children = []; this.innerHTML = ""; this.textContent = "";
    this.className = ""; this.dataset = {}; this.value = "all";
    this.classList = { add() {}, remove() {}, toggle() {} };
  }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener() {}
  querySelectorAll() { return []; }
  querySelector() { return null; }
  closest() { return null; }
}

function walk(dir, out) {
  fs.readdirSync(dir).forEach((f) => {
    const p = path.join(dir, f);
    if (fs.statSync(p).isDirectory()) { if (f !== "assets" && f !== "data") walk(p, out); }
    else if (f.endsWith(".html")) out.push(p);
  });
  return out;
}

let files = process.argv.slice(2);
if (!files.length) files = walk("pages", []).sort();

let bad = 0;
files.forEach((file) => {
  const html = fs.readFileSync(file, "utf8");
  const pm = html.match(/data-page="([^"]+)"/);
  const dm = html.match(/window\.DATA=([\s\S]*?);<\/script>/);
  if (!pm || !dm) { console.log("×", file, "缺少 page/DATA"); bad++; return; }
  const page = pm[1];
  let data;
  try { data = JSON.parse(dm[1].replace(/<\\\//g, "</")); }
  catch (e) { console.log("×", file, "DATA 解析失败", e.message); bad++; return; }

  const app = new El("div");
  const byId = { app, cnt: new El("span"), q: new El("input"),
                 bk: new El("select"), ex: new El("select") };
  global.document = {
    body: { dataset: { page }, classList: { toggle() {} },
            getAttribute: (k) => (k === "data-page" ? page : null) },
    getElementById: (id) => byId[id] || new El("div"),
    createElement: (t) => new El(t),
    querySelectorAll: () => [],
    querySelector: () => null,
    addEventListener() {},
    readyState: "complete",
  };
  global.window = { DATA: data, addEventListener() {},
                    location: { pathname: "/" + file, href: "" } };
  global.Event = function (t, o) { this.type = t; this.bubbles = !!(o && o.bubbles); };
  delete require.cache[require.resolve("./pages/assets/app.js")];

  let out = "";
  try {
    require("./pages/assets/app.js");
    out = app.innerHTML + app.children.map((c) => c.innerHTML || "").join("");
  } catch (e) {
    console.log("×", file, "渲染抛错：", e.message);
    bad++;
    return;
  }
  const size = (fs.statSync(file).size / 1024).toFixed(0);
  // 站点首页内容写在 body 里，不由 JS 渲染
  const ok = out.length || page === "index";
  console.log("%s %s  页面 %sKB  渲染 %sKB%s",
    ok ? "√" : "×", page, size, (out.length / 1024).toFixed(0),
    ok ? "" : "  （空！）");
  if (!ok) bad++;
});

console.log(bad ? "\n有 " + bad + " 个页面有问题" : "\n全部页面渲染正常");
process.exit(bad ? 1 : 0);
