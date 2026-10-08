"""背景图代抓不得占用事件循环。"""
import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import httpx

from module.api.app import create_app
from tests.test_api import fixture


def test_background_media_keeps_event_loop_free():
    with tempfile.TemporaryDirectory(prefix='azurpilot-bg-async-') as directory:
        app = create_app(root=fixture(Path(directory)), password='', manage_runtime=False, mount_mcp=False)
        token = app.state.gateway.router.background_token

        async def scenario():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
                def slow_fetch(url):
                    """模拟一次耗时的外网抓取。"""
                    time.sleep(1.5)
                    return b'image-bytes', 'image/png'

                with patch('module.api.app.proxy_fetch', side_effect=slow_fetch):
                    # 先发起代抓，再量事件循环能否按时醒来。
                    media = asyncio.create_task(client.get(f'/api/v1/background/media?url=http://example.com/a.png&token={token}'))
                    started = time.perf_counter()
                    await asyncio.sleep(0.05)
                    delayed = (time.perf_counter() - started) * 1000
                    assert (await media).status_code == 200
                    return delayed
                    return health.status_code, blocked

        delayed = asyncio.run(scenario())
        assert delayed < 300, f'代抓期间事件循环被占住 {delayed:.0f}ms'
