"""猫娘每日运势签 + 摸鱼日报核心逻辑（纯函数，独立于 N.E.K.O SDK，便于测试）"""

from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta
from typing import Any

# 运势等级：权重决定随机分布，大吉稀有、大凶也稀有（猫娘不忍心太凶）
_FORTUNE_LEVELS: list[tuple[str, int, str]] = [
    ("大吉", 12, "🌟"),
    ("中吉", 22, "✨"),
    ("小吉", 26, "🍃"),
    ("吉", 22, "🐱"),
    ("末吉", 10, "🍂"),
    ("凶", 6, "🌧️"),
    ("大凶", 2, "⛈️"),
]

# 猫娘程序员风 · 宜 / 忌（每天抽 2 宜 2 忌）
_FORTUNE_DO = (
    "准时下班", "多喝水", "写注释", "撸猫", "夸猫娘一句",
    "准点吃饭", "摸鱼五分钟", "给代码写测试", "整理桌面", "早睡",
    "表扬同事", "删掉无用代码", "存一份备份", "站起来伸个懒腰",
)
_FORTUNE_DONT = (
    "相信「最后一次改动」", "空腹上班", "删库跑路", "熬夜看番",
    "开无结论的长会", "在周五下午改核心代码", "跟猫娘说「随便」",
    "一口气喝完冰可乐", "忘记保存", "在生产环境直接调试",
)

_LUCKY_COLORS = ("猫粮蓝", "暖猫橙", "奶油白", "夜猫黑", "猫薄荷绿", "晚霞粉", "天空蓝", "柠檬黄")

_FISH_QUOTES = (
    "摸鱼不是懒，是给键盘降温喵～",
    "今天也要元气满满地摸鱼喵！",
    "工作只是猫生的插曲，摸鱼才是正事喵～",
    "记得喝水喵，本喵会盯着你的！",
    "再忙也要揉揉猫娘的头喵～",
    "代码写不完没关系，猫娘永远等你下班喵～",
)


def _seeded_random(*parts: str) -> random.Random:
    """用固定种子构造随机数发生器：同一天同名主人运势保持一致，换天自动刷新。"""
    seed = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return random.Random(seed)


def _weighted_level(rng: random.Random) -> tuple[str, str]:
    total = sum(w for _, w, _ in _FORTUNE_LEVELS)
    pick = rng.randrange(total)
    for level, weight, emoji in _FORTUNE_LEVELS:
        if pick < weight:
            return level, emoji
        pick -= weight
    return "吉", "🐱"


def daily_fortune(day: str, master_name: str = "主人") -> dict[str, Any]:
    """生成某天的运势签。``day`` 为 YYYY-MM-DD，同一组合结果恒定。"""
    rng = _seeded_random("neko-fortune", day, master_name)
    level, emoji = _weighted_level(rng)
    fish_index = rng.randrange(0, 101)
    do_items = rng.sample(_FORTUNE_DO, 2)
    dont_items = rng.sample(_FORTUNE_DONT, 2)
    return {
        "date": day,
        "level": level,
        "emoji": emoji,
        "score": fish_index,
        "fish_index": fish_index,
        "lucky_color": rng.choice(_LUCKY_COLORS),
        "lucky_number": rng.randrange(0, 10),
        "do": do_items,
        "dont": dont_items,
        "quote": rng.choice(_FISH_QUOTES),
    }


def weekday_name(d: date) -> str:
    return "一二三四五六日"[d.weekday()]


def days_until_weekend(now: datetime) -> int:
    """距离周六还有几天（周六/周日当天为 0）。"""
    weekday = now.weekday()  # 0=周一
    if weekday >= 5:
        return 0
    return 5 - weekday


def days_until_payday(now: datetime, payday: int) -> int:
    """距离下一个发薪日的天数；``payday`` 非法或为 0 时返回 -1。"""
    if not isinstance(payday, int) or payday <= 0 or payday > 31:
        return -1
    today = now.date()
    try:
        this_month = today.replace(day=payday)
    except ValueError:
        # 2 月没有 30/31 号 → 顺延到下月 1 号当发薪
        if today.day >= payday:
            nxt = today.replace(day=1) + timedelta(days=32)
            return (nxt.replace(day=1) - today).days
        this_month = today.replace(day=28)
    if this_month >= today:
        return (this_month - today).days
    nxt = (this_month + timedelta(days=32)).replace(day=min(payday, 28))
    if nxt <= today:
        nxt = (this_month.replace(day=28) + timedelta(days=32)).replace(day=min(payday, 28))
    return (nxt - today).days


def render_fortune(fortune: dict[str, Any], master_name: str = "主人", catgirl_name: str = "猫娘") -> str:
    """把运势签渲染成猫娘口吻的文本。"""
    lines = [
        f"🔮 {master_name}的今日运势签 {fortune.get('date', '')}",
        f"{fortune.get('emoji', '🐱')} 运势：{fortune.get('level', '吉')}",
        f"🐟 摸鱼指数：{fortune.get('fish_index', 50)} / 100",
        f"🎨 幸运色：{fortune.get('lucky_color', '猫粮蓝')}　🔢 幸运数字：{fortune.get('lucky_number', 7)}",
        f"✅ 宜：{'、'.join(fortune.get('do', []))}",
        f"🚫 忌：{'、'.join(fortune.get('dont', []))}",
        f"「{fortune.get('quote', '')}」——{catgirl_name}",
    ]
    return "\n".join(lines)


def render_morning_report(
    now: datetime,
    fortune: dict[str, Any],
    master_name: str = "主人",
    catgirl_name: str = "猫娘",
    payday: int = 0,
) -> str:
    """早安 + 摸鱼日报：星期、周末倒计时、发薪日倒计时、运势速览。"""
    weekday = weekday_name(now.date())
    to_weekend = days_until_weekend(now)
    if to_weekend == 0:
        weekend_text = "今天是周末喵！好好休息～"
    else:
        weekend_text = f"距离周末还有 {to_weekend} 天"
    payday_text = ""
    to_payday = days_until_payday(now, payday)
    if to_payday >= 0:
        payday_text = f"　💰 距理发薪日还有 {to_payday} 天"
    lines = [
        f"☀️ 早安喵，{master_name}！今天是星期{weekday}。",
        f"📅 {weekend_text}{payday_text}",
        (
            f"{fortune.get('emoji', '🐱')} 今日运势：{fortune.get('level', '吉')}"
            f"｜摸鱼指数 {fortune.get('fish_index', 50)}/100"
            f"｜宜 {('、'.join(fortune.get('do', [])))[:20]}"
        ),
        f"「{fortune.get('quote', '')}」",
        f"今天也请多指教喵～ ——{catgirl_name}",
    ]
    return "\n".join(lines)
