# -*- coding: utf-8 -*-
"""HTTP 层：限速、X-ND-AUTH 签名、镜像切换、流式落盘。"""

import base64
import hashlib
import hmac
import json
import math
import os
import random
import re
import threading
import time
from urllib.parse import unquote, urlsplit, urlunsplit

import requests

from .. import config

BASE_HEADERS = {
    "Authorization": "Bearer 0",
    "Origin": "https://basic.smartedu.cn",
    "Referer": "https://basic.smartedu.cn/",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    ),
    "X-ND-AUTH": 'MAC id="0",nonce="0",mac="0"',
}

NONCE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

session = requests.Session()
session.trust_env = False  # 不读取系统代理

_token: dict = {"access_token": "", "mac_key": "", "diff": 0}
_lock = threading.Lock()
_last_request_at = 0.0


def load_token(path: str = config.TOKEN_FILE) -> bool:
    """载入登录凭据 {access_token, mac_key, diff}。

    文件不存在、为空或不是合法 JSON 时一律退回匿名（匿名可下绝大多数教材），
    不让 fetch 因一个坏掉的凭据文件直接崩溃。
    """
    if not path or not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        print(f"[warn] 凭据文件无法解析，按匿名方式请求：{path}")
        return False
    if not isinstance(data, dict):
        print(f"[warn] 凭据格式不是 JSON 对象，按匿名方式请求：{path}")
        return False
    _token["access_token"] = str(data.get("access_token") or "")
    _token["mac_key"] = str(data.get("mac_key") or "")
    try:
        _token["diff"] = int(data.get("diff") or 0)
    except (TypeError, ValueError):
        _token["diff"] = 0
    return bool(_token["mac_key"])


def has_credentials() -> bool:
    return bool(_token["mac_key"])


def build_nd_auth(url: str, method: str = "GET") -> str:
    """按 URL 现算签名；无 mac_key 时退回占位头。"""
    token, mac_key, diff = _token["access_token"], _token["mac_key"], _token["diff"]
    if not mac_key:
        return f'MAC id="{token or "0"}",nonce="0",mac="0"'
    nonce = f"{int(time.time() * 1000) + diff}:" + "".join(
        NONCE_ALPHABET[math.ceil(35 * random.random())] for _ in range(8)
    )
    parts = urlsplit(url)
    text = (
        f"{nonce}\n{method.upper()}\n"
        f"{unquote(parts.path)}{f'?{parts.query}' if parts.query else ''}\n"
        f"{parts.hostname or ''}\n"
    )
    mac = base64.b64encode(
        hmac.new(mac_key.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")
    return f'MAC id="{token}",nonce="{nonce}",mac="{mac}"'


def request_headers(url: str, method: str = "GET") -> dict:
    return {**BASE_HEADERS, "X-ND-AUTH": build_nd_auth(url, method)}


def _pace() -> None:
    global _last_request_at
    with _lock:
        wait = config.MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def get_json(url: str, retries: int = 3):
    """GET 一个 JSON 接口并带退避重试。"""
    last = "未知错误"
    for i in range(retries):
        try:
            _pace()
            resp = session.get(url, headers=request_headers(url), timeout=config.REQUEST_TIMEOUT)
            if resp.ok:
                return resp.json()
            last = f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"请求失败 {url}：{last}")


def mirror_urls(url: str) -> list[str]:
    """私有 CDN 的 r1/r2/r3 镜像，原地址优先。"""
    parts = urlsplit(url)
    if parts.hostname not in config.PRIVATE_HOSTS:
        return [url]
    hosts = [parts.hostname, *(h for h in config.PRIVATE_HOSTS if h != parts.hostname)]
    return [urlunsplit((parts.scheme, h, parts.path, parts.query, parts.fragment)) for h in hosts]


def download_to(
    url: str,
    save_path: str,
    expected_size: int = 0,
    attempts: int = 3,
) -> tuple[bool, str]:
    """流式下载到 save_path（先写 .part，支持 Range 断点续传）。

    大文件（100MB+ 扫描版）常见连接中断，所以失败时保留 .part 供下一轮续传，
    并用 expected_size 校验，避免把截断文件当成成品。
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    tmp = f"{save_path}.part"
    last_reason = "没有可用的下载地址"

    for attempt in range(attempts):
        for candidate in mirror_urls(url):
            resume = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            headers = request_headers(candidate)
            if resume:
                headers["Range"] = f"bytes={resume}-"
            try:
                _pace()
                resp = session.get(
                    candidate, headers=headers, stream=True, timeout=config.REQUEST_TIMEOUT
                )
            except requests.RequestException as e:
                last_reason = str(e)
                continue
            try:
                if resp.status_code == 206:  # 断点续传
                    mode = "ab"
                elif resp.ok:
                    mode, resume = "wb", 0  # 服务端不支持 Range 则重头写
                elif resp.status_code in (401, 403):
                    return False, f"HTTP {resp.status_code}（需要登录凭据）"
                elif resp.status_code == 400:  # 多半是突发限流，退避后重试同一地址
                    last_reason = "HTTP 400"
                    if resume:  # 该 CDN 不接受带 Range 的续传（InvalidArgument），丢弃分片从头下
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                        resume = 0
                    time.sleep(config.RETRY_400_DELAYS[min(attempt, len(config.RETRY_400_DELAYS) - 1)])
                    continue
                else:
                    last_reason = f"HTTP {resp.status_code}"
                    continue

                with open(tmp, mode) as f:
                    for chunk in resp.iter_content(1 << 16):
                        if chunk:
                            f.write(chunk)
                size = os.path.getsize(tmp)
                if expected_size and size != expected_size:
                    last_reason = f"大小不符 {size}/{expected_size}"
                    continue  # 保留 .part，下一轮续传补齐
                os.replace(tmp, save_path)
                return True, ""
            except requests.RequestException as e:
                last_reason = str(e)  # 传输中断：已写字节保留，下一轮续传
            finally:
                resp.close()
        time.sleep(2.0 * (attempt + 1))
    return False, last_reason


_INVALID = str.maketrans({
    "\\": "＼", "/": "／", ":": "：", "*": "＊", "?": "？",
    '"': "＂", "<": "＜", ">": "＞", "|": "｜",
})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(10)}
    | {f"LPT{i}" for i in range(10)}
)


def sanitize_filename(name: str) -> str:
    name = _CONTROL.sub("_", name.translate(_INVALID)).rstrip(" .")
    if not name:
        return "download"
    stem, ext = os.path.splitext(name)
    if stem.upper() in _RESERVED:
        return f"_{stem}{ext}"
    return name
