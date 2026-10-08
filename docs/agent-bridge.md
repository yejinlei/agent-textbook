# 宿主接口说明（Agent / 语音 / 朗读）

页面除了能用鼠标点，还能被外面驱动：控制台里的 `window.AT`、嵌在 iframe 里时的
`postMessage`。两条路走的是**同一套动作**（`execute(action, params)`），
所以接 Agent 时不用另外写一套页面逻辑，只要会发动作名和参数。

## 一、页面内 API

```js
AT.actions()            // 列出所有动作（名称、参数、说明）
AT.execute(name, params) // 执行，返回 {ok, data} 或 {ok:false, error}
AT.state()              // 当前：学科、专题、筛选条件、可见条数
AT.query({q, limit})    // 在本页数据里检索，返回 [{pool, idx, title, where}]
AT.items()              // 当前渲染出来的条目（DOM），带 data-idx
AT.data()               // 本页内联数据（只读用）
AT.on(ev, fn) / AT.off(ev, fn)   // 订阅事件：ready / render / action / asr.result / tts.state
AT.asr / AT.tts         // 听写与朗读
```

### 动作表

| 动作 | 参数 | 作用 |
|---|---|---|
| `search` | `{q}` | 按关键词筛选（写进搜索框，和人敲字完全一样） |
| `filter` | `{book?, extra?, tab?}` | 按册次／附加条件／页签筛选 |
| `set` | `{id, value, evt?}` | 直接给控件设值并触发事件（滑块、下拉都行） |
| `click` | `{selector}` | 点页面上的东西（页签、标签、跳转） |
| `query` | `{q, limit?}` | 在本页数据里检索 |
| `open` | `{idx}` | 展开第 idx 条里的折叠内容（详解、分步） |
| `highlight` | `{idx}` | 滚动到第 idx 条并高亮 |
| `read` | `{idx?｜text?｜selector?}` | 朗读：默认读第 idx 条 |
| `speak` | `{text}` | 朗读任意文本 |
| `listen` | `{on, target?}` | 听写开关，识别结果写进 `target`（默认搜索框 `q`） |
| `goto` | `{subject?, slug?}` | 跳到某个学科／专题页 |
| `state` / `actions` | `{}` | 读状态 / 列动作 |

```js
AT.execute("search", { q: "圆" });       // 搜"圆"
AT.execute("highlight", { idx: 3 });     // 定位到第 4 条
AT.execute("read", { idx: 0 });          // 读第一条
AT.execute("listen", { on: true });      // 开始听写，说完自动搜
```

## 二、嵌在 iframe 里（Agent 面板操作页面）

页面 → 父窗口：

```js
{ source: "agent-textbook", type: "ready",  actions: [...], page: {...} }
{ source: "agent-textbook", type: "event",  ev: "render"｜"action"｜"asr.result"｜..., data }
{ source: "agent-textbook", type: "result", id, ok, data }      // 动作的执行结果
{ source: "agent-textbook", type: "asr.request", action: "asr.start"｜"asr.stop" }
{ source: "agent-textbook", type: "tts.request", action: "tts.speak", text, lang }
```

父窗口 → 页面：

```js
{ action: "search", params: { q: "分数" }, id: 7 }   // → 回 {type:"result", id:7, ok:true}
{ action: "asr.result", text: "圆的面积", final: true }
{ action: "asr.state", running: true }
```

页面自己没有麦克风／语音能力时，会把 `asr.request` / `tts.request` 发给父窗口，
由外面接自己的服务，再把结果按上面的格式发回来。

## 三、语音（ASR / TTS）：只留接口，实现可换

默认实现用的是浏览器自带的识别与合成；没装、不支持就自动降级（不报错、不影响页面）。

换成自己的服务，三种接法任选：

```js
// 1) 直接替换 adapter（同一页面里）
AT.asr.adapter = { start(opt){ ... }, stop(){ ... } };   // 结果用 AT.asr.push(text, final) 回传
AT.tts.adapter = { speak(text, opt){ ... }, stop(){ ... } };

// 2) 只挂回调，看识别到了什么
AT.asr.onResult = (text, final) => console.log(text);

// 3) 页面嵌在 iframe 里：由父窗口提供（见上一节的 asr.request）

// 常用参数
AT.asr.lang = "zh-CN"; AT.asr.target = "q";   // 识别结果落到搜索框
AT.tts.rate = 1; AT.tts.lang = "zh-CN";
```

## 四、自检

```bash
node tools/check-bridge.js                      # 用数学首页跑一遍接口
node tools/check-bridge.js pages/chinese/poetry.html
node _smoke.js                                  # 所有页面的渲染冒烟
```
