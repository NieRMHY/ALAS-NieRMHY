## 个人修改项目

### 2025.08.19 - 添加仪表盘
- **参考项目**：[Alas-with-Dashboard](https://github.com/Zuosizhu/Alas-with-Dashboard)
- **新增功能**：集成 Dashboard 模块，可实时显示游戏内所有资源量
  - 支持显示石油、金币、钻石等主要资源
  - 实时更新资源状态
  - 提供直观的资源监控界面

### 2025.09.15 - 重启逻辑优化
- **核心改进**：尝试重构脚本重启游戏逻辑
  - ~~修改 `Restart` 任务的调用机制，支持可配置的重启时间点~~ *(暂时弃用)*
  - ~~添加 `RestartTime` 配置选项，支持多种时间格式~~ *(暂时弃用)*
  - ~~优化 `task_call` 方法，避免自定义重启时间被覆盖~~ *(暂时弃用)*
  - 在部分异常情况下，系统会尝试保持运行状态，减少不必要的游戏重启
- **技术细节**：
  - ~~修改 `module/handler/login.py` 中的 `app_restart` 方法~~  *(暂时弃用)*
  - ~~更新 `module/config/config.py` 中的 `task_call` 方法~~  *(暂时弃用)*
  - ~~修改 `alas.py` 中的判断重启逻辑~~ *(已禁用修改)*
  - ~~修改 `module/campaign/run.py` 中的重启调用~~ *(已禁用修改)*
  - ~~添加了配置选项到 `module/config/argument/args.json`~~ *(暂时弃用)*
  - 支持禁用强制重启功能，以供特殊需求
- **状态说明**：
  - ✅ 已完成：禁用强制重启功能
  - ❌ 暂时弃用：独立配置`Restart`逻辑



**| [English](README_en.md) | 简体中文 | [日本語](README_jp.md) |**

# AzurLaneAutoScript

我们屁眼通红(Python)真的太有实力了

## 添加了

1. 智能调度
2. 解除大世界限制
3. 如果使用 docker 部署 默认 webui 密码为 123456

## 感谢某不知名 AI IDE 的支持（

请加 QQ 群 1077880342
