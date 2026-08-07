# AzurPilot — 碧藍航線自動化輔助工具

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/简体中文-中文-blue?style=flat-square" alt="简体中文"></a>
  <a href="README.zh-TW.md"><img src="https://img.shields.io/badge/繁體中文-繁體-green?style=flat-square" alt="繁體中文"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/English-English-red?style=flat-square" alt="English"></a>
  <a href="README.ja.md"><img src="https://img.shields.io/badge/日本語-日本語-orange?style=flat-square" alt="日本語"></a>
  <a href="README.ko.md"><img src="https://img.shields.io/badge/한국어-한국어-violet?style=flat-square" alt="한국어"></a>
</p>

<p align="center">
  <img src="doc/logo.webp" alt="AzurPilot Logo" width="400">
</p>

<p align="center">
  <strong><a href="https://alas.nanoda.work/">AzurPilot 官網</a></strong> ｜ 碧藍航線自動化腳本 · 大型作戰侵蝕循環 · 多平台支援
</p>

<p align="center">
  <a href="https://deepwiki.com/wess09/AzurPilot">
    <img src="https://deepwiki.com/badge.svg" alt="DeepWiki" height="22">
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/github/license/wess09/AzurPilot?style=flat-square&label=License&color=2ea44f" alt="License">
  <img src="https://img.shields.io/github/stars/wess09/AzurPilot?style=flat-square&label=Stars&color=ffcc00" alt="Stars">
  <img src="https://img.shields.io/github/forks/wess09/AzurPilot?style=flat-square&label=Forks&color=58a6ff" alt="Forks">
  <img src="https://img.shields.io/github/issues/wess09/AzurPilot?style=flat-square&label=Issues&color=f85149" alt="Issues">
</p>

<p align="center">
  <img src="https://img.shields.io/github/last-commit/wess09/AzurPilot?style=flat-square&label=Last%20Commit&color=8b949e" alt="Last Commit">
  <img src="https://img.shields.io/github/commit-activity/m/wess09/AzurPilot?style=flat-square&label=Commit%20Activity&color=8957e5" alt="Commit Activity">
  <img src="https://img.shields.io/github/repo-size/wess09/AzurPilot?style=flat-square&label=Repo%20Size&color=orange" alt="Repo Size">
  <img src="https://img.shields.io/github/languages/top/wess09/AzurPilot?style=flat-square&label=Top%20Language&color=3776AB" alt="Top Language">
</p>

<p align="center">
  <img src="https://img.shields.io/github/contributors/wess09/AzurPilot?style=flat-square&label=Contributors&color=00b4d8" alt="Contributors">
  <img src="https://img.shields.io/github/issues-pr/wess09/AzurPilot?style=flat-square&label=Pull%20Requests&color=ffb703" alt="Pull Requests">
  <img src="https://img.shields.io/github/issues-pr-closed/wess09/AzurPilot?style=flat-square&label=PRs%20Closed&color=2ea44f" alt="Closed Pull Requests">
</p>

<div align="center">
  <a href="https://alas.nanoda.work/">
    <img src="https://img.shields.io/badge/Web-下載-blue?style=for-the-badge&logo=google-chrome&logoColor=white" />
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://join.nanoda.work/#/">
    <img src="https://img.shields.io/badge/交流群-QQ-red?style=for-the-badge&logo=tencent-qq&logoColor=white" />
  </a>
</div>

## 專案簡介

AzurPilot 是基於 [AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) 修改而來的碧藍航線自動化輔助工具，保留原專案的核心能力，並在此基礎上整合了多個分支、功能改進和實驗性特性。透過 ADB/uiautomator2 控制 Android 模擬器，以截圖識別、影像比對與 OCR 自動執行遊戲任務，支援 CN/EN/JP/TW 四服。

> **請注意**：本專案程式碼基本上由 AI 產生並輔助編寫，存在較大的不確定性，歡迎提交 [Pull Request](https://github.com/wess09/AzurPilot/pulls) 修正。

前往 **[AzurPilot 官網](https://alas.nanoda.work/)** 了解更完整的功能說明，或前往 **[下載頁面](https://alas.nanoda.work/download.html)** 取得最新版本。

## GUI 預覽

<div align="center">
  <img src="doc/GUI.png" alt="GUI Preview" width="800">
</div>

## 快速開始

> 💡 **建議方式**：直接從 [AzurPilot 官網下載頁](https://alas.nanoda.work/download.html) 下載對應平台的啟動器，內建 Python 環境，開箱即用。

### Linux 一鍵部署

```shell
curl -fsSL https://alas.nanoda.work/install/deploy-image.sh | sudo -E bash
```

### 原始碼執行

本專案使用 `uv` 和專案根目錄 `.venv` 管理 Python 執行環境（需要 Python >= 3.14）。發布版啟動器會自帶 uv、Python、ADB、Git，並在 `.venv` 中同步相依套件；原始碼開發時可安裝 uv 後執行：

```bash
uv sync --frozen --no-dev
uv run python gui.py
```

啟動後瀏覽器造訪 `http://127.0.0.1:25548` 進入 WebUI。

## 重要說明

- 本專案包含大量自動化邏輯和影像識別相關功能。使用前請確認已完成[遊戲內設定](#使用前設定)，否則可能導致識別失敗、流程異常或任務無法正常執行。
- 本專案包含部分實驗性功能，可能存在未知問題。建議在使用前備份相關設定，並在發現異常時即時回報。

## 使用前設定

使用前必須依照以下標準修改遊戲內設定。

路徑：主畫面 → 右下角設定 → 左側邊欄選項。

| 設定名稱 | 建議值 |
| --- | --- |
| 幀數設定 | 60 幀 |
| 大型作戰設定，減少 TB 引導 | 開 |
| 大型作戰設定，自律時自動提交道具 | 開 |
| 大型作戰設定，安全海域預設開啟自律 | 關 |
| 劇情自動播放 | 開啟 |
| 劇情自動播放速度調整 | 特快 |
| 待機模式設定，啟用待機模式 | 關 |
| 其他設定，重複角色獲得提示 | 關 |
| 其他設定，快速更換二次確認介面 | 關 |
| 其他設定，顯示結算角色 | 關 |

### 大型作戰設定

路徑：大型作戰 → 右上角雷達 → 指令模組 → 潛艇支援。

| 設定名稱 | 建議值 |
| --- | --- |
| X 消耗時潛艇出擊 | 取消勾選 |

### 一鍵退役設定

路徑：主畫面 → 右下角建造 → 左側邊欄退役 → 左側齒輪圖示 → 一鍵退役設定。

| 設定名稱 | 建議值 |
| --- | --- |
| 選擇優先級 1 | R |
| 選擇優先級 2 | SR |
| 選擇優先級 3 | N |
| 擁有滿星的同名艦船時，保留幾艘符合退役條件的同名艦船 | 不保留 |
| 沒有滿星的同名艦船時，保留幾艘符合退役條件的同名艦船 | 滿星所需或不保留 |

### 影像識別注意事項

請移除以下可能影響識別的內容：

- 角色設備裝備
- 角色造型
- 可能遮蔽介面元素的自訂顯示內容

這些內容可能影響影像識別結果，導致自動化流程出現異常。

## MCP 服務

AzurPilot 提供 MCP 服務，可供支援 MCP 的用戶端或工具呼叫，方便使用 Agent 管理 AzurPilot。

> MCP 服務預設隨 WebUI 啟動並掛載於 `/mcp` 路徑下（WebUI 預設連接埠 25548），也可透過 `uv run python mcp_server_sse.py` 獨立執行（獨立連接埠 22268）。

### 本機連線設定

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://127.0.0.1:25548/mcp/sse"
    }
  }
}
```

### 雲端伺服器或內網連線設定

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://[IP_ADDRESS]:25548/mcp/sse"
    }
  }
}
```

請將 `[IP_ADDRESS]` 替換為實際伺服器位址或內網位址；若 WebUI 連接埠已修改，請同步替換 URL 中的連接埠。

### MCP 工具清單

目前可用的 MCP 工具共 18 個。

| 類別 | 工具名稱 | 功能 |
| --- | --- | --- |
| 實例管理 | `list_instances` | 列出所有實例 |
| | `get_status` | 取得實例狀態 |
| | `start_instance` | 啟動實例 |
| | `stop_instance` | 停止實例 |
| 任務管理 | `list_tasks` | 列出所有任務 |
| | `get_task_help` | 取得任務說明 |
| | `trigger_task` | 觸發任務 |
| | `get_scheduler_queue` | 取得排程佇列 |
| | `clear_scheduler_queue` | 清空排程佇列 |
| 監控與資訊 | `get_current_running_task` | 取得目前執行的任務 |
| | `get_resources` | 取得資源狀態 |
| | `get_config` | 取得實例設定 |
| | `get_recent_logs` | 取得最近的日誌 |
| | `get_screenshot` | 取得截圖 |
| 設定管理 | `update_config` | 更新設定 |
| 維護工具 | `restart_emulator` | 重新啟動模擬器 |
| | `restart_adb` | 重新啟動 ADB |
| | `update_alas` | 更新 AzurPilot |

## 多平台啟動器

> 📥 從 [AzurPilot 官網](https://alas.nanoda.work/download.html) 下載 Windows / macOS / Linux 啟動器

<div align="center">
  <img src="doc/loading.png" alt="loading" width="500" />
  <p>啟動載入畫面</p>
  <img src="doc/GUI.png" alt="GUI" width="500" />
  <p>Windows 用戶端介面</p>
  <img src="doc/macGUI.png" alt="macGUI" width="500" />
  <p>Mac 用戶端介面</p>
</div>

啟動器專案：[GitHub](https://github.com/wess09/alas-launcher) · 原始專案 [ALAS Launcher: 新型態的 AzurLaneAutoScript 啟動器](https://github.com/swordfeng/alas-launcher)

更改內容：

1. 增加托盤化功能
2. Windows 原生推播
3. GUI 樣式美化
4. uv 化
...

## 貢獻者

由於本專案基於 AzurLaneAutoScript 及其社群分支繼續開發，貢獻者清單不僅包含本儲存庫的直接貢獻者，也包含上游專案與相關分支中的原始貢獻者。

*本專案的貢獻名單

<a href="https://github.com/wess09/AzurPilot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/AzurPilot&max=1000" alt="AzurPilot Contributors">
</a>

*啟動器專案的貢獻名單

<a href="https://github.com/wess09/alas-launcher/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/alas-launcher&max=1000" alt="Launcher Contributors">
</a>

*ALAS 原專案的功能名單

<a href="https://github.com/LmeSzinc/AzurLaneAutoScript/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=LmeSzinc/AzurLaneAutoScript&max=1000" alt="AzurLaneAutoScript Contributors">
</a>

## 相關連結

- [AzurPilot 官網](https://alas.nanoda.work/) — 專案介紹、功能說明、碧藍航線自動化解決方案
- [AzurPilot 下載頁](https://alas.nanoda.work/download.html) — 下載 Windows / macOS / Linux 版本的碧藍航線腳本工具
- [GitHub 儲存庫](https://github.com/wess09/AzurPilot) — 原始碼、Issue、Pull Request
- [QQ 交流群](https://join.nanoda.work/#/) — 碧藍航線自動化社群交流
- [AzurLaneAutoScript 上游專案](https://github.com/LmeSzinc/AzurLaneAutoScript) — ALAS 原版
- [AzurPilot 樹莓派版](https://github.com/nnieie/AzurPilot) — 面向樹莓派 / Termux 真機的 AzurPilot CN 部署版

## 開發與貢獻

本專案基本上完全是 VibeCoding 的產物，不足之處敬請見諒。歡迎透過 Issue 或 Pull Request 回報問題、提交修正或改進文件。

### 開發環境

```bash
uv sync --frozen        # 建立/同步 .venv（含開發相依套件）

# 程式碼檢查（CI 使用 ruff 寬鬆設定——僅檢查致命語法錯誤和未定義名稱）
uv run ruff check . --select E9,F63,F7,F82 --ignore F821,F722

# 測試（約 160 個單元測試）
uv run python -m unittest discover -s tests

# 設定產生（修改設定 YAML 檔案後必須執行）
uv run -m module.config.config_updater
```

### 使用過的開發工具與模型

本專案開發過程中使用過多種 AI 模型與開發工具進行輔助。

**AI 模型：**

| | | |
| --- | --- | --- |
| Gemini | GPT | Claude |
| GLM | MiMo | DeepSeek |
| Kimi | Qwen | DouBao |

**開發工具：**

| | | |
| --- | --- | --- |
| Claude Code | Codex | Cursor | Antigravity |
| TRAE | ZCode | OpenCode | MiMoCode |


## 授權條款

本專案遵循原專案及相關上游專案的授權要求。啟動器專案遵循 GPL-3.0 協議開源。

本專案依賴的相關專案授權位於 /licenses

使用、修改或散佈本專案時，請同時遵守相關上游專案的授權要求。

## 贊助支持

<p align="center">
  <a href="https://afdian.com/a/miaonaa">
    <img src="doc/afdian.jfif" alt="愛發電" width="200">
  </a>
  <br>
  <b>支持本專案（用於支付伺服器費用或訓練新模型等？）</b>
</p>
