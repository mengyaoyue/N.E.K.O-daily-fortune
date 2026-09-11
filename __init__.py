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

from ._fortune_logic import (
    daily_fortune,
    render_fortune,
    render_morning_report,
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
        self._config_loaded = False

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

        switches_cfg = section.get("switches")
        switches_cfg = switches_cfg if isinstance(switches_cfg, dict) else {}
        for key, default in _DEFAULT_SWITCHES.items():
            self.switches[key] = _safe_bool(switches_cfg.get(key, self.switches.get(key, default)), default)
        # 开关持久化状态覆盖配置默认值
        self.switches.update(self._load_state().get("switches", {}))
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
        self.logger.info(
            "[daily_fortune] 启动：master={}, push_time={}, switches={}",
            self.master_name, self.push_time, self.switches,
        )
        return Ok({"status": "running", "version": "0.1.0"})

    @lifecycle(id="shutdown")
    def shutdown(self, **_):
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
                self._maybe_water(now, last_water_minute)
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

    def _maybe_water(self, now: datetime, last_water_minute: str) -> None:
        if not self.switches.get("water_reminder", False):
            return
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if minute_key == last_water_minute:
            return
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
            return
        if not (start <= now <= end):
            return
        # 对齐间隔：分钟数被 interval 整除才触发
        if now.minute % max(10, self.water_interval_minutes) != 0:
            return
        self._push(
            f"💧 喝水时间到喵！{self.master_name}要好好喝水，本喵才会放心～",
            metadata={"description": "🐱 喝水提醒"},
        )

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
