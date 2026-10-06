# -*- coding: utf-8 -*-
"""构建期 LLM 调用的工具层：只管"怎么调、怎么存"，不管"问什么"。

四层（校对 / 整理 / 补充 / 扩展）共用同一套约定，避免每层各写一份：

  * 输出一律要求 JSON，解析失败即判失败——不做宽容处理，否则脏数据
    会以"看起来正常"的形式混进库里，后面再也查不出来；
  * 按 id 追加写 JSONL，带 model 与时间戳，换模型重抽时覆盖同名文件；
  * 续跑：已存在的 id 跳过，跑一半中断不会丢已完成的部分；
  * 推理型模型会把 token 耗在思考上，max_tokens 给小了会返回空内容
    （config 里记录的同一个坑），默认给到 2048。
"""

import json
import os
import re

from .. import config

RE_JSON = re.compile(r"\{.*\}", re.S)


def _fix_inner_quotes(s: str) -> str:
    """把 JSON **字符串内部**未转义的双引号换成中文引号。

    模型写段意时会顺手给词加引号（`课文标题"夜色"及生字词…`），于是整段
    JSON 非法，`json.loads` 直接失败。判据：字符串里的引号后面若紧跟
    `,}]` 或 `:` 则是正常的闭合引号；否则它是内容，换成中文引号。
    """
    out: list[str] = []
    in_str = False
    n = len(s)
    i = 0
    bal = 0
    while i < n:
        c = s[i]
        if c == "\\" and in_str:
            out.append(s[i:i + 2])
            i += 2
            continue
        if c == '"':
            if not in_str:
                in_str = True
                out.append(c)
                i += 1
                continue
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j >= n or s[j] in ",}]:":
                in_str = False
                out.append(c)
            else:
                out.append("“" if bal % 2 == 0 else "”")
                bal += 1
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_json(text: str) -> dict:
    """从模型输出里抠出 JSON——它可能自带 ```json 围栏或前后废话。

    内容里夹了未转义引号时先修复再解析：这类输出是模型最常见的格式错误，
    宽度只到"引号转义"这一层，修完仍解析不了就照旧判失败——不做更宽容的
    兜底，否则脏数据会以"看起来正常"的形式混进库里。
    """
    m = RE_JSON.search(text or "")
    if not m:
        return {}
    s = m.group(0)
    try:
        return json.loads(s)
    except ValueError:
        pass
    try:
        return json.loads(_fix_inner_quotes(s))
    except ValueError:
        return {}


def load_done(path: str, key: str) -> set:
    """已处理过的 id 集合，用于续跑。"""
    done = set()
    if not os.path.exists(path):
        return done
    for l in open(path, encoding="utf-8"):
        if l.strip():
            try:
                done.add(json.loads(l).get(key))
            except ValueError:
                continue
    return done


def append_jsonl(path: str, rec: dict) -> None:
    os.makedirs(config.ATTRS_DIR, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def chat(prompt: str, max_tokens: int = 2048):
    """纯文本调用一次模型。异常交给调用方按条处理（不该整批中断）。"""
    from ..parse.vlm import VLMClient

    return VLMClient().chat(prompt, max_tokens=max_tokens)
