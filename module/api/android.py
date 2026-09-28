"""Android 宿主本机控制接口模块。

为 Android 宿主环境提供回环控制接口，调度器仍由 WebUI 的 ProcessManager 独占管理。
"""

import asyncio
import json
import os
import secrets
import socket
import threading
from urllib.request import urlopen

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from module.api.protocol import ApiError
from module.runtime.process_manager import ProcessManager

TOOLS = {'daemon': 'Daemon', 'event_story': 'EventStory'}
_operation_lock = threading.RLock()


def _local(request):
    """校验请求是否来自本地回环地址且携带有效的安全令牌。

    Args:
        request: Starlette HTTP 请求对象。

    Returns:
        bool: 请求合法返回 True，否则返回 False。
    """
    token = os.environ.get('AZURPILOT_ANDROID_TOKEN', '')
    supplied = request.headers.get('x-azurpilot-android-token', '')
    return (request.client and request.client.host in ('127.0.0.1', '::1')
            and bool(token) and secrets.compare_digest(supplied, token))


def _legacy_app_running():
    """检查旧版 ALAS-AOS 应用或服务是否正在运行。

    Returns:
        bool: 正在运行返回 True，未运行返回 False。
    """
    try:
        with socket.create_connection(('127.0.0.1', 22300), timeout=0.2):
            return True
    except OSError:
        pass
    try:
        with urlopen('http://127.0.0.1:22400/status', timeout=0.3) as response:
            state = json.load(response)
        return bool(state.get('runner_alive') or state.get('tool_alive'))
    except (OSError, ValueError):
        return False


def routes(configs, runtime):
    """创建 Android 专用的本地回环 HTTP 路由列表。

    仅在环境变量 AZURPILOT_ANDROID=1 时激活。

    Args:
        configs: 配置管理服务实例。
        runtime: 运行时管理服务实例。

    Returns:
        list[Route]: Starlette Route 列表。
    """
    if os.environ.get('AZURPILOT_ANDROID') != '1':
        return []

    def instance(request):
        """解析请求中的实例名称。"""
        name = request.query_params.get('config')
        if not name:
            name = next((key for key, proc in list(ProcessManager._processes.items()) if proc.alive), 'alas')
        configs.path(name)
        return name

    def manager(name):
        """获取指定实例的进程管理器。"""
        return ProcessManager._processes.get(name)

    def active_tool():
        """查找当前正在执行的工具任务及其所属实例。"""
        for name, proc in list(ProcessManager._processes.items()):
            if proc.alive and proc.started_func in TOOLS.values():
                return name, proc.started_func
        return None, None

    def status(request):
        """构建 Android 宿主所请求的实例状态字典。"""
        name = instance(request)
        proc = manager(name)
        tool_config, task = active_tool()
        running = proc is not None and proc.alive
        log_count = len(runtime.logs(name)['entries'])
        return {
            'runner_alive': bool(running and task is None),
            'pid': proc._process.pid if running and proc._process else None,
            'config': name if running else None,
            'gui_alive': True,
            'tool_alive': tool_config is not None,
            'tool_name': next((key for key, value in TOOLS.items() if value == task), None),
            'log_lines': log_count,
        }

    def execute(request):
        """处理启动/停止实例或工具任务的操作命令。"""
        with _operation_lock:
            name = instance(request)
            path = request.url.path
            if path.endswith('/start') and not path.endswith('/tool/start') and _legacy_app_running():
                raise ApiError('DEVICE_BUSY', 'ALAS-AOS 正在控制游戏，请先停止旧版任务')
            if path.endswith('/tool/start'):
                task = TOOLS.get(request.query_params.get('name'))
                if task is None:
                    raise ApiError('INVALID_PARAMS', '未知工具任务')
                if _legacy_app_running():
                    raise ApiError('DEVICE_BUSY', 'ALAS-AOS 正在控制游戏，请先停止旧版任务')
            else:
                task = None
            running = [key for key, proc in list(ProcessManager._processes.items()) if proc.alive]
            if path.endswith('/tool/stop'):
                tool_name, _ = active_tool()
                if tool_name:
                    runtime.stop(tool_name)
            elif path.endswith('/stop'):
                if name in running:
                    runtime.stop(name)
            else:
                if len(running) == 1 and running[0] == name and manager(name).started_func == (task or 'alas'):
                    return status(request)
                for key in running:
                    ProcessManager.get_manager(key).stop()
                runtime.start(name, task)
            return status(request)

    async def dispatch(request):
        """分派处理 Android 宿主 HTTP 请求。"""
        if not _local(request):
            return JSONResponse({'error': 'loopback only'}, status_code=403)
        path = request.url.path
        try:
            if path.endswith('/configs'):
                return JSONResponse({'configs': configs.names()})
            if path.endswith('/status'):
                return JSONResponse(await asyncio.to_thread(status, request))
            if path.endswith('/logs'):
                name = instance(request)
                count = min(max(int(request.query_params.get('tail', '80')), 0), 2000)
                data = await asyncio.to_thread(runtime.logs, name)
                return PlainTextResponse('\n'.join(entry['text'] for entry in data['entries'][-count:]))
            if request.method == 'POST':
                return JSONResponse(await asyncio.to_thread(execute, request))
        except (ApiError, ValueError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=400)
        return JSONResponse({'error': 'not found'}, status_code=404)

    return [Route('/android/status', dispatch), Route('/android/configs', dispatch),
            Route('/android/logs', dispatch), Route('/android/start', dispatch, methods=['POST']),
            Route('/android/stop', dispatch, methods=['POST']),
            Route('/android/tool/start', dispatch, methods=['POST']),
            Route('/android/tool/stop', dispatch, methods=['POST'])]
