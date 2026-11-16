# 前端

> React 控制台（frontend/）：React + TypeScript + Vite 实现的 WebUI，业务通信统一走 `/api/v1/ws`。详细界面设计与协议见 frontend/README.md 与 frontend/API.md。

## 1. 模块概述

[资源管理](resource-management.md) 保留独立导航与 `/i/:instance/resources` 页面；也可从「资源统计」内的「资源趋势」旁进入 `/i/:instance/statistics?view=management`，两种入口共用页面实现。由 `pages/ResourceManagement.tsx` 与 `resources/` 提供 ECharts 桑基图、库存与收支明细。图节点支持资源与任务筛选，明细支持分页和完整区间 CSV 导出；原调度的石油自动控制使用现有配置事务接口保存。四种语言、窄屏和空数据状态均沿用控制台组件与主题。

「舰队管理」下并列放置「智能换船」与「舰船数据」。`pages/FleetSwitch.tsx` 在 `/i/:instance/task/FleetSwitch` 整合「舰队信息」「换船配置」「换船调度」「换船装备」四个页签，使用与舰船数据相同的分段按钮样式；查询参数 `tab=info|rotation|training|equipment` 记录当前页签，刷新后保持选择。原 `FleetInfo`、`FleetRotation`、`FleetTraining`、`FleetEquipment` 及等级/好感调度链接自动跳转到对应页签。侧栏树、悬浮菜单及顶栏任务跳转共用 `components/taskNavItems.ts`，只保留一个智能换船入口，不注册新的游戏任务，各页签继续使用原有配置路径与保存接口。原「自动换装备」页面显示名称改为「换船装备」，默认开关和装备码规则不变。

整合前的[四个菜单入口](images/fleet-switch-before.png)来自用户提供的界面截图；整合后的[桌面](images/fleet-switch-desktop.png)与[手机](images/fleet-switch-mobile.png)截图来自隔离模拟服务，仅验证界面展示和交互，不代表实际游戏验证。

「舰队信息」页签仍由 `pages/FleetInfoPage.tsx` 提供舰队卡片和扫描开关，调用 `tasks.run(FleetScan)`，只在该扫描运行时调用 `scheduler.stop`；其他任务运行、更新或连接不可用时禁用。启动前等待配置队列保存，再以最新修订保存 `FleetInfo.FleetInfo.UpdateEmotion`（扫描时更新心情）选项；关闭时保留已有舰位心情参考，不进行被动学习。扫描运行期间及结束后重读舰队信息，显示扫描确认的舰位，不为历史记录推断舰位。浏览页面不启动游戏，也不修改实例自启设置；手动指定舰位互换尚未提供独立按钮，智能换船使用下述策略页签。

舰队信息的[桌面截图](images/fleet-management-desktop.png)与[手机截图](images/fleet-management-mobile.png)
来自隔离服务及合成记录，只验证舰位、未知心情和扫描选项展示，不代表实际账号操作。

「智能换船」的 `/i/:instance/task/FleetSwitch?tab=rotation` 页签名为「换船配置」，继续独立保存配置，
不注册游戏任务，也不显示调度状态或启动任务按钮。六支水面
舰队的36个舰位默认均为“不变”，可逐位改为“换船”，并为每支目标队多选候补队。
此页只保存共享的 `FleetInfo.FleetRotation.Rules`，不修改三个调度的开关和心情计算选项，
不调用 `tasks.run`。页面显示已保存
的上次来源与本轮进度，任务运行时只刷新进度，不覆盖尚未保存的规则编辑。
清空轮换记录按钮仅在任务停止时可用，不清空培养完成记录。实际刷图触发由战役出击前策略负责。

同页的`/i/:instance/task/FleetSwitch?tab=training`「换船调度」集中展示心情、等级和好感三个独立开关，
默认均关闭，共享上述舰位及候补。原等级/好感页面链接自动跳转到此页。等级与好感分别保存目标；
页面上方只保留一个`FleetInfo.FleetTraining.CheckIntervalHours`共用小时实读间隔，三个卡片内不再重复。
支持小数、不设上限、默认0.5小时；旧独立间隔优先按启用项目的最短值迁移，都关闭时取已有最短值，
分钟先等值换成小时，已有共用值优先，页面读取不写盘。0仍表示每次结算检查，实际读取时机仍为当前地图完成后。
任一模式开启都在开始、换船后和共用间隔到期时实读舰名与心情，再核对已启用培养条件。
“仅计算更换舰船心情”放在此页，三种调度共用；不开启心情调度时，低心情只延时，不临时换船。
记录区按“培养舰船”“完成舰船”“旧记录舰船”分成三个独立大框，显示舰队、舰位、实际舰名、
最近记录心情、等级、经验、好感及核对时间。培养舰船取共享配置中勾选舰位的在队船，完成状态优先归入完成框；
其余未完成记录归旧记录。每框按实际舰队、舰位1–6向下排列；完成和旧记录各选最近6条展示，
完整持久记录不裁剪，也不影响已完成舰船的排除。当前编队快照提供最近确认的位置和心情，
快照中不在队的记录回退到保存的位置及心情；同名多艘不能归并培养进度，缺失值不猜测。
同名舰船可以展示`State.readings`中同舰队、同舰位且舰名一致的实读值，不能借用其他同名舰船的记录，
这些舰位读数不进入完成分类，也不作为自动完成或换船依据。
旧空字符串编队快照按尚未扫描处理，已有历史仍可展示，不要求额外启动扫描。
各项保留最近记录值、不表示即时值，未知经验及旧记录缺项显示“未读取”，真实0心情/经验正常显示。
窄屏仅在表格内部横向滚动，分类标题保持可见。
当前[统一调度与三类记录截图](images/fleet-scheduling-and-records-desktop.png)使用隔离模拟服务和合成数据。
运行时只刷新记录和编队快照，不覆盖未保存输入。页面不显示任务运行侧栏，不调用`tasks.run`，
不改写心智计算器状态。浏览器验证使用隔离模拟服务，真实模拟器未在本轮验收。

frontend/ 是 AzurPilot 的浏览器控制台，替代旧版 PyWebIO 界面，覆盖主页与实例导航、任务配置表单、总览日志与截图预览、统计图表、系统设置、远程访问与更新器，并提供 APU 插件包的管理页与运行时。前端不包含任何游戏逻辑，所有业务操作都通过 WebSocket API 交给 [API 服务](api.md)执行；协议分为操作与数据两条连接，大消息按帧传输。

frontend/README.md 与 frontend/API.md 已经是本前端的详细文档：前者覆盖界面行为、主题材质、启动开发与迁移边界，后者定义消息协议。本文不重复其内容，只作为模块文档体系的索引篇，说明目录分工、构建测试入口与生成产物红线。

注意：项目中的 **1280×720 是游戏截图识别的约束，不适用于 WebUI 布局**。前端按普通响应式网页开发，支持移动端折叠菜单，e2e 视口为 1440×1100。

本地通知通过全局 `notifications` 主题接收，不绑定实例；浏览器在用户手势后申请系统通知权限，使用本地品牌与图标。通知订阅不触发普通数据快照轮询。

移动端在 950px 及以下使用导航与调度抽屉。新版主题的调度栏必须使用固定定位，桌面 L 形容器中的相对定位仅限 951px 及以上，隐藏抽屉不得占用正文高度；看图模式把手也仅在桌面显示。新版首页在窄屏按实例列表单列排列，由首页内容区整体滚动。480px 及以下，新版总览的日志工具栏沿用表头内排布，避免覆盖日志与截图切换入口；统计表格搜索另起一行，保留标题和导出操作的可读宽度。所有主题的统计分类在 950px 及以下统一使用下拉菜单，完整列出分类名称，不裁切横排标签；编辑模式的合并页面开关保留在下拉旁边。桌面仍使用分段分类栏，紧凑主题按可用宽度改用下拉。相关回归位于 `frontend/e2e/mobile/mock.spec.ts`，使用触摸移动视口检查正文可见性、滚动可达性、抽屉与桌面断点切换，运行 `npm run test:e2e:mock --prefix frontend -- e2e/mobile/mock.spec.ts`。

统计页各分类均保留历史展示与筛选，并提供导出入口：页面可导出本类数据，表格有各自的导出明细按钮，图表支持保存为图片。

## 2. 模块职责

### 负责

- 渲染单页应用（hash 路由）：主页、实例总览、任务配置、统计、系统设置、更新器等页面
- WebSocket 双通道连接管理：按方法把读写请求分发到 control/data 两条连接，各自认证、心跳、超时与重连；大消息分帧发送与重组（`src/api/socket.ts`、`src/api/client.ts`）
- 插件运行时：插件管理页、iframe 沙箱、导航/总览/调度槽位、主题样式注入与插件数据通道（`src/plugins/`）
- 配置表单展示与保存：字段保存队列、草稿恢复、重试与数值校验（`src/config/EditQueue.ts`）
- 任务优先级字段的拖动排序与解析：`src/app/taskPriority.ts`（纯函数：解析/合并/移动）+ `src/components/TaskPriorityField.tsx`（拖拽交互），写入 `Scheduler_Scheduler_Tasks`，提交值用 `
> ` 分隔（注释行与全角箭头已兼容归一）
- 主题、语言等浏览器侧偏好的保存与应用（localStorage）；背景记录与图库文件存服务端，见 `module/api/background_service.py`
- 日志面板在数据进入 React state 前只保留最近 1000 条，作为后端环形缓冲之外的独立防线，避免异常历史 payload 在 WebView2 中生成超大 DOM
- 独立 mock 服务（`mock/`），无需 Python、ADB 或模拟器即可开发验证前端交互

### 不负责

- API 协议、认证会话与业务适配：在 `module/api`，见 [API 服务](api.md)
- 进程、OCR、更新与认证等运行时服务：在 `module/runtime`，见 [WebUI 总览](index.md)
- 游戏配置定义与翻译生成：在 `module/config/`，见 [配置系统](../config.md)
- 真实运行与完整业务校验：mock 服务只验证前端交互，安全策略以 Python API 测试为准

## 3. 模块位置

```text
frontend/
├── src/main.tsx              # 应用入口：hash 路由表、错误兜底、先加载主题再挂载
├── src/api/                  # socket.ts 单通道传输；client.ts 双通道分发；generated.ts 与 contract.json 为生成产物
├── src/app/                  # 布局、主题系统（theme.ts 按需加载）、连接上下文、任务优先级解析（taskPriority.ts）、各类偏好
├── src/pages/                # 页面：Home / Overview / TaskConfig / Statistics / Settings / Updater 等
├── src/components/           # 可复用组件：FormControls、LogPanel、StatisticsChart、TaskPriorityField（任务优先级拖动排序）、实例切换等
├── src/config/               # EditQueue 跨页面字段保存队列、草稿恢复、输入校验
├── src/plugins/              # 插件上下文、iframe 沙箱、页面/导航/调度槽位与插件样式
├── src/styles/               # 设计变量与界面样式（apple / forms / compact / minimal 等 css）
├── src/i18n.ts               # 控制台固定文案（四种语言），独立于游戏翻译 module/config/i18n
├── e2e/                      # Playwright 浏览器测试
├── plugin-sdk/               # APU SDK bridge、插件清单示例与作者文档
├── mock/                     # 内存模拟服务（server.mjs、state.mjs）及其测试
├── playwright.config.ts      # e2e 主配置：连接 tests/serve_frontend.py 临时后端
├── playwright.mock.config.ts # e2e mock 配置：连接独立 mock server 与 Vite mock 模式
└── vite.config.ts            # 开发代理与相对构建（base: './'）
```

更细的文件级职责表见 frontend/README.md「目录职责」。

## 4. 核心入口

追代码从 `src/main.tsx` 开始：hash 路由表、顶层 ErrorBoundary 与主题加载流程都在这里。

| 入口 | 用途 |
| --- | --- |
| `npm run dev --prefix frontend` | 开发服务器（5173），代理到真实后端 |
| `npm run dev:mock --prefix frontend` | 同时启动 Vite 与 mock server（默认 22392），纯前端开发 |
| `npm run build --prefix frontend` | `tsc -b` 类型检查 + Vite 生产构建，产物在 `dist/` |
| `npm run typecheck --prefix frontend` | 仅 `tsc -b` 类型检查 |
| `npm test --prefix frontend` | vitest 单元测试（client、组件与纯函数） |
| `npm run test:e2e --prefix frontend` | Playwright e2e，主配置 |
| `npm run test:e2e:mock --prefix frontend` | Playwright e2e，mock 配置 |

Node.js >= 22.12（推荐 24），首次准备用 `npm ci --prefix frontend`。

两个 e2e 配置的区别：主配置在仓库根目录以 `uv run python -m tests.serve_frontend` 起服务——它使用临时配置目录、拒绝执行真实游戏任务（替换 `runtime.start/stop` 与 `updater.fetch/apply/cancel`），连接真实 Python API 跑除 `mock.spec.ts` 外的全部用例；mock 配置只跑 `mock.spec.ts`，同时拉起 mock server（22492）与 Vite mock 模式（5174），完全不需要 Python 与模拟器。

## 5. 双通道传输与插件运行时

前端 `src/api/socket.ts` 提供单通道 RPC 传输，`src/api/client.ts` 按方法把请求分发到两条 WebSocket：

- `/api/v1/ws?channel=control`：认证、实例/配置/调度写操作、插件管理、事件订阅；
- `/api/v1/ws?channel=data`：大读取，包括日志、预览、统计报表、配置/船坞/科研/调度读取等；清单来自生成产物 `dataMethods`，订阅主题 `logs`、`preview` 也走这里。

两条连接独立认证、心跳、超时与重连。数据连接断开时操作连接保持 `ready`，读取请求在数据连接重连成功后自动重试一次；写请求始终由调用方决定是否重试。会话事件里的 `channel` 与后端 `module/api/ws_transport.py` 协商分帧：单帧 64 KiB、请求 8 MiB、响应 64 MiB，超过单帧的 JSON 按“首字节 0 续片 / 1 末片”的二进制分片发送与重组。旧后端不返回 `channel` 时客户端退回单连接模式，全部请求仍走操作连接；`events.subscribe` 的参数由 `ApiClient.subscriptionParams()` 按同一能力裁剪——旧后端的 `SubscribeParams` 不认识 `plugins` 主题，原样发过去会让整条订阅判 `INVALID_PARAMS`，连带丢掉通知与实例事件，所以只在 hello 声明了 `channel` 的后端才带插件主题。

Socket 地址始终由 `new URL('api/v1/ws', document.baseURI)` 生成，并按页面协议选择 `ws/wss`；这是 SSH 前缀反代与 `/<peer_id>/` 隧道路径能继续工作的前提，不能改成绝对路径。`index.html` 的单段路径 `<base>` 注入逻辑保持不变，也不引入 Clarity 遥测。

插件包（APU API 1）由后端 `module/api/plugin_service.py` 安装到 `config/plugins/plugins.db`。前端 `src/plugins/` 提供管理页、iframe 沙箱、导航/总览/调度槽位与样式注入：

- 插件列表走 control 连接的 `plugins.list`，并订阅 `plugins` 主题自动刷新；导入、启停、卸载走同源 HTTP `/api/v1/plugins`，令牌由 `plugins.access` 下发，插件拿不到访问密码。
- iframe 使用 `sandbox="allow-scripts"`；父页面校验握手 nonce 后用 MessagePort 按 manifest 权限提供 `instance.read`、`storage`、`scheduler.control`，导航替换视图只能打开宿主列出的地址。
- 与本地外壳兼容的插件主题能力：`pages`、`panels`、`navigationView`、`overviewView`、`scheduler`、`styles`（`shell`/`navigation`/`overview`/`scheduler`/`global`）、`replaceSchedulerStyles` 与 `icons`。`theme.navigation` 的停靠位置和 `theme.overview` 的块顺序没有实现，因为本地是固定侧栏 + 固定总览布局，不能按上游多外壳模型假装支持。
- 用户 `public/theme.css`、本地主题（浅色/深色/旧版浅色/旧版深色/简约/紧凑 + 玻璃/朴素材质）与皮肤 CSS 继续生效；插件 `global` 槽位在应用挂载后加载，可覆盖本地主题变量，但不删除主题切换能力。已删的公告、茗交所、LLM、配对、Cloudflare/公网直连入口不会因插件系统恢复。
- 主题样式预载分两段：`index.html` 按 localStorage 的 `azurpilot.apu-styles` 记录先挂 `<link data-apu-preload>`，避免首帧闪默认外观；插件列表首次成功加载后由 `PluginStyles` 调 `src/plugins/themeStyles.ts` 的 `syncThemeStyles(ready, theme)` 接管：撤掉全部预载链接并按当前主题改写记录。`ready` 之前（登录前、列表未返回）一律不动记录——那时 `theme` 必然是空的，提前写缓存会把预载记录清成 `null`，下次刷新又要闪一遍。

## 6. 工作流程

- 开发联调：`uv run python gui.py` 起后端（默认端口见 config/deploy.yaml 的 `WebuiPort`），另开 `npm run dev`，Vite 将 `/api`（含 WebSocket）与 `/healthz` 代理到后端，`AZURPILOT_BACKEND` 可换目标；代理保留 Host，浏览器来源校验仍然有效。
- 纯前端开发：`npm run dev:mock`，模拟服务只读公开的 args.json、menu.json、翻译与 template.json，所有数据在内存，重启即重置。
- 构建部署：`npm run build` 产出 `dist/`。gui.py 启动时检查前端源码摘要，缺产物或源码变化时自动执行 `npm ci` 与构建；Docker 多阶段构建预装静态产物。
- 构建使用相对 base（`base: './'`）：远程访问经 `/<peer_id>/` 前缀式反代加载，绝对路径会 404。

## 16. 修改注意事项

- **生成产物红线**：`src/api/generated.ts` 与 `src/api/contract.json` 由 `uv run python -m dev_tools.export_api_schema` 生成，禁止手改；CI 会重新生成并用 `git diff --exit-code` 校验。新增 API 方法的顺序：先定义后端参数模型与路由，再运行生成器，然后更新 `src/api/types.ts` 响应类型与对应测试；不得通过方法名反射任意 Python 属性。带 `data_channel=True` 的后端方法会同时写入 `dataMethods`，双通道客户端据此把读取分发到数据连接；插件方法 `plugins.access/list/storage.*` 也由同一生成器输出，不要手写契约。
- **前端 UI 栈以本仓库实现为准**（Add by MHY, 合并 upstream_nanoda 时适用）：主题家族（浅色/深色/旧版浅色/旧版深色/简约/紧凑 + 材质轴）、背景、日志与页面外壳都是本地定制，依赖只用 [package.json](../../../frontend/package.json) 里的 CodeMirror、ECharts、motion、liquid-glass-react 等；上游的 Tailwind + shadcn 重写版不采用，冲突时按本地实现解析，不要整片取上游覆盖主题、外壳与样式。远程访问页沿用本仓库的 SSH 隧道界面，不引入上游的公网直连/P2P/Cloudflare 入口；公告、茗交所（MMEX）、LLM 日报与错误分析、配对码页面保持移除状态，mock 也不再提供 `announcement.get` 之类的已删接口。
- **插件主题按本地槽位实现**：`src/plugins/` 只消费 `pages`/`panels`/`navigationView`/`overviewView`/`scheduler`/`styles`/`replaceSchedulerStyles`/`icons`；`theme.navigation` 停靠位置与 `theme.overview` 块顺序未实现，不要为了插件把外壳改成多布局模型。`PluginThemeViews` 的导航 items 必须来自本地真实路由，禁止恢复 stock 侧栏入口。插件 `global` 样式可以覆盖本地主题变量，但不能替代或删除 `public/theme.css`、本地主题家族和材质轴。
- **旧版两列总览里的插件面板必须跨两列**：`.instance-page-grid` 在 ≥951px 是「左栏调度 + 右列资源/日志」的定高网格，`PluginPanels` 是它的第三个流内子项，留在自动流里会掉进 16–20rem 的左列并被 `main` 的 `overflow:hidden` 裁掉。`legacy.css` 用 `:has(> .apu-panels)` 把它放到第二行整行跨列，行高按内容但封顶 `min(38dvh, 26rem)`、超出部分在面板区自己滚；没有插件时这一行不存在，两列布局保持原样。
- **e2e 的 WebSocket 路由要带查询串**：双通道连接地址含 `?channel=control|data`，`page.routeWebSocket` 用 `**/api/v1/ws*`；只写 `**/api/v1/ws` 会漏接连接，导致测试挂起。直接 `new WebSocket(...)` 的夹具可不带 channel，后端会按单连接处理。
- **`base: './'` 不能改回绝对路径**：这是远程访问反代的硬性要求，且配套要求 deploy.yaml 的 `RemoteAccessMode` 为 ssh。
- **不要在 React 中重复登记游戏配置**：配置表单直接读取后端生成的 args.json、menu.json 与翻译文件；新增任务或参数只需改 `module/config/` 并重新生成。
- 新增选择器使用 `FormControls.tsx` 的 `Select`，配置字段使用 `FieldInput`，不要在各页面单独绘制箭头、勾选等图标。
- 控制台固定文案在 `src/i18n.ts`（四种语言）；游戏任务配置的名称与说明翻译在 `module/config/i18n/`，二者独立，别改错位置。
- 主题与语言只存浏览器（localStorage），不写入服务端部署配置；**背景是例外**：生效记录存 `cache/background/preference.json`，图库文件存 `cache/background/library/`，所以换浏览器或换访问地址（局域网 IP 与 frp 公网域名各算一份浏览器存储）看到的是同一张背景。旧的浏览器 IndexedDB 上传图会在首次打开时自动迁移进服务端图库。

## 17. 上游差异与已接纳修复

合并 upstream_nanoda/master 时，上游前端同时包含两件事：独立的协议/插件功能，以及整体 Tailwind 4 + shadcn 的换肤重写。本树只接纳前者：

**已接纳**

- 操作/数据双 WebSocket 与二进制分帧传输（`src/api/socket.ts`、`src/api/client.ts`、`src/api/client.test.ts`），保留 `document.baseURI` 反代路径与断线重连语义；旧后端无 `channel` 时单连接兼容。
- APU 插件 SDK、插件管理页、插件页面/面板、导航替换、总览替换、调度器替换、主题样式槽位、插件存储与权限校验（`frontend/plugin-sdk/`、`src/plugins/`、`src/pages/Plugins.tsx`）。
- `useInstanceOverview` 的跨实例隔离：切换实例后的首帧不再显示上一个实例的总览，旧实例返回的异步结果也不会写进新实例。
- `useSchedulerControls` 的同步防重入与过期实例结果拦截：同帧连点不会重复发启停请求，实例切换后返回的旧响应会被丢弃。
- 插件调度卡片的 `data-apu-part`、`replaceSchedulerStyles` 与图标替换；插件导航不包含 stock 侧栏入口。
- 生成契约中的 `plugins.*` 与 `dataMethods`；e2e 的 WebSocket 路由匹配补上 `?channel=` 查询串。

**未接纳（保留本地实现）**

- 上游把整站迁到 Tailwind 4 + shadcn/radix 的组件与样式重写，包括外壳、设置页、表单、弹层、表格和主题家族更名。本树继续用本地 React 组件、现有 CSS 域文件、六套主题与玻璃/朴素材质轴。
- 上游 `theme.navigation` 的 top/left/right/bottom 停靠位置与 `theme.overview` 的内置块顺序；本地是固定侧栏 + 固定总览布局，接入这两个字段会与本地外壳冲突，已在上文说明具体机制。
- 上游启动器 WebSocket 票据（`auth.launcher`）与桌面启动器协议：本树后端只有本地启动器通道，未导出该方法。
- 上游公告、茗交所（MMEX）、LLM、配对、Cloudflare/公网直连相关页面与入口：本树保持删除，也没有用插件系统变相恢复。
- 上游的品牌图标/ProjectLogo 与 Clarity 遥测：本树继续使用 ALAS 品牌与本地图标，`index.html` 不含 Clarity。

## 19. 调试方法

- 界面交互问题先用 mock 模式复现（无需 Python 与模拟器）；`AZURPILOT_MOCK_SCENARIO=empty` 从零实例测首次创建，`AZURPILOT_MOCK_PASSWORD` 可测登录与重连。
- 隔离合并树里 `module/config/i18n` 可能仍是冲突件：给 mock 与测试设置 `AZURPILOT_CONFIG_ROOT=/path/to/resolved/tree`，它会只读借用该树的 `module/config`、`config/template.json` 与 `assets`；不要为此改写父树或直接改冲突中的 i18n。
- 模拟统计报告的逐点序列同真实接口使用 `{t, v, s?}`，时间为微秒整数；通过前端 `normalizeReport` 还原后再渲染，避免旧 `{time, value}` 夹具导致日期与指标显示 NaN。
- e2e 失败先看截图输出在被 git 忽略的 `frontend/test-results/`；先确认跑的是哪套配置（主配置连临时 Python 后端，mock 配置连内存模拟服务）。
- 类型报错疑似与后端契约不一致时，先重跑 `dev_tools.export_api_schema`，再排查是否有人手改了生成产物。

## 20. 相关模块

- [舰队科技列表](fleet-technology.md) —— Lua 目录、累计扫描证据、人工校正和阵营加成。

- [WebUI 总览](index.md)
- [API 服务](api.md) —— 协议、认证与路由，前端所有业务通信的对端
- [配置系统](../config.md) —— args.json、menu.json 与翻译文件的来源
- [外部桥接与开发工具](../infra/submodule-tools.md) —— dev_tools.export_api_schema 所在的开发工具层
