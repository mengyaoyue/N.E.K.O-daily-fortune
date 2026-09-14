"""猫娘每日关怀 · 图片卡渲染（PIL，宿主自带 Pillow；零额外依赖）

- render_fortune_card：签文式运势卡（每天/每用户不同，猫娘立绘入卡）
- render_wife_card：今日老婆卡（角色名/作品/第N个老婆/货币奖励）

所有字体用系统微软雅黑；无网络依赖；同参数输出逐字节一致（确定性）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyh.ttf")
_FONT_BOLD_CANDIDATES = ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyhbd.ttf")

# 运势等级 → 卡片主色（边框/底纹/印章），凶签偏冷紫、大吉偏金红
_LEVEL_COLORS = {
    "大吉": ((214, 158, 46), (255, 236, 179)),
    "中吉": ((88, 152, 255), (214, 233, 255)),
    "小吉": ((96, 190, 140), (214, 245, 227)),
    "吉": ((130, 130, 220), (224, 224, 250)),
    "末吉": ((150, 140, 120), (235, 228, 214)),
    "凶": ((120, 100, 190), (226, 218, 248)),
    "大凶": ((84, 62, 140), (206, 196, 238)),
}

# 签文短语池（4 字 + 吉凶属性），渲染时按种子取 3 列
_ORACLE_POOL: list[tuple[str, str]] = [
    ("作事有成", "吉"), ("贵人相助", "吉"), ("出入平安", "吉"), ("财源自来", "吉"),
    ("病痛远离", "吉"), ("心想事成", "吉"), ("鱼水相逢", "吉"), ("枯木逢春", "吉"),
    ("明月当空", "吉"), ("云开见日", "吉"), ("静待佳音", "吉"), ("稳中求进", "吉"),
    ("猫伴身旁", "吉"), ("准时下班", "吉"), ("灵感迸发", "吉"), ("旧友重逢", "吉"),
    ("作事不和", "凶"), ("临危冒进", "凶"), ("口舌是非", "凶"), ("旧疾反复", "凶"),
    ("财帛勿急", "凶"), ("行舟逆水", "凶"), ("言多必失", "凶"), ("熬夜伤身", "凶"),
    ("过度自信", "凶"), ("错信谗言", "凶"), ("忘带钥匙", "凶"), ("临时改约", "凶"),
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = _FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _seeded(*parts: str) -> "hashlib._Hash":
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8"))


def _rng(*parts: str):
    import random

    return random.Random(_seeded(*parts).hexdigest())


def _load_portrait(explicit: Optional[str], search_dirs: Optional[list[str]]) -> Optional[Image.Image]:
    """加载猫娘立绘：优先显式路径，其次在目录里找第一张图（缓存交给调用方）。"""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    for d in search_dirs or []:
        base = Path(d)
        if base.is_dir():
            for pattern in ("*.png", "*.jpg", "*.webp"):
                candidates.extend(sorted(base.glob(pattern)))
    for path in candidates:
        try:
            if path.is_file():
                img = Image.open(path).convert("RGBA")
                return img
        except Exception:
            continue
    return None


def _vertical_text(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font: ImageFont.FreeTypeFont, fill) -> None:
    """竖排文字：逐字下排（参考签文样式）。"""
    step = int(font.size * 1.18)
    for i, ch in enumerate(text):
        draw.text((x, y + i * step), ch, font=font, fill=fill)


def _rounded(draw: ImageDraw.ImageDraw, box, radius: int, **kwargs) -> None:
    draw.rounded_rectangle(box, radius=radius, **kwargs)


def render_fortune_card(
    out_path: str,
    fortune: dict[str, Any],
    user_name: str = "主人",
    catgirl_name: str = "猫娘",
    portrait_path: Optional[str] = None,
    portrait_dirs: Optional[list[str]] = None,
    total_luck: Optional[int] = None,
    luck_score: Optional[int] = None,
) -> str:
    """渲染签文式运势卡。同 (date, user, level) 输出逐字节一致。"""
    w, h = 760, 960
    main, soft = _LEVEL_COLORS.get(str(fortune.get("level", "吉")), _LEVEL_COLORS["吉"])
    rng = _rng("fortune-card", fortune.get("date", ""), user_name, str(fortune.get("level")))

    # 背景：柔和渐变 + 主色描边
    img = Image.new("RGB", (w, h), soft)
    top = Image.new("RGB", (w, h), main)
    img = Image.blend(img, top, 0.18)
    draw = ImageDraw.Draw(img, "RGBA")

    # 底纹：斜向喵爪点缀（确定性伪随机）
    for _ in range(24):
        x, y = rng.randrange(0, w - 30), rng.randrange(0, h - 30)
        r = rng.randrange(6, 16)
        draw.ellipse((x, y, x + r, y + r), fill=(255, 255, 255, 26))

    # 猫娘立绘（右侧半透明），找不到就画一只极简猫轮廓
    portrait = _load_portrait(portrait_path, portrait_dirs)
    if portrait is not None:
        target_h = 520
        ratio = target_h / portrait.height
        portrait = portrait.resize((max(1, int(portrait.width * ratio)), target_h))
        alpha = portrait.split()[3].point(lambda a: int(a * 0.92))
        portrait.putalpha(alpha)
        img.paste(portrait, (w - portrait.width - 24, 150), portrait)
    else:
        cx, cy = w - 190, 380
        draw.polygon([(cx - 90, cy - 40), (cx - 55, cy - 150), (cx - 10, cy - 60)], fill=(255, 255, 255, 200))
        draw.polygon([(cx + 90, cy - 40), (cx + 55, cy - 150), (cx + 10, cy - 60)], fill=(255, 255, 255, 200))
        draw.ellipse((cx - 110, cy - 70, cx + 110, cy + 150), fill=(255, 255, 255, 210))
        draw.ellipse((cx - 62, cy + 6, cx - 22, cy + 46), fill=main)
        draw.ellipse((cx + 22, cy + 6, cx + 62, cy + 46), fill=main)

    # 签文卡（左侧竖排，右起三列 + 吉凶章）
    card_x0, card_y0, card_x1, card_y1 = 64, 150, 380, 760
    _rounded(draw, (card_x0, card_y0, card_x1, card_y1), 26, fill=(255, 255, 255, 235), outline=main, width=5)
    _rounded(draw, (card_x0 + 14, card_y0 + 14, card_x1 - 14, card_y1 - 14), 18, outline=main, width=2)

    # 三列签文（右→左），吉签优先取吉池，凶签取凶池
    want = "凶" if str(fortune.get("level")) in ("凶", "大凶") else "吉"
    pool = [(p, t) for p, t in _ORACLE_POOL if t == want]
    picked = rng.sample(pool, k=min(3, len(pool)))
    col_x = [card_x1 - 96, card_x1 - 196, card_x1 - 296]
    col_font = _font(44)
    for i, (phrase, tag) in enumerate(picked):
        _vertical_text(draw, col_x[i], card_y0 + 96, phrase, col_font, (55, 55, 65))
        _vertical_text(draw, col_x[i] + 4, card_y0 + 96 + 44 * 5 + 18, tag, _font(36, True), main)

    # 吉凶印章（盖在卡片右上角边框上，像真的印章）
    seal_r = 48
    sx, sy = card_x1 - 30, card_y0 + 26
    draw.ellipse((sx - seal_r, sy - seal_r, sx + seal_r, sy + seal_r), fill=main, outline=(255, 255, 255), width=3)
    level_text = str(fortune.get("level", ""))
    draw.text((sx - len(level_text) * 19 - 4, sy - 24), level_text, font=_font(36, True), fill=(255, 255, 255))

    # 顶部标题与日期
    draw.text((64, 48), f"{catgirl_name}的每日运势签", font=_font(44, True), fill=(50, 50, 60))
    draw.text((64, 104), str(fortune.get("date", "")), font=_font(28), fill=(90, 90, 100))

    # 底部信息条（无 emoji：微软雅黑没有彩色字形，会渲染成豆腐块）
    info_y = 792
    draw.text((64, info_y), f"摸鱼指数　{fortune.get('fish_index', 50)} / 100", font=_font(32), fill=(60, 60, 70))
    draw.text((64, info_y + 46), f"幸运色 {fortune.get('lucky_color', '')}　　幸运数字 {fortune.get('lucky_number', '')}", font=_font(28), fill=(90, 90, 100))
    shown_score = int(luck_score if luck_score is not None else fortune.get("score", 0))
    luck_line = f"今日幸运 {shown_score:+d}"
    if total_luck is not None:
        luck_line += f"　　累积幸运 {total_luck}"
    draw.text((64, info_y + 88), luck_line, font=_font(34, True), fill=main)
    draw.text((64, h - 38), f"—— {catgirl_name} 喵～", font=_font(24), fill=(120, 120, 130))

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def render_wife_card(
    out_path: str,
    wife: dict[str, Any],
    user_name: str = "主人",
    ordinal_today: int = 1,
    silver: int = 0,
    gold: int = 0,
    catgirl_name: str = "猫娘",
    portrait_path: Optional[str] = None,
    portrait_dirs: Optional[list[str]] = None,
    character_image: Optional[str] = None,
) -> str:
    """渲染今日老婆卡。同 (date, user) 输出逐字节一致。"""
    w, h = 760, 960
    rng = _rng("wife-card", wife.get("date", ""), str(wife.get("user_id", "")))
    main = (
        rng.randrange(140, 230),
        rng.randrange(120, 210),
        rng.randrange(180, 250),
    )
    img = Image.new("RGB", (w, h), (250, 246, 252))
    draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(26):
        x, y = rng.randrange(0, w - 30), rng.randrange(0, h - 40)
        r = rng.randrange(4, 14)
        draw.ellipse((x, y, x + r, y + r), fill=(*main, 30))

    draw.text((64, 44), f"💃 {user_name} 的今日老婆", font=_font(42, True), fill=(60, 60, 72))
    draw.text((64, 104), str(wife.get("date", "")), font=_font(28), fill=(110, 110, 120))

    # 角色名大字 + 作品
    name = str(wife.get("name", "？？？"))
    work = str(wife.get("work", ""))
    draw.text((64, 190), name[:12], font=_font(64, True), fill=main)
    if work:
        draw.text((66, 278), f"《{work[:16]}》", font=_font(32), fill=(110, 110, 125))

    # 角色图只用「按该角色检索到」的图；检索失败就画占位，绝不塞猫娘立绘，
    # 否则会出现「文字描述 A 角色、图却是 B 角色」的错配
    portrait = _load_portrait(character_image, None) if character_image else None
    box = (64, 340, w - 64, 800)
    _rounded(draw, box, 30, fill=(255, 255, 255, 200), outline=main, width=5)
    if portrait is not None:
        inner_w, inner_h = box[2] - box[0] - 24, box[3] - box[1] - 24
        ratio = min(inner_w / portrait.width, inner_h / portrait.height)
        portrait = portrait.resize((max(1, int(portrait.width * ratio)), max(1, int(portrait.height * ratio))))
        img.paste(portrait, (box[0] + 12 + (inner_w - portrait.width) // 2, box[1] + 12 + (inner_h - portrait.height) // 2), portrait)
    else:
        draw.text(((box[0] + box[2]) // 2 - 90, (box[1] + box[3]) // 2 - 40), "今日老婆", font=_font(48, True), fill=(*main, 160))

    # 计数与货币（无 emoji，避免豆腐块）
    draw.text((64, 820), f"今天的第 {ordinal_today} 个老婆", font=_font(36, True), fill=(70, 70, 82))
    draw.text((64, 872), f"银币 +{silver}　　金币 +{gold}", font=_font(32), fill=(90, 90, 100))
    draw.text((64, h - 40), f"—— 由 {catgirl_name} 亲自抽选喵～", font=_font(24), fill=(120, 120, 130))

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path
