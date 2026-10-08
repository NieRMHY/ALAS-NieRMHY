"""Discord Rich Presence 集成。

通过 pypresence 库连接 Discord RPC，展示 AzurPilot 的运行状态。
提供初始化和关闭接口，异步更新 Discord 状态信息。
"""
import asyncio
import time

from pypresence import AioPresence

from module.logger import logger

RPC: AioPresence | None = None
_connect_task: asyncio.Task | None = None
_close_task: asyncio.Task | None = None
_loop: asyncio.AbstractEventLoop | None = None
_CLOSE_TIMEOUT = 3


async def _close_writer(rpc: AioPresence):
    """在所属事件循环中关闭连接，兼容 Windows 的管道 transport。

    Args:
        rpc: AioPresence 实例。
    """
    writer = rpc.sock_writer
    if writer is None:
        return
    try:
        try:
            rpc.send_data(2, {'v': 1, 'client_id': rpc.client_id})
        finally:
            writer.close()
            wait_closed = getattr(writer, 'wait_closed', None)
            if wait_closed is not None:
                await asyncio.wait_for(wait_closed(), timeout=_CLOSE_TIMEOUT)
    except asyncio.CancelledError:
        # 若连接任务正在处理失败，关闭入口取消它后还需接手等待 writer。
        raise
    except Exception:
        logger.exception('Discord RPC 连接关闭失败')
    rpc.sock_writer = None


async def run(rpc: AioPresence):
    """运行 Discord RPC 状态更新后台协程。

    消费可选服务的连接异常，避免后台任务异常逃逸。

    Args:
        rpc: AioPresence 实例。
    """
    try:
        await rpc.connect()
        await rpc.update(state="AzurPilot is playing Azurlane", start=time.time(), large_image="alas")
    except Exception:
        logger.exception('Discord RPC 连接或状态更新失败')
        await _close_writer(rpc)


def init_discord_rpc() -> asyncio.Task | None:
    """在应用事件循环上初始化 Discord RPC 连接。

    仅初始化一次，并保留握手任务以便在关闭时安全回收。

    Returns:
        asyncio.Task | None: 启动的后台连接任务；失败时返回 None。
    """
    global RPC, _connect_task, _close_task, _loop
    if RPC is not None:
        return _connect_task
    try:
        loop = asyncio.get_running_loop()
        rpc = AioPresence("929437173764223057", loop=loop)
    except Exception:
        logger.exception('Discord RPC 初始化失败')
        return None
    RPC = rpc
    _loop = loop
    _close_task = None
    _connect_task = loop.create_task(run(rpc))
    return _connect_task


async def _close():
    """内部关闭实现，先终止握手或更新任务，再释放底层 socket/writer。"""
    global RPC, _connect_task, _loop
    rpc, connect_task = RPC, _connect_task
    try:
        if connect_task is not None:
            connect_task.cancel()
            try:
                await connect_task
            except asyncio.CancelledError:
                pass
        if rpc is not None:
            await _close_writer(rpc)
    finally:
        RPC = None
        _connect_task = None
        _loop = None


async def async_close_discord_rpc():
    """异步关闭 Discord RPC 连接。

    应用生命周期应等待此接口，确保退出前完成异步资源回收。
    """
    global _close_task
    if _loop is None:
        return
    if asyncio.get_running_loop() is not _loop:
        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(async_close_discord_rpc(), _loop))
        return
    if _close_task is None:
        _close_task = _loop.create_task(_close())
    await asyncio.shield(_close_task)


def close_discord_rpc():
    """兼容同步调用的关闭入口，将关闭操作派发到连接所属的事件循环。

    Returns:
        Any: 可等待的任务对象或 Future 对象；未初始化时返回 None。
    """
    loop = _loop
    if loop is None:
        return None
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    if current_loop is loop:
        return loop.create_task(async_close_discord_rpc())
    return asyncio.run_coroutine_threadsafe(async_close_discord_rpc(), loop)
