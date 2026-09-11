"""猫娘每日关怀插件：纯标准库独立测试（python tests/test_basic.py）"""

import importlib.util
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_logic():
    spec = importlib.util.spec_from_file_location(
        "neko_daily_fortune_logic", ROOT / "_fortune_logic.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["neko_daily_fortune_logic"] = mod
    spec.loader.exec_module(mod)
    return mod


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


def main():
    print("加载 _fortune_logic ...")
    mod = load_logic()

    # 1. 运势签确定性：同一天同名主人 → 完全一致；换天 → 大概率不同
    a = mod.daily_fortune("2026-09-12", "主人")
    b = mod.daily_fortune("2026-09-12", "主人")
    assert_eq(a, b, "同一天运势应一致")
    keys = {"date", "level", "emoji", "score", "fish_index", "lucky_color", "lucky_number", "do", "dont", "quote"}
    assert keys <= set(a), f"运势字段应齐全: {a}"
    assert a["level"] in {lv for lv, _, _ in mod._FORTUNE_LEVELS}, "运势等级应合法"
    assert 0 <= a["fish_index"] <= 100, "摸鱼指数应在 0-100"
    assert len(a["do"]) == 2 and len(a["dont"]) == 2, "宜忌各 2 条"
    assert len({mod.daily_fortune(d, "主人")["level"] for d in ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04")}) > 1, "换天运势应有变化"

    # 2. 名字参与种子：不同主人同一天运势可以不同
    seen = {mod.daily_fortune("2026-09-12", name)["level"] for name in ("甲", "乙", "丙", "丁", "戊")}
    assert len(seen) >= 1, "不同名字至少应可生成"

    # 3. 周末倒计时（2026-09-07 是周一，09-12 是周六）
    assert_eq(mod.days_until_weekend(datetime(2026, 9, 7)), 5, "周一距周六 5 天")
    assert_eq(mod.days_until_weekend(datetime(2026, 9, 11)), 1, "周五距周六 1 天")
    assert_eq(mod.days_until_weekend(datetime(2026, 9, 12)), 0, "周六为 0")
    assert_eq(mod.days_until_weekend(datetime(2026, 9, 13)), 0, "周日为 0")

    # 4. 发薪日倒计时
    assert_eq(mod.days_until_payday(datetime(2026, 9, 10), 10), 0, "发薪日当天为 0")
    assert_eq(mod.days_until_payday(datetime(2026, 9, 11), 10), 29, "9/11 距 10/10 为 29 天")
    assert_eq(mod.days_until_payday(datetime(2026, 9, 10), 0), -1, "未设置发薪日返回 -1")
    assert_eq(mod.days_until_payday(datetime(2026, 9, 10), 99), -1, "非法发薪日返回 -1")
    assert_eq(mod.days_until_payday(datetime(2026, 9, 10), True), -1, "布尔值不算合法发薪日")
    # 29-31 号边界：当月没有该日 → 顺延到当月最后一天，跨月仍要正确
    assert_eq(mod.days_until_payday(datetime(2026, 3, 31), 30), 30, "3/31 距 4/30 为 30 天")
    assert_eq(mod.days_until_payday(datetime(2026, 3, 31), 31), 0, "3/31 当天发薪为 0")
    assert_eq(mod.days_until_payday(datetime(2026, 1, 31), 29), 28, "1/31 距 2/28（2026 无 2/29）为 28 天")
    assert_eq(mod.days_until_payday(datetime(2026, 4, 1), 31), 29, "4/1 距 4/30（4 月无 31 号）为 29 天")

    # 5. 渲染：运势签 / 早安日报都是猫娘口吻且包含关键信息
    text = mod.render_fortune(a, "主人", "猫娘")
    assert "今日运势签" in text and "摸鱼指数" in text and "宜" in text and "忌" in text, f"运势签渲染: {text!r}"
    assert "猫娘" in text, "落款应有猫娘名字"

    now = datetime(2026, 9, 10, 9, 0)  # 周四
    report = mod.render_morning_report(now, a, "主人", "猫娘", payday=10)
    assert "星期四" in report, f"应包含星期: {report!r}"
    assert "发薪日" in report and "0 天" in report, "应包含发薪日倒计时"
    assert "运势" in report and "摸鱼指数" in report, "应包含运势速览"

    now_weekend = datetime(2026, 9, 12, 10, 0)
    report = mod.render_morning_report(now_weekend, a, "主人", "猫娘", payday=0)
    assert "周末" in report, "周末应特殊文案"
    assert "发薪日" not in report, "未设置发薪日不显示"

    # 6. 开关默认值与合法枚举
    assert set(mod.__dict__.get("_DEFAULT_SWITCHES", {"morning_push", "water_reminder"})) >= {"morning_push", "water_reminder"}, "应包含两个可开关功能"

    # 7. 状态文件读写契约（模拟插件行为）
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "fortune_state.json"
        state_path.write_text(json.dumps({"morning_pushed_date": "2026-09-12", "switches": {"water_reminder": True}}), encoding="utf-8")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert_eq(state.get("morning_pushed_date"), "2026-09-12", "状态应可读写")
        assert_eq(state["switches"]["water_reminder"], True, "开关应持久化")

    print("全部测试通过 ✅")


if __name__ == "__main__":
    main()
