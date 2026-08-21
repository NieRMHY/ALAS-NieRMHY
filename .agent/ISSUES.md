---
description:
alwaysApply: true
---

# 问题清单与优化路线图

**生成日期**: 2026-05-27（2026-08-14 全面复核更新）
**项目版本**: dev 分支（HEAD f992af6c0）
**复核说明**: 2026-08-14 已对 `.agent/` 全部 23 份文档逐一对齐当前代码（类名、方法名、文件路径、模块清单、任务数量、行号引用、继承关系），下列原记录问题绝大部分已修复。

---

## 一、问题汇总

### 1.1 严重问题 (🔴)

> 可能导致 bug 或安全漏洞的问题

| 问题 | 位置 | 说明 | 状态 |
|------|------|------|------|
| `platform/ssh.py` 路径错误 | DEVICE.md | 原文档称 SSH 在 `module/device/platform/`，实际在 `module/base/ssh.py`（86 行，功能为清理 known_hosts 主机指纹，非 SSH 连接工具） | ✅ 已修复 |
| `os_grid.py` 导出类名错误 | MAP-DETECTION.md | 原文档称不存在 `OSGrid` 类，实际存在 `class OSGrid(OSGridInfo, OSGridPredictor, Grid)`（os_grid.py L330），已按三个类的真实定义重写 | ✅ 已修复 |
| `os_run.py` 类名与职责错误 | CAMPAIGN.md | 原文档称 `class OpsiRun`，实际为 `class OSCampaignRun(OSMapOperation)`（175 行，14 个 opsi_* 方法），已修正 | ✅ 已修复 |
| `ambush_1_1.py` 定位错误 | CAMPAIGN.md | 原文档称"战役地图定义 + 战斗逻辑"，实际为 `class Ambush11`（继承 `CampaignRun, FleetEquipment, Retirement`），另有 `AmbushEmotion`/`AmbushCampaignOverride`，已修正 | ✅ 已修复 |
| `alas.py` 的 `opsi_daily_delay()` 调用不存在的方法 | alas.py / OS-SYSTEM.md | `alas.py` 的 `opsi_daily_delay()` 调用 `OSCampaignRun.opsi_daily_delay()`，但 `OSCampaignRun` 只有 `opsi_daily()`，运行时会抛 `AttributeError`（代码问题，文档已按实际记录） | ⚠️ 代码待修 |

### 1.2 中等问题 (🟡)

> 影响可维护性或性能的问题

| 问题 | 位置 | 说明 | 状态 |
|------|------|------|------|
| 文档行号/行数系统性过时 | 全部文档 | 约半数文档的逐行分析（`Lxxx-xxx`）与文件实际行数不符。2026-08-14 已全部按当前代码重新核实（如 al_ocr.py 759 行、map_base.py 1083 行、app.py 363 行、connection.py 1297 行） | ✅ 已修复 |
| `RESTART_SENSITIVE_TASKS` 已删除 | ENTRY-ALAS.md | 原文档称常量在 alas.py，实际已删除，改为 `Error_StrictRestart` + `{task}.Scheduler.Sensitive` 动态判断（`_check_sensitive_exit` L233-L271 + loop 严格重启检查 L1431-L1455；默认 Sensitive 任务为 OpsiCrossMonth/OpsiAbyssal/OpsiObscure），已重写 | ✅ 已修复 |
| `call_tool` 分发重构 | ENTRY-MCP-SERVER.md | 原文档称 if/elif 分发链，实际已改为 `TOOL_HANDLERS` 字典分发（L466-L484），`call_tool` 仅约 10 行，已修正 | ✅ 已修复 |
| 任务数量过时 | ENTRY-ALAS.md / MODULE-MAP.md | 原文档称 55 个任务方法，实际 alas.py 共 112 个方法（93 个游戏任务方法 + 6 个基础任务方法 + 13 个基础设施方法），已更新为精确统计 | ✅ 已修复 |
| 商店类名带日期后缀 | GAME-FUNCTIONS.md | 原文档称 `GeneralShop`/`MedalShop`/`CoreShop`，实际为 `GeneralShop_250814`、`MedalShop2_250814`、`CoreShop_250814` 等 8 个 Shop 类，已修正 | ✅ 已修复 |
| `smart_scheduling_utils.py` 已删除 | OS-SYSTEM.md | 原文档 tasks 表仍列出，实际已并入 `module/os/tasks/scheduling.py`（1518 行，`OpsiScheduling`/`CoinTaskMixin`），已修正 | ✅ 已修复 |
| WebUI app.py 拆分重构 | INFRASTRUCTURE.md / ENTRY-GUI.md | 原文档称 app.py 5060+ 行导出 `AlasGUI`，实际仅 363 行，已拆分为 app_* 系列（module/webui/ 共 51 个 .py），已重写 | ✅ 已修复 |
| 文档元信息未更新 | 全部文档 | 原各文档头部"生成日期/最后分析的代码版本"停留在 2026-05-27 / cf2944e9e，已统一更新为 2026-08-14 / f992af6c0 | ✅ 已修复 |

### 1.3 建议问题 (🟢)

> 可优化的代码风格或结构

| 问题 | 位置 | 说明 | 状态 |
|------|------|------|------|
| utils.py 过大 | BASE.md | 1288 行，建议拆分为 color/image/area 等子模块 | ⏳ 待优化 |
| config.py 过大 | CONFIG.md | 907 行，调度逻辑（`get_next_task`/`task_delay`/`opsi_task_delay`）仍在 config.py 中，建议提取到独立模块 | ⏳ 待优化 |
| server.py 全局变量 | CONFIG.md | 全局 `server = 'cn'` 影响所有资源加载，测试困难，建议改为依赖注入 | ⏳ 待优化 |
| 测试覆盖 | 全部 | 核心工具函数（`crop()`、`color_similarity()`）与 `deep.py` 边界条件缺少单元测试 | ⏳ 待优化 |
| `opsi_daily_delay` 代码缺陷 | alas.py | 调用不存在的方法，详见 1.1 | ⏳ 待修复 |

---

## 二、整体重构/优化路线图

### 2.1 已完成（2026-08-14 文档对齐）

- ✅ 统一更新 `.agent/` 各文档的行号引用（与当前代码对齐）
- ✅ 为 `module/auto_equip`、`module/storage`、`module/game_setting`、`module/template`、`module/combat_ui` 补充模块分析（GAME-FUNCTIONS.md）
- ✅ 修正 ENTRY-GUI.md 的 gui.py 重构描述（依赖同步服务、worker_registry、双栈 socket）
- ✅ WebUI app.py 拆分后的文档对齐（INFRASTRUCTURE.md、ENTRY-GUI.md）
- ✅ 模块清单与 `module/` 实际 74 个子目录完全一致（MODULE-MAP.md、GAME-FUNCTIONS.md）
- ✅ 各文档头部元信息统一更新（2026-08-14 / dev / f992af6c0）

### 2.2 中期优化

- config.py 调度逻辑拆分（独立调度模块）
- 服务器管理重构（依赖注入替代全局变量）
- 修复 `alas.py` 的 `opsi_daily_delay()` 缺陷（改调用 `opsi_daily` 或定义对应方法）

### 2.3 长期优化

- 为核心工具函数（`crop()`、`color_similarity()`、`deep_*`）补充单元测试
- 建立文档与代码的自动一致性检查（如行号引用校验）

---

## 三、问题统计

| 严重程度 | 数量 | 状态 |
|---------|------|------|
| 🔴 严重 | 4/5 | 4 项已修复，1 项为代码缺陷（`opsi_daily_delay`）待修 |
| 🟡 中等 | 8 | 全部已修复 |
| 🟢 建议 | 5 | 4 项待优化，1 项为代码缺陷待修 |

---

## 四、模块问题索引

| 模块 | 文档链接 | 复核结果 |
|------|---------|---------|
| 入口文件 | [ENTRY-ALAS.md](ENTRY-ALAS.md) | ✅ 任务数/常量/行号已对齐；`opsi_daily_delay` 代码缺陷已记录 |
| 基础层 | [BASE.md](BASE.md) | ✅ 文件清单（14 个）、ssh.py、行号已对齐 |
| 配置系统 | [CONFIG.md](CONFIG.md) | ✅ 文件清单、行号、调度逻辑位置已对齐 |
| 设备层 | [DEVICE.md](DEVICE.md) | ✅ ssh.py 位置、method/ 与 platform/ 清单、行号已对齐 |
| UI 导航 | [UI.md](UI.md) | ✅ setting.py、54 个页面实例、行号已对齐 |
| OCR 系统 | [OCR.md](OCR.md) | ✅ ppocr_v6/windows_ml.py、6 个文件、行号已对齐 |
| 处理器层 | [HANDLER.md](HANDLER.md) | ✅ 10 个文件、继承链、行号已对齐 |
| 战斗系统 | [COMBAT.md](COMBAT.md) | ✅ Combat 7 父类（含 AutoSearchHandler）、行号已对齐 |
| 战斗 UI | [COMBAT-UI.md](COMBAT-UI.md) | ✅ 22 暂停/13 退出按钮、行号已对齐 |
| 地图处理 | [MAP.md](MAP.md) | ✅ 继承链 Map→Fleet→Camera→MapOperation、行号已对齐 |
| 地图检测 | [MAP-DETECTION.md](MAP-DETECTION.md) | ✅ OSGrid 三个类、11 个文件、行号已对齐 |
| 战役执行 | [CAMPAIGN.md](CAMPAIGN.md) | ✅ os_run/ambush_1_1、campaign/ 134 个目录、行号已对齐 |
| 游戏功能 | [GAME-FUNCTIONS.md](GAME-FUNCTIONS.md) | ✅ 33 个模块 + 完整目录清单、Shop 类名、行号已对齐 |
| 大世界 | [OS-SYSTEM.md](OS-SYSTEM.md) | ✅ 6 个子模块 64 文件、tasks/ 16 文件、行号已对齐 |
| 基础设施 | [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | ✅ webui 51 文件、log_res、行号已对齐 |
| MCP 服务器 | [ENTRY-MCP-SERVER.md](ENTRY-MCP-SERVER.md) | ✅ 18 个工具、TOOL_HANDLERS、行号已对齐 |
| WebUI 入口 | [ENTRY-GUI.md](ENTRY-GUI.md) | ✅ 双栈 socket、worker_registry、行号已对齐 |
