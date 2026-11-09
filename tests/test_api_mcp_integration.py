"""MCP 默认端点回归：双传输可达、旧工具名与新规范工具名并存，工具调用走真实协议。

Add by MHY, 覆盖独立工厂与 WebUI 挂载的真实协议，验证共享服务、传输生命周期、
关闭后的调用行为，以及旧名称的发现、调用与文本兼容。
"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

import mcp_server_sse as mcp
from module.api.config_service import ConfigService
from module.api.runtime_service import RuntimeService


INITIALIZE = {
    'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
    'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
               'clientInfo': {'name': 'test-client', 'version': '1.0'}},
}
HEADERS = {'Accept': 'application/json, text/event-stream',
           'Content-Type': 'application/json'}
LEGACY_NAMES = {
    'list_instances', 'get_status', 'list_tasks', 'get_task_help', 'get_resources',
    'get_config', 'update_config', 'get_recent_logs', 'start_instance', 'stop_instance',
    'get_screenshot', 'get_current_running_task', 'get_scheduler_queue', 'trigger_task',
    'clear_scheduler_queue', 'restart_emulator', 'restart_adb', 'update_alas',
}


def fixture(directory):
    root = Path(directory)
    data = {'Alas': {}, 'Dashboard': {'Oil': {'Value': 123, 'Limit': 500,
                                              'Record': '2026-11-07 10:00:00'}},
            'Main': {'Scheduler': {'Enable': False, 'NextRun': '2026-01-01 00:00:00'},
                     'Option': {'Count': 2}}}
    args = {'Main': {'Scheduler': {'Enable': {'type': 'checkbox', 'value': False},
                                   'NextRun': {'type': 'datetime', 'value': '2026-01-01 00:00:00'}},
                     'Option': {'Count': {'value': 2, 'validate': [1, 5]}}}}
    for name, value in [('config/template.json', data), ('config/demo.json', data),
                        ('module/config/argument/args.json', args),
                        ('module/config/argument/menu.json', {}),
                        ('module/config/i18n/zh-CN.json', {})]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    return root


def parse_event_stream(body):
    """取 streamable-http 事件流里第一条 message 事件的 JSON-RPC 响应。"""
    for block in body.split('\n\n'):
        for line in block.splitlines():
            if line.startswith('data: '):
                return json.loads(line[len('data: '):])
    raise AssertionError(f'响应中没有 message 事件：{body[:200]}')


class McpEndpointTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = fixture(self.directory.name)
        self.configs = ConfigService(self.root)
        self.runtime = RuntimeService(self.configs)
        self.app = mcp.create_app(self.configs, self.runtime, manage_runtime=False)

    def request(self, client, message):
        response = client.post('/', json=message, headers=HEADERS)
        self.assertEqual(200, response.status_code, response.text[:200])
        return parse_event_stream(response.text)

    def test_default_endpoint_exposes_legacy_and_canonical_tools(self):
        with TestClient(self.app) as client:
            initialized = self.request(client, INITIALIZE)
            self.assertEqual('AzurPilot-MCP', initialized['result']['serverInfo']['name'])
            listing = self.request(client, {'jsonrpc': '2.0', 'id': 2,
                                            'method': 'tools/list', 'params': {}})
        tools = {tool['name']: tool for tool in listing['result']['tools']}
        self.assertLessEqual(LEGACY_NAMES, set(tools))
        for name in ('azurpilot_get_context', 'azurpilot_get_statistics',
                     'azurpilot_click', 'azurpilot_acquire_device_control'):
            self.assertIn(name, tools)
        self.assertTrue(tools['get_status']['description'].startswith(
            '获取所有 AzurPilot 实例的运行状态'))
        # 旧名称沿用拒绝未知字段的 Schema，避免静默忽略调用方拼错的参数
        self.assertFalse(tools['get_status']['inputSchema']['additionalProperties'])

    # Add by MHY, 验证真实 WebUI 挂载路径，而非只测独立 MCP 工厂。
    def test_webui_mount_uses_host_config_and_closes_shared_tools(self):
        from module.api.app import create_app as create_webui

        app = create_webui(root=self.root, password='', manage_runtime=False)
        route = next(route for route in app.routes if getattr(route, 'path', None) == '/mcp')
        mounted = route.app
        self.assertIs(mounted.state.tools.configs, app.state.gateway.router.configs)
        self.assertIs(mounted.state.tools.runtime, app.state.gateway.router.runtime)
        with TestClient(app) as client:
            response = client.post('/mcp/', json=INITIALIZE, headers=HEADERS)
            self.assertEqual(200, response.status_code, response.text[:200])
            response = client.post('/mcp/', json={
                'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call',
                'params': {'name': 'list_instances', 'arguments': {}}}, headers=HEADERS)
            self.assertEqual(200, response.status_code, response.text[:200])
            result = parse_event_stream(response.text)['result']
            self.assertEqual(['demo'], json.loads(result['content'][0]['text']))
        rejected = asyncio.run(mounted.state.tools.call('list_instances', {}))
        self.assertTrue(rejected.isError)
        self.assertEqual('SERVICE_STOPPING', rejected.structuredContent['error']['code'])

    def test_modern_endpoint_can_hide_legacy_names(self):
        app = mcp.create_modern_app(self.configs, self.runtime, manage_runtime=False)
        with TestClient(app) as client:
            self.request(client, INITIALIZE)
            listing = self.request(client, {'jsonrpc': '2.0', 'id': 2,
                                            'method': 'tools/list', 'params': {}})
        names = {tool['name'] for tool in listing['result']['tools']}
        self.assertTrue(names.isdisjoint(LEGACY_NAMES))
        self.assertIn('azurpilot_get_context', names)

    def test_legacy_tool_call_keeps_old_output_shape(self):
        with TestClient(self.app) as client:
            self.request(client, INITIALIZE)
            response = self.request(client, {
                'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                'params': {'name': 'get_status', 'arguments': {}}})
            canonical = self.request(client, {
                'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
                'params': {'name': 'azurpilot_list_instances', 'arguments': {}}})
        legacy_result = response['result']
        self.assertFalse(legacy_result.get('isError'))
        self.assertEqual([{'instance': 'demo', 'running': False, 'state': 2}],
                         json.loads(legacy_result['content'][0]['text']))
        self.assertIn('instances', canonical['result']['structuredContent'])

    def test_unknown_tool_reports_structured_error(self):
        with TestClient(self.app) as client:
            self.request(client, INITIALIZE)
            response = self.request(client, {
                'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
                'params': {'name': 'azurpilot_missing', 'arguments': {}}})
        result = response['result']
        self.assertTrue(result['isError'])
        self.assertEqual('UNKNOWN_TOOL', result['structuredContent']['error']['code'])

    def test_old_sse_endpoints_are_still_routed(self):
        """SSE 与 /messages 的路径分发保持不变；真实流由 TestClient 无法可靠收尾，
        这里只替换传输实现来验证路由，协议本身由 streamable 用例覆盖。"""
        seen = []

        def respond(marker):
            async def handler(scope, receive, send, *_):
                seen.append((scope['path'], scope['method']))
                await send({'type': 'http.response.start', 'status': 200,
                            'headers': [[b'content-type', b'text/plain']]})
                await send({'type': 'http.response.body', 'body': marker})
            return handler

        with TestClient(self.app) as client, \
                patch.object(mcp, '_run_sse', side_effect=respond(b'sse')), \
                patch.object(mcp, '_handle_mcp_post', side_effect=respond(b'post')):
            sse = client.get('/sse')
            post = client.post('/messages?session_id=' + 'a' * 32, content=b'{}')
        self.assertEqual((200, 'sse'), (sse.status_code, sse.text))
        self.assertEqual((200, 'post'), (post.status_code, post.text))
        self.assertEqual([('/sse', 'GET'), ('/messages', 'POST')], seen)
