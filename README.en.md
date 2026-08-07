# AzurPilot — Azur Lane Automation Assistant

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
  <strong><a href="https://alas.nanoda.work/">AzurPilot Official Website</a></strong> ｜ Azur Lane Automation Script · OS Erosion Cycle · Multi-Platform Support
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
    <img src="https://img.shields.io/badge/Web-Download-blue?style=for-the-badge&logo=google-chrome&logoColor=white" />
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://join.nanoda.work/#/">
    <img src="https://img.shields.io/badge/Community-QQ-red?style=for-the-badge&logo=tencent-qq&logoColor=white" />
  </a>
</div>

## Introduction

AzurPilot is an Azur Lane automation assistant modified from [AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript), retaining the core capabilities of the original project while integrating multiple branches, feature improvements, and experimental features. It controls Android emulators via ADB/uiautomator2, automatically executing game tasks through screenshot recognition, image matching, and OCR, with support for the CN/EN/JP/TW servers.

> **Note**: The code of this project is largely generated and assisted by AI, so there may be significant uncertainty. Pull requests to fix issues are welcome at [AzurPilot Pull Requests](https://github.com/wess09/AzurPilot/pulls).

Visit the **[AzurPilot Official Website](https://alas.nanoda.work/)** for more feature details, or go to the **[Download Page](https://alas.nanoda.work/download.html)** to get the latest version.

## GUI Preview

<div align="center">
  <img src="doc/GUI.png" alt="GUI Preview" width="800">
</div>

## Quick Start

> 💡 **Recommended**: Download the launcher for your platform from the [AzurPilot download page](https://alas.nanoda.work/download.html). It bundles a Python environment and is ready to use out of the box.

### Linux One-Click Deployment

```shell
curl -fsSL https://alas.nanoda.work/install/deploy-image.sh | sudo -E bash
```

### Running from Source

This project uses `uv` and a project-level `.venv` to manage the Python environment (requires Python >= 3.14). The release launcher bundles uv, Python, ADB, and Git, and syncs dependencies into `.venv`. For development from source, install uv and run:

```bash
uv sync --frozen --no-dev
uv run python gui.py
```

After startup, open `http://127.0.0.1:25548` in your browser to access the WebUI.

## Important Notes

- This project contains extensive automation and image recognition functionality. Before using it, make sure you have completed the [in-game settings](#before-you-start). Otherwise, recognition may fail, workflows may behave abnormally, or tasks may not run properly.
- This project includes some experimental features that may have unknown issues. It is recommended to back up your configuration before use and report any anomalies promptly.

## Before You Start

You must modify the in-game settings according to the standards below.

Path: Main Menu → Settings (bottom right) → Options (left sidebar).

| Setting | Recommended Value |
| --- | --- |
| Frame Rate | 60 FPS |
| OS Settings, Reduce TB Guidance | On |
| OS Settings, Auto-submit items during auto mode | On |
| OS Settings, Auto mode default on in safe seas | Off |
| Story auto-play | On |
| Story auto-play speed | Extra Fast |
| Idle mode settings, enable idle mode | Off |
| Other settings, duplicate character notification | Off |
| Other settings, quick-change second confirmation dialog | Off |
| Other settings, show settlement characters | Off |

### OS (Operation Siren) Settings

Path: OS → Radar (top right) → Command Module → Submarine Support.

| Setting | Recommended Value |
| --- | --- |
| Submarine sortie when X consumes | Unchecked |

### One-Click Retirement Settings

Path: Main Menu → Build (bottom right) → Retirement (left sidebar) → Gear icon (left) → One-Click Retirement Settings.

| Setting | Recommended Value |
| --- | --- |
| Selection priority 1 | R |
| Selection priority 2 | SR |
| Selection priority 3 | N |
| When owning max-limit-break duplicates, how many eligible duplicates to keep | None |
| When not owning max-limit-break duplicates, how many eligible duplicates to keep | Enough for max LB or none |

### Image Recognition Notes

Please remove the following content that may affect recognition:

- Character equipment
- Character skins
- Custom display content that may obscure UI elements

These may affect image recognition results and cause anomalies in the automation workflow.

## MCP Service

AzurPilot provides an MCP service that can be called by MCP-compatible clients or tools, making it convenient to manage AzurPilot with an Agent.

> The MCP service starts by default with the WebUI and is mounted under the `/mcp` path (WebUI default port 25548). It can also be run standalone via `uv run python mcp_server_sse.py` (standalone port 22268).

### Local Connection Configuration

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://127.0.0.1:25548/mcp/sse"
    }
  }
}
```

### Cloud Server or Intranet Connection Configuration

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://[IP_ADDRESS]:25548/mcp/sse"
    }
  }
}
```

Replace `[IP_ADDRESS]` with your actual server address or intranet address. If the WebUI port has been changed, update the port in the URL accordingly.

### MCP Tool List

18 MCP tools are currently available.

| Category | Tool Name | Description |
| --- | --- | --- |
| Instance Management | `list_instances` | List all instances |
| | `get_status` | Get instance status |
| | `start_instance` | Start an instance |
| | `stop_instance` | Stop an instance |
| Task Management | `list_tasks` | List all tasks |
| | `get_task_help` | Get task help |
| | `trigger_task` | Trigger a task |
| | `get_scheduler_queue` | Get the scheduler queue |
| | `clear_scheduler_queue` | Clear the scheduler queue |
| Monitoring & Info | `get_current_running_task` | Get the currently running task |
| | `get_resources` | Get resource status |
| | `get_config` | Get instance configuration |
| | `get_recent_logs` | Get recent logs |
| | `get_screenshot` | Get a screenshot |
| Configuration Management | `update_config` | Update configuration |
| Maintenance Tools | `restart_emulator` | Restart the emulator |
| | `restart_adb` | Restart ADB |
| | `update_alas` | Update AzurPilot |

## Multi-Platform Launcher

> 📥 Download the Windows / macOS / Linux launchers from the [AzurPilot Official Website](https://alas.nanoda.work/download.html)

<div align="center">
  <img src="doc/loading.png" alt="loading" width="500" />
  <p>Loading screen</p>
  <img src="doc/GUI.png" alt="GUI" width="500" />
  <p>Windows client UI</p>
  <img src="doc/macGUI.png" alt="macGUI" width="500" />
  <p>macOS client UI</p>
</div>

Launcher project: [GitHub](https://github.com/wess09/alas-launcher) · Original project [ALAS Launcher: A New Type of AzurLaneAutoScript Launcher](https://github.com/swordfeng/alas-launcher)

Changes:

1. Added system tray support
2. Native Windows notifications
3. Improved GUI styling
4. Migrated to uv
...

## Contributors

Since this project continues development based on AzurLaneAutoScript and its community forks, the contributor list includes not only direct contributors to this repository but also original contributors from upstream projects and related forks.

*Contributors to this project

<a href="https://github.com/wess09/AzurPilot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/AzurPilot&max=1000" alt="AzurPilot Contributors">
</a>

*Contributors to the launcher project

<a href="https://github.com/wess09/alas-launcher/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/alas-launcher&max=1000" alt="Launcher Contributors">
</a>

*Contributors to the original ALAS project

<a href="https://github.com/LmeSzinc/AzurLaneAutoScript/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=LmeSzinc/AzurLaneAutoScript&max=1000" alt="AzurLaneAutoScript Contributors">
</a>

## Related Links

- [AzurPilot Official Website](https://alas.nanoda.work/) — Project introduction, feature details, Azur Lane automation solutions
- [AzurPilot Download Page](https://alas.nanoda.work/download.html) — Download the Azur Lane script tool for Windows / macOS / Linux
- [GitHub Repository](https://github.com/wess09/AzurPilot) — Source code, Issues, Pull Requests
- [QQ Community Group](https://join.nanoda.work/#/) — Azur Lane automation community
- [AzurLaneAutoScript Upstream](https://github.com/LmeSzinc/AzurLaneAutoScript) — The original ALAS
- [AzurPilot Raspberry Pi Edition](https://github.com/nnieie/AzurPilot) — AzurPilot CN deployment for Raspberry Pi / Termux physical devices

## Development & Contribution

This project is almost entirely a product of VibeCoding, so please excuse any shortcomings. Feedback, fixes, or documentation improvements via Issue or Pull Request are welcome.

### Development Environment

```bash
uv sync --frozen        # Create/sync .venv (including dev dependencies)

# Code check (CI uses loose ruff settings — only checks for fatal syntax errors and undefined names)
uv run ruff check . --select E9,F63,F7,F82 --ignore F821,F722

# Tests (~160 unit tests)
uv run python -m unittest discover -s tests

# Config generation (must run after modifying config YAML files)
uv run -m module.config.config_updater
```

### Development Tools & Models Used

Various AI models and development tools were used during the development of this project.

**AI Models:**

| | | |
| --- | --- | --- |
| Gemini | GPT | Claude |
| GLM | MiMo | DeepSeek |
| Kimi | Qwen | DouBao |

**Development Tools:**

| | | |
| --- | --- | --- |
| Claude Code | Codex | Cursor | Antigravity |
| TRAE | ZCode | OpenCode | MiMoCode |


## License

This project follows the license requirements of the original project and related upstream projects. The launcher project is open source under the GPL-3.0 license.

The licenses of the projects this project depends on are located in /licenses.

When using, modifying, or distributing this project, please comply with the license requirements of the relevant upstream projects as well.

## Sponsorship

<p align="center">
  <a href="https://afdian.com/a/miaonaa">
    <img src="doc/afdian.jfif" alt="爱发电" width="200">
  </a>
  <br>
  <b>Support this project (for server costs or training new models, etc.?)</b>
</p>
