# 饺子可爱捏

> AzurLaneAutoScript (ALAS) 个人修改版 | 碧蓝航线自动化辅助

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/github/license/NieRMHY/ALAS-NieRMHY?style=flat-square&color=2ea44f)](LICENSE)

## 项目说明

本项目是 [AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) 的个人修改版，基于多个分支合并，用于碧蓝航线日常任务、委托、科研、大型作战等自动化流程。

### 合并来源

| 来源 | 说明 |
| --- | --- |
| [LmeSzinc/AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) | 官方原项目 |
| [wess09/AzurPilot](https://github.com/wess09/AzurPilot) | 上游 AzurPilot 分支 |
| [雪风源](https://gitee.com/wqeaxc/AzurLaneAutoScriptyukikaze21) | 雪风分支 |
| [nanoda](https://alas.nanoda.work/download.html) | AzurPilot 发布分支 |
| [Alas-with-Dashboard](https://github.com/Zuosizhu/Alas-with-Dashboard) | WebUI 面板部分功能 |
| 其他社区 PR | guoh064、sui-feng-cb 等分支的部分功能 |

## 个人修改

在上游分支基础上，本分支新增或修改了以下功能：

- **维护模式** — 游戏服务器维护前主动进入维护模式，暂停非必要任务；维护结束后自动恢复完整调度
- **全局隐私开关** — `ENABLE_THIRD_PARTY_API` 统一控制所有外联/数据上报，关闭后静默返回不发送任何数据
- **更新提示优化** — 取消全屏更新弹窗，仅保留右上角角标提示，避免打断运行中的任务
- **截图预览修复** — 修复 Device 初始化时 `screenshot_queue` 参数冲突导致截图预览失败
- **LLM 分析移除** — 移除 LLM 错误分析功能，禁用不必要的外部 API 连接
- **PT 识别兼容** — 适配「×PT」样式的活动点数识别
- **困难图均衡模式** — 新增均衡刷图开关，支持按图纸类型（驱逐/巡洋/战列/航母）选择关卡，跨天轮转分配每日3次困难次数，避免单一图纸偏科

## 许可证

本项目遵循原项目及相关上游项目的许可证要求。使用、修改或分发时请同时遵守相关上游项目的许可证要求。
