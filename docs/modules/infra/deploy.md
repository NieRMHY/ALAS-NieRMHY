# 部署与启动链路（deploy/ + 启动入口）

> 从「拿到一份源码」到「WebUI 起来、实例跑起来」的全部工程环节：安装器、启动脚本、Docker、依赖自举与前端构建。

## 1. 模块概述

`deploy/` 不是游戏业务，而是把仓库变成可运行系统的安装与启动工程。它要解决三件事：

- **自举**：用户机器上可能只有系统 Python。安装器先用它引导 `uv`，再由 `uv` 建出仓库内 `.venv/`，之后一切 Python、git、adb 都从 `.venv/` 取——系统环境零污染，依赖完全由 `pyproject.toml` + `uv.lock` 锁定。
- **安装**：git 拉仓库（含国内 CDN 兜底）、同步依赖、装 uiautomator2、连模拟器、构建前端，全部封装成 `python -m deploy.installer` 一个命令。
- **自更新**：WebUI 运行中可以替换源码与 `.venv`（父进程监督 + 更新事务，见 [WebUI 总览](../webui/index.md)）；安装器是冷启动路径，两者共享 `deploy/uv.py` 的依赖同步。

## 2. 模块职责

### 负责

- `installer.py`：安装总入口，组合五个管理器（git → 停调度器 → 依赖 → 前端 → adb）。
- `uv.py`：`.venv` 自举、uv 解析、依赖同步（`sync_project_venv`）、常驻依赖同步服务（`dependency_sync_service`，gui.py 运行期调用）。
- `git.py`：仓库更新（常规 git 与 GitOverCdn 兜底）、随机 User-Agent 绕镜像封禁。
- `adb.py` / `emulator.py`：adb 分发与自动连接；VirtualBox 系模拟器注册表扫描与端口发现。
- `frontend.py`：按源码内容摘要决定是否重建 `frontend/dist`。
- `atomic.py`：安装失败的原子清理（临时文件识别与回滚）。
- `patch.py`：安装前环境修补（运行目录检查、uiautomator2/apkutils2 补丁、证书链）。
- `launcher/Alas.bat`（打包为 `AzurPilot.exe`）：用户双击入口——跑安装器，成功后用 `pythonw` 拉起 `gui.py`。

### 不负责

- WebUI 的运行期进程管理——见[运行时服务](../webui/runtime.md)。
- 游戏识别资源与 OCR 模型——安装器只保证 adb/uiautomator2，模型随仓库分发。
- 配置内容（`config/deploy.yaml` 是部署参数，语义见第 10 节）。

## 3. 模块位置

```
deploy/
├── installer.py     # 总入口：Installer(GitManager, PipManager, AdbManager, AppManager, AlasManager)
├── config.py        # DeployConfig（config/deploy.yaml 的模型）+ ExecutionError
├── git.py / git_over_cdn/   # 仓库更新；CDN 客户端与端点表
├── pip.py / uv.py   # 依赖同步（实际是 uv sync，类名保留 pip 是历史）
├── adb.py / emulator.py     # adb 安装与模拟器探测（Windows 注册表 + VirtualBox）
├── frontend.py      # ensure_frontend：源码摘要 → npm ci + build
├── app.py           # AppManager：安装期前端构建步骤
├── patch.py         # pre_checks：路径检查、site-packages 补丁
├── atomic.py        # 失败清理（Windows 文件占用重试）
├── launcher/Alas.bat        # 双击入口（AzurPilot.exe 的本体）
├── Windows/         # Windows 专用 deploy 变体（模板 yaml 等）
├── docker/          # Dockerfile（含 cn 镜像源变体）与构建脚本
├── install/         # 平台辅助（模拟器探测）
└── AidLux/          # 安卓本地部署方案
```

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `python -m deploy.installer` | 全新安装/更新（Alas.bat 即调用它） |
| `AzurPilot.exe` / `deploy/launcher/Alas.bat` | 用户入口：安装器成功后 `pythonw gui.py` |
| `uv run python gui.py` | 开发态启动 WebUI（跳过安装器） |
| `python -m deploy.app` | 只重建前端产物 |
| `deploy/docker/Dockerfile` | 容器构建（多阶段，预装前端产物） |

## 6. 工作流程

### 安装器链条

```
Alas.bat → python -m deploy.installer
  patch.pre_checks()          # 运行目录、site-packages 补丁
  git_install()               # git pull / GitOverCdn 兜底
  alas_kill()                 # 停掉本实例的 alas 进程
  pip_install()               # 实为 uv sync（--frozen），失败抛 ExecutionError
  app_update()                # ensure_frontend()：摘要变化才 npm ci + build
  adb_install()               # adb 就位、替换系统 adb、自动连接、装 uiautomator2
失败 → atomic_failure_cleanup → 退出码 1 → bat pause
成功 → start pythonw gui.py --electron
```

### 启动后的依赖自举

`gui.py` 不直接信任 `.venv`：启动时用 `deploy/uv.py` 的 `dependency_sync_service` 做带超时与重试的依赖同步（pending 状态记录在 `module/runtime/setting.py`，崩溃后下次启动重做）。WebUI 服务有 120 秒就绪超时与最多 3 次重启；运行期检测到依赖标记时同样先同步再拉服务。

### 前端构建判据

`ensure_frontend` 对 `package.json`、`vite.config.ts`、`src/**`、`public/**` 做内容哈希（不依赖 git 检出时间），摘要变化才重建。这就是「改前端源码后不重启构建，界面不更新」的原因。

## 10. 配置

部署参数在 `config/deploy.yaml`（模型见 `deploy/config.py`）：git 仓库/分支/代理/SSL、Python 与 uv、镜像源、adb 替换与自动连接、OCR 服务器、更新检查间隔与自动重启时刻。安装器读它，WebUI 的部署设置页写它——两边经同一份文件交互。

## 11. 异常与错误处理

| 情况 | 处理 |
| --- | --- |
| 任一管理器抛 `ExecutionError` | 安装器 `exit(1)`，bat `pause` 停留展示日志 |
| uv sync 失败 | 输出 uv 日志（敏感文本经 `redact_sensitive_text` 脱敏）后中止 |
| git 418/镜像封禁 | 随机 git User-Agent + GitOverCdn 端点轮换兜底 |
| Windows 文件占用 | `atomic.py` 按重试上限等待后清理 |
| `.venv` 损坏 | `uv.py` 检测 python 不可用 → 自举重建 |

## 16. 修改注意事项

- **`PipManager` 名字是历史遗留**：它调用 `uv sync`，不要在其中加 pip 逻辑；依赖问题先查 `deploy/uv.py`。
- **`deploy/Windows/` 是旧布局副本**，主流程已用顶层 `deploy/*.py`；改安装逻辑改顶层，勿两边都改。
- **前端产物摘要机制**：只改 `dist/` 不改源码会被下次启动重建覆盖；发布产物请走正常构建。
- **随机 User-Agent、CDN 兜底是可用性关键**（国内网络），不要当可疑代码清理。
- `Alas.bat` 转 `AzurPilot.exe` 由外部工具完成，仓库只维护 bat。

## 17. 已知限制

- 模拟器自动探测仅支持 Windows 注册表可见的 VirtualBox 系模拟器；其他场景手动填 serial。
- 安装器假设能访问 git 远端或 CDN 端点；完全离线的首次安装不可行。

## 20. 相关模块

- [WebUI 启动器](../entry/gui.md) —— gui.py 的监督与依赖同步运行期行为
- [WebUI 总览](../webui/index.md) —— 更新事务与进程监督全貌
- [运行时服务](../webui/runtime.md) —— updater 与 installer 共享的依赖同步
- [外部桥接与开发工具](submodule-tools.md) —— dev_tools 中的生成器（CI 侧的对应物）
