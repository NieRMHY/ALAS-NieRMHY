"""AzurPilot 原生交易终端的实例代理；直接同步现有行动力记录，不验证其真实性。"""
import json
import hashlib
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from functools import wraps
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen

from module.api.protocol import ApiError
from module.api.stock_exchange_identity import load_identity, binding_key, make_report
from module.api.stock_exchange_history import ActionHistory
from module.runtime.game_data import GameDataProtector, damaged


def exchange_url():
    value = os.environ.get('STOCK_EXCHANGE_URL', 'https://stock.nanoda.work').rstrip('/')
    try:
        parsed = urlparse(value)
        parsed.port
    except ValueError:
        raise ApiError('INVALID_PARAMS', 'STOCK_EXCHANGE_URL 地址格式无效') from None
    if (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path
            or not parsed.hostname or parsed.scheme not in ('https', 'http')
            or parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1')):
        raise ApiError('INVALID_PARAMS', 'STOCK_EXCHANGE_URL 须为 HTTPS origin，本机开发可使用回环 HTTP')
    return value


def action_snapshot(data, instance):
    row = data.get('Dashboard', {}).get('ActionPoint', {})
    total, recorded = row.get('Total'), row.get('Record')
    # 只检查传输字段格式，不判断数据真实与否。
    if type(total) is not int or not 0 <= total <= 1_000_000 or not recorded:
        return None
    try:
        observed = int(datetime.fromisoformat(recorded).timestamp())
    except (TypeError, ValueError, OSError):
        return None
    return {'instance': instance, 'actionPoints': total, 'observedAt': observed}


def public_stock_path(path):
    parsed = urlparse(path)
    if parsed.scheme or parsed.netloc or parsed.fragment or not re.fullmatch(r'/stocks/[1-9][0-9]*', parsed.path):
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    patterns = {'period': r'(time|day|m5|m10|m20|m30|m60)', 'month': r'\d{4}-\d{2}', 'day': r'\d{4}-\d{2}-\d{2}'}
    return all(k in patterns and len(v) == 1 and re.fullmatch(patterns[k], v[0]) for k, v in query.items())


def account_operation(method):
    """重建与后台同步互斥，避免旧会话在重建后继续上传。"""
    @wraps(method)
    def run(self, *args, **kwargs):
        with self.operation_lock:
            return method(self, *args, **kwargs)
    return run


class StockExchangeService:
    """每实例永久绑定一个账户；浏览器不接触远端会话、上传令牌或实例私钥。"""
    def __init__(self, configs):
        self.configs = configs
        self.protection = GameDataProtector(configs.root)
        self.path = self.protection.directory / 'bindings.json'
        self.lock = threading.RLock()
        self.operation_lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.event_thread = None
        self.event_response = None
        self.listeners = set()
        self.bindings, self.sessions, self.identities, self.instance_locks = {}, {}, {}, {}
        self.stamps, self.records, self.statuses, self.attempts = {}, {}, {}, {}
        self.uploaded, self.last_upload = {}, {}
        self.meta_cache = None
        self.history = ActionHistory(configs.root)
        self.names = {}
        self.storage_error = None
        self.refresh_stamp = None
        self.refresh_check = 0
        self.monitors = set()
        try:
            self._refresh()
        except ApiError as error:
            self.storage_error = error

    @staticmethod
    def _valid_binding(value):
        return (isinstance(value, dict) and type(value.get('playerId')) is int and value['playerId'] > 0
                and all(isinstance(value.get(field), str) and value[field] for field in ('bindingKey', 'username', 'uploadToken', 'url')))

    def _storage_stamp(self):
        paths = [self.path, self.protection.marker, self.protection.legacy_marker,
                 self.protection.state_path, self.protection.key_path]
        paths.extend(sorted((Path(self.configs.root) / 'config').glob('*.json')))
        result = []
        for path in paths:
            try:
                stat = path.stat()
                result.append((str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino))
            except FileNotFoundError:
                result.append((str(path), None))
            except OSError:
                raise damaged('无法检查游戏文件状态，已停止同步') from None
        return tuple(result)

    @account_operation
    def _refresh(self):
        """文件系统重命名沿用 UUID；删除和同名重建撤销旧会话及监视。"""
        with self.lock:
            self.protection.migrate_cache()
            stamp = self._storage_stamp()
            if stamp == self.refresh_stamp and self.storage_error is None and time.monotonic() < self.refresh_check:
                return
            if not self.path.exists() and not self.protection.initialized():
                return
            if self.path.exists() and not self.protection.has_file('bindings.json'):
                try:
                    legacy = json.loads(self.path.read_bytes())
                    if not isinstance(legacy, dict) or any(not self._valid_binding(value) for value in legacy.values()):
                        raise ValueError()
                    migrated = {}
                    for name, value in legacy.items():
                        from module.api.config_service import validate_name
                        if validate_name(name) != name:
                            raise damaged('旧玩家绑定包含无效实例名称')
                        if not (Path(self.configs.root) / 'config' / (name + '.json')).is_file():
                            continue
                        old = self.protection.directory / 'identities' / (hashlib.sha256(name.encode()).hexdigest() + '.json')
                        if not old.exists():
                            config = json.loads((Path(self.configs.root) / 'config' / (name + '.json')).read_bytes())
                            identity = config.get('_stockInstance')
                            if not isinstance(identity, str) or not self.protection.has_file('identities/' + identity + '.json'):
                                raise damaged('已绑定账户的旧身份文件丢失，不能自动重新生成')
                        identity, key = load_identity(self.configs.root, name)
                        if binding_key(identity, key) != value['bindingKey']:
                            raise damaged('旧玩家绑定与实例身份不匹配')
                        migrated[identity] = value
                    self.protection.write_file('bindings.json', migrated, legacy=True)
                except (OSError, ValueError, TypeError):
                    raise damaged('玩家绑定文件损坏，请恢复完整备份，不能按未绑定实例处理') from None
            active = self.protection.reconcile()
            configs = self.protection._configs()
            for identity, name in active.items():
                if name in configs and configs[name] != identity:
                    self.protection.resolve(name)
            active = self.protection.reconcile()
            stored = self.protection.read_file('bindings.json') or {}
            if not isinstance(stored, dict) or any(not self._valid_binding(value) for value in stored.values()):
                raise damaged('玩家绑定文件格式无效')
            current = {name: identity for identity, name in active.items()}
            for old, identity in self.names.items():
                new = active.get(identity)
                if new == old:
                    continue
                for state in (self.sessions, self.identities, self.stamps, self.records, self.statuses, self.attempts, self.uploaded, self.last_upload,
                              self.history.scanned, self.history.next_send, self.history.next_check, self.history.failures, self.history.pending,
                              self.history.legacy_warnings):
                    value = state.pop(old, None)
                    if new and value is not None:
                        state[new] = value
            self.names = current
            self.bindings = {active[identity]: value for identity, value in stored.items() if identity in active}
            self.monitors = set(self.bindings)
            self.storage_error = None
            self.history.discard_retired(active)
            retired = set(stored) - set(active)
            if retired:
                self.protection.write_file('bindings.json', {key: value for key, value in stored.items() if key in active})
            with self.protection.transaction() as (state, _):
                retired = [identity for identity, record in state['instances'].items() if not record['active']]
            for identity in retired:
                for name in ('identities/' + identity + '.json', 'history/' + identity + '.sqlite3'):
                    path = self.protection.file_path(name)
                    for suffix in ('', '-wal', '-shm'):
                        try:
                            path.with_name(path.name + suffix).unlink(missing_ok=True)
                        except PermissionError:
                            # 另一进程的 SQLite 连接可能尚未退出；登记已撤销，后续继续清理密文。
                            pass
            self.refresh_stamp = self._storage_stamp()
            self.refresh_check = time.monotonic() + 300

    def _identity(self, instance):
        with self.lock:
            identity, key = load_identity(self.configs.root, instance)
            binding = self.bindings.get(instance)
            if binding and binding['bindingKey'] != binding_key(identity, key):
                raise damaged('玩家绑定与当前实例身份不匹配')
            self.identities[instance] = identity, key
            return identity, key

    def _instance_lock(self, instance):
        identity = self.protection.resolve(instance)
        with self.lock:
            return self.instance_locks.setdefault(identity, threading.RLock())

    def start(self):
        with self.lock:
            if (self.monitors or self.storage_error) and self.thread is None:
                self.thread = threading.Thread(target=self._run, name='stock-instance-relay', daemon=True)
                self.thread.start()

    def close(self):
        self.stop.set()
        if self.event_response:
            self.event_response.close()
        if self.event_thread:
            self.event_thread.join(timeout=2)
        if self.thread:
            self.thread.join(timeout=10)
        # 正在网络超时中的守护线程退出后再关闭日志，避免竞态。
        if not self.thread or not self.thread.is_alive():
            self.history.close()

    def subscribe(self, listener):
        """复用一个远端事件流；浏览器订阅只收到公开变更通知。"""
        with self.lock:
            self.listeners.add(listener)
            if self.event_thread is None or not self.event_thread.is_alive():
                self.event_thread = threading.Thread(target=self._listen_events, name='stock-market-events', daemon=True)
                self.event_thread.start()

        def unsubscribe():
            with self.lock:
                self.listeners.discard(listener)
        return unsubscribe

    def _notify(self, data):
        with self.lock:
            listeners = tuple(self.listeners)
        for listener in listeners:
            listener(data)

    def _listen_events(self):
        failures = 0
        while not self.stop.is_set():
            try:
                request = Request(exchange_url() + '/api/events', headers={'Accept': 'text/event-stream'})
                with urlopen(request, timeout=12) as response:
                    self.event_response = response
                    if response.headers.get_content_type() != 'text/event-stream':
                        raise ValueError('交易所不支持实时事件流')
                    while not self.stop.is_set():
                        line = response.readline()
                        if not line:
                            raise OSError('交易所事件流已断开')
                        if line.startswith(b'data: '):
                            data = json.loads(line[6:])
                            if isinstance(data, dict) and type(data.get('revision')) is int:
                                failures = 0
                                self._notify({**data, 'online': True})
            except (URLError, TimeoutError, OSError, ValueError, ApiError):
                if not self.stop.is_set():
                    self._notify({'online': False})
                    failures = min(failures + 1, 5)
                    self.stop.wait(min(30, 2 ** (failures - 1)))
            finally:
                self.event_response = None

    def _save(self):
        from module.config.transaction import config_transaction
        with config_transaction(self.path):
            stored = self.protection.read_file('bindings.json') or {}
            active = self.protection.reconcile()
            stored = {identity: value for identity, value in stored.items() if identity in active}
            for name, value in self.bindings.items():
                identity, key = self._identity(name)
                if binding_key(identity, key) != value['bindingKey']:
                    raise damaged('不能保存不属于当前实例的玩家数据')
                stored[identity] = value
            self.protection.write_file('bindings.json', stored)
        self.names = {name: self.protection.resolve(name) for name in self.bindings}

    def _read_snapshot(self, instance):
        database = Path(self.configs.root) / 'config' / 'scheduler' / (instance + '.sqlite3')
        paths = [self.configs.path(instance), database, Path(str(database) + '-wal')]
        stamp = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in paths)
        with self.lock:
            if self.stamps.get(instance) == stamp and time.monotonic() < self.history.scanned.get(instance, 0):
                return self.records.get(instance)
        data, _ = self.configs.read(instance)
        record = None
        try:
            point = self.history.capture(instance, data, database)
            if point:
                record = {'instance': instance, 'actionPoints': point[1], 'observedAt': point[0] // 1000}
        except sqlite3.Error:
            raise ApiError('STOCK_HISTORY_UNAVAILABLE', '行动力历史暂不可读取，已停止同步，稍后重试') from None
        with self.lock:
            self.records[instance] = record
            self.stamps[instance] = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in paths)
        return record

    def _report(self, instance, initial=False):
        record = self._read_snapshot(instance)
        if initial and (not record or record['observedAt'] < time.time() - 86400):
            record = {'actionPoints': 0, 'observedAt': int(time.time())}
        if not record:
            raise ApiError('QUOTE_MISSING', '当前实例尚无行动力记录，请等待游戏任务更新')
        instance_id, key = self._identity(instance)
        return make_report(instance_id, key, record['actionPoints'], record['observedAt'])

    def _remote(self, path, method='GET', body=None, token='', instance_key='', etag=''):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if instance_key:
            headers['X-MMEX-Instance'] = instance_key
        if etag:
            headers['If-None-Match'] = etag
        payload = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        request = Request(exchange_url() + '/api' + path, data=payload, headers=headers, method=method)
        try:
            response = urlopen(request, timeout=12)
        except HTTPError as error:
            response = error
        except (URLError, TimeoutError, OSError):
            raise ApiError('STOCK_UNAVAILABLE', '交易所暂不可连接，稍后自动重试') from None
        with response:
            raw = response.read()
            try:
                data = json.loads(raw) if raw else None
                server_time = int(parsedate_to_datetime(response.headers['Date']).timestamp()) if response.headers.get('Date') else int(time.time())
            except (ValueError, TypeError):
                raise ApiError('STOCK_INVALID_RESPONSE', '交易所响应格式无效') from None
            return {'status': response.status, 'data': data, 'etag': response.headers.get('ETag', ''), 'serverTime': server_time}

    @staticmethod
    def _accepted(reply):
        if reply['status'] >= 400:
            error = (reply['data'] or {}).get('error', {})
            raise ApiError(error.get('code', 'STOCK_ERROR'), error.get('message', '交易所拒绝请求'))
        return reply['data']

    @account_operation
    def status(self, instance):
        self._refresh()
        self.configs.path(instance)
        identity, key = self._identity(instance)
        record = self._read_snapshot(instance)
        self.start()
        with self.lock:
            binding = self.bindings.get(instance)
            message = self.statuses.get(instance, '后台行动力同步已启用' if binding else '注册后与当前实例永久绑定；行动力直接使用实例现有记录')
            warning = self.history.legacy_warnings.get(instance, '')
            if warning:
                message += '；' + warning
            return {'url': exchange_url(), 'instance': instance, 'instanceId': identity,
                    'bound': bool(binding), 'boundUsername': binding['username'] if binding else '',
                    'authenticated': instance in self.sessions,
                    'message': message,
                    'lastObservedAt': record['observedAt'] if record else 0, 'snapshot': record,
                    'bindingKey': binding_key(identity, key)}

    @account_operation
    def request(self, instance, path, method='GET', body=None, etag=''):
        self._refresh()
        with self._instance_lock(instance):
            reply = self._request(instance, path, method, body, etag)
        if method != 'GET' or reply['status'] == 401:
            self._notify({'instance': instance})
        return reply

    @account_operation
    def rebuild(self, instance, confirm=False, scope='instance'):
        from module.api.stock_exchange_recovery import StockExchangeRecovery
        recovery = StockExchangeRecovery(self.configs, self._valid_binding)
        if confirm:
            self.history.close()
        result = recovery.rebuild(instance, confirm, scope)
        if result['rebuilt']:
            with self.lock:
                for name in result['affectedInstances']:
                    for state in (self.bindings, self.sessions, self.identities, self.names, self.stamps, self.records,
                                  self.statuses, self.attempts, self.uploaded, self.last_upload, self.history.scanned,
                                  self.history.next_send, self.history.next_check, self.history.failures,
                                  self.history.pending, self.history.legacy_warnings):
                        state.pop(name, None)
                    self.monitors.discard(name)
                self.storage_error = None
                self.refresh_stamp = None
            self._refresh()
            self._notify({'instance': instance})
        return result

    def _request(self, instance, path, method='GET', body=None, etag=''):
        self.configs.path(instance)
        public = method == 'GET' and (path in ('/meta', '/market', '/seasons') or re.fullmatch(r'/history/[1-9][0-9]*', path) or public_stock_path(path))
        auth = method == 'POST' and path in ('/register', '/login')
        private = (method == 'GET' and path in ('/account', '/orders') or method == 'POST' and path in ('/orders', '/watchlist', '/sync', '/logout')
                   or method == 'DELETE' and re.fullmatch(r'/orders/[1-9][0-9]*', path))
        if not (public or auth or private):
            raise ApiError('INVALID_PARAMS', '交易接口不在实例代理白名单中')
        if body is not None and not isinstance(body, dict):
            raise ApiError('INVALID_PARAMS', '交易请求正文须为对象')
        if body and set(body) & {'report', 'evidence', 'instanceId', 'actionPoints', 'observedAt', 'token', 'uploadToken', 'publicKey', 'points', 'digest', 'signature'}:
            raise ApiError('INVALID_PARAMS', '浏览器不能提供实例身份、报价或远端凭据')
        if public:
            if path == '/meta' and self.meta_cache and self.meta_cache[0] > time.monotonic():
                return self.meta_cache[1]
            reply = self._remote(path, etag=etag)
            if path == '/meta' and reply['status'] == 200:
                self.meta_cache = (time.monotonic() + 60, reply)
            return reply
        if path == '/logout':
            with self.lock:
                self.sessions.pop(instance, None)
            return {'status': 200, 'data': {'ok': True}, 'etag': '', 'serverTime': int(time.time())}
        # 交易会话仍在内存中时也必须核验身份文件，不能用缓存绕过损坏的私钥。
        self._identity(instance)
        if auth:
            with self.lock:
                previous = self.bindings.get(instance)
            if previous and previous['url'] != exchange_url():
                raise ApiError('STOCK_ORIGIN_CHANGED', '交易所地址已改变，请恢复绑定时的地址')
            if previous and path == '/register':
                raise ApiError('INSTANCE_TAKEN', '请登录当前实例永久绑定的账户：' + previous['username'])
            reply = self._remote(path, 'POST', {**(body or {}), 'report': self._report(instance, initial=True)})
            if reply['status'] >= 400:
                return reply
            result = reply['data']
            actual = result['player']['binding']
            identity, key = self._identity(instance)
            if actual['key'] != binding_key(identity, key) or actual['instanceId'] != identity:
                raise ApiError('INSTANCE_MISMATCH', '远端账户与当前实例身份不一致')
            if previous and previous['playerId'] != result['player']['id']:
                raise ApiError('INSTANCE_MISMATCH', '当前实例已经永久绑定其他账户')
            upload = result.get('uploadToken') or (previous or {}).get('uploadToken')
            if not upload:
                rotated = self._accepted(self._remote('/upload-token', 'POST', {}, result['token'], actual['key']))
                upload = rotated['uploadToken']
            with self.lock:
                self.sessions[instance] = result['token']
                self.bindings[instance] = {'playerId': result['player']['id'], 'username': result['player']['username'], 'bindingKey': actual['key'], 'uploadToken': upload, 'url': exchange_url()}
                self.monitors.add(instance)
                self.uploaded[instance] = (result['player']['quote']['observedAt'], result['player']['quote']['price']//100)
                self._save()
            self.start()
            reply['data'] = {'token': 'instance-session', 'player': result['player']}
            return reply
        with self.lock:
            session, binding = self.sessions.get(instance), self.bindings.get(instance)
        if not session or not binding:
            raise ApiError('UNAUTHORIZED', '请登录当前实例绑定的交易账户')
        if binding['url'] != exchange_url():
            raise ApiError('STOCK_ORIGIN_CHANGED', '交易所地址已改变，请恢复绑定时的地址')
        if path == '/sync':
            self.sync_once(instance, force=True)
            return {'status': 200, 'data': {'ok': True}, 'etag': '', 'serverTime': int(time.time())}
        reply = self._remote(path, method, body, session, binding['bindingKey'])
        if path == '/account' and reply['status'] == 200:
            player = (reply.get('data') or {}).get('player') or {}
            username = player.get('username')
            if player.get('id') == binding['playerId'] and isinstance(username, str) and username and username != binding['username']:
                with self.lock:
                    binding['username'] = username
                    self._save()
        if reply['status'] == 401:
            with self.lock:
                self.sessions.pop(instance, None)
        return reply

    @account_operation
    def sync_once(self, only=None, force=False):
        try:
            self._refresh()
        except ApiError as error:
            with self.lock:
                self.storage_error = error
                for name in self.monitors:
                    self.statuses[name] = str(error)
            if force:
                raise
            return
        with self.lock:
            instances = [only] if only else tuple(self.monitors)
        for instance in instances:
            if self.stop.is_set():
                return
            with self._instance_lock(instance):
                try:
                    self._sync_instance(instance, force)
                finally:
                    self._sync_history(instance, force)

    def _sync_history(self, instance, force):
        try:
            with self.lock:
                binding = self.bindings.get(instance)
            if not binding:
                return
            if binding['url'] != exchange_url():
                raise ApiError('STOCK_ORIGIN_CHANGED', '交易所地址与绑定地址不一致，已停止转发')
            if force or time.monotonic() >= self.history.scanned.get(instance, 0):
                data, _ = self.configs.read(instance)
                database = Path(self.configs.root) / 'config' / 'scheduler' / (instance + '.sqlite3')
                self.history.capture(instance, data, database, force=True)
            if not force and not self.history.ready(instance):
                return
            identity, key = self._identity(instance)
            self.history.synchronize(instance, identity, key, binding, self._remote, self._accepted, force)
            while self.history.pending.get(instance) and not self.stop.is_set():
                self.history.synchronize(instance, identity, key, binding, self._remote, self._accepted, force)
        except (ApiError, OSError, sqlite3.Error, ValueError, TypeError) as error:
            with self.lock:
                self.statuses[instance] = '行动力历史等待补传：' + str(error)
            if force:
                raise

    def _sync_instance(self, instance, force):
        stamp, attempts = None, 0
        try:
            with self.lock:
                binding = self.bindings.get(instance)
            if not binding:
                return
            record = self._read_snapshot(instance)
            if not record:
                raise ApiError('QUOTE_MISSING', '当前实例尚无行动力记录，请等待游戏任务更新')
            stamp = (record['observedAt'], record['actionPoints'])
            with self.lock:
                attempts, retry_at = self.attempts.get(instance, {}).get(stamp, (0, 0))
                done = self.uploaded.get(instance) == stamp
            if done:
                return
            if not force and time.monotonic() < retry_at:
                return
            if record['observedAt'] < time.time() - 86400:
                return  # 旧记录由整月历史接口补传，实时接口只接收新鲜报价。
            if binding['url'] != exchange_url():
                raise ApiError('STOCK_ORIGIN_CHANGED', '交易所地址与绑定地址不一致，已停止转发')
            identity, key = self._identity(instance)
            report = make_report(identity, key, record['actionPoints'], record['observedAt'])
            self._accepted(self._remote('/quotes', 'POST', {'report': report}, binding['uploadToken'], binding['bindingKey']))
            with self.lock:
                self.uploaded[instance] = stamp
                self.last_upload[instance] = time.monotonic()
                self.statuses[instance] = '行动力已同步；后台等待新记录'
                self.attempts.pop(instance, None)
        except (ApiError, OSError, ValueError, TypeError) as error:
            with self.lock:
                self.statuses[instance] = str(error)
                self.attempts[instance] = {stamp: (attempts + 1, time.monotonic() + min(60, 2 ** min(attempts, 6)))}
            if force:
                raise

    def _run(self):
        try:
            while not self.stop.wait(.25):
                self.sync_once()
        finally:
            self.history.close()
