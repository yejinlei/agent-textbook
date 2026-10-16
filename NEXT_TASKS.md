# 下一步任务记录（供另一台机器接续）

本文件在 `f:\src\agent-textbook` 主工作机上于 2026-10-16 更新，用于在新环境（另一台机器）续做时对齐进度。

## 已上库（当前工作区干净，均可 pull 到任意机器）

| commit | 内容 |
|--------|------|
| `c02de21c` | attrs/en_vocab.jsonl 同步补全词（829→1621），供 TTS 提取 |
| `9388f28a` | 补全全部正式课文单元词汇（829→1621 词，P2：音标+例句 100%） |
| `cb2b475c` | 五年级下册 U3-U6 补词（90 词） |

范围：8 册正式课文单元全部补齐（三上 U4-U7 / 三下 U3-U7 / 四上 U4-U7 / 四下 U3-U7 / 五上 U3-U7 / 五下 U3-U6 / 六上 U3-U7 / 六下 U2-U5），共新增 792 词。
备注：Songs / Useful expressions / Recycle / Pronunciation 等纯附录栏目按约定跳过，不计入正式单元。

## 当前阻塞（主工作机无法完成）

- **Piper 未在项目 venv 安装**：`.venv` 只含 python，无 piper-tts、无 pip。
- **模型下载被 hf-mirror 限流**：`models/piper` 仅剩 `alan.onnx.tmp`，下载接口返回 rate limit（quota 100000 resolvers/5min）。
- 现有本地点读音频（data/tts ~25258 个 MP3）是历史产物，索引 map.json/index.json 已存在——**存量语音匹配不受影响**。
- 新增 792 词目前在页面上可朗读，但走浏览器降级（无本地 Piper 音频）。

## 下一步（在另一台有网络/无限流的环境做）

1. **建项目 venv 并装 piper**
   ```powershell
   cd <仓库根>
   uv venv --python 3.11
   # --note-- 不要 `-e .`：项目 pyproject 的 tool.setuptools.packages.find 写法
   #        会让新版 setuptools 报配置错误。装包用 PYTHONPATH 指向 src 即可。
   uv pip install --python .venv\Scripts\python.exe piper-tts
   ```
2. **下载 4 个音色模型**（避开限流：错峰/换直连 HF，或用 `tts download`）
   ```powershell
   $env:PYTHONPATH="$PWD\src"; python -m agent_textbook tts download
   ```
3. **生成新增词音频**（增量，仅合成缺失 hash）
   ```powershell
   $env:PYTHONPATH="$PWD\src"; python -m agent_textbook tts gen
   ```
   attrs 已同步，`extract_texts` 会读到 1621 条词 + 例句，自动补齐缺失音频并更新 map/index。

4. **重新生成页面并同步音频**
   ```powershell
   $env:PYTHONPATH="$PWD\src"; python -m agent_textbook pages
   # 构建后用 git 提交 pages/ 改动（注意：先还原 pages/math/problem.html 的行尾漂移）
   git checkout -- pages/math/problem.html
   ```

## 一致性提醒
- en_vocab 主键写法：`{book_id}:{word.lower()}:{unit_no}`（unit 词）或 `source=vocab`（书末总表）。
- 新增词字段：word / phonetic / meaning（带 `\uf020` 前缀，与既有一致）/ example（教材原句数组）/ source=unit。
- 前端 hubVocab 按 `book(册次名)+unit_no` 匹配，多版本同一册共享单元号，按 (册次,单元号) 合并补词即可。
