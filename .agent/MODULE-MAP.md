---
description:
alwaysApply: true
---

# 模块映射表

**生成日期**: 2026-08-14
**项目版本**: dev 分支（HEAD f992af6c0）

## 项目概述

- **项目类型**: 桌面自动化工具 + WebUI 管理界面
- **主要语言**: Python 3.14+
- **框架**: PyWebIO + Starlette + uvicorn (WebUI), ADB/uiautomator2 (设备控制)
- **包管理器**: uv (项目模式)
- **总文件数**: 2025 个 Python 文件（不含 `.venv` 与 `webapp/node_modules`）

---

## 模块分层架构

### 第一层：入口层

| 模块名称 | 包含文件 | 说明 |
|---------|---------|------|
| **alas** | `alas.py` | 核心调度器入口 |
| **gui** | `gui.py` | WebUI 启动器 |
| **mcp_server** | `mcp_server_sse.py` | MCP SSE 服务器 |

### 第二层：核心基础层

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **base** | `module/base/` | 基础工具类：Button、Template、Filter、Timer、装饰器 |
| **config** | `module/config/` | 配置系统：YAML 解析、配置生成、i18n |
| **device** | `module/device/` | 设备连接层：ADB、截图、输入模拟 |
| **ui** | `module/ui/` | UI 导航系统：Page、路由 |
| **ocr** | `module/ocr/` | OCR 文字识别系统 |
| **handler** | `module/handler/` | 游戏处理器：登录、自动搜索、信息处理 |

### 第三层：战斗系统层

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **combat** | `module/combat/` | 战斗逻辑：自动/手动战斗、情绪、血量 |
| **combat_ui** | `module/combat_ui/` | 战斗 UI 界面 |
| **map** | `module/map/` | 地图处理：摄像机、舰队、网格 |
| **map_detection** | `module/map_detection/` | 地图检测：单应性、透视、网格预测 |
| **campaign** | `module/campaign/` | 战役执行逻辑 |

### 第四层：游戏功能模块

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **research** | `module/research/` | 科研系统 |
| **commission** | `module/commission/` | 委托系统 |
| **tactical** | `module/tactical/` | 战术学院 |
| **dorm** | `module/dorm/` | 宿舍管理 |
| **meowfficer** | `module/meowfficer/` | 指挥喵 |
| **guild** | `module/guild/` | 大舰队 |
| **shop** | `module/shop/` | 商店系统 |
| **shop_event** | `module/shop_event/` | 活动商店 |
| **reward** | `module/reward/` | 奖励收取 |
| **exercise** | `module/exercise/` | 演习 PvP |
| **gacha** | `module/gacha/` | 建造系统 |
| **daily** | `module/daily/` | 每日任务 |
| **hard** | `module/hard/` | 困难模式 |
| **sos** | `module/sos/` | SOS 任务 |
| **war_archives** | `module/war_archives/` | 作战档案 |
| **raid** | `module/raid/` | 突袭任务 |
| **event** | `module/event/` | 活动处理 |
| **eventstory** | `module/eventstory/` | 活动剧情 |
| **event_hospital** | `module/event_hospital/` | 医院活动 |
| **coalition** | `module/coalition/` | 联动活动 |
| **island** | `module/island/` | 岛屿系统 |
| **island_business** | `module/island_business/` | 岛屿子模块（商业） |
| **island_cargo_preparation** | `module/island_cargo_preparation/` | 岛屿子模块（货运准备） |
| **island_daily_interact** | `module/island_daily_interact/` | 岛屿子模块（每日互动） |
| **island_daily_order** | `module/island_daily_order/` | 岛屿子模块（每日订单） |
| **island_farm** | `module/island_farm/` | 岛屿子模块（农场） |
| **island_fishery** | `module/island_fishery/` | 岛屿子模块（渔业） |
| **island_grill** | `module/island_grill/` | 岛屿子模块（烧烤） |
| **island_juu_coffee** | `module/island_juu_coffee/` | 岛屿子模块（啾咖啡） |
| **island_juu_eatery** | `module/island_juu_eatery/` | 岛屿子模块（啾食堂） |
| **island_manufacture** | `module/island_manufacture/` | 岛屿子模块（制造） |
| **island_mine_forest** | `module/island_mine_forest/` | 岛屿子模块（采矿/森林） |
| **island_pearl_sell** | `module/island_pearl_sell/` | 岛屿子模块（珍珠出售） |
| **island_rancher** | `module/island_rancher/` | 岛屿子模块（牧场） |
| **island_restaurant** | `module/island_restaurant/` | 岛屿子模块（餐厅） |
| **island_select_character** | `module/island_select_character/` | 岛屿子模块（角色选择） |
| **island_teahouse** | `module/island_teahouse/` | 岛屿子模块（茶馆） |
| **private_quarters** | `module/private_quarters/` | 私人休息室 |
| **shipyard** | `module/shipyard/` | 船坞系统 |
| **freebies** | `module/freebies/` | 免费福利 |
| **minigame** | `module/minigame/` | 小游戏 |
| **awaken** | `module/awaken/` | 觉醒系统 |
| **retire** | `module/retire/` | 退役系统 |
| **equipment** | `module/equipment/` | 装备管理 |
| **auto_equip** | `module/auto_equip/` | 自动配装（AutoEquip） |
| **meta_reward** | `module/meta_reward/` | META 奖励 |
| **storage** | `module/storage/` | 仓库（拆解、StorageHandler） |
| **game_setting** | `module/game_setting/` | 游戏内设置（player_prefs 等） |
| **template** | `module/template/` | 模板匹配资源（assets.py） |
| **ui_white** | `module/ui_white/` | 白色主题 UI 资源（assets.py） |

### 第五层：大世界系统

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **os** | `module/os/` | 大世界核心 |
| **os_combat** | `module/os_combat/` | 大世界战斗 |
| **os_handler** | `module/os_handler/` | 大世界事件处理 |
| **os_ash** | `module/os_ash/` | 余烬/信标系统 |
| **os_shop** | `module/os_shop/` | 大世界商店 |
| **os_simulator** | `module/os_simulator/` | 大世界模拟器 |

### 第六层：基础设施层

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **statistics** | `module/statistics/` | 掉落统计 |
| **azur_stats** | `module/azur_stats/` | AzurStats 数据提交 |
| **notify** | `module/notify/` | 推送通知 |
| **daemon** | `module/daemon/` | 守护模式 |
| **webui** | `module/webui/` | WebUI 应用 |
| **submodule** | `module/submodule/` | 外部桥接 |
| **log_res** | `module/log_res/` | 日志资源管理 |
| **llm** | `module/llm.py` | LLM 错误分析 |
| **logger** | `module/logger.py` | 日志系统 |

### 第七层：战役数据层

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **campaign_main** | `campaign/campaign_main/` | 主线战役数据 |
| **campaign_hard** | `campaign/campaign_hard/` | 困难战役数据 |
| **campaign_sos** | `campaign/campaign_sos/` | SOS 战役数据 |
| **campaign_war_archives** | `campaign/campaign_war_archives/` | 作战档案数据 |
| **event_*_cn** | `campaign/event_*/` | 各活动战役数据 |
| **war_archives_*_cn** | `campaign/war_archives_*/` | 各作战档案活动数据 |

> 实际目录结构：除 `campaign_main`、`campaign_hard`、`campaign_sos`、`campaign_war_archives` 外，含 82 个 `event_*` 目录和 48 个 `war_archives_*` 目录（加 4 个基础目录共 134 个条目）。

### 第八层：资源与工具层

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **assets** | `assets/` | UI 模板图像（按服务器组织） |
| **bin** | `bin/` | 二进制工具、OCR 模型 |
| **dev_tools** | `dev_tools/` | 开发工具 |
| **deploy** | `deploy/` | 部署脚本 |
| **config** | `config/` | 配置模板 |

---

## 模块依赖关系概览

```
入口层 (alas.py, gui.py, mcp_server_sse.py)
    ↓
核心基础层 (base, config, device, ui, ocr)
    ↓
战斗系统层 (combat, map, campaign)
    ↓
游戏功能层 (research, commission, dorm, ...)
    ↓
基础设施层 (statistics, notify, daemon, webui)
```

---

## 关键文件清单

### 入口文件
- `alas.py` - 核心调度器（1568 行，112 个方法，其中 93 个任务方法）
- `gui.py` - WebUI 启动器（1026 行）
- `mcp_server_sse.py` - MCP 服务器（574 行，18 个工具）
- `module/webui/app.py` - WebUI 应用工厂与 ASGI 入口（363 行，已拆分为 `app_*` 系列约 50 个文件，如 `app_home.py`、`app_instances.py`、`app_stat_*.py`、`app_developer_*.py`）

### 配置文件
- `module/config/argument/*.yaml` - 配置源文件
- `module/config/argument/args.json` - 生成的配置
- `module/config/config_generated.py` - 生成的 Python 类
- `config/template.json` - 配置模板

### 核心模块入口
- `module/base/base.py` - ModuleBase 基类
- `module/config/config.py` - AzurLaneConfig 配置类
- `module/device/device.py` - Device 设备类
- `module/ui/ui.py` - UI 导航类
- `module/ocr/ocr.py` - OCR 识别类
