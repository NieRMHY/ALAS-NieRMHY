---
description:
alwaysApply: true
---

# mcp_server_sse.py 入口文件深度分析

> **最后核对**：2026-09-11（dev 分支）。文中行号均已按当前 mcp_server_sse.py 重新核实。本次核对加入 MCP 鉴权（见 §12）。

## 1. 文件基础信息

| 项目 | 内容 |
|---|---|
| 文件路径 | `mcp_server_sse.py` |
| 总行数 | 731 行 |
| 文件类型 | Python 脚本（MCP SSE 服务器） |
| 许可证 | GPL-3.0 |
| 服务器名称 | `"AzurPilot-MCP"` |
| 默认端口 | 22268（`STANDALONE_PORT`，注意与 OCR 服务的 `OcrServerPort` 同号） |
| SSE 端点 | `/mcp/sse`（独立运行时为 `/sse`） |
| 消息端点 | `/mcp/messages` |
| 鉴权 | 复用 WebUI 密码，见 §12.1 |

### 导入依赖

| 模块来源 | 具体导入 | 用途 |
|---|---|---|
| 标准库 | `os`, `logging`, `json`, `datetime`, `base64`, `time`, `subprocess`, `threading` | 系统操作、日志、序列化、时间、编码、进程、线程 |
| 标准库 | `typing.List, Dict, Any` | 类型注解 |
| 标准库 | `io.BytesIO` | 内存字节流 |
| 标准库 | `re` | 从 SSE 出站流中提取 `session_id` |
| 第三方 | `starlette.applications.Starlette` | ASGI 框架 |
| 第三方 | `starlette.middleware.Middleware` | 中间件 |
| 第三方 | `starlette.middleware.cors.CORSMiddleware` | CORS 跨域支持 |
| 第三方 | `mcp.server.Server` | MCP 服务器核心 |
| 第三方 | `mcp.server.sse.SseServerTransport` | SSE 传输层 |
| 第三方 | `mcp.types.TextContent, ImageContent, Tool` | MCP 类型定义 |
| 项目内部 | `module.config.config.AzurLaneConfig` | 配置系统 |
| 项目内部 | `module.config.time_source.now`（别名 `current_time`） | 统一时间源（NTP 校准） |
| 项目内部 | `module.config.utils.DEFAULT_CONFIG_NAME, alas_instance` | 默认实例名、实例列表 |
| 项目内部 | `module.webui.process_manager.ProcessManager` | 进程管理 |
| 项目内部 | `module.config.mcp_helper.McpConfigHelper` | MCP 配置辅助 |
| 项目内部 | `module.webui.mcp_auth` | MCP 鉴权判定与日志脱敏（纯标准库） |
| 项目内部 | `module.webui.setting.State` | WebUI 全局状态 |
| 可选 | `module.webui.fake_pil_module.remove_fake_pil_module` | PIL 模块伪装清理 |
| 惰性 | `module.webui.password_utils.ensure_password_for_host, is_demo_mode` | 独立模式的密码解析（仅在 `_resolve_standalone_password` 内导入） |

> `module.webui.mcp_auth` 与 `module.webui.password_utils` 都是纯标准库模块，不会把
> `app_dependencies` / `module.ocr.rpc` / pywebio 拖进独立 MCP 进程
> （`tests/test_ci_import.py::TestProcessIsolation` 守护该约束）。

---

## 2. 模块级初始化 (L35-L45)

```python
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("azurpilot-mcp")

helper = McpConfigHelper()

mcp_server = Server("AzurPilot-MCP")

ToolResponse = List[TextContent | ImageContent]
```

- **日志**: 使用标准库 `logging`（非项目的 `module.logger`），级别 INFO，logger 名为 `"azurpilot-mcp"`
- **helper**: `McpConfigHelper` 实例，加载 `args.json` 和 i18n 数据
- **mcp_server**: MCP 服务器实例，名称 `"AzurPilot-MCP"`
- **ToolResponse**: 类型别名 `List[TextContent | ImageContent]`，所有工具处理器的返回类型

---

## 3. `list_tools()` 工具注册 (L47-L198)

```python
@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
```

注册 18 个 MCP 工具。每个工具定义了 `name`、`description` 和 `inputSchema`。

### 3.1 工具清单

| # | 工具名 | 功能 | 必需参数 | 可选参数 |
|---|---|---|---|---|
| 1 | `list_instances` | 列出所有 AzurPilot 实例 | 无 | 无 |
| 2 | `get_status` | 获取所有实例运行状态 | 无 | 无 |
| 3 | `list_tasks` | 列出所有顶级任务名 | 无 | 无 |
| 4 | `get_task_help` | 获取任务详细参数结构 | `task_name` | 无 |
| 5 | `get_resources` | 获取实例资源状态 | `instance` | 无 |
| 6 | `get_config` | 获取实例当前配置 | `instance` | `task` |
| 7 | `update_config` | 修改配置项 | `instance`, `task`, `group`, `arg`, `value` | 无 |
| 8 | `get_recent_logs` | 读取最近日志 | `instance` | `lines` (默认 50) |
| 9 | `start_instance` | 启动实例 | `instance` | 无 |
| 10 | `stop_instance` | 停止实例 | `instance` | 无 |
| 11 | `get_screenshot` | 获取模拟器截图 | `instance` | 无 |
| 12 | `get_current_running_task` | 获取当前执行的子任务 | `instance` | 无 |
| 13 | `get_scheduler_queue` | 获取任务排队列表 | `instance` | 无 |
| 14 | `trigger_task` | 强制立即执行任务 | `instance`, `task` | 无 |
| 15 | `clear_scheduler_queue` | 清空任务队列 | `instance` | 无 |
| 16 | `restart_emulator` | 重启模拟器 | `instance` | 无 |
| 17 | `restart_adb` | 重启 ADB 服务 | 无 | `instance` |
| 18 | `update_alas` | 触发 Git Pull 更新 | 无 | 无 |

### 3.2 inputSchema 设计

所有工具使用 JSON Schema 定义输入参数：

```python
# 简单示例 - 无参数
inputSchema={"type": "object", "properties": {}}

# 复杂示例 - 多参数
inputSchema={
    "type": "object",
    "properties": {
        "instance": {"type": "string", "description": "实例名称"},
        "task": {"type": "string"},
        "group": {"type": "string"},
        "arg": {"type": "string"},
        "value": {
            "oneOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {"type": "object"},
                {"type": "array"},
                {"type": "null"}
            ],
            "description": "新的配置值"
        }
    },
    "required": ["instance", "task", "group", "arg", "value"]
}
```

**注意**: `update_config` 的 `value` 参数使用 `oneOf` 支持多种类型，这是 MCP 工具中较复杂的 schema 设计。

---

## 4. `call_tool(name, arguments)` 工具调用处理 (L488-L497)

```python
@mcp_server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> ToolResponse:
```

**这是所有工具调用的统一分发函数。**

- **参数**: `name` (str) - 工具名, `arguments` (Dict) - 工具参数
- **返回**: `List[TextContent]` 或 `List[ImageContent]`
- **错误处理**: 外层 `try/except` 捕获所有异常，返回错误文本
- **分发机制**: 使用 `TOOL_HANDLERS` 字典（L466-485）将工具名映射到独立的 `_tool_*` 实现函数，`call_tool` 本身仅约 10 行，负责查表分发

### 4.1 逐工具分析

> 注意：各工具实现已拆分为独立的 `_tool_*` 函数，行号与原 if/elif 结构不同，以下行号为函数内部实现位置。

#### `list_instances` (L200-L202)

```python
instances = alas_instance()
return [TextContent(type="text", text=json.dumps(instances, ensure_ascii=False, indent=2, default=str))]
```

- **数据源**: `alas_instance()` 从 `config/` 目录扫描 JSON 配置文件
- **返回**: JSON 格式的实例名列表

#### `get_status` (L205-L211)

```python
instances = alas_instance()
results = []
for inst in instances:
    manager = ProcessManager.get_manager(inst)
    results.append({"instance": inst, "running": manager.alive, "state": manager.state})
```

- **数据源**: `ProcessManager` 单例管理器
- **返回**: 每个实例的 `{instance, running, state}`
- **性能**: 遍历所有实例，每个实例获取一次进程状态

#### `list_tasks` (L214-L216)

```python
tasks = helper.get_tasks()
```

- **数据源**: `McpConfigHelper.get_tasks()` 从 `args.json` 提取任务名
- **返回**: 任务名列表

#### `get_task_help` (L219-L222)

```python
task_name = arguments["task_name"]
details = helper.get_task_details(task_name)
```

- **数据源**: `McpConfigHelper.get_task_details()` 从 `args.json` + i18n 数据组装
- **返回**: 包含 `task_name`, `display_name`, `help`, `groups` 的详细结构

#### `get_resources` (L225-L229)

```python
config = AzurLaneConfig(inst)
res = helper.get_dashboard_resources(config.data)
```

- **数据源**: 实例配置中的 `Dashboard` 节点
- **返回**: 资源状态（油、金币、红尖尖等）的 Value/Limit/Total

#### `get_config` (L232-L237)

```python
config = AzurLaneConfig(inst)
data = config.data.get(task, {}) if task else config.data
```

- **参数**: `instance` (必需), `task` (可选过滤)
- **返回**: 配置数据（可按任务过滤）

#### `update_config` (L240-L250)

```python
config = AzurLaneConfig(inst)
path = f"{task}.{group}.{arg}"
config.cross_set(path, value)
config.save()
```

- **功能**: 修改指定配置项并保存到磁盘
- **路径格式**: `Task.Group.Arg`（如 `Research.Scheduler.Enable`）
- **副作用**: 写入 `config/{instance}.json`

#### `get_recent_logs` (L253-L277)

```python
date_str = datetime.date.today().strftime("%Y-%m-%d")
log_file = f"./log/{date_str}_{inst}.txt"
```

- **日志路径**: `./log/YYYY-MM-DD_{instance}.txt`，回退到 `./log/YYYY-MM-DD_alas.txt`
- **返回**: 最近 N 行日志（默认 50）
- **实现**: 读取整个文件后截取最后 N 行（对大文件不高效）

#### `start_instance` (L280-L288)

```python
manager = ProcessManager.get_manager(inst)
if manager.alive:
    return [TextContent(type="text", text=f"Error: {inst} is already running.")]
from module.submodule.utils import get_config_mod
func = get_config_mod(inst)
manager.start(func=func)
```

- **前置检查**: 已运行则返回错误
- **功能**: 通过 `ProcessManager` 启动实例子进程
- **模块选择**: `get_config_mod()` 根据配置确定要运行的模块

#### `stop_instance` (L291-L297)

```python
manager = ProcessManager.get_manager(inst)
if not manager.alive:
    return [TextContent(type="text", text=f"Error: {inst} is not running.")]
manager.stop()
```

- **前置检查**: 未运行则返回错误
- **功能**: 通过 `ProcessManager` 停止实例子进程

#### `get_screenshot` (L300-L327)

```python
config = AzurLaneConfig(inst)
device = Device(config)
image = device.screenshot()
image_pil = Image.fromarray(image)
buffered = BytesIO()
image_pil.save(buffered, format="JPEG")
img_data = base64.b64encode(buffered.getvalue()).decode("utf-8")
return [ImageContent(type="image", data=img_data, mimeType="image/jpeg")]
```

- **功能**: 截取模拟器屏幕并返回 Base64 编码的 JPEG 图像
- **流程**: ADB 截图 -> numpy 数组 -> PIL Image -> JPEG Bytes -> Base64
- **环境变量**: 若 `ALAS_CONFIG_NAME` 未设置则写入当前实例名，用于设备连接
- **特殊处理**: `remove_fake_pil_module()` 清理 PIL 模块伪装
- **错误处理**: 捕获异常返回错误文本（含堆栈跟踪）
- **性能**: 每次调用创建新的 Device 实例（无缓存）

#### `get_current_running_task` (L330-L359)

```python
manager = ProcessManager.get_manager(inst)
if not manager.alive:
    return [TextContent(type="text", text="Error: Instance is not running.")]
# 从日志文件解析当前任务
for line in reversed(lines):
    m = re.search(r"调度器: 开始任务\s*[`'\" ](.*?)[`'\" ]", line)
    if not m:
        m = re.search(r"<<<\s*Run task\s*(.*?)\s*>>>", line)
    if m:
        task = m.group(1)
        break
```

- **功能**: 从日志文件中解析当前正在执行的任务
- **正则匹配**: 支持两种日志格式：
  - 现代格式: `调度器: 开始任务 \`TaskName\``
  - 旧版格式: `<<< Run task TaskName >>>`
- **回退**: 匹配失败返回 `"Unknown"`

#### `get_scheduler_queue` (L362-L374)

```python
config = AzurLaneConfig(inst)
queue_data = []
for task_name in config.data:
    if task_name in ["Alas", "Error", "MUMU", "MumuPlayer12", "EmulatorManagement", "Dashboard"]:
        continue
    scheduler = config.data.get(task_name, {}).get("Scheduler", {})
    if scheduler.get("Enable", False):
        next_run = scheduler.get("NextRun", "2050-01-01 00:00:00")
        queue_data.append({"task": task_name, "next_run": str(next_run)})
queue_data.sort(key=lambda x: str(x["next_run"]))
```

- **功能**: 获取已启用任务的执行队列
- **过滤**: 跳过系统任务（Alas, Error, MUMU 等）
- **排序**: 按 `NextRun` 时间升序
- **返回**: `[{task, next_run}, ...]`

#### `trigger_task` (L377-L385)

```python
config = AzurLaneConfig(inst)
config.cross_set(f"{task}.Scheduler.Enable", True)
now = current_time()  # 统一时间源 module.config.time_source.now（导入别名 current_time）
config.cross_set(f"{task}.Scheduler.NextRun", str(now))
config.save()
```

- **功能**: 强制将指定任务加入队列并立即执行
- **实现**: 启用任务调度器 + 设置 NextRun 为当前时间

#### `clear_scheduler_queue` (L388-L399)

```python
config = AzurLaneConfig(inst)
cleared = []
for task_name in config.data:
    scheduler = config.data.get(task_name, {}).get("Scheduler", {})
    if scheduler.get("Enable", False):
        config.cross_set(f"{task_name}.Scheduler.Enable", False)
        cleared.append(task_name)
if cleared:
    config.save()
```

- **功能**: 清空所有已启用任务的队列
- **实现**: 遍历所有任务，禁用 Scheduler.Enable
- **返回**: 被清除的任务列表

#### `restart_emulator` (L402-L421)

```python
config = AzurLaneConfig(inst)
device = Device(config)
device.emulator_stop()
time.sleep(60)
device.emulator_start()
```

- **功能**: 重启模拟器
- **流程**: 停止 -> 等待 60 秒 -> 启动
- **注意**: 使用 `time.sleep(60)` 阻塞当前线程（在 async 函数中调用同步阻塞操作）
- **性能问题**: 60 秒阻塞可能影响 MCP 服务器响应其他请求

#### `restart_adb` (L424-L450)

```python
adb_path = State.deploy_config.AdbExecutable
# ... 搜索 ADB 路径 ...
subprocess.run([adb_path, "kill-server"], check=False)
subprocess.run([adb_path, "start-server"], check=False)
```

- **功能**: 重启 ADB 服务
- **ADB 路径搜索顺序**: deploy.yaml 配置 -> `.venv/Scripts/adb.exe` -> `.venv/bin/adb` -> `./bin/adb/adb.exe` -> `adb` (PATH)
- **实现**: kill-server + start-server

#### `update_alas` (L453-L463)

```python
from module.webui.updater import updater
def do_update():
    updater.update()
threading.Thread(target=do_update).start()
```

- **功能**: 在后台线程中触发 AzurPilot 更新
- **实现**: 启动独立线程执行 `updater.update()`
- **返回**: 立即返回成功消息（不等待更新完成）

### 4.2 错误处理 (L495-L497)

```python
except Exception as e:
    logger.exception(f"Tool {name} error")
    return [TextContent(type="text", text=f"Error: {str(e)}")]
```

所有工具调用的外层错误处理，记录异常日志并返回错误文本。

---

## 5. SSE 传输层与鉴权 (L500-L689)

### 5.1 SSE 传输初始化 (L501)

```python
transport = SseServerTransport("/mcp/messages")

STANDALONE_HOST = "0.0.0.0"
STANDALONE_PORT = 22268
SESSION_ID_PATTERN = re.compile(rb"session_id=([0-9a-fA-F]{32})")
SNIFF_BUFFER_LIMIT = 4096
```

创建 SSE 传输实例，消息端点路径为 `/mcp/messages`；同时定义独立运行时的监听地址、端口，以及从 SSE 出站流中提取 `session_id` 的正则与缓冲区上限。

### 5.2 `configure_auth(key, public_bind)` 鉴权注入 (L522-L537)

```python
def configure_auth(key, public_bind=False):
    mcp_auth.install_access_log_filter()
    mcp_auth.configure(key, public_bind=public_bind)
    logger.info("[MCP] 鉴权%s，监听公网=%s" % (...))
```

鉴权的唯一入口，由两个调用方使用：

| 调用方 | 时机 | `public_bind` |
|---|---|---|
| `module/webui/app.py` (L380-L387) | 挂载 `/mcp` 之前，注入 app 工厂已解析好的 `key` | 由 `State.webui_host` / `DeployConfig.WebuiHost` 判定 |
| `__main__` (L726-L730) | 独立启动时 | 恒为 `True` |

具体判定逻辑全部集中在 `module/webui/mcp_auth.py` 的 `authorize()`，ASGI 层只做转发。

### 5.3 `_sniff_session_id` 会话捕获 (L540-L563)

```python
def _sniff_session_id(message, buffer, captured):
    if captured or message.get("type") != "http.response.body":
        return
    buffer[0] = (buffer[0] + body)[-SNIFF_BUFFER_LIMIT:]
    match = SESSION_ID_PATTERN.search(buffer[0])
    ...
    mcp_auth.register_session(session_id)
```

MCP 的 `endpoint` 事件会把带 `session_id` 的 POST 地址下发给客户端，客户端后续的 POST 只能填这个 URL、带不上请求头。因此把「由已鉴权 SSE 通道下发的 `session_id`」当作一次性凭据登记，支撑只能填 URL 的客户端。

- 通过包装 `send` 嗅探**出站**字节流，不触碰 `transport._read_stream_writers` 私有字典（该字典在第三方实现中从不清理，读取它会产生并发竞态，并让陈旧会话永久有效）；
- 带 4096 字节滚动缓冲，不假设 SSE 分块边界；
- 收到第一个 `session_id` 即停止嗅探（`captured` 非空直接返回）。

### 5.4 `_run_sse` SSE 连接 (L566-L587)

```python
async def _run_sse(scope, receive, send):
    captured, buffer = [], [b""]

    async def send_wrapper(message):
        _sniff_session_id(message, buffer, captured)
        await send(message)

    try:
        async with transport.connect_sse(scope, receive, send_wrapper) as (read_stream, write_stream):
            try:
                options = mcp_server.create_initialization_options()
                await mcp_server.run(read_stream, write_stream, options)
            except Exception as e:
                logger.error(f"MCP Server Loop Error: {e}", exc_info=True)
    finally:
        for session_id in captured:
            mcp_auth.expire_session(session_id)
```

1. 建立 SSE 连接，获取读写流（`send` 被包装用于嗅探）
2. 创建 MCP 初始化选项
3. 运行 MCP 服务器循环（阻塞直到连接关闭）
4. `finally` 中把会话转入 60 秒宽限期，避免客户端最后一帧 POST 被误拒

### 5.5 POST 消息处理 (L590-L609)

```python
def _is_mcp_client_disconnected(error: Exception) -> bool:
    return (
        "BrokenResourceError" in str(type(error))
        or "BrokenPipeError" in str(error)
        or "ClosedResourceError" in str(type(error))
    )
```

区分客户端断开连接（警告）和其他错误（记录完整堆栈）。`ClosedResourceError` 对应「SSE 已断开但客户端仍在宽限期内投递消息」，属正常现象，不应记为错误。

### 5.6 `mcp_asgi_app` ASGI 应用 (L653-L689)

```python
async def mcp_asgi_app(scope, receive, send):
```

**纯 ASGI 应用，先鉴权再路由。**

- **参数**: 标准 ASGI 接口 (`scope`, `receive`, `send`)
- **处理顺序**:

| 步骤 | 处理 | 说明 |
|---|---|---|
| 1 | `scope["type"] != "http"` → 直接返回 | 放行 lifespan / websocket 等非 HTTP 作用域 |
| 2 | 记录 `[MCP] {method} {path}?{query}` | 经 `mcp_auth.redact()` 脱敏后再落日志 |
| 3 | `mcp_auth.authorize(...)` | 不通过则 `_send_denied()` 返回 401 / 405 / 503 |
| 4 | `path.endswith("/sse")` | `_run_sse()` 建立 SSE 连接，运行 MCP 服务器循环 |
| 5 | `path.endswith("/messages")` 或 `"/messages/"` | `_handle_mcp_post()` 处理客户端 POST |
| 6 | 其他 | `_send_not_found()` 返回 404 |

鉴权层**只读 `scope["headers"]` / `scope["query_string"]`，绝不构造 Starlette `Request` 读 body**——`handle_post_message` 自己要 `await request.body()`，提前读会消费掉 `receive`。`query_string` 按 UTF-8 解码、失败退回 latin-1，避免非法字节触发 500。

### 5.7 `_send_denied` 拒绝响应 (L625-L650)

```python
await send({'type': 'http.response.start', 'status': status, 'headers': [...]})
```

- 响应体取自 `DENIED_MESSAGES`（401 / 405 / 503 各自的中文提示）
- 记录拒绝日志（含客户端 IP）
- **刻意不返回 `WWW-Authenticate`**：MCP 客户端会把该响应头判定为「本服务要求 OAuth」，转去请求 resource metadata；503 同理只回纯文本

---

## 6. Starlette 应用包装 (L691-L697)

```python
app = Starlette(
    middleware=[
        Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    ]
)
app.mount("/", mcp_asgi_app)
```

- **CORS 配置**: 完全开放（`allow_origins=["*"]`），允许所有来源、方法和头部。保持不动是有意为之：浏览器端 MCP 客户端依赖它，鉴权才是安全边界。CORS 预检（`OPTIONS` + `Access-Control-Request-Method`）会在 `CORSMiddleware` 内部短路，不会走到 `mcp_asgi_app`，因此不会被鉴权误拦。
- **路由**: 根路径 `/` 挂载 MCP ASGI 应用
- **用途**: 可被 `gui.py` 中的 uvicorn 通过 `app.mount("/mcp", mcp_app)` 挂载到主 WebUI 应用

---

## 7. `__main__` 入口 (L699-L731)

```python
def _resolve_standalone_password():
    from module.webui.password_utils import ensure_password_for_host, is_demo_mode

    password = State.deploy_config.Password
    ...
    if password and password != State.deploy_config.Password:
        State.deploy_config.Password = password
    return password


if __name__ == "__main__":
    import uvicorn
    logger.info(f"[MCP] 启动 AzurPilot MCP 服务 (Port: {STANDALONE_PORT})")
    configure_auth(_resolve_standalone_password(), public_bind=True)
    uvicorn.run(app, host=STANDALONE_HOST, port=STANDALONE_PORT)
```

- **独立运行模式**: 直接在 `0.0.0.0:22268` 启动 MCP 服务器
- **密码解析顺序**: `deploy.yaml` 的 `Password` → 未设置且监听公网时自动生成 32 位随机密码并写入根目录 `password.txt`（同时回写部署配置，避免每次重启换密码）。与 WebUI 复用同一份 `module/webui/password_utils.py` 策略，不另造一套。
- **与 gui.py 的关系**: 可独立运行，也可被 gui.py 挂载到 `/mcp` 路径下

---

## 8. 数据结构分析

### 8.1 MCP Tool 结构

```python
Tool(
    name="tool_name",           # 工具名称
    description="描述",          # 工具描述
    inputSchema={               # JSON Schema
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "参数描述"}
        },
        "required": ["param"]
    }
)
```

### 8.2 MCP 响应结构

```python
# 文本响应
TextContent(type="text", text="响应内容")

# 图像响应
ImageContent(type="image", data="base64编码数据", mimeType="image/jpeg")
```

### 8.3 工具返回数据结构示例

```python
# list_instances
["alas", "alas2"]

# get_status
[{"instance": "alas", "running": true, "state": 2}]

# get_task_help
{
    "task_name": "Research",
    "display_name": "科研",
    "help": "...",
    "groups": {
        "Scheduler": {
            "display_name": "调度器",
            "help": "...",
            "arguments": {
                "Enable": {
                    "display_name": "启用",
                    "help": "...",
                    "type": "toggle",
                    "default": true,
                    "options": null
                }
            }
        }
    }
}

# get_scheduler_queue
[{"task": "Commission", "next_run": "2025-01-01 00:00:00"}, ...]
```

---

## 9. 模块内部调用关系

```
mcp_server_sse.py
  │
  ├── MCP Server (mcp.server.Server)
  │   ├── list_tools() -> List[Tool]          # 工具注册
  │   └── call_tool() -> ToolResponse       # 工具调用分发（TOOL_HANDLERS 查表）
  │
  ├── SseServerTransport
  │   ├── connect_sse() -> (read_stream, write_stream)
  │   └── handle_post_message()
  │
  ├── McpConfigHelper (module.config.mcp_helper)
  │   ├── get_tasks() -> List[str]
  │   ├── get_task_details(task_name) -> Dict
  │   └── get_dashboard_resources(config_data) -> Dict
  │
  ├── AzurLaneConfig (module.config.config)
  │   ├── data: Dict                          # 原始配置数据
  │   ├── cross_set(path, value)              # 设置配置值
  │   └── save()                              # 保存到磁盘
  │
  ├── ProcessManager (module.webui.process_manager)
  │   ├── get_manager(inst) -> ProcessManager
  │   ├── alive: bool
  │   ├── state: int
  │   ├── start(func)
  │   └── stop()
  │
  ├── Device (module.device.device)           # 惰性加载
  │   ├── screenshot() -> numpy.ndarray
  │   ├── emulator_stop()
  │   └── emulator_start()
  │
  ├── mcp_auth (module.webui.mcp_auth)         # 纯标准库
  │   ├── configure(key, public_bind)
  │   ├── authorize(path, method, headers, query_string) -> (allowed, status)
  │   ├── register_session(id) / expire_session(id) / is_authorized_session(id)
  │   ├── redact(text)
  │   └── install_access_log_filter()
  │
  ├── password_utils (module.webui.password_utils)   # 惰性，纯标准库
  │   └── ensure_password_for_host(key, host, demo)
  │
  ├── State (module.webui.setting)
  │   ├── deploy_config.AdbExecutable
  │   └── deploy_config.Password             # 独立模式的密码来源
  │
  └── Starlette + CORSMiddleware
      └── mcp_asgi_app (ASGI) -> authorize() -> _run_sse / _handle_mcp_post
```

---

## 10. 设计模式与架构分析

### 10.1 设计模式

| 模式 | 应用位置 | 说明 |
|---|---|---|
| **注册模式** | `@mcp_server.list_tools()` | 装饰器注册工具列表 |
| **分发模式** | `TOOL_HANDLERS` 字典 | 工具名 → `_tool_*` 实现函数映射分发 |
| **传输抽象** | `SseServerTransport` | SSE 传输层抽象 |
| **ASGI 组合** | `app.mount("/", mcp_asgi_app)` | Starlette 应用组合 |
| **惰性加载** | `Device` 和 `remove_fake_pil_module` | 按需导入重模块 |

### 10.2 架构风格

- **MCP 协议**: 基于 JSON-RPC 的工具调用协议，通过 SSE 传输
- **双模式运行**: 可独立运行（端口 22268）或被 gui.py 挂载（`/mcp` 路径）
- **无状态设计**: 每次工具调用独立，不维护客户端会话状态；仅有的进程内可变状态是 `mcp_auth` 的会话登记表（`threading.Lock` 保护，TTL + 容量上限）
- **异步优先**: 所有工具处理器都是 `async` 函数

---

## 11. 性能分析

### 11.1 性能瓶颈

| 位置 | 瓶颈 | 原因 | 影响 |
|---|---|---|---|
| `get_screenshot` | ~500ms+ | ADB 截图 + 图像编码 | 每次调用创建新 Device |
| `restart_emulator` | 60 秒 | `time.sleep(60)` 阻塞 | 阻塞事件循环 |
| `get_recent_logs` | 文件 I/O | 读取整个日志文件 | 大文件性能差 |
| `get_current_running_task` | 文件 I/O | 读取整个日志文件 + 正则匹配 | 大文件性能差 |
| `update_alas` | 后台线程 | Git 操作 | 不阻塞但资源竞争 |

### 11.2 优化建议

| 问题 | 建议 |
|---|---|
| `get_screenshot` 每次创建 Device | 缓存 Device 实例或使用连接池 |
| `restart_emulator` 阻塞 60 秒 | 使用 `asyncio.sleep()` 替代 `time.sleep()` |
| `get_recent_logs` 读取整个文件 | 使用文件尾部读取（`tail` 逻辑） |

### 11.3 并发考虑

- **SSE 连接**: 每个客户端一个长连接，`mcp_server.run()` 阻塞直到连接关闭
- **工具调用**: MCP 协议保证同一连接上的请求顺序处理
- **阻塞操作**: `restart_emulator` 的 60 秒 `time.sleep()` 会阻塞当前 SSE 连接的消息处理

---

## 12. 安全性分析

### 12.1 鉴权机制（2026-09-11 新增）

MCP 的 18 个工具里有 `stop_instance`、`update_config`、`clear_scheduler_queue`、
`restart_emulator`、`update_alas`（git pull）等破坏性操作，原先整条链路无任何鉴权。
WebUI 的密码校验发生在 PyWebIO 会话内部（`module/webui/utils.py` 的 `login()`），
属于页面层，**管不到挂载的 ASGI 子应用**，所以鉴权必须做在 MCP ASGI 应用自己这一层。

| 项目 | 设计 |
|---|---|
| 密钥来源 | **复用 WebUI 密码**（`--key` / `config/deploy.yaml` 的 `Password`），不引入第二把密钥 |
| 未配置密码时 | 沿用 WebUI 的自动生成机制（监听公网 → 生成 32 位随机密码 → 写根目录 `password.txt` → 回写 `deploy.yaml`） |
| 凭据传递 | ① `Authorization: Bearer <密码>` ② `X-API-Key: <密码>` ③ 查询参数 `?key=` / `?api_key=` / `?token=`（取第一个） |
| URL-only 客户端 | SSE 的 `endpoint` 事件下发的 `session_id` 视为该次已鉴权连接的凭据，供 POST `/messages` 兜底 |
| 比较方式 | `secrets.compare_digest`，比较前先 `encode("utf-8")`（CPython 对含非 ASCII 的 `str` 会抛 `TypeError`），并 `except (TypeError, UnicodeError)` 判否 |
| 方法白名单 | `/sse` 只允许 GET，`/messages` 只允许 POST，其余 405 |
| fail-closed | 密码为空且监听公网 → 全部请求 503（只可能出现在 `DEMO=1` 或自动生成失败时） |
| 未配置密码 + 仅回环 | 放行，与 WebUI 自身的暴露面一致 |
| 改密码 | 需重启 WebUI 才生效（与 WebUI 登录行为一致，`key` 在 app 工厂时捕获） |

实现位置为 `module/webui/mcp_auth.py`（纯标准库，可独立单测），全部判定集中在
`authorize(path, method, headers, query_string) -> (allowed, status)`，ASGI 层只做转发。
会话登记表用 `time.monotonic()` 滑动续期（TTL 12h、断开宽限 60s、容量 512 FIFO 淘汰）。

**日志脱敏**：选了 `?key=` 传参后，日志本身就会变成可用凭据，因此
`mcp_auth.redact()` 会抹掉 `key=` / `api_key=` / `token=` / `password=` / `session_id=`
的值与 `Bearer xxx`；`_RedactFilter` 挂到 `uvicorn.access` logger 上覆盖访问日志。
该过滤器**必须保持 `record.args` 的结构**——uvicorn 的 `AccessFormatter` 会把访问日志
参数解包成 `(client_addr, method, full_path, http_version, status_code)` 五元组，
清空或替换结构会让日志格式化直接报错。

### 12.2 已实现的安全措施

| 措施 | 位置 | 说明 |
|---|---|---|
| 请求鉴权 | `mcp_asgi_app` (L674-L679) + `mcp_auth.authorize` | 无有效凭据一律 401；方法白名单 405；fail-closed 503 |
| 会话绑定 | `_sniff_session_id` (L540-L563) | 只有经已鉴权 SSE 通道下发的 `session_id` 才能免头 POST |
| 日志脱敏 | `mcp_auth.redact` / `_RedactFilter` | 出站日志与 uvicorn access log 中的凭据全部替换为 `***` |
| 拒绝不误导 | `_send_denied` (L625-L650) | 不返回 `WWW-Authenticate`，避免 MCP 客户端转去走 OAuth 发现流程 |
| CORS 中间件 | L691-L697 | 配置跨域访问策略（保持全开，见 §6） |
| 异常信息截断 | L497 | 返回 `str(e)` 而非完整堆栈 |
| 日志记录 | L496 | `logger.exception()` 记录完整异常 |
| 错误隔离 | L495-L497 | 工具调用异常不影响服务器运行 |

### 12.3 剩余安全风险

| 风险 | 位置 | 严重程度 | 说明 |
|---|---|---|---|
| CORS 完全开放 | L694 | **中** | `allow_origins=["*"]` 允许任何来源访问；鉴权已挡住未授权调用，此项降级为纵深防御问题 |
| `update_config` 可修改任意配置 | L242-L253 | **中** | 可修改服务器等敏感配置；密码本身在 `deploy.yaml` 而非实例配置中，不受影响 |
| `start_instance` / `stop_instance` | L282-L299 | **中** | 已需凭据，可远程启停进程 |
| `restart_emulator` | L403-L422 | **中** | 已需凭据，可远程重启模拟器 |
| `update_alas` | L454-L465 | **中** | 已需凭据，可触发代码更新 |
| 主 WebUI 其余端点无鉴权 | `module/webui/app.py` | **中** | `/api/notify*`、`/obs`、`/ws/live_screenshot` 等同样未鉴权，属同一条安全债，不在本次 MCP 鉴权范围内 |
| `?key=` 使 URL 即凭据 | `mcp_auth.extract_credential` | **低** | 兼容只能填 URL 的客户端的必要代价；浏览器历史、代理日志、截图均可能泄漏，文档已提示优先用请求头 |
| `restart_adb` 子进程执行 | L447-L448 | **低** | `subprocess.run()` 但参数受控 |
| 环境变量注入 | L303-L304 | **低** | 写入 `ALAS_CONFIG_NAME` 环境变量 |
| 独立模式端口与 OCR 撞车 | L505 / `deploy/config.py:41` | **低** | 22268 同时是 `OcrServerPort` 默认值，`module/ocr/rpc.py` 会绑 `tcp://*:22268`（pickle 且无鉴权）；同机运行时留意端口占用 |

### 12.4 安全建议

1. **限制 CORS**: 配置具体的允许来源（需先确认浏览器端 MCP 客户端的使用方式）
2. **操作审计**: 记录所有配置修改和敏感操作
3. **权限控制**: 区分只读和读写操作（如只读工具免鉴权、破坏性工具强制鉴权）
4. **输入验证**: 验证 `instance` 和 `task` 参数的有效性
5. **补齐其余端点**: 为 `/api/notify*`、`/obs`、`/ws/*` 等端点复用同一套 `mcp_auth` 判定
6. **失败限速**: 当前失败仅打 IP 日志，未做限速（32 位随机密码 + 常量时间比较已足够）

---

## 13. 代码质量评估

### 13.1 优点

1. **MCP 协议标准实现**: 遵循 MCP 规范，工具定义清晰
2. **完整的工具集**: 18 个工具覆盖实例管理、配置、监控、截图等
3. **错误隔离**: 工具调用异常不影响服务器运行
4. **双模式运行**: 支持独立运行和挂载模式
5. **类型注解**: 使用 `typing` 模块提供类型信息
6. **日志完善**: 请求和错误都有日志记录，且凭据经脱敏后落盘
7. **鉴权与业务解耦**: 判定逻辑集中在 `module/webui/mcp_auth.py` 的纯函数里，可独立单测，且不引入重依赖

### 13.2 问题与不足

1. **同步阻塞操作**: `restart_emulator` 中的 `time.sleep(60)` 在 async 函数中
2. **重复的实例化模式**: 多个工具重复 `AzurLaneConfig(inst)` + `Device(config)` 模式
3. **日志系统不一致**: 使用标准库 `logging` 而非项目的 `module.logger`
4. **注释混合语言**: 中英文注释混合

> 注：原 `call_tool()` 过长与 `if/elif` 分发链问题已通过 `TOOL_HANDLERS` 字典重构解决（L466-497）。

---

## 14. 潜在问题与改进建议

### 14.1 潜在 Bug

1. **`restart_emulator` 阻塞事件循环**: `time.sleep(60)` 会阻塞整个 SSE 连接的消息处理
2. **`get_screenshot` 环境变量泄漏**: 写入 `ALAS_CONFIG_NAME` 环境变量可能影响其他调用
3. **`get_recent_logs` 文件锁定**: 在 Windows 上可能与其他进程的日志写入冲突
4. **`update_config` 无验证**: 不验证配置路径和值的有效性

### 14.2 改进建议

1. **异步化阻塞操作**:
   ```python
   async def restart_emulator(self, inst):
       # ...
       await asyncio.sleep(60)  # 替代 time.sleep(60)
       # ...
   ```

2. **缓存 Device 实例**:
   ```python
   _device_cache: Dict[str, Device] = {}
   def get_device(inst: str) -> Device:
       if inst not in _device_cache:
           _device_cache[inst] = Device(AzurLaneConfig(inst))
       return _device_cache[inst]
   ```

3. **添加输入验证**:
   ```python
   def validate_instance(inst: str) -> bool:
       return inst in alas_instance()
   ```

4. **统一日志系统**: 使用项目的 `module.logger` 替代标准库 `logging`

5. ~~**添加 API 认证**~~: 已于 2026-09-11 实现（复用 WebUI 密码，见 §12.1）
