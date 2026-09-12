"""猫娘每日关怀 · 角色图片多来源拉取（首个成功即短路）

来源链（按序尝试，任一成功即停）：
  1. safebooru —— 全年龄图站，匿名 JSON API，最稳
  2. danbooru  —— 需要 key 的概率在，匿名常 403，但放链里不亏
  3. yande.re  —— 壁纸站，rating:s 过滤

安全：所有来源强制全年龄过滤（safebooru 本身安全；其余加 rating 参数）。
确定性：同一 (角色, 日期, 用户) 命中的图恒定。
全部失败返回 None，由上层回退到本地绘制的装饰卡。
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

MIN_IMAGE_BYTES = 5 * 1024  # 小于 5KB 视为占位图/错误页

# 查询后缀：保证抽到的是单人全年龄图
_SOLO_SUFFIX = " solo"
_SOLO_RATING_GENERAL = " solo rating:general"
_SOLO_RATING_S = " solo rating:s"


def _get_bytes(url: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": _UA, "Referer": url})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, resp.read()
    except Exception:
        return 0, b""


def _deterministic_pick(count: int, seed_key: str) -> int:
    import hashlib

    digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % max(1, count)


def _posts_safebooru(tag: str, limit: int, timeout: float) -> list[str]:
    status, body = _get_bytes(
        "https://safebooru.org/index.php?page=dapi&s=post&q=index"
        f"&tags={urllib.parse.quote(tag + _SOLO_SUFFIX)}&json=1&limit={limit}",
        timeout,
    )
    if status != 200 or not body:
        return []
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    posts = data if isinstance(data, list) else (data.get("post") if isinstance(data, dict) else None)
    urls: list[str] = []
    for p in posts or []:
        if isinstance(p, dict) and p.get("directory") and p.get("image"):
            urls.append(f"https://safebooru.org/images/{p['directory']}/{p['image']}")
    return urls


def _posts_danbooru(tag: str, limit: int, timeout: float) -> list[str]:
    status, body = _get_bytes(
        f"https://danbooru.donmai.us/posts.json?tags={urllib.parse.quote(tag + _SOLO_RATING_GENERAL)}&limit={limit}",
        timeout,
    )
    if status != 200 or not body:
        return []
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    return [str(p.get("file_url")) for p in (data or []) if isinstance(p, dict) and p.get("file_url")]


def _posts_yandere(tag: str, limit: int, timeout: float) -> list[str]:
    status, body = _get_bytes(
        f"https://yande.re/post.json?tags={urllib.parse.quote(tag + _SOLO_RATING_S)}&limit={limit}",
        timeout,
    )
    if status != 200 or not body:
        return []
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    return [str(p.get("file_url")) for p in (data or []) if isinstance(p, dict) and p.get("file_url")]


# 来源链：名称 → (取候选 URL 列表函数, 下载时是否带 Referer)
SOURCE_CHAIN: dict[str, Callable[[str, int, float], list[str]]] = {
    "safebooru": _posts_safebooru,
    "danbooru": _posts_danbooru,
    "yandere": _posts_yandere,
}
SOURCE_ORDER = ("safebooru", "danbooru", "yandere")


def fetch_character_image(
    en_tag: str,
    save_path: str,
    seed_key: str,
    timeout: float = 12.0,
    limit: int = 20,
    order: tuple[str, ...] = SOURCE_ORDER,
    fetchers: Optional[dict[str, Callable[[str, int, float], list[str]]]] = None,
    downloader: Optional[Callable[[str], tuple[int, bytes]]] = None,
) -> Optional[str]:
    """多来源拉取角色图：任一来源成功即短路；全失败返回 None。

    ``fetchers`` / ``downloader`` 可注入用于测试。
    """
    get_bytes = downloader or _get_bytes
    for source in order:
        fetcher = (fetchers or SOURCE_CHAIN).get(source)
        if fetcher is None:
            continue
        try:
            urls = fetcher(en_tag, limit, timeout)
        except Exception:
            urls = []
        if not urls:
            continue
        picked = urls[_deterministic_pick(len(urls), f"{source}|{seed_key}|{en_tag}")]
        status, body = (get_bytes(picked) if downloader else get_bytes(picked, timeout))
        if status == 200 and len(body) >= MIN_IMAGE_BYTES:
            try:
                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                Path(save_path).write_bytes(body)
                return save_path
            except Exception:
                continue
    return None


# 猫娘运势卡的主题标签池：按日期轮换，同一天所有用户同一张
CATGIRL_TAGS = ("cat_girl", "nekomimi", "cat_ears", "animal_ears")


def fetch_catgirl_artwork(
    save_path: str,
    seed_key: str,
    timeout: float = 12.0,
    limit: int = 20,
    fetchers: Optional[dict[str, Callable[[str, int, float], list[str]]]] = None,
    downloader: Optional[Callable[[str], tuple[int, bytes]]] = None,
) -> Optional[str]:
    """拉取"猫娘"主题插画作为当日运势卡图。

    标签按 seed（含日期）确定性轮换；来源链 safebooru→danbooru→yandere，
    任一来源命中即短路。全失败返回 None。
    """
    import hashlib as _hashlib

    digest = _hashlib.sha256(f"catgirl-art|{seed_key}".encode("utf-8")).digest()
    tag = CATGIRL_TAGS[int.from_bytes(digest[:4], "big") % len(CATGIRL_TAGS)]
    return fetch_character_image(
        tag, save_path, seed_key, timeout=timeout, limit=limit,
        fetchers=fetchers, downloader=downloader,
    )
