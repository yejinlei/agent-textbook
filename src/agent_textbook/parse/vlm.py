# -*- coding: utf-8 -*-
"""通道 B：VLM 多模态抽取。

**构建期**与**运行期共用同一套客户端**：
- 构建期：把无文本层的教材页（扫描版）渲染成图，转录为文本后入库；
- 运行期：把孩子拍的作业题/试卷照片转成文本，再交给 Agent 管线处理。

教材页转录的硬要求是**保留拼音声调**——本地 OCR 会丢声调（实测 ``dirénniwóta``），
VLM 能保住，这也是扫描册必须走本通道的原因。
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field

import pymupdf
import requests

from .. import config


@dataclass
class VLMResult:
    text: str
    model: str
    elapsed: float
    usage: dict = field(default_factory=dict)


class VLMClient:
    """多模态抽取客户端（OpenAI 兼容接口）。"""

    def __init__(self, base_url: str | None = None, model: str | None = None,
                 api_key: str | None = None, timeout: int | None = None):
        self.base_url = (base_url or config.VLM_BASE_URL).rstrip("/")
        self.model = model or config.VLM_MODEL
        self.api_key = api_key or config.VLM_API_KEY
        self.timeout = timeout or config.VLM_TIMEOUT
        if not self.api_key:
            raise RuntimeError(
                "未配置 VLM_API_KEY。请设置环境变量："
                "$env:VLM_API_KEY='...'（构建期与运行期共用）"
            )

    def extract(self, image: bytes, prompt: str = config.VLM_PROMPT_PAGE,
                max_tokens: int | None = None) -> VLMResult:
        b64 = base64.b64encode(image).decode()
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            "temperature": 0,
            "max_tokens": max_tokens or config.VLM_MAX_TOKENS,
        }
        t0 = time.time()
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        # 推理型模型可能只返回 reasoning_content（或 token 被推理耗尽导致 content 为空）
        text = (msg.get("content") or msg.get("reasoning_content") or "").strip()
        if not text:
            raise RuntimeError(
                f"VLM 返回空内容（可能被推理 token 耗尽，max_tokens="
                f"{max_tokens or config.VLM_MAX_TOKENS}）"
            )
        return VLMResult(
            text=text,
            model=self.model,
            elapsed=round(time.time() - t0, 1),
            usage=data.get("usage", {}),
        )


def dpi_for_attempt(attempt: int) -> int:
    """重试时逐级降低 dpi。

    图片越大，推理型模型消耗的思考 token 越多——实测 200 dpi 时大量页面"想完了却
    吐不出正文"（返回空内容），150 dpi 能救回一部分，但书法作品这类密集页面仍不够。
    因此失败重试时自动降档：150 → 120 → 96，同时也能避开 413（请求体过大）。
    """
    base = config.VLM_DPI
    return base if attempt <= 0 else max(72, int(base * 0.8 ** attempt))


def needs_backoff(err: str) -> bool:
    """这个错误需要退避等待，还是可以直接降 dpi 重试？

    429（限流）、413（请求体过大）、超时/连接错误属于平台侧，等一会儿才可能恢复；
    "返回空内容"是模型侧问题（想太多吐不出正文），**等着没用**，直接降档重试。
    """
    return any(s in err for s in ("429", "413", "Timeout", "timeout", "Connection"))


def render_page(pdf_path: str, page_no: int, dpi: int | None = None) -> bytes:
    """把教材页渲染为 PNG 字节。"""
    doc = pymupdf.open(pdf_path)
    try:
        return doc[page_no].get_pixmap(dpi=dpi or config.VLM_DPI).tobytes("png")
    finally:
        doc.close()


def extract_page_vlm(pdf_path: str, page_no: int, client: VLMClient | None = None,
                     prompt: str | None = None, dpi: int | None = None) -> VLMResult:
    """构建期：抽取单页教材。"""
    client = client or VLMClient()
    return client.extract(render_page(pdf_path, page_no, dpi),
                          prompt or config.VLM_PROMPT_PAGE)


def extract_photo(image: bytes, client: VLMClient | None = None) -> VLMResult:
    """运行期：孩子拍的作业题/试卷照片 → 文本。"""
    client = client or VLMClient()
    return client.extract(image, config.VLM_PROMPT_PHOTO)
