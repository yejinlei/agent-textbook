# OCR 错位自动修复总结报告

- **日期**：2026-11-05
- **范围**：统编版小学语文教材（1–6 年级，全册）课文数据 `data/attrs/lesson_text.jsonl`
- **目标文件**：[lesson_text.jsonl](file:///f:/src/agent-textbook/data/attrs/lesson_text.jsonl)
- **方式**：正则规则修复 + VLM 视觉语言模型精修
- **结果**：**三波累计修复 134 条**，全部落地写回并提交

---

## 一、总览

| 波次 | 脚本 | 方法 | 修复数量 |
|---|---|---|---|
| 第一波 | [fix_ocr.py](file:///f:/src/agent-textbook/scripts/fix_ocr.py) | 正则 | 91 |
| 第二波 | [fix_ocr_v2.py](file:///f:/src/agent-textbook/scripts/fix_ocr_v2.py) | 正则 | 35 |
| 第三波 | [fix_ocr_vlm.py](file:///f:/src/agent-textbook/scripts/fix_ocr_vlm.py) | VLM 精修 | 8 |
| **合计** | | | **134** |

> 说明：第三波按"课文"计 8 篇（VLM 一次处理 4 组同页课，每组修复 2 篇课文）；按"问题条目"计 4 条。

---

## 二、问题类型与处理明细

### 第一波：正则修复（91 条）

由 [fix_report.md](file:///f:/src/agent-textbook/data/audit/fix_report.md) 记录，备份 `lesson_text.jsonl.bak`。

| 类型 | 数量 | 说明 |
|---|---|---|
| author_glue | 28 | 作者行残留粘连（如"本文作者是美国的艾萨克·阿西莫夫，"粘在正文头部） |
| empty_exercise | 63 | 练习题数组存在空项（`exercises[N]` 为空） |
| **小计** | **91** | |

### 第二波：正则修复（35 条）

由 [fix_v2_report.md](file:///f:/src/agent-textbook/data/audit/fix_v2_report.md) 记录，备份 `lesson_text.jsonl.bak2`。

| 类型 | 数量 | 说明 |
|---|---|---|
| variant_author | 19 | 作者信息变体（如"韩翃"漏字、注音残缺）合并到主 title 字段 |
| newchars_leak | 15 | 生字表条目误粘到课文正文尾部（如"识字加油站……"），正则切回 |
| repeat_paragraph | 1 | 段内重复行去重 |
| **小计** | **35** | |

### 第三波：VLM 精修（8 篇）

由 [fix_vlm_report.md](file:///f:/src/agent-textbook/data/audit/fix_vlm_report.md) 记录，备份 `lesson_text.jsonl.bak3`。

**处理对象**：`multi_lesson_page`（多课共页）共 17 条，其中 13 条为合辑类父课（"古诗三首""文言文二则"等，属数据结构问题，非 OCR 错位），经 `RE_COLLECTION` 正则 + ZWNJ 零宽字符清理后正确跳过；**剩 4 条真·多课共页进入 VLM 精修，全部成功**。

| lesson_id | 课文 | 修复篇目 |
|---|---|---|
| `47eee424:026` | 《马诗》 | 马诗 + 石灰吟 |
| `95fe99ed:016` | 《四时田园杂兴（其二十五）》 | 四时田园杂兴 + 宿新市徐公店 |
| `8a551db2:016` | 《暮江吟》 | 暮江吟 + 题西林壁 |
| `725c537b:002` | 《绝句》 | 绝句 + 惠崇春江晚景 |

**VLM 模型**：`sensenova-6.8-flash-lite`（OpenAI 兼容，视觉 + 思考）。

---

## 三、关键技术点

1. **强制 JSON 输出**：VLM 带 thinking 模式会吃掉 max_tokens 导致 content 为空，加 `response_format: {"type": "json_object"}` 后 content 正常返回 JSON。
2. **PDF 页码 0-based**：`page_from` 是物理页 0-based 索引，渲染时**不再减 1**，修复了偏移到单元导语页的问题。
3. **lesson_id 匹配**：以"冒号后 3 位页码号"作为 book 内唯一 key 建索引，避免字符串 `endswith` 误匹配。
4. **ZWNJ 零宽字符**：CSV 部分"古诗三首"标题混入 U+200B 零宽不换行符，导致合辑正则不匹配；用 `ZW_RE` 清理后再匹配，过滤恢复生效（17→4）。
5. **多课写回对齐**：VLM 返回的 `lessons[i]` 按顺序对齐 `involved[i]` 逐课写回，并加幻觉兜底（新文本 <10 字或 <原长 20% 则丢弃）。
6. **Windows 文件名**：lesson_id 含冒号，写日志时替换为下划线 `:` → `_`。

---

## 四、产物清单

| 文件 | 说明 |
|---|---|
| [fix_ocr.py](file:///f:/src/agent-textbook/scripts/fix_ocr.py) | 第一波正则脚本 |
| [fix_ocr_v2.py](file:///f:/src/agent-textbook/scripts/fix_ocr_v2.py) | 第二波正则脚本 |
| [fix_ocr_vlm.py](file:///f:/src/agent-textbook/scripts/fix_ocr_vlm.py) | 第三波 VLM 精修脚本 |
| [fix_report.md](file:///f:/src/agent-textbook/data/audit/fix_report.md) | 第一波报告 |
| [fix_v2_report.md](file:///f:/src/agent-textbook/data/audit/fix_v2_report.md) | 第二波报告 |
| [fix_vlm_report.md](file:///f:/src/agent-textbook/data/audit/fix_vlm_report.md) | 第三波报告 |
| `data/audit/vlm_runs/*.json` | VLM 运行日志（每次调用请求/响应全量） |
| `data/attrs/lesson_text.jsonl` | 修复后数据（主产物） |
| `lesson_text.jsonl.bak / .bak2 / .bak3` | 三波备份（已加入 `.gitignore` 的 `*.bak*`） |

---

## 五、提交记录

- `352d1fc0` fix(chinese): OCR 错位自动修复第一波 author_glue+empty_exercise 91 条
- `ba181b89` fix(chinese): OCR 错位修复第二波+第三波（v2 正则 35 条 + VLM 精修 8 篇）

> 当前分支 `feature/english-tts-spelling`，已领先 `origin` 2 个提交（尚未 push）。

---

## 六、注意事项 / 后续建议

- 第三波中 **13 条合辑类父课**（"古诗三首"等）未处理，属数据结构设计问题（父课无独立正文，由多首子课组成），如需彻底解决需调整数据模型或拆分逻辑，不在本次 OCR 精修范围内。
- VLM 精修依赖外部 API，建议保留 `data/audit/vlm_runs/*.json` 运行日志以便追溯与复现。
- 如需回滚，可按 `lesson_text.jsonl.bak*` 备份恢复对应波次之前的状态。
