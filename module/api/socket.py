"""单连接会话、认证、事件订阅及慢客户端背压。"""
import asyncio
import contextlib
import json
import secrets
import time
from collections import OrderedDict
from urllib.parse import urlsplit

import anyio
from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from module.api.protocol import ApiError, AuthParams, Request, SubscribeParams, failure, response
from module.logger import logger
from module.runtime.password_utils import REMOTE_ACCESS_HEADER, is_local_client

# 重主题仍按各自节奏采样；日志由 worker 队列逐条到达事件直接唤醒。
TOPIC_INTERVAL = {'overview': 1, 'instances': 2}
TICK = min(TOPIC_INTERVAL.values())


class Gateway:
    def __init__(self, router, password):
        self.router = router
        self.password = str(password or '')
        self.connections = 0
        self.workers = asyncio.Semaphore(8)
        self.failures = OrderedDict()

    async def endpoint(self, ws: WebSocket):
        origin = ws.headers.get('origin')
        # WebSocket 不受浏览器 CORS 保护，必须在升级前验证来源。
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in ('http', 'https') or parsed.netloc != ws.headers.get('host'):
                await ws.close(code=1008)
                return
        if self.connections >= 32:
            await ws.close(code=1013)
            return
        self.connections += 1
        try:
            await Session(self, ws, self.is_local(ws)).run()
        finally:
            self.connections -= 1

    @staticmethod
    def is_local(ws: WebSocket):
        """本机直连判定：启动器内嵌窗口与本机浏览器免密，其余仍需密码。"""
        client = ws.client.host if ws.client else ''
        return is_local_client(
            client,
            ws.headers.get('host'),
            ws.headers.get('origin'),
            ws.headers.get(REMOTE_ACCESS_HEADER),
        )

    def authenticate(self, peer, password):
        now = time.monotonic()
        count, until = self.failures.get(peer, (0, 0))
        if until > now:
            raise ApiError('RATE_LIMITED', '登录尝试过于频繁，请稍后重试')
        if not secrets.compare_digest(password.encode(), self.password.encode()):
            count += 1
            self.failures[peer] = (count, now + min(60, count * 2))
            if len(self.failures) > 1024:
                self.failures.popitem(last=False)
            raise ApiError('UNAUTHORIZED', '访问密码不正确')
        self.failures.pop(peer, None)


class Session:
    def __init__(self, gateway, ws, local=False):
        """local 为 True 表示本机直连：无需密码即可使用全部方法。"""
        self.gateway, self.ws = gateway, ws
        self.authorized = local or not bool(gateway.password)
        self.queue = asyncio.Queue(maxsize=32)
        self.subscription = SubscribeParams(topics=[])
        self.sequence = 0
        self.cache = {}
        self.responses = OrderedDict()
        self.log_cursor = 0
        self.logs_initialized = False
        self.window = time.monotonic()
        self.requests = 0
        self.topic_seen = {}
        self.logs_changed = asyncio.Event()
        self.preview_changed = asyncio.Event()
        self.preview_pending = None

    async def enqueue(self, message):
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            await self.ws.close(code=1013, reason='客户端读取过慢，请重新连接')
            raise WebSocketDisconnect(1013)

    async def event(self, topic, data):
        message = {'v': 1, 'type': 'event', 'topic': topic, 'data': data}
        if topic == 'preview':
            if self.preview_pending is None:
                await self.enqueue({'previewSlot': True})
            self.preview_pending = message
        else:
            await self.enqueue(message)

    async def writer(self):
        while True:
            message = await self.queue.get()
            if message.get('previewSlot'):
                message, self.preview_pending = self.preview_pending, None
                if (not message or 'preview' not in self.subscription.topics
                        or message['data']['instance'] != self.subscription.instance):
                    continue
            if message.get('type') == 'event':
                self.sequence += 1
                message['seq'] = self.sequence
            await asyncio.wait_for(self.ws.send_json(message), timeout=10)

    async def run(self):
        await self.ws.accept()
        writer = asyncio.create_task(self.writer())
        producer = asyncio.create_task(self.producer())
        reader = asyncio.create_task(self.reader())
        logs = asyncio.create_task(self.log_producer())
        preview = asyncio.create_task(self.preview_producer())
        await self.event('session', {'authRequired': not self.authorized, 'protocolVersion': 1})
        tasks = [writer, producer, reader, logs, preview]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            # ASGI 服务器可能在客户端退出时取消整个会话作用域。
            # 屏蔽外层取消，确保收发任务实际结束后再归还连接槽位。
            with anyio.CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                with contextlib.suppress(RuntimeError):
                    await self.ws.close()

    async def reader(self):
        while True:
            raw = await asyncio.wait_for(self.ws.receive_text(), timeout=60 if self.authorized else 30)
            request_id = None
            try:
                if len(raw.encode()) > 1024 * 1024:
                    raise ApiError('INVALID_REQUEST', '请求超过 1 MiB 限制')
                now = time.monotonic()
                if now - self.window > 1:
                    self.window, self.requests = now, 0
                self.requests += 1
                if self.requests > 30:
                    raise ApiError('RATE_LIMITED', '请求过于频繁')
                decoded = json.loads(raw)
                if isinstance(decoded, dict) and isinstance(decoded.get('id'), str):
                    request_id = decoded['id'][:100]
                request = Request.model_validate(decoded)
                request_id = request.id
                if request_id in self.responses:
                    raise ApiError('DUPLICATE_REQUEST', '请求 ID 已使用，请检查状态后使用新 ID')
                if request.method == 'auth.login':
                    params = AuthParams.model_validate(request.params)
                    peer = self.ws.client.host if self.ws.client else 'unknown'
                    self.gateway.authenticate(peer, params.password)
                    self.authorized = True
                    result = {'authenticated': True}
                elif not self.authorized:
                    raise ApiError('UNAUTHORIZED', '请先登录')
                elif request.method == 'events.subscribe':
                    subscription = SubscribeParams.model_validate(request.params)
                    if any(topic != 'instances' for topic in subscription.topics):
                        self.gateway.router.configs.path(subscription.instance)
                    self.subscription = subscription
                    self.cache.clear()
                    self.log_cursor = 0
                    self.logs_initialized = False
                    self.topic_seen.clear()
                    self.logs_changed.set()
                    self.preview_changed.set()
                    result = {'topics': subscription.topics, 'instance': subscription.instance}
                else:
                    async with self.gateway.workers:
                        result = await asyncio.to_thread(self.gateway.router.dispatch, request.method, request.params)
                reply = response(request_id, result)
            except ValidationError as exc:
                # 错误详情不包含输入，避免密码或私有配置被回显。
                reply = failure(request_id, ApiError('INVALID_PARAMS', '请求格式或参数不正确',
                                [{'path': list(e['loc']), 'type': e['type']} for e in exc.errors()]))
            except ApiError as exc:
                reply = failure(request_id, exc)
            except (ValueError, PermissionError) as exc:
                reply = failure(request_id, ApiError('INVALID_PARAMS', str(exc)))
            except Exception:
                logger.exception('WebSocket API 执行失败')
                reply = failure(request_id, ApiError('INTERNAL_ERROR', '服务暂时无法完成请求，请检查服务日志'))
            if request_id:
                self.responses[request_id] = True
                if len(self.responses) > 128:
                    self.responses.popitem(last=False)
            await self.enqueue(reply)

    async def producer(self):
        while True:
            await asyncio.sleep(TICK)
            if not self.authorized:
                continue
            subscription = self.subscription
            runtime = self.gateway.router.runtime
            for topic in subscription.topics:
                try:
                    if topic in ('logs', 'preview'):
                        continue
                    if (now := time.monotonic()) - self.topic_seen.get(topic, 0) < TOPIC_INTERVAL.get(topic, 2):
                        continue
                    self.topic_seen[topic] = now
                    if topic == 'instances':
                        action = runtime.instances
                    elif topic == 'overview':
                        action = lambda: runtime.overview(subscription.instance)
                    async with self.gateway.workers:
                        data = await asyncio.to_thread(action)
                    # 用户切换实例期间完成的旧结果不允许覆盖新工作区。
                    if subscription is not self.subscription:
                        break
                    fingerprint = json.dumps(data, sort_keys=True, default=str)
                    if self.cache.get(topic) != fingerprint:
                        self.cache[topic] = fingerprint
                        await self.event(topic, data)
                except ApiError as exc:
                    fingerprint = f'{exc.code}:{exc.message}'
                    if subscription is self.subscription and self.cache.get(topic) != fingerprint:
                        self.cache[topic] = fingerprint
                        await self.event('subscription.error', {'topic': topic, 'instance': subscription.instance,
                                                               'code': exc.code, 'message': exc.message})
                except (WebSocketDisconnect, asyncio.CancelledError):
                    raise
                except Exception:
                    logger.exception('订阅数据读取失败')
                    if self.cache.get(topic) != 'INTERNAL_ERROR':
                        self.cache[topic] = 'INTERNAL_ERROR'
                        await self.event('subscription.error', {'topic': topic, 'instance': subscription.instance,
                                                               'code': 'INTERNAL_ERROR', 'message': '订阅暂时不可用，请检查服务日志'})
            if subscription.instance and (time.monotonic() - self.topic_seen.get('statistics', 0)) >= 1:
                self.topic_seen['statistics'] = time.monotonic()
                try:
                    from module.api.statistics_service import get_statistics_fingerprint
                    stats_fp = await asyncio.to_thread(get_statistics_fingerprint, subscription.instance)
                    if subscription is self.subscription:
                        old_fp = self.cache.get('statistics')
                        if old_fp is not None and old_fp != stats_fp:
                            self.cache['statistics'] = stats_fp
                            await self.event('statistics', {'instance': subscription.instance, 'updatedAt': time.time()})
                        elif old_fp is None:
                            self.cache['statistics'] = stats_fp
                except (WebSocketDisconnect, asyncio.CancelledError):
                    raise
                except Exception:
                    pass

    async def log_producer(self):
        """日志到达后立即读取增量；初始化/重置成批发送，实时新增逐条发送。"""
        from module.runtime.log_hub import hub
        loop = asyncio.get_running_loop()

        def changed(instance):
            if instance == self.subscription.instance and not loop.is_closed():
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(self.logs_changed.set)

        hub.subscribe(changed)
        try:
            while True:
                await self.logs_changed.wait()
                self.logs_changed.clear()
                subscription = self.subscription
                if not self.authorized or 'logs' not in subscription.topics:
                    continue
                initial = not self.logs_initialized
                try:
                    async with self.gateway.workers:
                        data = await asyncio.to_thread(
                            self.gateway.router.runtime.logs, subscription.instance, self.log_cursor
                        )
                    if subscription is not self.subscription:
                        continue
                    entries = data['entries']
                    if not entries and not data['reset']:
                        self.log_cursor = data['cursor']
                        self.logs_initialized = True
                        continue
                    if initial or data['reset']:
                        self.log_cursor = data['cursor']
                        self.logs_initialized = True
                        await self.event('logs', data)
                        continue
                    for entry in entries:
                        self.log_cursor = entry['id']
                        await self.event('logs', {
                            'instance': data['instance'], 'cursor': entry['id'],
                            'reset': False, 'entries': [entry],
                        })
                    self.log_cursor = data['cursor']
                    self.logs_initialized = True
                except ApiError as exc:
                    if subscription is self.subscription:
                        await self.event('subscription.error', {
                            'topic': 'logs', 'instance': subscription.instance,
                            'code': exc.code, 'message': exc.message,
                        })
                except (WebSocketDisconnect, asyncio.CancelledError):
                    raise
                except Exception:
                    logger.exception('日志订阅读取失败')
                    if subscription is self.subscription:
                        await self.event('subscription.error', {
                            'topic': 'logs', 'instance': subscription.instance,
                            'code': 'INTERNAL_ERROR', 'message': '日志订阅暂时不可用，请检查服务日志',
                        })
        finally:
            hub.unsubscribe(changed)

    async def preview_producer(self):
        """收到新帧即推送；慢浏览器合并为最新帧，不产生截图请求。"""
        from module.runtime.preview import hub
        loop = asyncio.get_running_loop()

        def changed(instance):
            if instance == self.subscription.instance and not loop.is_closed():
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(self.preview_changed.set)

        hub.subscribe(changed)
        try:
            while True:
                await self.preview_changed.wait()
                self.preview_changed.clear()
                subscription = self.subscription
                if not self.authorized or 'preview' not in subscription.topics:
                    continue
                frame = hub.get(subscription.instance)
                await self.event('preview', frame)
        finally:
            hub.unsubscribe(changed)
