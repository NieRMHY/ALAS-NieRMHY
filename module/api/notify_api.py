"""任务推送通知的本地 HTTP 路由。

调度器侧（module/notify/notify.py 的 notify_webui）向 /api/notify 发 POST，
这里兵分两路：经 notify_hub 实时广播给已订阅的浏览器（弹 Windows 原生通知），
同时放进队列供 /api/notify_stream 以 SSE 供外部启动器订阅。
端点路径与报文格式是旧版 WebUI 传下来的对接面，外部启动器按它写死——改名即断连。
"""
import asyncio
import contextlib
import json

from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from module.runtime.launcher import is_local_request
from module.runtime.notify_hub import hub

#: 通知流空闲多久发一次保活帧（秒）。
STREAM_IDLE_TIMEOUT = 30

#: 待推送通知队列上限；启动器离线时丢弃最旧，防止无人消费无限堆积。
_NOTIFICATION_QUEUE_MAXSIZE = 100
_notification_queue: asyncio.Queue = asyncio.Queue(maxsize=_NOTIFICATION_QUEUE_MAXSIZE)


async def notify(request):
    """POST /api/notify — 接收调度器推送的通知，入队等待启动器取走。"""
    if not is_local_request(request):
        return JSONResponse({"success": False, "error": "通知接收只允许本机调用"}, status_code=403)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        # 浏览器跨站请求发不出 application/json（预检不会通过），据此阻断恶意网页伪造推送。
        return JSONResponse({"success": False, "error": "Content-Type 必须是 application/json"}, status_code=400)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "请求体不是有效 JSON"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"success": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    notification = {
        "instance": data.get("instance", ""),
        "title": data.get("title", ""),
        "content": data.get("content", ""),
    }
    if _notification_queue.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            _notification_queue.get_nowait()
    # 无 await 间隙，检查与写入不会和并发 POST 交错。
    _notification_queue.put_nowait(notification)
    hub.publish(notification)
    return JSONResponse({"success": True})


async def notify_stream(request):
    """GET /api/notify_stream — 启动器订阅的通知流（SSE）。"""
    if not is_local_request(request):
        return JSONResponse({"success": False, "error": "通知流只允许本机连接"}, status_code=403)

    async def events():
        while True:
            if await request.is_disconnected():
                break
            try:
                notification = await asyncio.wait_for(_notification_queue.get(), timeout=STREAM_IDLE_TIMEOUT)
                yield f"data: {json.dumps(notification, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def routes() -> list[Route]:
    """任务通知的本地回环路由。"""
    return [Route("/api/notify", notify, methods=["POST"]),
            Route("/api/notify_stream", notify_stream)]
