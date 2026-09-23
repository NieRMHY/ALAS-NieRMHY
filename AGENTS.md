# AGENTS.md

本文件是 Codex、Claude Code 等编码代理共用的仓库规范。只保留影响决策的项目约束；实现细节按任务查阅下方入口。

## 协作与完成标准

- 使用简体中文交流，新增注释、文档和提交说明也使用简体中文；代码标识符使用英文，翻译资源使用对应语言。
- 将用户请求推进到可交付结果：完成实现、必要的生成产物与相关验证，修复本次改动引入的问题后再交付。若请求包含运行或界面验收，将其纳入完成范围。
- 在已授权范围内，直接进行本地编辑、构建、隔离测试及失败修复，无需逐步确认。只有缺失信息会实质影响结果，或下一步超出授权范围时才询问；已有授权持续有效。
- 真实游戏任务可能消耗资源或改变账号状态。普通开发验证优先使用测试夹具、已有截图和模拟服务；实际账号操作按用户指定的实例与任务范围执行。
- 保留已有工作区修改。交付时说明结果、实际验证及剩余限制；遇到环境或权限阻塞，明确未完成的部分，不把初版或未验证结果当作完成。

## 项目与环境

AzurPilot 是面向安卓模拟器的碧蓝航线自动化框架，支持 CN/EN/JP/TW，按 7×24 小时运行设计。游戏识别基于 **1280×720** 截图，不支持真机；这一尺寸约束不适用于 WebUI 布局。

- Python 使用 `uv` 项目模式和仓库内 `.venv/`。版本要求以 [pyproject.toml](pyproject.toml) 为准；依赖声明与 `uv.lock` 配套维护，不维护 `requirements*.txt`。
- WebUI 使用 React、TypeScript、Vite，前端用 npm；Node.js 要求与脚本以 [frontend/package.json](frontend/package.json) 为准。
- 在仓库根目录运行下列命令，按需选择，不是每次任务的必跑清单。

| 用途 | 命令 |
| --- | --- |
| 同步 Python 依赖 | `uv sync --frozen` |
| 安装前端锁定依赖 | `npm ci --prefix frontend` |
| 启动 WebUI | `uv run python gui.py` |
| 启动游戏调度器 | `uv run python alas.py` |
| 启动独立 MCP SSE 服务 | `uv run python mcp_server_sse.py` |
| Python 单个测试模块（示例） | `uv run python -m unittest tests.test_api` |
| Python 全量单元测试 | `uv run python -m unittest discover -s tests` |
| Python 基础 CI lint | `uv run ruff check . --select E9,F63,F7,F82 --ignore F821,F722` |
| 前端类型检查 | `npm run typecheck --prefix frontend` |
| 前端单元测试 | `npm test --prefix frontend` |
| 前端生产构建 | `npm run build --prefix frontend` |
| 浏览器端到端测试 | `npm run test:e2e --prefix frontend` |
| 前端模拟服务端到端测试 | `npm run test:e2e:mock --prefix frontend` |
| Python 导入冒烟检查 | `uv run python -m dev_tools.import_smoke_test` |

## 按任务查阅

先定位相关实现；需要背景时再打开对应文档。小范围文案或局部修改不要求通读架构。模块文档位于 [docs/modules/](docs/modules/README.md)（按模块职责组织的 20 节标准文档，入口见其索引）；目录、依赖和行为以当前代码、清单及 CI 为准。`.agent/` 仅存历史分析，已由 docs/modules/ 取代；其中旧流程或固定格式要求与本文件冲突时，以本文件为准。

| 涉及的工作 | 实现与参考入口 |
| --- | --- |
| 服务边界、跨模块改动 | [目录与任务映射](docs/modules/overview/directory-map.md)、[编码规范与设计模式](docs/modules/overview/conventions.md)、[调度器](docs/modules/entry/alas.md) |
| 调度、失败恢复、任务派发 | `alas.py`、[调度器](docs/modules/entry/alas.md)、[运行时服务](docs/modules/webui/runtime.md) |
| 配置定义、迁移、热重载 | `module/config/`、[配置系统](docs/modules/config.md)，以及下方配置生成约束 |
| WebUI、接口、运行进程 | `gui.py`、[WebUI 总览](docs/modules/webui/index.md)、[API 服务](docs/modules/webui/api.md)、[运行时服务](docs/modules/webui/runtime.md)、[frontend/README.md](frontend/README.md)、[frontend/API.md](frontend/API.md) |
| MCP 集成 | `mcp_server_sse.py`、[MCP SSE 服务器](docs/modules/entry/mcp-server.md) |
| 游戏页面、弹窗、识别资源 | [UI 导航](docs/modules/ui.md)、[处理器层](docs/modules/handler.md)、[基础层](docs/modules/base/index.md) |
| 设备、截图或 OCR | [设备层](docs/modules/device.md)、[OCR 系统](docs/modules/ocr.md) |
| 战斗、地图、活动适配 | `campaign/` 下相近关卡、[战役执行](docs/modules/campaign.md)、[战斗系统](docs/modules/combat.md)、[地图系统与检测](docs/modules/map.md) |
| 大世界或具体游戏功能 | [大世界核心](docs/modules/os/index.md)、[大世界辅助模块](docs/modules/os/auxiliary.md)、[其他游戏功能](docs/modules/game/misc.md) |
| 构建、部署或 CI | `deploy/`、[.github/workflows/ci.yml](.github/workflows/ci.yml) |

## 游戏交互约束

游戏流程采用持续的「截图 → 识别 → 操作」状态循环。用当前画面的正向状态确认退出，点击后继续循环获取新截图；不要用固定休眠猜测界面已就绪。

```python
def some_function(self, skip_first_screenshot=True):
    while True:
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.device.screenshot()

        if self.appear(END_CONDITION):
            break
        if self.appear_then_click(BUTTON_A, interval=2):
            continue
        if self.handle_popup():
            continue
```

- 退出检测用 `appear()`，不设 `interval`；`appear_then_click()` 用于操作，通常以 2–5 秒 `interval` 防止连击。
- 不在状态循环内调用 `sleep()`，不以负面识别条件控制循环，不嵌套状态循环；将状态分支合并到父循环。
- 游戏交互的 `handle_*()` 返回 `bool`：`True` 表示已操作、需要新截图，`False` 表示未操作。只有已有可用截图时才跳过首次截图。
- 复用 `GameStuckError`、`GameTooManyClickError` 等检测与上层恢复机制；不要用吞异常或无限重试绕过它们。异常语义见 `module/exception.py`。
- 页面跳转复用 `UI` / `Page` 导航。涉及界面前后置条件时，在 Google 风格 docstring 中用 `Pages:` 标注；注释解释状态和原因，不规定注释比例或为凑行数拆文件。
- 使用现有 `logger.hr()`、`logger.attr()` 记录阶段和状态。截图、日志、测试夹具中避免引入账号信息和密钥。

## 配置与生成文件

修改配置定义时，先改 `module/config/argument/` 下的源文件：

| 源文件 | 职责 |
| --- | --- |
| `task.yaml` | 任务、选项组映射与菜单 |
| `argument.yaml` | 参数类型、选项、默认值与校验 |
| `default.yaml` | 用户可修改的任务特定默认值 |
| `override.yaml` | 强制覆盖及隐藏等属性；与可修改默认值区分 |
| `gui.yaml` | GUI 翻译键 |
| `dashboard.yaml` | 仪表盘资源定义 |

修改相关 YAML 后运行 `uv run -m module.config.config_updater`。`args.json`、`menu.json`、`module/config/config_generated.py` 与 `config/template.json` 由生成器维护，不直接修改，也不把真实用户配置当作模板。

`module/config/i18n/*.json` 是例外：生成器保留已有翻译，新增名称和说明可能只是键路径（如 `Campaign.Event.name`）。生成后补齐 `zh-CN`、`zh-MIAO`、`en-US`、`ja-JP`、`zh-TW` 的新增翻译，选项文案也需检查；繁体用词需校对，不能假设生成器已完成翻译。

配置路径为 `<Task>.<Group>.<Argument>`，绑定任务后通过 `self.config.Group_Argument` 访问。涉及加载或迁移时注意 `AzurLaneConfig` 初始化可能保存配置，测试使用临时配置目录。

## 资源与接口生成

- 游戏图像资源位于 `assets/{cn,en,jp,tw}/`；按 1280×720 游戏画面的坐标约定提取，模板可以是局部裁剪。模板对象名称使用 `TEMPLATE_` 前缀。
- 修改按钮资源后运行 `uv run -m dev_tools.button_extract`，检查生成的 `assets.py`。切换服务器进行离线识别时，在导入游戏模块前设置 `module.config.server.server`，避免资源已按其他服务器加载。
- `campaign/` 下关卡主要是 Python 地图定义与战斗逻辑；活动适配参考相近活动及 [campaign/Readme.md](campaign/Readme.md)，不要套用统一 YAML 地图流程。
- WebUI 业务通信使用 `/api/v1/ws`；前端位于 `frontend/`，后端接口与运行服务分别位于 `module/api/`、`module/runtime/`。新增功能沿用这些边界。
- 修改后端 API 参数模型或方法注册后，运行 `uv run python -m dev_tools.export_api_schema`，同步 `frontend/src/api/generated.ts` 与 `frontend/src/api/contract.json`，不手改生成产物。
- CI 会重新生成按钮、配置和 API 契约并检查差异。相关源文件与生成产物应一并交付；生成器产生无关差异时先查明原因，保留原有工作区修改。

## 验证与交付

根据行为影响选择验证，不因修改一个文件就默认运行全部检查：

- 纯文档改动核对事实、链接及差异即可；生成规则改动需验证对应产物。
- Python 逻辑先运行受影响的 `unittest` 模块；跨模块、导入或运行时改动再扩大到相关集成检查、全量测试或导入冒烟。
- 前端改动按影响选择类型检查、相关单元测试和构建；交互或布局变化还需浏览器验证。Playwright 主配置使用 `tests/serve_frontend.py` 的临时配置并禁止真实游戏进程，运行前需有最新前端构建；模拟服务测试使用独立 mock。
- 本地隔离测试可以连续执行、修复并重跑，无需逐次确认。检查通过后，只有新的修改、失败或未解决风险才需要扩大或重复验证。
- 游戏识别改动优先使用已有截图离线验证；模拟器实测按本次授权执行。未实测时明确说明，不能用静态检查替代实测结论。

交付前审阅本次差异，重点检查需求完整性、兼容性、并发与状态、隐私及无关修改。可修复的问题直接修复；报告实际发现和验证结果，不要求每次输出固定审查模板。

提交前查看全部 staged、unstaged 和 untracked 修改，区分本次变更与已有工作，按功能目的组织提交。独立的格式、依赖或工程调整应分开；实现、必要配置、生成产物和回归测试可在同一功能提交中。排除缓存、构建产物和调试残留。提交信息采用中文 Conventional Commits，例如 `fix(config): 避免热重载覆盖并发配置更新`，说明为什么修改。

AI 自行创建 PR 或执行任何涉及提 PR 的操作时，必须按 [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) 模板填写：如实勾选变更类型与代码质量确认项（未执行的检查不勾选），并在描述中说明变更原因、验证结果与相关 Issue。

## 维护这些指令

共享规范只在本文件维护，`CLAUDE.md` 仅负责导入。新增规则应针对实际工作流或已证实的陷阱；条件性细节放在相关文档并注明何时查阅。不要重新堆积完整 API 清单、易过期的数量或版本副本，也不要将单次任务的偏好扩展为所有任务的固定流程。
