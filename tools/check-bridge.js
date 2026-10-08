/* 自检宿主接口：Agent / ASR / TTS 那条链路是不是通的。
   用页面里内联的真实数据跑一遍动作，不改页面、不联网。
   用法：node tools/check-bridge.js [页面.html]，默认 pages/math/all.html */

const fs = require("fs");
const path = require("path");

const file = process.argv[2] || path.join("pages", "math", "index.html");

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
  dispatchEvent() { return true; }
}

const html = fs.readFileSync(file, "utf8");
const page = (html.match(/data-page="([^"]+)"/) || [])[1] || "";
const dm = html.match(/window\.DATA=([\s\S]*?);<\/script>/);
if (!dm) { console.log("× 没取到页面数据：", file); process.exit(1); }
const data = JSON.parse(dm[1].replace(/<\\\//g, "</"));

const app = new El("div");
const byId = { app, cnt: new El("span"), q: new El("input"), bk: new El("select") };
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
                  location: { pathname: "/" + file.replace(/\\/g, "/"), href: "" } };
global.Event = function (t, o) { this.type = t; this.bubbles = !!(o && o.bubbles); };

require(path.resolve("pages", "assets", "app.js"));

const AT = global.window.AT;
let bad = 0;

function check(name, fn) {
  let r;
  try { r = fn(); } catch (e) { console.log("×", name, e.message); bad++; return; }
  console.log(r ? "√" : "×", name, r === true ? "" : JSON.stringify(r).slice(0, 90));
  if (!r) bad++;
}

console.log("页面：%s（%s）", file, page);
check("window.AT 已挂上", () => !!AT);
check("动作清单", () => AT.actions().length >= 10 && AT.actions().length);
check("state 能读出学科与筛选", () => AT.state().subject === page.split("-")[0] && AT.state().subject);
check("execute:state", () => AT.execute("state").ok);
check("execute:actions", () => AT.execute("actions").ok);
check("execute:search（写进搜索框）", () => AT.execute("search", { q: "圆" }).ok);
check("execute:query（检索本页数据）", () => AT.execute("query", { q: "圆", limit: 3 }).ok);
check("execute:set（设控件）", () => AT.execute("set", { id: "bk", value: "all", evt: "change" }).ok);
check("未知动作要有报错", () => AT.execute("no-such-action").ok === false);
check("ASR 有降级处理（没识别能力也不崩）", () => AT.execute("listen", { on: true }).ok !== undefined);
check("TTS 有降级处理（没合成能力也不崩）", () => AT.execute("speak", { text: "圆的面积" }).ok !== undefined);

// 事件总线：订阅后执行动作应收到通知
let got = 0;
AT.on("action", () => { got++; });
AT.execute("search", { q: "分数" });
check("事件总线能收到动作", () => got > 0 && got);

console.log(bad ? "\n有 " + bad + " 项没通过" : "\n宿主接口全部通过");
process.exit(bad ? 1 : 0);
