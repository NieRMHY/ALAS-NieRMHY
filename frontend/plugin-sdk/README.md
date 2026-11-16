# ALAS 插件包（APU API 1）

在 WebUI 的「插件」页导入 `.apu`，再启用。已安装的包、启用状态与插件数据保存在 ALAS 服务的 `config/plugins/plugins.db`。其他设备打开同一个服务时也能使用已启用的插件。主题布局选择保存在当前浏览器，可以在插件页切回默认布局；已选主题的样式会在应用启动前按上次记录预载，减少默认外观闪现。卸载会删除该插件的数据，停用时会保留数据。演示模式下禁止导入、启停和卸载插件。

本仓库的 WebUI 使用本地 React + 主题系统（浅色/深色/旧版浅色/旧版深色/简约/紧凑 + 玻璃/朴素材质），不引入上游的 Tailwind + shadcn 换肤版。插件系统按这套外壳适配：

- 支持 `pages`、`panels`、`permissions`、`theme.navigationView`、`theme.overviewView`、`theme.scheduler`、`theme.styles`、`theme.replaceSchedulerStyles` 与 `theme.icons`；
- `theme.navigation` 的 top/left/right/bottom 停靠位置未实现（本地是固定侧栏），声明后只影响插件自己的预期，不改变宿主外壳；
- `theme.overview` 的内置块顺序未实现（本地总览是资源卡 + 日志/截图的固定布局）；
- 用户 `public/theme.css` 定制继续生效；插件 `global` 槽位样式在应用挂载后加载，可覆盖本地主题变量，但不会删除本地主题切换能力。

## 打包

在仓库根目录运行：

```powershell
uv run python -m dev_tools.pack_apu frontend/plugin-sdk/examples/workbench dist/workbench.apu
uv run python -m dev_tools.pack_apu frontend/plugin-sdk/examples/task-favorites dist/task-favorites.apu
uv run python -m dev_tools.pack_apu frontend/plugin-sdk/examples/compact-scheduler dist/compact-scheduler.apu
```

`.apu` 是 ZIP，根目录须有 `manifest.json`。可以用任意构建工具开发插件，导入的是可直接运行的 HTML、JS、CSS、图片和字体。使用 Vite 时设 `base: './'`，将 npm 依赖打入插件自己的构建产物，再把清单放进构建输出目录。包内路径使用英文字母、数字、点、下划线、连字符和斜杠。清单声明的入口和资源必须存在，导入失败会保留已安装版本。包体上限 20 MiB，解压后上限 80 MiB、512 个文件，清单上限 64 KiB。

## 清单

`id`、`name`、`version` 和 `apiVersion: 1` 必填。`theme`、`permissions`、`pages` 和 `panels` 可省略。相同 ID 重新导入会更新原插件，保留启用状态与数据。

| 字段 | 用途 |
| --- | --- |
| `theme.navigation` | `top`、`left`、`right` 或 `bottom`；本地固定侧栏外壳不消费该字段 |
| `theme.navigationView` | 用包内 HTML 替换主导航，通过 `navigation.items` 和 `navigation.open` 接入宿主路由 |
| `theme.overview` | 上游的内置块顺序声明；本地总览不消费该字段 |
| `theme.overviewView` | 用包内 HTML 替换总览主视图 |
| `theme.scheduler` | 用包内 HTML 完整替换调度器界面 |
| `theme.styles` | 为 `shell`、`navigation`、`overview`、`scheduler` 指定各自的 CSS，或用 `global` 提供不加作用域的全局样式 |
| `theme.replaceSchedulerStyles` | 设为 `true` 后由插件 CSS 负责调度卡片外观，保留原控件、状态和操作 |
| `theme.icons` | 将 `scheduler.title`、`scheduler.start`、`scheduler.stop` 指向包内图标 |
| `pages` | 每项有 `id`、`title`、`entry`、可选 `scope`（`global` 或默认的 `instance`）和可选 `icon`（包内图片，显示在导航里） |
| `panels` | 每项有 `id`、`title`、`entry` 和可选 `icon`（包内图片），在实例总览中出现 |
| `permissions` | 按需声明 `instance.read`、`storage` 和 `scheduler.control` |

调度卡片的公开样式部位是 `header`、`counts`、`running`、`pending`、`waiting` 和 `toggle`。用 `[data-apu-part="toggle"]` 之类的选择器定位部位。用 `:scope` 选择组件根节点，根节点的 `data-state` 为 `running` 或 `stopped`。CSS 由宿主限定在对应组件内，`url()` 按样式表位置解析包内图片或字体。支持 `@media`、`@supports`、`@font-face` 和 `@keyframes`。字体与动画名称以 `apu-<插件 id>-` 开头。

组件槽位（`shell`、`navigation`、`overview`、`scheduler`）被宿主包进 `@scope ([data-apu-component="…"])`，负责给对应区域上色；`global` 槽位不加作用域，负责组件槽位够不到的两处——宿主在 `:root` 上合成的派生变量，以及 portal 到 `body` 的弹层组件（下拉菜单、对话框）。规则校验与组件槽位相同。

## 皮肤作者指南

皮肤按需覆盖的宿主令牌：

| 变量 | 宿主定义位置 | 用途 |
| --- | --- | --- |
| `--bg`、`--surface`、`--surface-muted`、`--text`、`--muted`、`--border`、`--accent`、`--red`、`--radius`、`--shadow` | `frontend/src/styles/tokens.css` 与各主题调色板 | 本地主题的基础色板与基调 |
| `--theme-surface`、`--theme-surface-bg`、`--theme-surface-alpha`、`--theme-glass`、`--theme-radius-*` | `frontend/src/styles/theme-system.css`、`theme-primitives.css`、`theme-material.css` | 面板、玻璃拟态等派生外观 |
| `--rail-panel-*` | `frontend/src/styles/layout.css`、`components.css` | 任务配置卡、侧栏面板 |

实战提示：

- 基础色在 `:root` / 对应主题根上接管后，`--theme-*`、`--rail-panel-*` 等派生值会自动跟随；把 `--theme-surface-alpha` 设为 `100%` 可以关掉半透明玻璃效果，让实底色板生效。
- 本地部分规则使用多级类选择器（如 `.task-config-page .config-group`），皮肤需要同等或更高特异度的选择器压过它们；在皮肤选择器里加一个元素名即可抬一级。
- 本地弹层挂在页面内而不是统一 portal 的，直接使用组件槽位；跨到 `body` 的弹层需要 `global` 槽位。
- 变量名与类名以后可能调整，主题应在覆盖后用浏览器计算样式验证关键控件。

## 自定义页面、面板和调度器

`pack_apu` 会在包根目录加入 `apu.js`。从插件 HTML 中按相对路径导入：

```js
import { request, subscribe } from '../apu.js'

const instance = await request('instance.current')
const favorites = await request('storage.get', {key: 'favorites'})
subscribe('appearance', ({mode}) => { document.documentElement.style.colorScheme = mode })
```

| API | 权限和行为 |
| --- | --- |
| `instance.current`、`instance.overview` | `instance.read`，读取当前实例、资源和任务摘要 |
| `storage.get`、`storage.set`、`storage.delete` | `storage`，按插件和当前实例隔离；写入使用 `{key, value}` |
| `scheduler.toggle` | `scheduler.control`，只在调度器替换视图中可用；宿主负责保存配置后启动 |
| `subscribe('scheduler.state', fn)` | 调度器替换视图的状态和计数 |
| `subscribe('appearance', fn)` | 当前语言和明暗 |
| `subscribe('navigation.items', fn)`、`navigation.open` | 导航替换视图可用，订阅宿主提供的 `{title, to}[]` 并使用 `{to}` 打开其中一项 |

插件视图在沙箱 iframe 中运行。静态资源从同一插件版本加载，业务调用经宿主消息通道。把所需依赖与资源随包发布。调度器替换视图初始化失败时会回退到本地调度卡片。

插件数据按插件与当前实例隔离，单项上限 64 KiB，每个插件总量上限 1 MiB。`subscribe` 返回取消函数，并在监听时先回放最近一次数据。
