"""AzurPilot MCP 服务入口。

提供 SSE（旧规范）与 streamable-http（新规范）双传输通道的 MCP 服务，
供大语言模型（如 Claude / ChatGPT）查询 AzurPilot 状态、任务列表、读写配置、
读取统计与截图，并在调度器停止后接管设备做坐标操作。

本地产线（Add by MHY）保留两条与上游不同的约定：
1. 不带访问密码，与 WebUI 一致直接进入，不引入 ``module/runtime/mcp_auth``；
2. 默认端点在 ``azurpilot_`` 工具之外同时登记 18 个旧名称，因为现有客户端仍按
   旧名称调用，旧名称的文本输出由 ``module/mcp/legacy.py`` 还原。
"""

import asyncio
import contextlib
import logging
from contextvars import ContextVar
from typing import Any, Dict, List

# Modify by MHY, 本地保留自己的 ASGI 双传输实现（上游只走 create_app + 密码鉴权）
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import CallToolResult, Tool

from module.mcp.lifecycle import lifespan
from module.mcp.tools import Tools


# 初始化日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("azurpilot-mcp")

# 每个挂载应用独享服务适配器，通过请求上下文传递。
active_tools = ContextVar("mcp_tools", default=Tools(allow_legacy=True))

# 初始化 MCP 服务器
mcp_server = Server("AzurPilot-MCP")

ToolResponse = CallToolResult


@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    """按当前端点的固定注册表列出工具；本地产线默认包含旧名称。"""
    return active_tools.get().definitions()


@mcp_server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: Dict[str, Any]) -> ToolResponse:
    """经统一适配层校验并调用工具，保留结构化错误与 isError。"""
    return await active_tools.get().call(name, arguments)


# SSE 传输层初始化 - 固定端点（与 /mcp 挂载点匹配）
transport = SseServerTransport("/mcp/messages")

# 独立运行时的监听地址与端口
STANDALONE_HOST = "0.0.0.0"
STANDALONE_PORT = 22268


async def _run_sse(scope, receive, send):
    """处理 /sse 端点的请求，建立并运行 SSE 流式连接。

    Args:
        scope: ASGI scope 字典。
        receive: ASGI receive 异步可调用对象。
        send: ASGI send 异步可调用对象。
    """
    logger.info("Matched endpoint: /sse. Opening SSE connection...")

    try:
        async with transport.connect_sse(scope, receive, send) as (read_stream, write_stream):
            logger.info("SSE Stream connected. Running MCP server loop...")
            try:
                options = mcp_server.create_initialization_options()
                await mcp_server.run(read_stream, write_stream, options)
            except Exception as e:
                logger.error(f"MCP Server Loop Error: {e}", exc_info=True)
            logger.info("MCP Server Loop exited.")
    finally:
        pass


def _is_mcp_client_disconnected(error: Exception) -> bool:
    """判断异常是否属于客户端主动断开连接。

    ClosedResourceError：SSE 已断开但客户端仍在宽限期内投递消息，属正常现象。

    Args:
        error (Exception): 捕获的异常对象。

    Returns:
        bool: 是否属于客户端正常断连。
    """
    return (
        "BrokenResourceError" in str(type(error))
        or "BrokenPipeError" in str(error)
        or "ClosedResourceError" in str(type(error))
    )


async def _handle_mcp_post(scope, receive, send, method):
    """处理客户端通过 POST /messages 发送过来的消息。

    Args:
        scope: ASGI scope 字典。
        receive: ASGI receive 异步可调用对象。
        send: ASGI send 异步可调用对象。
        method (str): HTTP 请求方法。
    """
    logger.info(f"Matched endpoint: /messages. Method: {method}")
    try:
        await transport.handle_post_message(scope, receive, send)
        logger.info("MCP Message POST handled.")
    except Exception as e:
        # 捕获常见的断开连接错误，避免服务器崩溃
        if _is_mcp_client_disconnected(e):
            logger.warning("MCP client disconnected during POST message.")
        else:
            logger.error(f"Error handling MCP message: {e}", exc_info=True)


async def _send_not_found(send):
    """返回 404 Not Found 响应。

    Args:
        send: ASGI send 异步可调用对象。
    """
    await send({
        'type': 'http.response.start',
        'status': 404,
        'headers': [[b'content-type', b'text/plain']]
    })
    await send({
        'type': 'http.response.body',
        'body': b'Not Found'
    })


async def mcp_asgi_app(scope, receive, send):
    """MCP 服务的纯 ASGI 应用：SSE（旧规范）与 streamable-http（新规范）双传输。"""
    path = scope.get("path", "")
    method = scope.get("method", "")

    if scope["type"] != "http":
        return

    logger.info("[MCP] %s %s", method, path)

    # Add by MHY, streamable-http（新 MCP 规范，单端点 POST）：挂载根路径的
    # POST/GET/DELETE 交给 streamable manager——dsh-mcp-client 等只讲新规范的
    # 客户端经 /mcp 根直连；SSE 旧规范路径（/sse + /messages）保持不变
    if path.endswith("/sse"):
        await _run_sse(scope, receive, send)

    elif path.endswith("/messages") or path.endswith("/messages/"):
        await _handle_mcp_post(scope, receive, send, method)

    else:
        await _run_streamable(scope, receive, send, method)


# Add by MHY, streamable-http 传输管理器：与 SSE 共用同一个 mcp_server 实例，
# 工具注册一次两种传输都可调用
_streamable_manager = None
_streamable_task = None
_streamable_loop = None
_streamable_ready = None


def _new_streamable_manager():
    """创建一个未启动的 streamable manager；每个事件循环必须独占一个实例。"""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    return StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=False,
        stateless=True,
    )


def _get_streamable_manager():
    global _streamable_manager
    if _streamable_manager is None:
        _streamable_manager = _new_streamable_manager()
    return _streamable_manager


async def _start_streamable():
    """确保当前事件循环里的 streamable manager 已进入运行态。

    WebUI 以 Mount('/mcp') 直接挂载本模块的 ASGI 函数，不会执行子应用的
    lifespan；此时若不在这里补启动，handle_request 会以 Task group is not
    initialized 失败。已在运行的循环直接复用。
    """
    global _streamable_manager, _streamable_task, _streamable_loop, _streamable_ready
    loop = asyncio.get_running_loop()
    if _streamable_task is not None and not _streamable_task.done() and _streamable_loop is loop:
        return
    # manager.run() 只能进入一次；换事件循环（测试客户端、重启用例）时重建实例。
    _streamable_manager = _new_streamable_manager()
    manager = _streamable_manager

    async def serve():
        async with manager.run():
            _streamable_ready.set()
            # 一直持有 task group，直到服务关闭时被取消。
            await loop.create_future()

    _streamable_ready = asyncio.Event()
    _streamable_loop = loop
    _streamable_task = asyncio.create_task(serve(), name='mcp-streamable')
    await _streamable_ready.wait()


async def _stop_streamable():
    """取消 streamable manager 的后台任务，关闭 task group。"""
    global _streamable_manager, _streamable_task, _streamable_loop
    task, _streamable_task, _streamable_loop = _streamable_task, None, None
    if task is None or task.done():
        _streamable_manager = None
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    _streamable_manager = None


async def _run_streamable(scope, receive, send, method):
    """streamable-http 入口：POST（消息）/ GET（SSE 流可选）/ DELETE（会话终结）。"""
    if method not in ("POST", "GET", "DELETE"):
        await _send_not_found(send)
        return
    try:
        await _start_streamable()
        await _get_streamable_manager().handle_request(scope, receive, send)
    except Exception:
        logger.exception("[MCP] streamable-http 处理异常")
        try:
            await _send_not_found(send)
        except Exception:
            pass


def _app_lifespan(manage_runtime):
    """组合应用生命周期：先启动 streamable manager，再按需管理共享运行时。"""

    @contextlib.asynccontextmanager
    async def combined(application):
        await _start_streamable()
        try:
            if manage_runtime:
                async with lifespan(application):
                    yield
            else:
                yield
        finally:
            await _stop_streamable()

    return combined


def create_app(configs=None, runtime=None, *, manage_runtime=True, legacy=True):
    """创建 Starlette 应用实例。

    独立模式管理 State；挂载模式复用宿主注入的服务与生命周期。

    Args:
        configs: 配置服务实例，默认为 None（按需惰性创建）。
        runtime: 运行时服务实例，默认为 None（按需惰性创建）。
        manage_runtime (bool, optional): 是否由本应用接管生命周期。默认为 True。
        legacy (bool, optional): 是否登记旧工具名。默认为 True——
            Add by MHY, 本地产线的现有客户端仍调用旧名称，默认端点必须可发现可调用；
            需要纯 ``azurpilot_`` 目录时显式传 legacy=False。

    Returns:
        Starlette: 已配置好的 ASGI Starlette 应用。
    """
    tools = Tools(configs, runtime, allow_legacy=legacy)

    async def bound_app(scope, receive, send):
        token = active_tools.set(tools)
        try:
            await mcp_asgi_app(scope, receive, send)
        finally:
            active_tools.reset(token)

    application = Starlette(
        lifespan=_app_lifespan(manage_runtime),
        middleware=[Middleware(CORSMiddleware, allow_origins=["*"],
                               allow_methods=["*"], allow_headers=["*"])],
    )
    application.state.tools = tools
    application.mount("/", bound_app)
    return application


def create_modern_app(configs=None, runtime=None, *, manage_runtime=True):
    """只登记 ``azurpilot_`` 规范名称的端点，供新客户端使用。"""
    return create_app(configs, runtime, manage_runtime=manage_runtime, legacy=False)


# 独立与挂载都使用同一份默认端点：旧名称 + 新规范名称并存。
app = create_app()

if __name__ == "__main__":
    import uvicorn
    logger.info(f"[MCP] 启动 AzurPilot MCP 服务 (Port: {STANDALONE_PORT})")
    uvicorn.run(app, host=STANDALONE_HOST, port=STANDALONE_PORT)
