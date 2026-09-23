# WebSocket API v1

## 连接与认证

地址为同源 `/api/v1/ws`，HTTPS 下使用 `wss`。协议版本固定为 `v: 1`。服务只通过 HTTP 提供静态资源与 `/healthz`；业务数据与操作使用 WebSocket。独立 MCP 是另一项对外集成，仍保留自己的 SSE 协议。

服务升级连接前检查 Origin 与 Host 是否一致，拒绝跨站连接。最多同时保留 32 个连接，每连接请求上限 30 次/秒、单请求 1 MiB。反向代理必须支持 WebSocket Upgrade，并正确保留外部 Host/Origin。

建立连接后收到：

```json
{"v":1,"type":"event","topic":"session","seq":1,"data":{"authRequired":true,"protocolVersion":1}}
```

若需要认证，先调用 `auth.login`。认证前不能调用业务方法或订阅。密码来自现有 `--key` 或部署文件的 Password；通配地址监听且未设置密码时延用随机密码生成策略。认证材料只通过消息体传输，不放在 URL 或日志中。按用户要求恢复密码记忆：登录成功后访问密码保存在当前浏览器同源 localStorage，刷新、重新打开页面和断线重连自动登录；密码失效时删除旧值并重新显示登录页。浏览器禁止存储时仅保留本页登录。

```json
{"v":1,"type":"request","id":"login-1","method":"auth.login","params":{"password":"访问密码"}}
```

登录失败按来源地址递增退避，最长 60 秒。未认证会话 30 秒无消息后断开，已认证会话 60 秒无消息后断开。官方客户端每 15 秒发送一次 `system.ping`。

## 信封

请求必须包含 `v`、`type`、唯一字符串 `id`、白名单 `method`；`params` 默认空对象。不允许额外参数或隐式类型转换。

```json
{"v":1,"type":"request","id":"request-42","method":"config.get","params":{"instance":"alas"}}
```

成功：

```json
{"v":1,"type":"response","id":"request-42","ok":true,"result":{"instance":"alas","revision":"SHA256","values":{}}}
```

失败：

```json
{"v":1,"type":"response","id":"request-42","ok":false,"error":{"code":"INVALID_PARAMS","message":"参数格式不正确：Main.Scheduler.NextRun","details":null}}
```

同一连接最近 128 个请求 ID 不允许重复。ID 用于关联请求，**不是**跨连接的幂等键。配置字段赋值由独立队列在断线或超时后自动重试；启停、创建、删除等操作不自动重试，必须先查询最终状态。默认请求超时 45 秒，超时不代表服务端事务回滚。

## 方法

精确参数结构、必填项、长度和范围约束以 [contract.json](src/api/contract.json) 为准；前端参数类型由同一份 Python 模型生成。

| 方法 | 参数 | 结果/作用 |
| --- | --- | --- |
| `auth.login` | password | 当前连接通过认证 |
| `system.ping` | 无 | pong |
| `schema.get` | 可选 language | 任务菜单、参数定义与指定语言翻译；默认 zh-CN |
| `instances.list` | 无 | 实例名称、状态、序列号、服务器、currentTask（停止时为 null） |
| `instances.create` | name、可选 source | 从模板或已有实例复制配置 |
| `instances.delete` | instance、revision | 停止状态下将配置移至备份 |
| `config.get` | instance | 当前值及 revision |
| `config.patch` | instance、changes、可选 revision | 锁内合并指定字段，校验后原子保存 |
| `shop_strategy.validate` | instance、task、script | 只读校验高级商店策略，返回可定位的诊断，不执行脚本也不写入配置 |
| `overview.get` | instance | 资源、任务计划、连接配置与状态 |
| `scheduler.start` | instance | 启动调度器，返回当前总览 |
| `scheduler.stop` | instance | 停止调度器并执行配置的收尾动作 |
| `tasks.run` | instance、task | 运行允许单独执行的工具 |
| `logs.get` | instance、可选 after | 游标之后的日志，有界保留 |
| `preview.capture` | instance | 读取最近一张缓存 JPEG；不主动截图，无缓存时 image/capturedAt 为 null |
| `statistics.resources` | instance、days、resource | 兼容资源时间线，支持全部 12 种资源，最多 5,000 点 |
| `statistics.report` | instance、category、month、days、period | 六类统计，返回 metrics、series、tables 和 notes |
| `statistics.refreshLoot` | instance | 重新聚合本设备已有本地短猫掉落记录，不访问游戏 |
| `settings.get` | 无 | 部署设置定义及值，密码只写不读 |
| `settings.patch` | values | 校验并保存部署设置，重启生效 |
| `startup.get` | instance | 当前实例是否启动时自动运行、是否启动时记忆运行 |
| `startup.set` | instance、enabled?、remember? | 修改启动时自动运行 / 启动时记忆运行 |
| `updater.status` | 无 | 全局更新状态、localHead、upstreamHead、branch、ahead/behind、available、busy、canApply、canCancel、error |
| `updater.commits` | offset（默认 0）、limit（默认 50，上限 100） | 本地与上游完整可达历史，含完整 SHA、作者、时间、提交正文、total、hasMore 与两端 HEAD |
| `updater.fetch` | 无 | 后台获取远程更新，返回 accepted；不修改本地 HEAD |
| `updater.apply` | 无 | 后台复用原更新器，等待任务退出、更新代码、同步依赖并重启 |
| `updater.cancel` | 无 | 仅在等待任务结束阶段取消更新 |
| `events.subscribe` | topics、可选 instance | 原子替换当前连接的订阅集合 |

`instance` 必须指向 config 目录内已存在的实例，禁止路径分隔符、符号链接和系统保留名称。创建实例名称以字母或汉字开头，可包含字母、数字、汉字、短横线和下划线，总长不超过 64。运行实例禁止删除，已有运行实例禁止重复启动。

状态枚举：`running`、`stopped`、`error`、`updating`。枚举表示工作进程状态，不能据此推断游戏中的具体画面。

更新器接口不接收实例名；三个写方法沿用认证和 DEMO 只读限制。前端每三秒读取一次更新状态，重连后重新读取；后台操作立即响应，不占用 WebSocket 请求等待时间。HEAD 变化时提交列表返回第一页。`upstreamHead` 指配置分支的 `origin/<Branch>` 远程跟踪引用，获取更新后刷新；未获取时为 null。本地与上游分叉、没有新提交、更新器忙碌或监督器重启/依赖同步事件不可用时，`canApply` 为 false。

`schema.get.language` 支持 `zh-CN`、`zh-TW`、`en-US`、`ja-JP`、`zh-MIAO`，只影响本次返回的翻译，不修改运行器或其他浏览器的语言。参数定义保留 `mode: yaml`，供前端选择多行 YAML 编辑器。

## 高级商店策略校验

`shop_strategy.validate` 仅解析并校验受限 Lua 风格策略的语法和白名单；它不会启动 Lua VM、不会访问商品或设备，也不会保存用户输入。`task` 必须是 `EventShop`、`ShopFrequent`、`ShopOnce`、`PrivateQuarters`、`OpsiShop` 或 `OpsiVoucher` 之一，`script` 最长 20,000 个字符。

```json
{"v":1,"type":"request","id":"check-shop-script-1","method":"shop_strategy.validate","params":{"instance":"alas","task":"ShopFrequent","script":"return shop.plan { candidates = candidates:take(0) }"}}
```

无论脚本是否通过，参数本身合法时响应都在 `result` 中返回：

```json
{"valid":false,"diagnostics":[{"code":"missing_return","message":"必须返回 shop.plan {...}","line":1,"column":1}]}
```

`diagnostics` 是按源码顺序返回的错误列表；每项包含稳定的机器可读 `code`、可直接展示的 `message`，以及从 1 开始计数的 `line`、`column`（无法定位时为 `null`）。客户端应使用这些位置标记编辑器，不应执行、转换或自行放宽脚本。空脚本代表尚未启用高级策略，校验结果可为 `valid: true`；切换到高级模式前仍必须保存非空且有效的脚本。

## 配置事务

revision 是磁盘 JSON 内容的 SHA-256，仅用于读取快照和删除保护；配置保存接受旧版客户端传入 revision，但不再据此拒绝写入。`config.patch` 仅接受 `Task.Group.Argument` 形式的叶子路径，最多 200 项修改。完整校验成功后一次性原子替换；失败不保存任何字段。

```json
{"v":1,"type":"request","id":"save-1","method":"config.patch","params":{"instance":"alas","changes":[{"path":"Alas.Emulator.Serial","value":"127.0.0.1:5555"},{"path":"Main.Scheduler.Enable","value":true}]}}
```

API 和核心运行器共用跨进程事务锁。API 只合并请求指定的字段，其他页面或运行任务更新无关字段不会拒绝保存。同一字段的显式修改按服务端事务顺序生效。运行器加载时保留独立快照，在再次加载或保存时检查待写字段；磁盘值已变化时放弃该字段的旧任务回写，保留外部编辑。

前端任务参数、部署设置及启动偏好共用页面之外的保存队列，输入时同步保留原文并立即发起字段提交，不等待失焦或防抖。每个作用域串行提交，正在等待响应的字段继续接受输入，尚未发送的同字段输入合并为最新值。响应只确认对应输入版本，不覆盖后续输入。启动调度器或任务工具前会等待该实例队列保存完成，停止操作不受待保存内容影响。

每个字段显示保存中、已保存或错误状态。格式错误只阻止该字段写入，原文保留用于修正；其他字段照常保存。连接和临时服务错误自动重试；页面切换不停止队列。未确认的输入保存在当前标签页的 sessionStorage，刷新并重新认证后恢复所有作用域的待提交项，已确认项不再重放。浏览器禁用或耗尽存储时明确提示，并继续在内存中保留输入。关闭标签页前应确认已保存；离线期间无法使服务端立即生效。游戏任务在下一次读取或绑定配置时使用新值，部署设置仍按各项既有规则在重启服务后生效。直接绕开配置服务的外部脚本不受事务锁约束。

隐藏、固定和只读字段由服务端强制拒绝修改；`storage` 的唯一例外是通过 `config.patch` 将值清空为 `{}`，用于恢复旧版清除内部任务状态的按钮，其他状态内容仍禁止写入。布尔值必须是真正的 JSON boolean；数值范围来自参数定义；日期格式为 `YYYY-MM-DD HH:mm:ss`；多选值必须来自声明的候选项。YAML 字段使用安全解析器校验语法和顶层映射结构，并返回可定位的行列错误；保留原始文本存储。受限 Lua 字段在写入时会再次静态校验，不能通过只调用前端检查接口来绕过；同一事务合并后的 `ShopAdvanced.Mode=advanced` 必须配套非空且有效的 `ShopAdvanced.Script`。简单模式允许清空脚本。

## 订阅与恢复

```json
{"v":1,"type":"request","id":"subscribe-1","method":"events.subscribe","params":{"instance":"alas","topics":["instances","overview","logs"]}}
```

支持 `instances`、`overview`、`logs`、`preview`。除 `instances` 外必须提供 instance；空 topics 表示取消订阅。订阅会立即生效，并在下一次采样时发送初始快照。默认两秒采样，内容未变化时不发送。预览在总览切换到截图时订阅，在每次已有截图完成后通过独立事件通道推送，不使用轮询计时器，不访问 ADB 或额外调用截图后端。

```json
{"v":1,"type":"event","topic":"overview","seq":2,"data":{"instance":"alas","status":"stopped","revision":"SHA256","tasks":[],"resources":[],"emulator":{}}}
```

`seq` 只在当前连接内递增。重连后从新会话开始，客户端重新认证、读取元数据并重建订阅；服务不提供跨连接事件重放。切换实例时，旧订阅未完成的采样结果会被丢弃。

总览 `resources` 中的资源项包含 `value`、可选 `limit` 和记录时间。`ActionPoint` 额外可包含 `total`，表示当前行动力加上可按现有设置折算的行动力药剂总量，不是游戏上限；仅当 `total` 大于 `value` 时客户端展示该值。

日志响应包含 `cursor`、`reset`、`entries`。每条日志有单调递增的 `id`、`level` 和纯文本 `text`。服务及页面各保留最多 400 条；客户端游标落后缓冲区或服务重启时返回 reset，客户端替换窗口。清空页面只影响当前视图，不删除服务端日志。完整运行日志仍由原有文件日志系统保存。

单连接控制消息队列最多 32 条，慢客户端以 1013 关闭并重新同步。预览只占一个待发送槽，新帧替换未发送旧帧，事件序号按实际发送顺序分配。网络断开不停止任务。预览/实例读取失败会发送 `subscription.error`，包含 topic、instance、code、message；其他订阅继续运行。

## 错误码

| 类别 | 错误码 |
| --- | --- |
| 协议 | INVALID_REQUEST、INVALID_PARAMS、METHOD_NOT_FOUND、DUPLICATE_REQUEST |
| 认证/权限 | UNAUTHORIZED、RATE_LIMITED、READ_ONLY |
| 配置/实例 | NOT_FOUND、ALREADY_EXISTS、CONFIG_INVALID、CONFLICT、INSTANCE_RUNNING |
| 运行/设备 | START_FAILED、STOP_FAILED、DEVICE_UNAVAILABLE |
| 服务内部 | INTERNAL_ERROR |
| 客户端本地 | DISCONNECTED、TIMEOUT |

INTERNAL_ERROR 不向浏览器返回堆栈；参数校验详情不回显输入。DEMO 模式下所有注册的写方法统一拒绝执行。

## 扩展与版本规则

1. 在 `module/api/protocol.py` 添加严格参数模型。
2. 在独立业务服务中实现操作，在 `router.py` 显式登记是否写入。
3. 执行 `uv run python -m dev_tools.export_api_schema` 更新 JSON Schema 和 TypeScript 参数类型。
4. 更新 `types.ts` 响应类型和 API 文档，并增加真实 WebSocket 回归。
5. v1 只允许兼容性新增；删除方法、更换字段语义或类型需要新版本路径。

前端构建方式参考 [React 官方说明](https://react.dev/learn/build-a-react-app-from-scratch)，开发代理行为参考 [Vite 官方文档](https://vite.dev/config/server-options.html)。

## 总览任务状态与被动预览

任务条目新增 `state: running | pending | waiting`，兼容保留 `pending` 字段。运行中由工作进程在任务进入和 finally 退出时发送明确的状态事件，等待/待执行按核心校准时间与 NextRun 比较；运行任务优先展示，停止或异常进程不会残留运行状态。

`module/device/screenshot.py` 的统一入口在截图后投递 RGB 图像。`module/runtime/preview.py` 在后台编码 JPEG，通过有界跨进程队列交给父进程，再通知 WebSocket。所有已注册截图后端共用这条路径；未安装通道的独立脚本不额外编码。运行批次标识隔离重启前后的任务状态与截图。没有新截图时保留原帧和采集时间，API 不会启动截图任务。

## 分类统计

`category` 支持 `resources`（12 种资源）、`action`（行动力、资产、海里、黄币、紫币）、`opsi`（侵蚀1与短猫运行）、`commission`（收益与结算记录）、`ships`（升级进度、经验与时长）、`loot`（累计短猫掉落）。

资源页支持最近 1–365 天，最多读取最近 50,000 行快照并明确提示截断。大世界与行动力按月份读取；委托支持今日、本周、选定月份，周统计跨月读取。舰船展示最新检测与保留的历史日记录；掉落缓存沿用旧版全设备累计口径，不假装按实例或月份隔离。

图表保留独立采样时间和空值语义；聚合折线取桶末值，K 线取开、高、低、收，日聚合按浏览器本地自然日分桶。图表时间序列保持升序，原始记录和委托结算明细默认按时间降序显示，用户排序可覆盖默认值。CSV 导出保留原始精度，明细支持分页、排序、搜索和导出。侵蚀1沿用旧界面口径：轮数向上取整，每轮消耗 5 行动力；舰船效率与升级用时沿用原有估算公式。
