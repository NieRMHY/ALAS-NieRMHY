"""Starlette 应用工厂：静态 React 页面与同源 WebSocket。"""
import argparse
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from module.api.config_service import ConfigService, ROOT
from module.api.router import Router
from module.api.runtime_service import RuntimeService
from module.api.socket import Gateway
from module.api.static import FrontendFiles
from module.logger import logger
from module.runtime.password_utils import ensure_password_for_host, is_demo_mode
from module.runtime.setting import State


def create_app(*, root: Path = ROOT, password=None, manage_runtime=True, mount_mcp=True):
    """创建应用；测试可以关闭真实进程生命周期并使用临时配置目录。"""
    configs = ConfigService(root)
    runtime = RuntimeService(configs)
    mcp_app = None
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('-k', '--key')
    parser.add_argument('--run', nargs='+')
    args, _ = parser.parse_known_args()
    if password is None:
        key = args.key or State.deploy_config.Password
        host = State.webui_host or State.deploy_config.WebuiHost
        password = ensure_password_for_host(key, host, demo=is_demo_mode())
        if password and password != key:
            State.deploy_config.Password = password
    gateway = Gateway(Router(configs, runtime), password)

    @asynccontextmanager
    async def lifespan(application):
        try:
            if manage_runtime:
                from module.api.lifecycle import startup
                from module.runtime.deploy_settings import parse_run_config
                from module.runtime.startup_memory import consume_update_restart, startup_runs
                update_restart = consume_update_restart()
                runs = args.run or parse_run_config(State.deploy_config.Run)
                if not args.run:
                    # --run 是显式清单，不叠加记忆。
                    runs = startup_runs(runs, update_restart=update_restart)
                await asyncio.to_thread(startup, runs)
                if State.deploy_config.DiscordRichPresence:
                    try:
                        from module.runtime.discord_presence import init_discord_rpc
                        init_discord_rpc()
                    except Exception:
                        logger.exception('Discord RPC 启动失败，继续运行 WebUI')
            yield
        finally:
            try:
                # 先禁止 MCP 新操作并等待在途操作结束，再回收共享运行时。
                if mcp_app is not None:
                    await mcp_app.state.tools.close()
            finally:
                if manage_runtime:
                    try:
                        from module.runtime.discord_presence import async_close_discord_rpc
                        await async_close_discord_rpc()
                    except Exception:
                        logger.exception('Discord RPC 清理失败，继续回收共享运行时')
                    finally:
                        from module.api.lifecycle import clearup
                        await asyncio.to_thread(clearup)

    dist = root / 'frontend/dist'

    async def index(request):
        if (dist / 'index.html').is_file():
            return FileResponse(dist / 'index.html', headers={'Cache-Control': 'no-cache'})
        return PlainTextResponse('前端尚未构建，请在 frontend 目录运行 npm ci 和 npm run build。', status_code=503)

    async def health(request):
        return JSONResponse({'status': 'ok', 'protocolVersion': 1})

    async def meowfficer_score_report(request):
        """指挥喵评分报告（自包含 HTML），供浏览器直接打开查看。"""
        path = root / 'log' / 'meowfficer_score.html'
        if not path.is_file():
            return PlainTextResponse('评分报告尚未生成，请先运行「指挥喵评分」任务。', status_code=404)
        return FileResponse(path, media_type='text/html', headers={'Cache-Control': 'no-cache'})

    routes = [Route('/healthz', health),
              Route('/reports/meowfficer_score', meowfficer_score_report),
              WebSocketRoute('/api/v1/ws', gateway.endpoint)]
    if (dist / 'assets').is_dir():
        routes.append(Mount('/assets', StaticFiles(directory=dist / 'assets')))
    if mount_mcp:
        # Modify by MHY, 本地保留 MCP 旧版免密 ASGI 应用（上游为 create_app 工厂+鉴权），
        # 直接挂载模块级应用，不做密码注入
        from mcp_server_sse import mcp_asgi_app
        routes.append(Mount('/mcp', mcp_asgi_app))
    if (dist / 'index.html').is_file():
        routes.append(Mount('/', FrontendFiles(directory=dist)))
    else:
        routes.append(Route('/{path:path}', index))
    application = Starlette(routes=routes, lifespan=lifespan)
    application.state.gateway = gateway
    return application
