# agent-textbook

面向小学生的教材 Agent 工程。主题是 **Agent**，教材采集只是整条链路的**预处理阶段**。

```
① 采集 collect   ② 解析 parse   ③ 入库 index   ④ 应用 agent
电子课本 PDF  ──▶ 文本/OCR ──▶ 分块+向量 ──▶ 答疑/讲解/出题
books/                （待实现）      （待实现）      （待实现）
```

- 阶段一 `collect` 已实现：从国家中小学智慧教育平台抓取电子课本，落地到 `books/`。
- 阶段二三四为占位包，接口约定写在各自的 `__init__.py` 与 `docs/教材提取原理与使用.md`。

## 快速开始

```powershell
$env:PYTHONIOENCODING = 'utf-8'          # Windows 控制台中文
.\.venv\Scripts\python.exe -m agent_textbook catalog          # 1. 拉目录
.\.venv\Scripts\python.exe -m agent_textbook list --preset hangzhou
.\.venv\Scripts\python.exe -m agent_textbook fetch --preset hangzhou --stage 小学,初中
.\.venv\Scripts\python.exe -m agent_textbook status           # 看进度与失败原因
```

常用子命令：`catalog / list / fetch / retry / sync / organize / status`。

## 目录结构

```
books/浙江杭州/<学段>/<学科>/<版本>/<年级>/<书名>.pdf   # 采集产物
data/catalog.jsonl      平台全量书目（2925 条）
data/downloads.jsonl    下载清单（含直链、状态、体积）→ 后续解析阶段的输入
src/agent_textbook/
  ├─ collect/   采集：net(签名/限速) · catalog(目录) · downloader(详情/下载)
  ├─ parse/     解析：PDF 文本/OCR、章节切分（待实现）
  ├─ index/     入库：分块、向量与关键词索引（待实现）
  └─ agent/     应用：答疑、讲解、出题（待实现）
docs/教材提取原理与使用.md
```

## 文档

- 采集原理与用法：`docs/教材提取原理与使用.md`（平台接口、X-ND-AUTH 签名、限流策略、命令与参数、版本对照表、常见问题）
- 知识库选型：`docs/知识库方案.md`（RAG / 知识图谱 / 本体论 / LLM-wiki 的取舍与分层结论）
- 系统设计：`docs/系统设计文档.md`（架构、数据模型、parse/index/agent 接口约定、评测与实施计划）

## 合规

教材版权归国家中小学智慧教育平台及相关权利人所有，下载内容仅供个人学习与教学参考，请勿二次分发或商用。
