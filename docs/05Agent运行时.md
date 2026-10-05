# 05 Agent 运行时

> 由 `系统设计文档.md` 拆分而来（原 §8.1–§8.10：编排、工具、Guard、展示层）。
> 文中 `§N` 沿用原章节编号，跨文件定位见 `00文档索引.md`。

---

## 8. 阶段四：多 Agent 设计（核心）

### 8.1 为什么需要多 Agent

不是为了"多才显得智能"，而是四个具体问题：

1. **任务差异大**：讲解、解题、出题、批改、作文指导的提示词、输出格式、检索策略完全不同。塞进一个万能 prompt 会互相干扰。
2. **学科差异大**：语文作文和数学解题的"正确"定义不同（见 §9）。
3. **防幻觉需要独立裁判**：让生成答案的 Agent 自查编造，等于运动员兼裁判。
4. **对象适配**：同一知识点给一年级和六年级的讲法不同；给孩子的讲法和给家长的辅导话术也不同。

### 8.2 角色清单

| Agent | 职责 | 是否需 LLM | 说明 |
| --- | --- | --- | --- |
| **Router 调度** | 判断 `subject + capability + scope`（语文·字词 / 数学·解题 / 语文·习作 …） | 小模型或规则 | 作用域缺失则 `ask_user` 追问 |
| **Planner 检索规划** | 拆检索计划：查表 / 语义 / 整篇课文；查询改写；是否跨册 | 是（小模型） | 一题多问时拆成多个子查询 |
| **Retriever 检索** | 执行检索，返回带页码片段 | 否 | 确定性，可缓存 |
| **Teacher 主讲** | 按 `年级 × 学科` 话术讲解；解题时输出分步链 | 是（主模型） | 事实句带 `[册次·页码]` |
| **Quizzer 出题** | 按课/知识点出题，附答案与出处 | 是 | 两阶段：先定题型分布，再逐题生成 |
| **Grader 批改** | 判分 + 错因归因（数学按 `MistakeType`）+ 建议 | 部分 | **判对错用规则**（字词/计算），**解释错因用 LLM** |
| **Guard 校验** ★ | 按模式校验，见 §9.2 | 是（小模型）或规则 | **硬约束执行者**，独立于 Teacher |
| **Coach 陪练** | 鼓励式、分步提示、不直接给答案 | 是 | 用于做题过程中的引导 |
| **Assistant 助教** ★ | 课文学习/课堂场景中的辅学：沿途提问、检查理解、阶段小结、提示下一步 | 是（小模型） | 与 Teacher 分工：**Teacher 主讲，Assistant 互动与检查**；二者结论必须一致（不设"各执一词的 AI 同学"） |
| **Parent 家长视角** | 转成家长可用的辅导话术 + 易错点提示 | 是 | 同一内容的不同受众 |
| **Learner 学情** | 记录错题、更新掌握度与错因分布 | 否（规则） | 写 L1 事件 + L2 画像 |

### 8.3 Agent Runtime（借鉴 DeepTutor）

所有能力共享**一个循环**，不同能力是不同的 pipeline 编排：

```python
def run(turn: Turn) -> Answer:
    profile = subjects[turn.subject]              # 学科 Profile 决定工具与 Guard 模式
    tools   = mount_tools(profile, turn.capability)
    for round in range(MAX_ROUNDS):               # 建议 6
        msg = llm.chat(messages, tools=tools)     # think
        if not msg.tool_calls:
            return finalize(msg)                  # 不带工具调用的消息 = 结束
        for call in msg.tool_calls:
            if call.name == "ask_user":           # 暂停回合，追问后恢复
                return pause_and_ask(call.args)
            messages.append(tool_result(call))    # observe
    return Answer(refused=True)                   # 超轮次：保守拒答
```

要点：

- **工具按学科 + 能力挂载**：数学挂 `gen_mental_math`、`check_answer`；语文挂 `lookup_word`、`read_lesson`。不一次性塞满。
- **上下文两类**：*sticky*（年级、学科、版本、册次、persona、学情、当前课）跨回合持久；*one-time*（某页、某题、某篇课文）单次注入。
- **超轮次即拒答**（事实类）；创作类不适用拒答，见 §9.2。

### 8.4 工具集

| 工具 | 作用 | 主要学科 |
| --- | --- | --- |
| `search_textbook(query, scope, top_k)` | 混合检索，返回带页码片段 | 全部 |
| `read_page(book_id, page_no)` | 读指定页原文（引用核对） | 全部 |
| `read_lesson(book_id, lesson)` | **整篇课文** | 语文 |
| `lookup_word(char, scope)` | **精确查字**（拼音/部首/笔画/组词/近反义/多音字） | 语文 |
| `lookup_problem(kp_id, type)` | 按知识点与类型找题（例题优先） | 数学 |
| `gen_mental_math(grade, n)` | **口算题程序化生成**（不走检索、不调 LLM） | 数学 |
| `check_answer(question, answer)` | **确定性判题**（字词、计算），不用 LLM | 语文/数学 |
| `get_rubric(book_id, unit)` | 取习作要求与评分量规 | 语文 |
| `list_lessons(scope)` | 列单元/课大纲（支撑两阶段生成） | 全部 |
| `get_knowledge_point(kp_id)` | 知识点定义、出现册次、先修关系 | 全部 |
| `read_memory() / write_memory()` | 读/写学情 | 全部 |
| `ask_user(question)` | 暂停并追问澄清 | 全部 |
| `parse_sheet(file)` ★ | **练习卷 VLM 提取**（题号/题干/作答），返回待确认条目 | 全部 |
| `diagnose(sheet_ids[])` ★ | 判分 + 归因 + 跨卷聚合（按课 / 知识点 / 错因） | 全部 |
| `make_plan(learner, scope)` ★ | 生成提升计划（回看哪课 / 练什么 / 何时复测） | 全部 |

### 8.5 协作模式

**① 管线式（答疑 / 讲解 / 解题）**

```
Router → Planner → Retriever → Teacher → Guard(按模式) → 输出
                                  ↑         │
                                  └─────────┘ 不通过则重写（≤2 轮）
```

**② 角色切换式（同一 loop 换 persona）**

```
讲解 → Teacher（讲清楚）
陪练 → Coach（分步提示，不直接给答案）
家长 → Parent（辅导话术 + 易错点）
```

**③ 对抗校验式（Guard）**：见 §9.2 三模式。

**④ 导师引导式（★ 交互式，最适合教学）**
不是"生成一份答案"，而是**一步步带着孩子走**：先问"你觉得第一步该做什么" → 依据回答给提示 →
卡住才给下一步 → 结束时给"你哪里卡住了"的小结并写学情。

```
Teacher 讲解 ⇄ Coach 陪练 ⇄ Assistant 追问
   每一步的提示都来自教材锚点（例题 / 课文段落 / 习作要求）
```

硬规则：**不主动给最终答案**；同一处卡住 3 次才降级给下一步提示；结束必须产出小结（供 Parent 与学情用）。
适用：解题（数学 derivation）、习作支架、课文精读、阅读理解定位。

### 8.6 成本与延迟控制

| 手段 | 做法 |
| --- | --- |
| 小模型下沉 | Router / Planner / Guard 用轻量模型，主模型只给 Teacher |
| 能规则就不用 LLM | 字词判对错、计算判分、口算生成、查表全部确定性实现 |
| Retriever 不调 LLM | 仅 Planner 做查询改写时用一次 |
| Guard 分级 | 先规则校验，抽样或小模型复核 |
| 缓存 | 同 `scope + question` 命中直接返回 |
| 轮次上限 | ≤ 6 轮，超了保守拒答 |

**目标**：一次普通问答 ≤ 3 次 LLM 调用；**字词查询与口算练习 0 次 LLM 调用**。

### 8.7 接口

```python
def run_turn(turn: Turn) -> Answer

def ask(question: str, scope: dict) -> Answer          # 答疑/概念讲解（strict）
def solve(problem: str, scope: dict) -> Solution        # 数学解题（derivation）
def drill(scope: dict, lesson: str, n: int) -> list[Question]
def grade(answers: list[str], questions: list[Question]) -> list[Result]
def guide_writing(task: str, scope: dict) -> WritingGuide  # 习作指导（rubric）
def plan(scope: dict, learner: str) -> StudyPlan       # 针对性复习计划

# 教学形态能力（对应 DeepTutor capability，教材限定版）
def read_lesson_interactive(book_id, lesson, learner) -> LessonSession  # 沉浸式课文学习：分段讲 + 沿途提问
def mastery_path(scope: dict, learner: str) -> MasteryPath              # 掌握度路径：按要素/知识点设闸门
def research_in_book(query: str, scope: dict) -> ResearchResult         # 教材内探究（不引课外语料）
def visualize(problem: str, scope: dict) -> Figure                      # 数学/科学图形可视化（SVG/互动 HTML）

# Solution: {steps:[{text, basis: 页码|推导}], answer, check: 验算结果}
# Answer:   {text, citations:[(book_id, page_no, snippet)], refused: bool, guard_report}
```

```powershell
python -m agent_textbook ask "分数是什么意思" --grade 三年级 --subject 数学
python -m agent_textbook solve "25×4÷5=?" --grade 三年级 --subject 数学
python -m agent_textbook drill --grade 三年级 --subject 数学 --lesson 分数的初步认识
python -m agent_textbook write --grade 四年级 --subject 语文 --unit 习作：记一次游戏
python -m agent_textbook memory show --learner 小明
```

---

## 8.8 展示层：同一内容，多种呈现（★）

输出形态不止文字：可以是 **PPT、视频、播客、动画、游戏，也可以是 Agent 扮演导师一步步引导**。
但绝不能"每种形态各生成一遍"——那会导致 PPT 里讲的和文字答的不一样，成本也翻几倍。

### 8.8.1 原则：内容与呈现分离

Agent 只产出**一份结构化内容**（`ContentPlan`：教学目标、环节、讲解要点、例子、提问、引用与 tier），
再由渲染器翻译成各形态：

```
Planner/Teacher → ContentPlan（结构化，已过 Guard，带引用）
                     ├─ 文字渲染器       → Markdown / 终端（默认）
                     ├─ 幻灯片渲染器     → .pptx
                     ├─ 播客渲染器       → TTS 脚本 → 音频
                     ├─ 视频渲染器       → 幻灯片图片 + 音频 + 字幕 → .mp4
                     ├─ 互动 HTML 渲染器 → 单文件 HTML（点击展开、自测）
                     ├─ 动画渲染器       → 参数化 SVG / Canvas 动画（数学主力）
                     ├─ 游戏渲染器       → 本地小游戏（口算闯关、拖拽解题）
                     └─ 引导式会话       → 不渲染，直接多轮对话（导师模式）
```

三个好处：① 各形态内容一致；② 换形态不重跑 LLM；③ **引用与 Guard 只在内容层做一次**。

### 8.8.2 形态矩阵

| 形态 | 适合场景 | 技术 | 单机成本 | 优先级 |
| --- | --- | --- | --- | --- |
| **文字 + 引用** | 答疑、字词、解题（默认） | Markdown | 0 | **P0** |
| **导师引导（交互）** | 解题陪练、习作支架、课文精读——一步步问、不给答案 | 多轮对话，无渲染 | **0** | **P0** |
| **动画** ★ | **数学**：分数切分、线段图、几何变换、面积模型 | 参数化 SVG / Canvas + 模板 | 低（模板化） | **P0（数学）** |
| **游戏化练习** ★ | **数学**：口算闯关、连线、拖拽、即时反馈 | 本地 JS 模板 + 程序生成题目 | **0（不调 LLM）** | **P0（数学）** |
| 幻灯片 PPT | 讲一课、单元梳理、给家长讲解 | `python-pptx` | 低（秒级） | P1 |
| 播客 / 音频 | 语文朗读、听写、复习、路上听、**护眼** | `edge-tts` + `ffmpeg` | 低 | P1 |
| 互动 HTML | 课文精读、自测、点击展开 | 单文件 HTML + JS | 低 | P1 |
| 视频 | 讲一课（画面 + 讲解 + 字幕） | 图片 + TTS + `ffmpeg` | **高**（分钟级） | P2 |

### 8.8.3 关键：展示形态也要按学科差异化（★）

语文用朗读和文本效果好，**不代表数学也该这样**——两个学科的认知对象根本不同：

| 学科 | 认知对象 | 首选形态 | 为什么不这样就不行 |
| --- | --- | --- | --- |
| **语文** | 文本与意义 | 文字 + 朗读（播客）+ 导师引导 + 作家作品集 | 语言靠"听"和"读"习得；作文靠**可模仿的样本**（见 6.8.5 汪曾祺例） |
| **数学** | **关系与变化过程** | **动画 + 游戏化 + 分步引导** | "怎么分的、怎么变的、怎么推的"是**过程**，静态文字讲不清 |
| 科学 | 动作序列与现象 | 实验装置图 + 步骤动画 + 安全提示 | 探究是"先做什么后做什么"，可视化即流程 |
| 英语 | 语音与对话 | 音频跟读 + 角色扮演 | 语音优先，文本次之 |
| 道法 | 情境与价值判断 | 情境卡片 + 引导式提问 | 靠情境触发判断，不是靠讲解 |

**数学为什么必须是动画**：同一个知识点，两种呈现的差距是数量级的——

| 知识点 | 文字讲解 | 动画 |
| --- | --- | --- |
| 为什么除以分数等于乘倒数 | 需 200 字推导，三年级孩子读完仍然懵 | 把 `2 ÷ 1/2` 做成"2 个饼里能切出几个半块"——**3 秒看懂** |
| 和差问题 | 抽象关系，容易记成公式 | 线段图动画：长线段截去一段，剩多少一目了然 |
| 三角形内角和 180° | 记住结论，不理解 | 拖动三个角拼成一条直线 |
| 分数大小比较 | 通分后比分子（机械） | 两块同样大的饼切不同份数，取出来比 |

即：**数学的可视化不是装饰，是理解本身**。

**游戏化为什么对数学特别有效**：数学练习是**高频、可判定、可进阶**的——
题目由 `gen_mental_math` 程序化生成（**0 次 LLM 调用**），前端加计时、连击、关卡、即时反馈即可，
成本为零且天然适配错题归因（错了就推同型题再战，见 §9.4 错因分类）。

### 8.8.4 小学生场景的特殊取舍

| 约束 | 结论 |
| --- | --- |
| **护眼** | 音频（播客）比视频更适合"多讲几遍"——这是与 OpenMAIC 最大的分歧点：成人 MOOC 可长时间看视频，小学生不行；视频控制在 3–5 分钟 |
| **拼音与朗读** | 低年级要注音 + 朗读；拼音来自教材文本层（准确率 100%），TTS 只负责读，不让它猜声调 |
| **游戏化要有度** | 目标是练，不是玩：单局 3–5 分钟、与错题归因绑定、不给无限奖励机制（避免本末倒置） |
| **动画必须正确** | 动画参数化、模板化（数值来自教材例题），**不自由生成图形**——画错的分数动画比不画更糟 |
| **可核对** | 每种形态都能回到教材页码：PPT 页脚标引用、音频口播"书上第 X 页"、动画角落标例题出处 |

### 8.8.5 落地顺序

```
P0  文字 + 导师引导 +（数学）动画模板 + 游戏化练习     零成本或模板化，最贴近教学本质
P1  PPT + 播客 + 互动 HTML                            成本都很低
P2  视频                                              合成慢、屏幕时间代价高，按需做
```

新增依赖（按形态启用）：

```
python-pptx>=0.6.23   # 幻灯片（纯 Python）
edge-tts>=6.1         # 中文 TTS；离线兜底 pyttsx3
ffmpeg                # 音频拼接与视频合成（外部二进制）
# 动画与游戏：纯前端 SVG/Canvas/JS，无需额外 Python 依赖
```

> 合规：PPT / 音频 / 视频含教材原文与插图，**仅家庭个人学习使用**，不得分发或公开部署。

### 8.8.6 接口

```python
def render(content_plan: ContentPlan, form: str, profile: SubjectProfile) -> Artifact
#   form: text | pptx | audio | video | html | animation | game | guided
#   形态可用性由 SubjectProfile.render_forms 决定（语文不给 game，数学优先 animation）

def make_content_plan(capability: str, scope: dict, ...) -> ContentPlan   # 已过 Guard 的结构化内容
def make_animation(kp_id: str, params: dict) -> SVGAnimation             # 参数化动画（数值来自教材例题）
def make_game(scope: dict, kp_id: str, mistake_type: str = None) -> Game # 题目程序生成，0 次 LLM
```

```powershell
python -m agent_textbook teach --lesson 昆虫备忘录 --form guided      # 语文：导师引导式
python -m agent_textbook teach --lesson 昆虫备忘录 --form audio        # 语文：朗读播客
python -m agent_textbook teach --kp 分数的初步认识 --form animation    # 数学：分数切分动画
python -m agent_textbook drill --grade 三年级 --form game              # 数学：口算闯关
python -m agent_textbook sheet --upload 练习卷.jpg                      # ★ 练习卷诊断（见 8.9）
python -m agent_textbook plan --learner 小明 --scope 三上语文           # 提升计划
```

### 8.9 从练习卷到提升计划（★ 学情闭环）

教材告诉系统"该会什么"，练习卷告诉系统"孩子实际会什么"——**这是唯一能直接观测学情的输入**。

#### 8.9.1 课级字词：不用另抽，附录自带课号

用户要"细化到每一课的字词"。实证：**教材附录的识字表 / 写字表 / 词语表本身就是按课编号的**
（二年级 P117 实测）：

```
1  咏 yǒng 贺 hè 妆 zhuāng 丝 sī 裁 cái 剪 jiǎn 莺 yīng 拂 fú 堤 dī 醉 zuì 趁 chèn
2  脱 tuō 袄 ǎo 遮 zhē 掩 yǎn 探 tàn 眉…
```

→ **按课号切分即得课级字词表**，不必重新抽取。实测锚点：识字表 20 处、写字表 12 处、词语表 10 处。
待验证：各册课号格式是否一致（部分册为 VLM 转录，需逐册确认后再全量切分）。

```python
LessonWords:  book_id, lesson_no, lesson_title,
              chars_recognize[]   # 会认字（识字表按课切分）
              chars_write[]       # 会写字（写字表按课切分）
              words[]             # 词语表按课切分
              source_page, source: 附录切分 | VLM抽取
```

有了它，错一个字就能定位到"三上第 3 课"，而不是笼统的"字词需要加强"。

#### 8.9.2 练习卷流程（五个环节，人工在环）

```
① 上传（拍照 / PDF）
   ↓
② VLM 提取：题号、题干、孩子作答、卷面标识
   ↓
③ 【人工确认】展示提取结果，可逐题修改      ← 不可省
   ↓
④ 判分：字词/计算走 check_answer（确定性），开放题走 rubric
   ↓
⑤ 归因 → 聚合 → 提升计划
```

两个关键决策：

| 决策 | 理由 |
| --- | --- |
| **自己判，不信任卷面的红勾** | 卷面只有对错，判不出"错在哪"。自己判才能归因到思维断点 / 错因类型 |
| **人工确认环节不可省** | 手写识别必然有错；让人花 2 分钟改一遍，远好过基于错识别给出错误诊断 |

#### 8.9.3 数据模型

```python
ExerciseSheet: sheet_id, learner, subject, scope, upload_time,
               items[], status: 待确认 | 已确认 | 已诊断
SheetItem:     idx, stem, answer_given, answer_std,
               correct: bool, kp_ids[], lesson_no,
               mistake_type, thinking_break        # 归因结果
Diagnosis:     sheet_id, summary, by_lesson{}, by_kp{}, by_mistake{}
```

#### 8.9.4 提升计划：必须落到"哪一课的哪几个字"

`plan` 的输出不能是"加强字词积累"这种空话。合格的输出形如：

```
最近 3 张卷子，错 12 处，集中在两类：
  ① 三上第 2、4 课的会写字："舞""姿"各错 3 次 → 笔顺与部件问题
  ② "的/地/得"错 5 次 → 用法规则未掌握（非粗心）
本周计划（每天 15 分钟）：
  D1 回看第 2 课课文，听写该课 8 个会写字
  D2 笔顺动画：舞、姿（重点：舞的 4 竖、姿的次字旁）
  D3 的/地/得规则讲解 + 10 题填空（确定性判分）
  D5 复测：D1 的 8 个字 + 同型填空 5 题
  D7 达标则进入第 5 课，未达标则回到 D1
```

排序依据：**错得多 + 先修在前 + 近期刚学**（遗忘曲线），并与 `mastery_path` 的闸门联动——
达标才放行，未达标自动生成下一轮。

#### 8.9.5 ★ 隐私：练习卷和教材不是一回事

| | 教材 | 练习卷 |
| --- | --- | --- |
| 性质 | 公开出版物 | **孩子的个人信息**（姓名、班级、笔迹、成绩） |
| 可否送云端 | 可以（内容本就公开） | **默认不可以** |

若 VLM 走云端 API，上传练习卷 = 把孩子的作业与笔迹传给第三方。对策：

1. **默认本地 VLM**（Ollama + Qwen2-VL / InternVL），云端仅作可选；
2. 上传前**提示遮盖姓名与班级**，或自动裁切卷头区域；
3. 送云端时必须**显式提示并征得确认**，不得无感上传；
4. 卷面与诊断结果本地加密存储，支持**一键删除**。

> 这是本项目唯一涉及未成年人真实数据的环节，其余全部基于公开教材。
> **宁可识别率低一点用本地模型，也不要默认外传。**

### 8.10 教学环节：预习 / 学习 / 复习 / 测试（★）

四个环节的目标、数据、Guard 约束、形态都不同，**且各自有一个典型的坑**。统一入口——
共享 scope、学情与 Guard，不是四个孤岛：

```python
def study(mode: Literal["preview", "learn", "review", "test"], scope, learner) -> StudySession
```

#### 8.10.1 教材自带的锚点（实测）

| 环节 | 教材锚点 | 说明 |
| --- | --- | --- |
| **预习** | **0 处——教材没有预习板块** | 这正是 AI 创造价值的地方；但内容仍必须取自教材 |
| **学习** | 数学「做一做」**355 处**、课文 / 例题 | 随学随练的天然素材 |
| **复习** | 语文「语文园地」**165 处** +「梳理与交流」40 +「日积月累」84；数学「复习与关联」59 +「整理和复习」50 + **「知识结构图」26**；英语「Recycle」6 | **复习有现成锚点，直接挂上去** |
| **测试** | 数学「练习」178、英语 Recycle | 范围锁定后出题 |

两个命名细节值得注意：

- 新版数学把复习单元叫 **「复习与关联」**——**复习不是重讲，是把知识连起来**；
- 教材明确示范了 **「知识结构图」**（26 处，如"下面是小明整理的本单元知识结构图"）
  → **复习的默认形态是结构图，不是刷题**。

#### 8.10.2 四个环节各自的坑

| 环节 | 典型做法 | 坑 | 正确做法 |
| --- | --- | --- | --- |
| **预习** | 把新课讲一遍 | 孩子上课觉得"我学过了"→ 不听 | **只给框架 + 激活旧知 + 2–3 个悬念问题**；**Guard 禁止给出本课结论** |
| **学习** | 讲完就完 | 无即时巩固 | 讲完立刻接「做一做」（355 处现成锚点） |
| **复习** | 重讲一遍 | **重读的效果远差于检索练习** | **先测后讲**（test-then-teach）：先让孩子回忆 / 做题，再针对性补；用知识结构图串联 |
| **测试** | 出一套卷子 | 超纲 + 只报分数 | 范围锁定（只测已学）+ **测完必须归因并进入提升计划** |

#### 8.10.3 闭环

```
预习（建框架 + 留问题） → 学习（讲解 + 做一做） → 复习（先测后讲 + 结构图）
   → 测试（范围锁定 + 判分） → 达标？ → 下一课  :  进入提升计划（§8.9）
```

四环节共享同一份学情（L1 事件 → L2 画像），任一环节的表现都更新掌握度；
`mastery_path` 的闸门决定是否放行。

```python
StudySession: session_id, learner, mode, scope(册|单元|课), steps[],
              started_at, ended_at, mastery_before, mastery_after
```

粒度约定：**预习按课**（明天上第 X 课）、**复习按单元或当日课**、**测试按单元或册**。

```powershell
python -m agent_textbook study --mode preview --lesson 分数除法
python -m agent_textbook study --mode review  --unit 三上第三单元
python -m agent_textbook study --mode test    --scope 三上数学 --n 10
```
