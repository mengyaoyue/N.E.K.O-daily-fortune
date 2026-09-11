# 猫娘每日关怀（neko_daily_fortune）

> 相近的「定时关怀」功能集成在一个插件里，每个功能独立开关喵～ ☀️ 早安摸鱼日报 · 🔮 今日运势签 · 💧 喝水提醒

- 版本：`0.1.0`
- 作者：MENGYAOYUE
- 适用：N.E.K.O 插件运行时（SDK `>=0.1.0, <0.3.0`）
- 依赖：零第三方库，仅用 N.E.K.O 插件 SDK 与 Python 标准库

## 功能与开关

| 功能 | 说明 | 默认 | 开关方式 |
|------|------|------|----------|
| ☀️ 早安摸鱼日报 | 每天到点推送：星期、周末倒计时、发薪日倒计时、运势速览、猫娘语录 | 开 | 配置 `switches.morning_push` 或入口 `set_switch` |
| 🔮 今日运势签 | 随时可查：运势等级、摸鱼指数、幸运色/数字、宜忌（同一天结果固定） | 常开（按需查询） | 直接调用 |
| 💧 喝水提醒 | 工作时段按间隔提醒喝水 | 关 | 配置 `switches.water_reminder` 或入口 `set_switch` |

开关通过插件入口 `set_switch(feature, enabled)` 控制（猫娘聊天里说"关掉喝水提醒"即可触发），持久化在插件数据目录 `fortune_state.json`，重启不丢。

## 使用

- 聊天里说 **"今日运势"** / **"摸鱼日报"**：猫娘直接生成
- 自然语言命令插件（`/` 命令）也可跨插件调用本插件：`neko_daily_fortune:fortune`
- 推送内容走 `ctx.push_message`，由猫娘以自己的口吻主动说出口

## 配置（`[neko_daily_fortune]` 段）

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `master_name` | 主人 | 文案中的主人称呼 |
| `catgirl_name` | 猫娘 | 文案落款 |
| `timezone` | Asia/Shanghai | "今天"的判定时区 |
| `push_time` | 08:30 | 早安日报推送时间（启动晚于该点也会补推） |
| `payday` | 0 | 发薪日（1-31），0 不显示 |
| `water_start` / `water_end` | 09:00 / 21:00 | 喝水提醒生效时段 |
| `water_interval_minutes` | 60 | 喝水提醒间隔（最小 10 分钟） |

## 本地自测（无需 N.E.K.O 运行）

```bash
python tests/test_basic.py
```

## 数据存放

- `data/fortune_state.json`：推送去重（当天是否已推）与开关持久化
- 运势完全由本地算法生成，不联网、不依赖 API
