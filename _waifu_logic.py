"""猫娘每日关怀 · 今日老婆与幸运积分（纯逻辑，独立于 SDK 与图片渲染，便于测试）"""

from __future__ import annotations

import datetime
import random
from functools import lru_cache
from typing import Any

# 今日老婆池：广为人知的二次元女性角色（name, work）。够丰富但不追求全。
WAIFU_POOL: list[tuple[str, str, str]] = [
    ("雷姆", "Re:从零开始的异世界生活", "rem_(re:zero)"),
    ("拉姆", "Re:从零开始的异世界生活", "ram_(re:zero)"),
    ("艾米莉娅", "Re:从零开始的异世界生活", "emilia_(re:zero)"),
    ("后藤一里", "孤独摇滚！", "gotou_hitori"),
    ("伊地知虹夏", "孤独摇滚！", "ijichi_nijika"),
    ("山田凉", "孤独摇滚！", "yamada_ryou"),
    ("喜多郁代", "孤独摇滚！", "kita_ikuyo"),
    ("芙莉莲", "葬送的芙莉莲", "frieren"),
    ("费伦", "葬送的芙莉莲", "fern_(sousou_no_frieren)"),
    ("芙宁娜", "原神", "furina_(genshin_impact)"),
    ("神里绫华", "原神", "kamisato_ayaka"),
    ("雷电将军", "原神", "raiden_shogun"),
    ("甘雨", "原神", "ganyu_(genshin_impact)"),
    ("胡桃", "原神", "hu_tao"),
    ("八重神子", "原神", "yae_miko"),
    ("刻晴", "原神", "keqing_(genshin_impact)"),
    ("纳西妲", "原神", "nahida_(genshin_impact)"),
    ("心海", "原神", "sangonomiya_kokomi"),
    ("优菈", "原神", "eula_(genshin_impact)"),
    ("宵宫", "原神", "yoimiya_(genshin_impact)"),
    ("芭芭拉", "原神", "barbara_(genshin_impact)"),
    ("三月七", "崩坏：星穹铁道", "march_7th_(honkai:_star_rail)"),
    ("卡芙卡", "崩坏：星穹铁道", "kafka_(honkai:_star_rail)"),
    ("银狼", "崩坏：星穹铁道", "silver_wolf_(honkai:_star_rail)"),
    ("花火", "崩坏：星穹铁道", "sparkle_(honkai:_star_rail)"),
    ("姬子", "崩坏：星穹铁道", "himeko_(honkai:_star_rail)"),
    ("阿米娅", "明日方舟", "amiya_(arknights)"),
    ("陈晖洁", "明日方舟", "ch'en_(arknights)"),
    ("凯尔希", "明日方舟", "kal'tsit"),
    ("能天使", "明日方舟", "exusiai_(arknights)"),
    ("加藤惠", "路人女主的养成方法", "katou_megumi"),
    ("亚丝娜", "刀剑神域", "yuuki_asuna"),
    ("御坂美琴", "魔法禁书目录", "misaka_mikoto"),
    ("时崎狂三", "约会大作战", "tokisaki_kurumi"),
    ("约尔", "间谍过家家", "yor_briar"),
    ("帕瓦", "电锯人", "power_(chainsaw_man)"),
    ("玛奇玛", "电锯人", "makima_(chainsaw_man)"),
    ("星野爱", "我推的孩子", "hoshino_ai"),
    ("雏田", "火影忍者", "hyuuga_hinata"),
    ("娜美", "海贼王", "nami_(one_piece)"),
    ("祢豆子", "鬼灭之刃", "kamado_nezuko"),
    ("蕾塞", "电锯人", "reze_(chainsaw_man)"),
]

# 运势等级 → 幸运积分（参考同类机器人：凶签扣分）
LUCK_SCORES = {"大吉": 7, "中吉": 5, "小吉": 3, "吉": 1, "末吉": 0, "凶": -1, "大凶": -3}


def draw_wife(date: str, user_id: str, catgirl_name: str = "猫娘") -> dict[str, Any]:
    """抽今日老婆：同 (date, user) 恒定；连续 len(WAIFU_POOL) 天内绝不重复。

    实现：为每个用户单独生成一条「池子的固定随机置换」（角色顺序），
    再按 `绝对日期序号 % 池大小` 取位。这样得到的是确定性、无状态的取法，
    却能做到理论最优的去重：
      1. 同一 (date, user) 结果恒定，重复查询不变（纯函数）；
      2. 任意连续 42 天内恰好抽到 42 个互不相同的角色，且相邻两天必不同；
      3. 只有相隔满 42 天才会再次抽到同一角色（42 个角色时的极限）。

    ``catgirl_name`` 保留仅为兼容旧签名，不参与抽选。
    """
    size = len(WAIFU_POOL)
    cycle = _user_cycle(user_id, size)
    try:
        day_index = datetime.date.fromisoformat(str(date)).toordinal()
    except (ValueError, TypeError):
        day_index = 0
    name, work, en_tag = WAIFU_POOL[cycle[day_index % size]]
    rng = random.Random(f"waifu|{date}|{user_id}")
    return {
        "date": date,
        "user_id": user_id,
        "name": name,
        "work": work,
        "en_tag": en_tag,
        "bond": rng.randrange(60, 100),  # 与主人的契合度彩蛋
    }


@lru_cache(maxsize=None)
def _user_cycle(user_id: str, size: int) -> tuple[int, ...]:
    """每个用户一条固定的角色顺序（0..size-1 的确定性随机置换）。"""
    rng = random.Random(f"waifu-cycle|{user_id}|{size}")
    return tuple(rng.sample(range(size), size))


def luck_score_for(level: str) -> int:
    return LUCK_SCORES.get(level, 0)


def wife_rewards(fortune_fish_index: int, date: str, user_id: str) -> dict[str, int]:
    """今日老婆的货币奖励：银币保底+摸鱼指数加成，金币小概率暴击。"""
    rng = random.Random(f"wife-reward|{date}|{user_id}")
    silver = 100 + int(fortune_fish_index) * 3 + rng.randrange(0, 100)
    gold = 5 if rng.random() < 0.1 else 0
    return {"silver": silver, "gold": gold}


def update_user_record(
    users: dict[str, Any],
    user_id: str,
    user_name: str,
    date: str,
    luck_score: int,
    rewards: dict[str, int],
    wife_name: str,
) -> dict[str, Any]:
    """登记某用户某天的运势/老婆/货币记录；返回该用户的最新档案。

    同一天重复查询不重复计分（幂等），但会补齐字段。
    """
    user = users.get(user_id)
    if not isinstance(user, dict):
        user = {"name": user_name, "total_luck": 0, "days": {}, "coins": {"silver": 0, "gold": 0}}
    user.setdefault("name", user_name)
    days = user.setdefault("days", {})
    day = days.get(date)
    if not isinstance(day, dict):
        day = {}
    if "score" not in day:
        user["total_luck"] = int(user.get("total_luck", 0)) + luck_score
        day["score"] = luck_score
    day["level_tagged"] = True
    day["wife"] = wife_name
    coins = user.setdefault("coins", {"silver": 0, "gold": 0})
    if "silver" not in day:
        day["silver"] = rewards["silver"]
        coins["silver"] = int(coins.get("silver", 0)) + rewards["silver"]
    if "gold" not in day:
        day["gold"] = rewards["gold"]
        coins["gold"] = int(coins.get("gold", 0)) + rewards["gold"]
    days[date] = day
    users[user_id] = user
    return user


def luck_ranking(users: dict[str, Any], today: str = "") -> list[dict[str, Any]]:
    """累计幸运排行（并列按名字排序保证稳定）；today 提供时附带今日分。"""
    rows: list[dict[str, Any]] = []
    for uid, user in users.items():
        if not isinstance(user, dict):
            continue
        row = {
            "user_id": uid,
            "name": str(user.get("name") or uid),
            "total_luck": int(user.get("total_luck", 0)),
            "today": int((user.get("days") or {}).get(today, {}).get("score", 0)) if today else None,
        }
        rows.append(row)
    rows.sort(key=lambda r: (-r["total_luck"], r["name"]))
    return rows


def render_luck_rank(rows: list[dict[str, Any]], today: str = "", catgirl_name: str = "猫娘") -> str:
    """排行文本（前 10 名 + 货币）。"""
    if not rows:
        return f"还没有人抽过运势喵，快来让{catgirl_name}给你算一算～"
    lines = ["🏆 幸运排行榜（累计）"]
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows[:10]):
        medal = medals[i] if i < len(medals) else f"{i + 1}."
        today_part = f"｜今日 {row['today']:+d}" if (today and row.get("today") is not None) else ""
        lines.append(f"{medal} {row['name']}　累计 {row['total_luck']:+d}{today_part}")
    return "\n".join(lines)
