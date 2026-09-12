"""猫娘每日关怀插件（neko_daily_fortune）v0.1 · 作者：MENGYAOYUE

把相近的「定时关怀」功能集成在一个插件里，每个功能独立开关：
- ☀️ 早安摸鱼日报：早安 + 星期/周末倒计时/发薪日倒计时 + 当日运势速览（开关 morning_push）
- 🔮 今日运势签：随时可查，按「日期+主人名」确定性生成，一天内结果不变
- 💧 喝水提醒：工作时间按间隔提醒喝水（开关 water_reminder，可配时段与间隔）

纯标准库实现，零第三方依赖。推送走 N.E.K.O SDK 的 ctx.push_message（猫娘主动开口），
所有文案都是猫娘口吻。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from plugin.sdk.plugin import (
    Err,
    NekoPluginBase,
    Ok,
    SdkError,
    lifecycle,
    llm_tool,
    neko_plugin,
    plugin_entry,
)

from ._fortune_images import render_fortune_card, render_wife_card
from ._image_sources import fetch_character_image, fetch_catgirl_artwork
from ._platform import PlatformServer
import os as _os
from ._fortune_logic import (
    daily_fortune,
    render_fortune,
    render_morning_report,
)
from ._waifu_logic import (
    draw_wife,
    luck_ranking,
    luck_score_for,
    render_luck_rank,
    update_user_record,
    wife_rewards,
)

_PLUGIN_ID = "neko_daily_fortune"

# 各功能的默认开关状态（config 未写时生效）
_DEFAULT_SWITCHES: dict[str, bool] = {
    "morning_push": True,
    "water_reminder": False,
}


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _safe_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _safe_int(value: Any, default: int) -> int:
    return int(_safe_float(value, default))


def _safe_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"1", "true", "yes", "on", "开"}:
            return True
        if low in {"0", "false", "no", "off", "关"}:
            return False
    return default


def _now_in_tz(tz_name: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.now()


@neko_plugin
class DailyFortunePlugin(NekoPluginBase):
    """猫娘每日关怀：运势签 + 摸鱼日报 + 喝水提醒，功能独立开关。"""

    def __init__(self, ctx):
        super().__init__(ctx)
        self.file_logger = self.enable_file_logging(log_level="INFO")
        self.logger = self.file_logger

        self.data_dir = Path(self.data_path())
        self.state_path = self.data_dir / "fortune_state.json"

        # 配置在 startup 里注入
        self.master_name: str = "主人"
        self.catgirl_name: str = "猫娘"
        self.timezone: str = "Asia/Shanghai"
        self.push_time: str = "08:30"
        self.payday: int = 0
        self.water_interval_minutes: int = 60
        self.water_start: str = "09:00"
        self.water_end: str = "21:00"
        self.switches: dict[str, bool] = dict(_DEFAULT_SWITCHES)
        self.portrait_path: str = ""
        self.fetch_image: bool = True
        self.fortune_art_source: str = "local"
        self.platform_port: int = 15672
        self.platform_enabled: bool = True
        self.auto_open: bool = True
        self._platform: Optional[PlatformServer] = None
        self._users_lock = threading.Lock()
        self._config_loaded = False

        # 多用户档案（"仅本插件的小平台"）：per-user 运势/老婆/货币记录
        self.users: dict[str, Any] = {}
        self.wife_counter: dict[str, int] = {}
        self._portrait_dirs: list[str] = []

        # 分钟级 ticker（与 catgirl_daily_planner 相同的框架模式）
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._tick_thread: Optional[threading.Thread] = None

    # ── 配置与状态 ─────────────────────────────────────────────
    async def _load_config(self) -> None:
        try:
            cfg = await self.config.dump(timeout=5.0)
        except Exception as exc:
            self.logger.warning("[daily_fortune] 读取配置失败：{}", exc)
            cfg = {}
        section = cfg.get(_PLUGIN_ID) if isinstance(cfg, dict) else None
        section = section if isinstance(section, dict) else {}

        self.master_name = _safe_str(section.get("master_name"), "主人") or "主人"
        self.catgirl_name = _safe_str(section.get("catgirl_name"), "猫娘") or "猫娘"
        self.timezone = _safe_str(section.get("timezone"), "Asia/Shanghai") or "Asia/Shanghai"
        self.push_time = _safe_str(section.get("push_time"), "08:30") or "08:30"
        self.payday = _safe_int(section.get("payday"), 0)
        self.water_interval_minutes = max(10, _safe_int(section.get("water_interval_minutes"), 60))
        self.water_start = _safe_str(section.get("water_start"), "09:00") or "09:00"
        self.water_end = _safe_str(section.get("water_end"), "21:00") or "21:00"
        self.portrait_path = _safe_str(section.get("portrait_path"))
        self.fetch_image = _safe_bool(section.get("fetch_image"), True)
        art_src = _safe_str(section.get("fortune_art_source"), "local").lower()
        self.fortune_art_source = art_src if art_src in ("auto", "local", "off") else "auto"
        self.platform_port = _safe_int(section.get("platform_port"), 15672)
        self.platform_enabled = _safe_bool(section.get("platform_enabled"), True)
        self.auto_open = _safe_bool(section.get("auto_open"), True)
        self._portrait_dirs = []

        switches_cfg = section.get("switches")
        switches_cfg = switches_cfg if isinstance(switches_cfg, dict) else {}
        for key, default in _DEFAULT_SWITCHES.items():
            self.switches[key] = _safe_bool(switches_cfg.get(key, self.switches.get(key, default)), default)
        # 开关持久化状态覆盖配置默认值（类型与布尔化守卫，避免脏状态导致启动失败）
        saved_switches = self._load_state().get("switches")
        if isinstance(saved_switches, dict):
            for key in _DEFAULT_SWITCHES:
                if key in saved_switches:
                    self.switches[key] = _safe_bool(saved_switches[key], self.switches[key])
        self._config_loaded = True

    async def _ensure_config_loaded(self) -> None:
        if not self._config_loaded:
            await self._load_config()

    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _load_users(self) -> None:
        state = self._load_state()
        users = state.get("users")
        self.users = users if isinstance(users, dict) else {}
        counter = state.get("wife_counter")
        self.wife_counter = counter if isinstance(counter, dict) else {}

    def _save_users(self) -> None:
        state = self._load_state()
        state["users"] = self.users
        state["wife_counter"] = self.wife_counter
        self._save_state(state)

    def _portrait_search_dirs(self) -> list[str]:
        """猫娘立绘搜索目录：N.E.K.O 根目录的 card_faces / character_cards。"""
        if self._portrait_dirs:
            return self._portrait_dirs
        dirs: list[str] = []
        if _safe_str(self.portrait_path):
            dirs.append(self.portrait_path)
        try:
            root = self.data_dir.parent.parent.parent
            for name in ("card_faces", "character_cards"):
                p = root / name
                if p.is_dir():
                    dirs.append(str(p))
        except Exception:
            pass
        self._portrait_dirs = dirs
        return dirs

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            self.logger.warning("[daily_fortune] 状态写入失败：{}", exc)

    # ── 生命周期 ───────────────────────────────────────────────
    @lifecycle(id="startup")
    async def startup(self, **_):
        await self._load_config()
        self._stop_event.clear()
        self._wake_event.clear()
        self._tick_thread = threading.Thread(
            target=self._tick_loop, daemon=True, name="neko-daily-fortune-tick"
        )
        self._tick_thread.start()
        self._start_platform()
        self.logger.info(
            "[daily_fortune] 启动：master={}, push_time={}, switches={}",
            self.master_name, self.push_time, self.switches,
        )
        return Ok({"status": "running", "version": "0.1.0"})

    def _start_platform(self) -> None:
        """启动附属网页（仅 127.0.0.1）；端口占用则自动 +1 重试三次。"""
        if not self.platform_enabled:
            return
        for offset in range(4):
            server = PlatformServer(
                self.platform_port + offset, self.data_dir / "cards", self._platform_data
            )
            if server.start():
                self._platform = server
                self.platform_port += offset
                self.logger.info("[daily_fortune] 平台网页已启动: http://127.0.0.1:{}", self.platform_port)
                break
        else:
            self.logger.warning("[daily_fortune] 平台网页启动失败（端口全被占用）")
            return
        # 注册 static UI 到宿主：插件管理页的「面板」页内嵌本插件的网页，右上角出现「打开界面」
        try:
            registered = self.register_static_ui("static")
            self.logger.info("[daily_fortune] static UI 注册: {}", registered)
        except Exception as exc:
            self.logger.warning("[daily_fortune] static UI 注册失败: {}", exc)

    def _platform_data(self, user_id: str) -> dict[str, Any]:
        """为平台页面准备数据：确保当天卡片已生成（线程安全，幂等）。"""
        with self._users_lock:
            fortune, wife, rewards, ordinal = self._today_record_sync(user_id, self.users.get(user_id, {}).get("name") or self.master_name)
            user = self.users.get(user_id, {})
            total_luck = int(user.get("total_luck", 0))
            day_score = int((user.get("days") or {}).get(fortune.get("date", ""), {}).get("score", 0))
            fortune_img = f"cards/fortune_{user_id}_{fortune['date']}.png"
            wife_img = f"cards/wife_{user_id}_{wife['date']}.png"
            fp = self.data_dir / fortune_img
            wp = self.data_dir / wife_img
            if not fp.exists():
                art = self._get_fortune_art(str(fortune.get("date", "")), user_id)
                render_fortune_card(str(fp), fortune, user.get("name") or self.master_name,
                                    self.catgirl_name, portrait_path=art,
                                    total_luck=total_luck, luck_score=day_score)
            if not wp.exists():
                char_img = None
                if self.fetch_image:
                    char_img = fetch_character_image(
                        str(wife.get("en_tag") or ""),
                        str(self.data_dir / f"cards/wifeimg_{user_id}_{wife['date']}.img"),
                        f"{wife['date']}|{user_id}",
                    )
                render_wife_card(str(wp), wife, user.get("name") or self.master_name, ordinal,
                                 rewards["silver"], rewards["gold"], self.catgirl_name,
                                 portrait_path=self.portrait_path or None,
                                 portrait_dirs=self._portrait_search_dirs(),
                                 character_image=char_img)
            self._save_users()
            rows = luck_ranking(self.users, fortune.get("date", ""))
            from ._fortune_logic import render_fortune
            return {
                "today": fortune.get("date", ""),
                "fortune_img": "/" + fortune_img,
                "wife_img": "/" + wife_img,
                "fortune_text": f"{fortune.get('emoji')} {fortune.get('level')}｜宜 {'、'.join(fortune.get('do', []))[:14]}｜摸鱼 {fortune.get('fish_index', 50)}/100",
                "wife_text": f"{wife['name']}《{wife['work']}》｜第 {ordinal} 个｜契合度 {wife['bond']}",
                "rank_rows": rows,
                "user_name": user.get("name") or self.master_name,
                "me": {"user_id": user_id, **user},
                "catgirl_name": self.catgirl_name,
            }

    def _today_record_sync(self, user_id: str, user_name: str):
        """_today_record 的同步版（平台线程里没有事件循环）。"""
        now = _now_in_tz(self.timezone)
        today = now.strftime("%Y-%m-%d")
        fortune = daily_fortune(today, user_id)
        score = luck_score_for(str(fortune.get("level", "吉")))
        wife = draw_wife(today, user_id, self.catgirl_name)
        rewards = wife_rewards(int(fortune.get("fish_index", 50)), today, user_id)
        user = update_user_record(self.users, user_id, user_name, today, score, rewards, wife["name"])
        self.wife_counter[today] = int(self.wife_counter.get(today, 0)) + 1
        ordinal = self.wife_counter[today]
        return fortune, wife, rewards, ordinal

    def _local_portrait_rotation(self, date: str) -> Optional[str]:
        """本地卡面库轮换：card_faces / character_cards 里所有图按日期轮着用。"""
        dirs = self._portrait_search_dirs()
        pool: list[Path] = []
        for d in dirs:
            base = Path(d)
            if base.is_dir():
                for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                    pool.extend(base.glob(pattern))
        if not pool:
            return None
        pool = sorted(set(pool))
        import hashlib as _hl
        idx = int.from_bytes(_hl.sha256(date.encode("utf-8")).digest()[:4], "big") % len(pool)
        return str(pool[idx])

    def _get_fortune_art(self, date: str, user_id: str) -> Optional[str]:
        """当日运势卡配图：图站猫娘插画（auto）→ 本地社区卡面轮换 → 固定立绘。

        当天缓存一次（art_{date}.img），全用户共享同一张当日图。
        """
        cache = self.data_dir / f"cards/art_{date}.img"
        if cache.exists():
            return str(cache)
        if self.fortune_art_source == "auto" and self.fetch_image:
            try:
                got = fetch_catgirl_artwork(str(cache), f"{date}|{user_id}")
                if got:
                    return got
            except Exception:
                pass
        if self.fortune_art_source in ("auto", "local"):
            local = self._local_portrait_rotation(date)
            if local:
                return local
        return self.portrait_path or None

    def _open_browser(self, url: str) -> bool:
        try:
            if _os.name == "nt":
                _os.startfile(url)  # type: ignore[attr-defined]
                return True
            import subprocess
            subprocess.Popen(["xdg-open", url])
            return True
        except Exception:
            return False

    def _platform_url(self, user_id: str) -> str:
        return f"http://127.0.0.1:{self.platform_port}/?user={user_id}"

    @lifecycle(id="shutdown")
    def shutdown(self, **_):
        if self._platform:
            self._platform.stop()
        self._stop_event.set()
        self._wake_event.set()
        if self._tick_thread and self._tick_thread.is_alive():
            self._tick_thread.join(timeout=3.0)
        self.logger.info("[daily_fortune] 关闭")
        return Ok("stopped")

    # ── 分钟级 ticker ──────────────────────────────────────────
    def _tick_loop(self) -> None:
        last_minute = ""
        last_water_minute = ""
        while not self._stop_event.is_set():
            try:
                now = _now_in_tz(self.timezone)
                minute_key = now.strftime("%Y-%m-%d %H:%M")
                if minute_key != last_minute:
                    last_minute = minute_key
                    self._handle_minute(now)
                # 喝水提醒按独立间隔触发（不占 last_minute，避免和其他推送抢拍）
                if self._maybe_water(now, last_water_minute):
                    last_water_minute = minute_key
            except Exception:
                self.logger.exception("[daily_fortune] tick 异常")
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
            self._wake_event.wait(timeout=20.0)
        self.logger.info("[daily_fortune] ticker 退出")

    def _handle_minute(self, now: datetime) -> None:
        state = self._load_state()
        today = now.strftime("%Y-%m-%d")

        # 早安摸鱼日报：到点且今天还没推过
        if self.switches.get("morning_push", True):
            push_at = now.replace(
                hour=int(self.push_time.split(":")[0]) if ":" in self.push_time else 8,
                minute=int(self.push_time.split(":")[1]) if ":" in self.push_time else 30,
                second=0, microsecond=0,
            )
            if now >= push_at and state.get("morning_pushed_date") != today:
                fortune = daily_fortune(today, self.master_name)
                report = render_morning_report(
                    now, fortune, self.master_name, self.catgirl_name, self.payday
                )
                self._push(report, metadata={"description": "🐱 早安摸鱼日报"})
                state["morning_pushed_date"] = today
                self._save_state(state)

    def _maybe_water(self, now: datetime, last_water_minute: str) -> bool:
        """判断并推送喝水提醒；返回是否真的推送了（供 ticker 去重）。"""
        if not self.switches.get("water_reminder", False):
            return False
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if minute_key == last_water_minute:
            return False
        try:
            start = now.replace(
                hour=int(self.water_start.split(":")[0]), minute=int(self.water_start.split(":")[1]),
                second=0, microsecond=0,
            )
            end = now.replace(
                hour=int(self.water_end.split(":")[0]), minute=int(self.water_end.split(":")[1]),
                second=0, microsecond=0,
            )
        except (ValueError, IndexError):
            return False
        if not (start <= now <= end):
            return False
        # 对齐间隔：分钟数被 interval 整除才触发
        if now.minute % max(10, self.water_interval_minutes) != 0:
            return False
        self._push(
            f"💧 喝水时间到喵！{self.master_name}要好好喝水，本喵才会放心～",
            metadata={"description": "🐱 喝水提醒"},
        )
        return True

    def _push(self, text: str, metadata: Optional[dict] = None) -> None:
        try:
            self.ctx.push_message(
                source=_PLUGIN_ID,
                visibility=[],
                ai_behavior="respond",
                parts=[{"type": "text", "text": text}],
                priority=5,
                metadata=metadata or {"description": "🐱 每日关怀"},
            )
        except Exception:
            self.logger.exception("[daily_fortune] push_message 失败")

    # ── 功能入口 ───────────────────────────────────────────────
    async def _fortune_text(self, date_str: str = "") -> str:
        await self._ensure_config_loaded()
        day = date_str or _now_in_tz(self.timezone).strftime("%Y-%m-%d")
        fortune = daily_fortune(day, self.master_name)
        return render_fortune(fortune, self.master_name, self.catgirl_name)

    @llm_tool(
        name="neko_daily_fortune",
        description="查询猫娘为用户生成的今日运势签（含运势等级、摸鱼指数、幸运色、宜忌、发薪日/周末倒计时等猫娘趣味内容）。",
        parameters={
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "可选，YYYY-MM-DD，默认今天"},
            },
        },
        timeout=10.0,
    )
    @plugin_entry(
        id="fortune",
        name="今日运势签",
        description="生成/查询猫娘口吻的今日运势签与摸鱼指数（同一日期结果固定）。",
        input_schema={
            "type": "object",
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD，默认今天"}},
        },
    )
    async def fortune_entry(self, date: str = "", **_):
        try:
            return Ok(await self._fortune_text(date))
        except Exception as exc:
            self.logger.exception("生成运势失败: {}", exc)
            return Err(SdkError(f"呜…运势签生成失败了：{exc}"))

    @plugin_entry(
        id="morning_report",
        name="摸鱼日报",
        description="立即生成一份早安摸鱼日报（星期/周末倒计时/发薪日倒计时/运势速览），不推送，直接返回文本。",
        input_schema={"type": "object", "properties": {}},
    )
    async def morning_report_entry(self, **_):
        await self._ensure_config_loaded()
        now = _now_in_tz(self.timezone)
        fortune = daily_fortune(now.strftime("%Y-%m-%d"), self.master_name)
        return Ok(render_morning_report(now, fortune, self.master_name, self.catgirl_name, self.payday))

    @plugin_entry(
        id="set_switch",
        name="功能开关",
        description="开关某个功能：feature=morning_push/water_reminder，enabled=true/false。",
        input_schema={
            "type": "object",
            "properties": {
                "feature": {"type": "string", "enum": ["morning_push", "water_reminder"]},
                "enabled": {"type": "boolean"},
            },
            "required": ["feature", "enabled"],
        },
    )
    async def set_switch_entry(self, feature: str = "", enabled: bool = True, **_):
        await self._ensure_config_loaded()
        if feature not in _DEFAULT_SWITCHES:
            return Err(SdkError(f"未知功能：{feature}（可选：{'、'.join(_DEFAULT_SWITCHES)}）"))
        self.switches[feature] = bool(enabled)
        state = self._load_state()
        switches = state.get("switches") if isinstance(state.get("switches"), dict) else {}
        switches[feature] = bool(enabled)
        state["switches"] = switches
        self._save_state(state)
        label = "早安摸鱼日报" if feature == "morning_push" else "喝水提醒"
        return Ok(f"已{'开启' if enabled else '关闭'}「{label}」喵～")

    async def _today_record(self, user_id: str, user_name: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], int]:
        """取/建某用户当天的运势+老婆+奖励记录（幂等）。"""
        await self._ensure_config_loaded()
        self._load_users()
        now = _now_in_tz(self.timezone)
        today = now.strftime("%Y-%m-%d")
        fortune = daily_fortune(today, user_id)
        score = luck_score_for(str(fortune.get("level", "吉")))
        wife = draw_wife(today, user_id, self.catgirl_name)
        rewards = wife_rewards(int(fortune.get("fish_index", 50)), today, user_id)
        user = update_user_record(
            self.users, user_id, user_name, today, score, rewards, wife["name"]
        )
        self.wife_counter[today] = int(self.wife_counter.get(today, 0)) + 1
        ordinal = self.wife_counter[today]
        self._save_users()
        return fortune, wife, rewards, ordinal

    @llm_tool(
        name="neko_daily_wife",
        description="抽今日老婆：按用户和日期确定性随机一位二次元角色，带第N个老婆计数与银币/金币奖励，并生成老婆卡图片。",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "用户标识（QQ 号等，可省略）"},
                "user_name": {"type": "string", "description": "展示用昵称（可省略）"},
            },
        },
        timeout=15.0,
    )
    @plugin_entry(
        id="daily_wife",
        name="今日老婆",
        description="抽取今日老婆（同人同日结果固定），生成老婆卡图片并记录货币奖励。",
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "user_name": {"type": "string"},
            },
        },
    )
    async def daily_wife_entry(self, user_id: str = "", user_name: str = "", **_):
        await self._ensure_config_loaded()
        uid = _safe_str(user_id, "local") or "local"
        uname = _safe_str(user_name, self.master_name) or self.master_name
        _fortune, wife, rewards, ordinal = await self._today_record(uid, uname)
        img_path = self.data_dir / f"cards/wife_{uid}_{wife['date']}.png"
        # 多来源拉角色图（首个成功即短路）；全失败回退本地绘制
        char_img = None
        if self.fetch_image:
            char_img = await asyncio.to_thread(
                fetch_character_image,
                str(wife.get("en_tag") or ""),
                str(self.data_dir / f"cards/wifeimg_{uid}_{wife['date']}.img"),
                f"{wife['date']}|{uid}",
            )
        render_wife_card(
            str(img_path), wife, uname, ordinal,
            rewards["silver"], rewards["gold"], self.catgirl_name,
            portrait_path=self.portrait_path or None,
            portrait_dirs=self._portrait_search_dirs(),
            character_image=char_img,
        )
        via = "（图片来源：图站检索）" if char_img else "（图站没搜到，本喵手绘的占位卡喵）"
        url = self._platform_url(uid)
        if self.auto_open:
            self._open_browser(url)
        return Ok(
            f"你的今日老婆是「{wife['name']}」（{wife['work']}）喵！\n"
            f"🌸 今天的第 {ordinal} 个老婆\n"
            f"🪙 银币 +{rewards['silver']}　💠 金币 +{rewards['gold']}\n"
            f"💞 与主人的契合度 {wife['bond']}\n"
            f"🖼 卡片已生成：{img_path}\n{via}\n"
            f"🖥 看图请看弹出的平台页：{url}"
        )

    @plugin_entry(
        id="fortune_card",
        name="运势签图片",
        description="生成签文式运势卡图片（每天不同，猫娘立绘入卡），返回文字摘要与图片路径。",
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "user_name": {"type": "string"},
            },
        },
    )
    async def fortune_card_entry(self, user_id: str = "", user_name: str = "", **_):
        await self._ensure_config_loaded()
        uid = _safe_str(user_id, "local") or "local"
        uname = _safe_str(user_name, self.master_name) or self.master_name
        fortune, _wife, _rewards, _ordinal = await self._today_record(uid, uname)
        user = self.users.get(uid, {})
        total_luck = int(user.get("total_luck", 0))
        day_score = int((user.get("days") or {}).get(fortune.get("date", ""), {}).get("score", luck_score_for(str(fortune.get("level", "吉")))))
        img_path = self.data_dir / f"cards/fortune_{uid}_{fortune['date']}.png"
        art = self._get_fortune_art(str(fortune.get("date", "")), uid)
        render_fortune_card(
            str(img_path), fortune, uname, self.catgirl_name,
            portrait_path=art,
            total_luck=total_luck,
            luck_score=day_score,
        )
        if self.auto_open:
            self._open_browser(self._platform_url(uid))
        return Ok(
            f"{fortune.get('emoji')} 今日运势：{fortune.get('level')}（{fortune.get('date')}）\n"
            f"🍀 幸运 {day_score:+d}｜累积幸运 {total_luck}\n"
            f"✅ 宜 {'、'.join(fortune.get('do', []))}\n"
            f"🚫 忌 {'、'.join(fortune.get('dont', []))}\n"
            f"🖼 签卡已生成：{img_path}\n"
            f"🖥 看图请看弹出的平台页：{self._platform_url(uid)}"
        )

    @plugin_entry(
        id="luck_rank",
        name="幸运排行",
        description="查看本插件记录的幸运排行榜（累计幸运分，可附今日分）。",
        input_schema={
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
        },
    )
    async def luck_rank_entry(self, user_id: str = "", **_):
        await self._ensure_config_loaded()
        self._load_users()
        today = _now_in_tz(self.timezone).strftime("%Y-%m-%d")
        rows = luck_ranking(self.users, today)
        text = render_luck_rank(rows, today, self.catgirl_name)
        uid = _safe_str(user_id, "local") or "local"
        me = self.users.get(uid)
        if me:
            text += f"\n（你目前的银币 {me.get('coins', {}).get('silver', 0)}｜金币 {me.get('coins', {}).get('gold', 0)}）"
        return Ok(text)

    @plugin_entry(
        id="open_platform",
        name="打开关怀平台",
        description="在浏览器打开猫娘每日关怀平台（运势卡/老婆卡/幸运排行，仅本机可访问）。",
        input_schema={
            "type": "object",
            "properties": {"user_id": {"type": "string"}, "user_name": {"type": "string"}},
        },
    )
    async def open_platform_entry(self, user_id: str = "", user_name: str = "", **_):
        await self._ensure_config_loaded()
        if not self.platform_enabled or not self._platform:
            return Err(SdkError("平台网页未开启喵（platform_enabled=false 或端口被占）。"))
        uid = _safe_str(user_id, "local") or "local"
        if user_name:
            with self._users_lock:
                self._load_users()
                self.users.setdefault(uid, {}).setdefault("name", user_name)
                self._save_users()
        url = self._platform_url(uid)
        opened = self._open_browser(url)
        return Ok(f"平台页{'已在浏览器打开' if opened else '地址'}喵：{url}")

    @plugin_entry(
        id="status",
        name="关怀状态",
        description="查看各功能开关与当前配置。",
        input_schema={"type": "object", "properties": {}},
    )
    async def status_entry(self, **_):
        await self._ensure_config_loaded()
        lines = ["🐱 猫娘每日关怀："]
        lines.append(f"- 早安摸鱼日报：{'✅ 开' if self.switches.get('morning_push') else '⛔ 关'}（每天 {self.push_time}）")
        lines.append(f"- 💧 喝水提醒：{'✅ 开' if self.switches.get('water_reminder') else '⛔ 关'}（{self.water_start}~{self.water_end}，每 {self.water_interval_minutes} 分钟）")
        lines.append(f"- 主人：{self.master_name}｜发薪日：{self.payday or '未设置'}")
        return Ok("\n".join(lines))
