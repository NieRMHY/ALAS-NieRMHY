# 守护模式 module/daemon

> 以「无终止条件的截图循环」长时间驻留的监控类任务：画面守护、大世界守护、基准测试与若干独立小工具。

## 1. 模块概述

普通任务是「做一件事然后延迟」；守护模式是「盯着一件事持续处理」。`module/daemon` 收录了所有这类长驻任务：`Daemon` 在任意战斗画面后台护航（用户半自动打图时自动点结算、清弹窗），`OpsiDaemon` 在大世界做同样的事并附加港口维修与自动选敌，`Benchmark`/`OcrBenchmark` 量化截图/OCR 性能，`GameManager`、`AzurLaneUncensored` 等提供一次性运维动作。

守护与普通任务的本质区别有两点，决定了代码形态：

- **主循环没有退出条件**。`run()` 是 `while True` 截图循环，注释明确「需手动停止」；它们通过 `alas.py` 的工具任务入口（`get_available_func()` 列出的 Daemon/OpsiDaemon/Benchmark 等）以独立任务身份运行。
- **刻意关闭死循环检测**。`DaemonBase.__init__` 调用 `disable_stuck_detection()`——挂机时画面可能长时间静止（战斗中、待机），若不禁用 `GameStuckError` 会在正常挂机时误报。

## 2. 模块职责

### 负责

- `daemon.py`：主线战斗守护（结算点击、伏击规避、进图准备、退役、紧急委托、弹窗）。
- `os_daemon.py`：大世界守护（战斗、经验结算、地图事件、港口维修、最近敌人选择）。
- `daemon_base.py`：`DaemonBase`，提供守护基座（禁用死循环检测）。
- `benchmark.py` / `ocr_benchmark.py`：截图、点击、滑动与 OCR 的耗时基准（Rich 表格输出）。
- `game_manager.py`：停止游戏进程（可选配合任务使用）。
- `uncensored.py`：向设备推送 `localization.txt` 并重启游戏（解禁皮肤立绘的运维工具）。

### 不负责

- 任务调度与下次运行决策——守护任务是「启停式」的，不申请 `task_delay`。
- 大世界任务编排、舰队策略——见[大世界核心](../os/index.md)；守护只是复用其能力做被动响应。
- 模拟器/ADB 的连接管理——见[设备层](../device.md)。

## 3. 模块位置

```
module/daemon/
├── daemon_base.py   # DaemonBase：disable_stuck_detection() 基座（约 13 行）
├── daemon.py        # AzurLaneDaemon(DaemonBase, CampaignBase)：主线守护
├── os_daemon.py     # AzurLaneDaemon(DaemonBase, OSFleet, PortHandler)：大世界守护
├── benchmark.py     # Benchmark(DaemonBase, CampaignUI)：截图/点击/滑动基准
├── ocr_benchmark.py # OcrBenchmark：三模型 OCR 精度/速度基准（含 tar 数据集）
├── game_manager.py  # GameManager(LoginHandler)：app_stop
└── uncensored.py    # localization.txt 推送与游戏重启
```

## 4. 核心入口

| 入口 | 任务名 | 用途 |
| --- | --- | --- |
| `AzurLaneDaemon.run()`（daemon.py） | Daemon | 主线战斗守护 |
| `AzurLaneDaemon.run()`（os_daemon.py） | OpsiDaemon | 大世界守护 |
| `Benchmark.run()` / `OcrBenchmark.run()` | Benchmark/OcrBenchmark | 性能基准（OCR 结果可回写 `Optimization_OcrDevice`） |
| `GameManager` / `AzurLaneUncensored` | —— | 经 `alas.py` 的 `game_manager/azur_lane_uncensored` 等工具任务调用 |

各文件 `__main__` 块支持脱离调度器直接运行：`b = AzurLaneDaemon('alas', task='Daemon'); b.run()`。

## 6. 工作流程

### 主线守护（daemon.py）的优先级链

每帧截图后按序检查，命中即处理并进入下一帧：战斗执行中（跳过）→ 战斗准备 → 战斗结算（`combat_status(expected_end='no_searching')`）→ 伏击规避 → 神秘格 → 进图准备（`Daemon_EnterMap` 开关）→ 退役 → 紧急委托 → 大舰队/投票弹窗 → 剧情跳过。注意 `handle_guild_popup_cancel()` 分支直接 `return True` 退出循环——单看是可疑写法（其余分支都是 `continue`），实际因无终止条件该 return 等价于「处理完本轮后停止任务」，修改时需确认是否有意。

### 大世界守护（os_daemon.py）的三个适配

1. `config.merge(OSConfig())` + `HOMO_EDGE_DETECT=False`——大世界不跑地图边缘检测。
2. 战斗结算必须走覆写的 `_os_combat_expected_end`（优先点 AUTO_SEARCH_REWARD），不能传普通地图的 `'no_searching'`——大世界地图检测永不成立会卡死在奖励页（代码注释详述）。
3. `battle_status_s_autoclick_delay = 3`：半自动模式 S 评价页不会自行推进，无需通用层的 20 秒防抢点兜底。

港口维修以 30 秒 interval 触发并提示用户「移出港口避免重复维修」；`OpsiDaemon_SelectEnemy` 开启时用雷达数据点击最近目标。

## 16. 修改注意事项

- **不要给守护任务加 task_delay**。它们被设计为手动启停的工具任务；若需要定时挂机，用普通任务组合而不是改守护。
- **守护禁用 stuck 检测是前提**：向 `DaemonBase` 加新分支时，任何「等待某画面」的循环都要自带超时，否则会真的无限等。
- **大世界守护的 `combat_status()` 必须用大世界结算路径**（见 `os_daemon` 注释与[大世界辅助模块](../os/auxiliary.md)），改通用 `Combat` 结算时回归验证两条守护链路。
- `handle_guild_popup_cancel` 在主线守护主循环里 `return True` 的写法疑似缺陷（与其他分支的 `continue` 语义不一致），修改弹窗处理时留意。

## 17. 已知限制

- 守护模式没有通知/断线重连以外的自愈手段，模拟器崩溃后不会自动重启游戏（与 `GameManager` 手动配合）。
- `Benchmark` 的 `TEST_TOTAL=15`、去最慢 20% 取均值的口径针对 720p 实机；更换模拟器后数值不可跨环境比较。

## 20. 相关模块

- [战役执行](../campaign.md) —— 主线守护组合的 `CampaignBase` 能力
- [大世界核心](../os/index.md) 与 [大世界辅助模块](../os/auxiliary.md) —— 大世界守护复用的舰队/港口/维修能力
- [OCR 系统](../ocr.md) —— `OcrBenchmark` 与 `OcrDevice` 自动选择的来源
- [调度器](../entry/alas.md) —— 工具任务的注册与启停
