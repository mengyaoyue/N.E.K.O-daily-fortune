"""猫娘每日关怀 · 扩展数据源（涩图池 + 今日热点）

涩图：safebooru 的 bikini/swimsuit/underwear 标签（全年龄但好看），标签按日期轮换
热点：60s API（viki.moe）免费每日新闻，无需 key
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Optional

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# 涩图标签池（safebooru 全年龄，但泳装/内衣类够"好看"）
_ART_TAGS = ("bikini", "swimsuit", "underwear", "cleavage", "towel")


def _get_json(url: str, timeout: float = 12.0) -> Optional[dict[str, Any]]:
    request = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


def _get_bytes(url: str, timeout: float = 12.0) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": _UA, "Referer": url})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, resp.read()
    except Exception:
        return 0, b""


# ── 涩图 ─────────────────────────────────────────────────────────

def fetch_sexy_art(save_path: str, date: str = "", seed: Optional[str] = None, timeout: float = 12.0) -> Optional[str]:
    """从 safebooru 拉一张泳装/内衣系全年龄图。

    ``seed`` 传值时结果可复现；不传则每次调用随机换一张（支持无上限刷新）。
    返回保存路径，失败返回 None。
    """
    import hashlib
    import random

    key = seed if seed else f"{date}|{random.random()}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    tag = _ART_TAGS[int.from_bytes(digest[:4], "big") % len(_ART_TAGS)]
    url = (
        "https://safebooru.org/index.php?page=dapi&s=post&q=index"
        f"&tags={urllib.parse.quote(tag + ' solo')}&json=1&limit=30"
    )
    data = _get_json(url, timeout)
    posts = data if isinstance(data, list) else (data.get("post") if isinstance(data, dict) else None)
    if not posts:
        return None
    rng = random.Random(key)
    post = rng.choice(posts)
    img_url = f"https://safebooru.org/images/{post['directory']}/{post['image']}"
    status, body = _get_bytes(img_url, timeout)
    if status != 200 or len(body) < 5000:
        return None
    from pathlib import Path

    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    Path(save_path).write_bytes(body)
    return save_path


# ── 今日热点 ──────────────────────────────────────────────────────

def fetch_daily_news(timeout: float = 15.0) -> list[str]:
    """60s API 拉取今日新闻（15 条）。失败返回空列表。"""
    data = _get_json("https://60s.viki.moe/v2/60s", timeout)
    if not data or data.get("code") != 200:
        return []
    return [str(item) for item in (data.get("data") or {}).get("news") or [] if item]


def render_news(items: list[str], catgirl_name: str = "猫娘") -> str:
    """渲染今日热点。"""
    if not items:
        return "📰 今日热点没拉到喵，网络可能不太好。"
    lines = [f"📰 今日热点（{len(items)} 条）："]
    for i, item in enumerate(items[:10], 1):
        lines.append(f"{i}. {item[:60]}")
    if len(items) > 10:
        lines.append(f"…等 {len(items)} 条")
    lines.append(f"以上来自 60s API，{catgirl_name}帮你整理喵～")
    return "\n".join(lines)
