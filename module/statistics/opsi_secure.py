"""大世界统计的本地存储支持与旧加密数据的自动解密。

统计载荷存在两代历史加密格式：V1（`OPSIV1.`，本机 DPAPI 密钥）与
V2（`OPSIV2.XCHACHA20-POLY1305.`，本机凭据/设备封装密钥）。2026-10 起
统计不再加密：载荷直接以明文 JSON 存放在既有列与文件位形里
（cl1_data.secure_json、opsi_items.secure_payload、resource_snapshots.opsi_payload、
daily_summary_cl1_events.secure_payload 存 JSON 文本，daily_summary_periods.report_text
存正文文本，日志文件为普通 JSON/CSV）。

本模块保留两类职责：
1. 明文载荷的编解码、原子文件写出与统计写事务；
2. 旧密文的兼容读取与一次性解密：启动时 initialize() 有界地尝试把全部密文
   解密为明文，确认无残留后才移除描述文件并撤销本机密钥；密钥暂不可用时
   按原样保留，读取路径与后续启动自动重试（可用性优先，绝不丢数据）。
"""
from __future__ import annotations
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path

import portalocker
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from Crypto.Cipher import AES, ChaCha20_Poly1305
from module.statistics.opsi_keys import (ContainerFileProvider, ProviderUnavailable, installation_slot,
                                         provider_for_descriptor)
from module.logger import logger

CL1_SECURE_FIELDS = frozenset({
    'battle_count',
    'akashi_encounters',
    'akashi_ap',
    'akashi_ap_entries',
    'ap_snapshots',
    'last_ap_notification',
    'yellow_coin_snapshots',
    'coins_snapshots',
    'coins_history_version',
    'coins_cleanup_version',
    'meow_battle_raw_count',
    'meow_battle_count',
    'meow_round_times',
    'meow_battle_times',
    'meow_hazard_stats',
    'siren_research_devices',
    'siren_research_device_entries',
})

LOOT_SECURE_FIELDS = ('server', 'zone', 'zone_type', 'zone_id', 'item', 'amount', 'tag', 'hazard_level', 'combat_count')

RES_SECURE_FIELDS = ('action_point', 'yellow_coin', 'purple_coin')

LEGACY_PREFIX = 'OPSIV1.'
ALGORITHM = 'XCHACHA20-POLY1305'
BLOB_PREFIX = 'OPSIV2.' + ALGORITHM + '.'
LEGACY_WRAPPER_KEY = '__opsi_secure_v1__'
WRAPPER_KEY = '__opsi_secure_v2__'
MISSING_MARKER = '__opsi_secure_missing__'

# 加密时代的辅助对象（触发器与辅助表），解密迁移时连同触发器一并移除。
AUX_PREFIX = '__opsi_'
DATABASE_NAMES = ('cl1_data.db', 'azurstats_local.db', 'daily_summary.db')
# 加密时代可能存放密文的位置：(库文件名, 表, 列, 载荷类别)。
DATABASE_LAYOUT = (
    ('cl1_data.db', 'cl1_data', 'secure_json', 'cl1'),
    ('azurstats_local.db', 'opsi_items', 'secure_payload', 'loot'),
    ('azurstats_local.db', 'resource_snapshots', 'opsi_payload', 'res'),
    ('daily_summary.db', 'daily_summary_cl1_events', 'secure_payload', 'daily'),
    ('daily_summary.db', 'daily_summary_periods', 'report_text', 'reports'),
)
# 加密时代收尾遗留的标记文件：数据解密完成后一并移除。
RESIDUE_FILES = ('keyring.json', 'pending.json', 'wipe.json', 'integrity.json', 'transition.bin', 'state.json')

MIGRATION_LOCK_TIMEOUT = 20.0
DECODER_RETRY_INTERVAL = 60.0


class StoreError(RuntimeError):
    """统计存储错误基类。"""


class StoreUnavailable(StoreError):
    """统计运行环境暂不可用（旧密文尚未解密、载荷不可读等）。"""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def serialize_obj(obj):
    """把统计载荷编码为存储文本（明文 JSON）。"""
    return canonical(obj).decode('utf-8')


def _b64d(text):
    return base64.b64decode(text, validate=True)


def _subkey(key, info):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info.encode()).derive(key)


def _decrypt(key, value, aad):
    """解密一条 V2 记录；失败抛出 ValueError（调用方按不可读处理）。"""
    raw = _b64d(value)
    if len(raw) < 40:
        raise ValueError('记录长度不合法')
    cipher = ChaCha20_Poly1305.new(key=key, nonce=raw[:24])
    cipher.update(canonical(aad))
    return cipher.decrypt_and_verify(raw[24:-16], raw[-16:])


def is_ciphertext(value):
    """值是否为旧加密载荷（V1/V2 前缀）。"""
    return isinstance(value, str) and value.startswith((BLOB_PREFIX, LEGACY_PREFIX))


def partition_cl1(data):
    return ({k: v for k, v in data.items() if k not in CL1_SECURE_FIELDS},
            {k: v for k, v in data.items() if k in CL1_SECURE_FIELDS})


def row_context(kind, row):
    if kind == 'cl1':
        return {'dataset': kind, 'instance': row['instance'], 'identity': row['month'], 'period': row['month']}
    stamp = row.get('ts') if kind in ('res', 'daily') else row.get('created_at')
    if isinstance(stamp, (int, float)):
        from datetime import datetime, timezone
        stamp = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
    return {'dataset': kind, 'instance': row.get('instance'), 'identity': str(row['id']),
            'period': str(stamp or '')[:7], 'stamp': stamp,
            'imgid': row.get('imgid'), 'device': row.get('device_id'), 'genre': row.get('genre')}


def report_context(instance, period):
    month = re.search(r'\d{4}-\d{2}', period)
    return {'dataset': 'reports', 'instance': instance, 'identity': str(period), 'period': month[0] if month else period}


def file_context(root, kind, path, instance=None):
    path = Path(path).resolve()
    relative = str(path.relative_to(Path(root).resolve())).replace('\\', '/')
    # 缓存与舰船文件覆盖多个月，逻辑周期属于整个历史集合。
    return {'dataset': kind, 'instance': instance if instance is not None else relative,
            'identity': relative, 'period': 'all-history'}


def durable_write(path, data):
    """原子写出文件：同目录临时文件 + fsync + replace。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + os.urandom(12).hex() + '.stage')
    try:
        with open(temp, 'xb') as stream:
            stream.write(data if isinstance(data, bytes) else data.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        if os.name != 'nt':
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def immediate_transaction(conn):
    """统计写事务：BEGIN IMMEDIATE 取写锁，跨线程与跨进程串行化读改写。"""
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def database_paths(root):
    return [Path(root) / 'config' / name for name in DATABASE_NAMES]


def protected_files(root):
    """登记过的统计文件（舰船经验、月度 JSON 与 farming CSV 及其备份）。"""
    root = Path(root)
    files = set()
    cl1 = root / 'log' / 'cl1'
    for pattern in ('*/ship_exp_data.json', '*/ship_exp_data.json.bak',
                    '*/cl1_monthly.json', '*/cl1_monthly.json.bak'):
        files.update(cl1.glob(pattern))
    for pattern in ('azurstat_meowofficer_farming*.csv', 'azurstat_meowofficer_farming*.csv.bak'):
        files.update((root / 'log').glob(pattern))
    return sorted(files)


def _file_kind(path):
    if 'cl1_monthly' in path.name:
        return 'archives'
    return 'ships' if '.json' in path.name else 'loot'


def archive_files(root):
    """备份目录里的受保护归档（加密时代为包装文件）。"""
    base = Path(root) / 'AzurPilot_Data_Backup'
    if not base.exists():
        return []
    result = []
    for path in base.rglob('*'):
        if not path.is_file():
            continue
        if path.name in DATABASE_NAMES or (path.parent.name == 'opsi_secure' and path.suffix == '.json'):
            result.append(path)
    return sorted(result)


class _VaultKeys:
    """旧加密环境的密钥材料（按需加载，进程内缓存）。

    - V2：按描述文件恢复当时的凭据提供者并读取状态；本机按当前安装槽读不到时，
      枚举同 installation_id 的状态找回（安装目录被移动或复制后的解密路径）。
    - V1：描述文件自带 DPAPI 保护的本地密钥。
    任一步失败都只记录一次并按间隔重试（进入系统后钥匙串或凭据服务可能才可用）。
    """

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / 'config' / 'opsi_secure'
        self._tried = False
        self._next_retry = 0.0
        self._provider = None
        self._state = None
        self._slot = None
        self._dek = None
        self._legacy = None
        # 最近一次尝试里出现过"暂时性"失败（凭据服务报错、描述文件读不出）：
        # 这种环境下不能把解不开的旧载荷当作不可救，必须保留原样等重试。
        self._blips = True

    def _keyring(self):
        try:
            value = json.loads((self.directory / 'keyring.json').read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError):
            logger.warning('[统计-解密] 统计描述文件不可读，旧密文保持原样')
            return None
        return value if isinstance(value, dict) else None

    def _legacy_key(self, ring):
        """V1 描述文件里的 DPAPI 本地密钥（含完整性校验）。"""
        try:
            key = _dpapi(_b64d(ring['wrapped_local']), decrypt=True)
        except Exception:
            return None
        payload = {k: v for k, v in ring.items() if k != 'mac'}
        mac_key = _subkey(key, 'opsi-stats/v1/keyring-mac')
        mac = hmac.new(mac_key, canonical(payload), hashlib.sha256).hexdigest()
        if len(key) != 32 or not hmac.compare_digest(mac, str(ring.get('mac', ''))):
            return None
        return key

    def _ensure(self):
        now = time.monotonic()
        if self._dek is not None or self._legacy is not None:
            return
        if self._tried and now < self._next_retry:
            return
        self._tried = True
        self._next_retry = now + DECODER_RETRY_INTERVAL
        self._blips = False
        ring = self._keyring()
        if ring is None and (self.directory / 'keyring.json').exists():
            self._blips = True
        slot = installation_slot(self.root)
        self._slot = slot
        if isinstance(ring, dict) and ring.get('version') == 1:
            self._legacy = self._legacy_key(ring)
            if self._legacy is None:
                self._blips = True
        provider = provider_for_descriptor(ring.get('provider') if ring else None, self.directory)
        if provider is None:
            if ring is not None:
                logger.warning(f'[统计-解密] 描述文件的凭据提供者不受支持（{ring.get("provider")}），旧密文保持原样')
            if self._legacy is None:
                return
        else:
            self._provider = provider
            try:
                state = provider.load(slot)
            except ProviderUnavailable:
                state = None
                self._blips = True
            if state is None and isinstance(ring, dict) and ring.get('installation_id'):
                try:
                    state = provider.load_any(slot, ring['installation_id'])
                except ProviderUnavailable:
                    state = None
                    self._blips = True
                if state is not None:
                    logger.warning('[统计-解密] 当前安装槽没有本机凭据，已按安装标识找回（安装目录可能被移动过）')
            if state is None and not isinstance(provider, ContainerFileProvider):
                # 描述文件缺失或提供者不可用时，再试数据目录内的本地文件状态。
                container = ContainerFileProvider(self.directory / 'state.json')
                try:
                    state = container.load(slot)
                except ProviderUnavailable:
                    state = None
                    self._blips = True
                if state is not None:
                    self._provider = container
            if state is not None:
                self._state = state
                try:
                    self._dek = provider.key(state)
                except (ProviderUnavailable, ValueError, KeyError, TypeError):
                    self._dek = None
                    self._blips = True
                if self._dek is None and self._provider is not provider:
                    try:
                        self._dek = self._provider.key(state)
                    except (ProviderUnavailable, ValueError, KeyError, TypeError):
                        self._dek = None
            if self._dek is not None:
                self._blips = False
        if self._dek is None and self._legacy is None and (ring is not None or self._state is not None):
            logger.warning('[统计-解密] 本机密钥暂不可用，旧密文保持原样，稍后自动重试')

    def retry(self):
        """显式重试：丢弃失败缓存后重新加载（启动解密入口使用，读取路径仍按间隔限频）。"""
        if self._dek is None and self._legacy is None:
            self._tried = False
        self._ensure()

    def available(self):
        self._ensure()
        return self._dek is not None or self._legacy is not None

    def definitive(self):
        """密钥已可用，或已确认本机不存在能解密的旧密钥（干净的未命中）。

        凭据服务报错的"暂时不可用"返回 False：调用方应保留原样等重试，
        不能把还救得回的旧载荷替换掉。
        """
        self._ensure()
        return self._dek is not None or self._legacy is not None or not self._blips

    def decrypt_record(self, kind, value, context):
        """旧密文 → 载荷字典；当前不可读时返回 None。"""
        self._ensure()
        if value.startswith(BLOB_PREFIX):
            if self._dek is None or not context or not self._state:
                return None
            aad = dict(context, schema=2, algorithm=ALGORITHM,
                       installation_id=self._state.get('installation_id'))
            try:
                return json.loads(_decrypt(_subkey(self._dek, 'opsi-stats/v2/' + kind),
                                           value[len(BLOB_PREFIX):], aad))
            except (ValueError, TypeError, UnicodeError):
                return None
        if value.startswith(LEGACY_PREFIX):
            if self._legacy is None:
                return None
            try:
                raw = _b64d(value[len(LEGACY_PREFIX):])
                cipher = AES.new(_subkey(self._legacy, 'opsi-stats/v1/' + kind), AES.MODE_GCM, nonce=raw[:12])
                cipher.update(('opsi-stats/v1/' + kind).encode())
                return json.loads(cipher.decrypt_and_verify(raw[12:-16], raw[-16:]))
            except (ValueError, TypeError, UnicodeError):
                return None
        return None


def _dpapi(data, decrypt=False):
    from module.runtime.account_local import dpapi
    return dpapi(data, decrypt=decrypt)


class StatsStore:
    """统计存储句柄：根目录与读取兼容入口。"""

    def __init__(self, root=None):
        self.root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
        self._keys = None

    @property
    def directory(self):
        return self.root / 'config' / 'opsi_secure'

    def vault_keys(self):
        if self._keys is None:
            self._keys = _VaultKeys(self.root)
        return self._keys


_STORE = None


def get_store():
    global _STORE
    if _STORE is None:
        _STORE = StatsStore()
    return _STORE


def set_store(store):
    global _STORE
    _STORE = store


def decode_record(kind, value, context=None):
    """读取一条统计载荷：明文 JSON 直接解析；旧密文尝试解密，失败返回 None。"""
    if not isinstance(value, str) or not value:
        return None
    if is_ciphertext(value):
        return get_store().vault_keys().decrypt_record(kind, value, context)
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def decode_text(value, context=None):
    """读取日报正文：明文即正文；旧密文解密出 {'text': ...}。"""
    if not isinstance(value, str) or not value:
        return None
    if is_ciphertext(value):
        payload = get_store().vault_keys().decrypt_record('reports', value, context)
        text = payload.get('text') if isinstance(payload, dict) else None
        return text if isinstance(text, str) else None
    return value


def decode_file_payload(kind, path, data, root=None):
    """读取统计文件载荷：普通 JSON 直接返回；旧包装解开并解密，失败返回 None。"""
    if not isinstance(data, dict):
        return None
    if not (data.get(WRAPPER_KEY) or data.get(LEGACY_WRAPPER_KEY)):
        return data
    payload = data.get('payload')
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            context = file_context(root or get_store().root, kind, path)
        except ValueError:
            return None
        return get_store().vault_keys().decrypt_record(kind, payload, context)
    return None


def write_file(kind, path, data):
    """原子写出统计文件：字典写 JSON 文本，字符串原样写。"""
    raw = canonical(data) if isinstance(data, (dict, list)) else str(data).encode('utf-8')
    durable_write(path, raw)


def quarantine_unreadable(kind, identity, value):
    """把无法读取的旧载荷另存到旁路备份文件（原样保留，绝不销毁）；返回存放路径。

    仅在本机确认解不开（密钥可用但记录解不开，或干净的凭据未命中）时调用；
    调用方之后按现状继续写入，避免单条旧数据永久冻结整个统计。
    """
    directory = get_store().directory
    directory.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        payload, encoding = base64.b64encode(value).decode('ascii'), 'base64'
    else:
        payload, encoding = value, 'text'
    target = directory / f'unreadable-{time.strftime("%Y%m%d-%H%M%S")}-{os.urandom(3).hex()}.json'
    durable_write(target, canonical({'kind': kind, 'identity': str(identity), 'encoding': encoding,
                                     'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'payload': payload}))
    logger.warning(f'[统计-解密] 旧数据无法在本机解密，已另存备份并按现状继续写入: {identity} -> {target}')
    return target


# ---- 旧密文的一次性解密 ----

def _database_rows(conn, path):
    """按登记位置清点库内密文行，yield (table, column, kind, rowid, value)。"""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for name, table, column, kind in DATABASE_LAYOUT:
        if name != Path(path).name or table not in tables:
            continue
        columns = [row[1] for row in conn.execute('PRAGMA table_info(' + table + ')')]
        if column not in columns:
            continue
        for rowid, value in conn.execute(f'SELECT rowid, {column} FROM {table}').fetchall():
            if is_ciphertext(value):
                yield table, column, kind, rowid, value


def pending_blobs(root):
    """清点仍处于加密态的位置；返回位置描述列表，空列表表示没有密文。"""
    root = Path(root).resolve()
    pending = []
    for path in database_paths(root):
        if not path.exists():
            continue
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
                counts = {}
                for table, _, _, _, _ in _database_rows(conn, path):
                    counts[table] = counts.get(table, 0) + 1
                for table, count in sorted(counts.items()):
                    pending.append(f'{path.name}:{table}×{count}')
        except sqlite3.Error as exc:
            # 读不了就不能断言"没有密文"：按待处理对待，下次再试。
            pending.append(f'{path.name}（{type(exc).__name__}）')
    for path in [*protected_files(root), *archive_files(root)]:
        try:
            with path.open('rb') as stream:
                head = stream.read(64)
        except OSError:
            # 读不了就不能断言"没有密文"：按待处理对待。
            pending.append(str(path.relative_to(root)))
            continue
        if head.startswith((f'{{"{LEGACY_WRAPPER_KEY}"'.encode(), f'{{"{WRAPPER_KEY}"'.encode())):
            pending.append(str(path.relative_to(root)))
            continue
        try:
            with path.open(encoding='utf-8') as stream:
                text = stream.read(64)
        except (OSError, UnicodeError):
            continue
        if text.startswith((BLOB_PREFIX, LEGACY_PREFIX)):
            pending.append(str(path.relative_to(root)))
    return pending


def _row_context_for(kind, row):
    if kind == 'reports':
        return report_context(row['instance'], row['period_key'])
    return row_context(kind, row)


def _decrypt_database(conn, path, keys, quarantined):
    """解密一个库文件里的全部密文行；返回解密行数。不可读行按原样保留并记入隔离。"""
    done = 0
    columns_cache = {}
    for table, column, kind, rowid, value in _database_rows(conn, path):
        if table not in columns_cache:
            columns_cache[table] = [r[1] for r in conn.execute('PRAGMA table_info(' + table + ')')]
        try:
            row = dict(zip(columns_cache[table],
                           conn.execute(f'SELECT * FROM {table} WHERE rowid=?', (rowid,)).fetchone()))
            payload = keys.decrypt_record(kind, value, _row_context_for(kind, row))
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            payload = None
        updated = None
        if isinstance(payload, dict):
            if kind == 'reports':
                text = payload.get('text')
                updated = text if isinstance(text, str) else None
            else:
                updated = serialize_obj(payload)
        if updated is None:
            quarantined.append(f'{Path(path).name}:{table}#{rowid}')
            continue
        conn.execute(f'UPDATE {table} SET {column}=? WHERE rowid=?', (updated, rowid))
        done += 1
    return done


def _drop_aux_objects(conn):
    """移除加密时代的触发器与辅助表。

    触发器引用辅助表，必须一并移除（先触发器后表），否则后续写入会失败。
    """
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND substr(name,1,7)=?",
                                (AUX_PREFIX,)).fetchall():
        conn.execute('DROP TRIGGER IF EXISTS "' + name.replace('"', '""') + '"')
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND substr(name,1,7)=?",
                                (AUX_PREFIX,)).fetchall():
        conn.execute('DROP TABLE IF EXISTS "' + name.replace('"', '""') + '"')


def _payload_to_csv(payload):
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(payload.get('header') or [])
    for row in payload.get('rows') or []:
        writer.writerow(row)
    return stream.getvalue().encode('utf-8')


def _decode_file_blob(root, path, kind, payload, keys):
    """解密文件载荷；`.bak` 是主文件的字节拷贝，身份绑定主文件，失败时按主文件重试。"""
    opened = keys.decrypt_record(kind, payload, file_context(root, kind, path))
    if opened is None and path.name.endswith('.bak'):
        base = path.with_name(path.name[:-len('.bak')])
        opened = keys.decrypt_record(kind, payload, file_context(root, kind, base))
    return opened


def _decrypt_file(root, path, keys, quarantined):
    """解密一个统计文件（JSON 包装或整体密文）；返回是否已改写。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    kind = _file_kind(path)
    if raw[:1] == b'{':
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            return False
        if not (isinstance(data, dict) and (data.get(WRAPPER_KEY) or data.get(LEGACY_WRAPPER_KEY))):
            return False
        payload = data.get('payload')
        if isinstance(payload, dict):
            opened = payload
        elif isinstance(payload, str):
            opened = _decode_file_blob(root, path, kind, payload, keys)
        else:
            opened = None
        if not isinstance(opened, dict):
            quarantined.append(str(path.relative_to(root)))
            return False
        durable_write(path, canonical(opened))
        return True
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        return False
    if not is_ciphertext(text):
        return False
    opened = _decode_file_blob(root, path, kind, text, keys)
    if not isinstance(opened, dict) or not isinstance(opened.get('rows'), list):
        quarantined.append(str(path.relative_to(root)))
        return False
    durable_write(path, _payload_to_csv(opened))
    return True


def _decrypt_database_image(image, name, keys, quarantined):
    """解密归档库映像内部的行与辅助对象，返回 (新映像, 解密行数)。"""
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.deserialize(image)
        done = _decrypt_database(conn, Path(name), keys, quarantined)
        _drop_aux_objects(conn)
        conn.commit()
        return conn.serialize(), done


def _decrypt_archive(root, path, keys, quarantined):
    """解密备份目录里的一个归档包装；返回解密处数。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return 0
    if raw[:1] != b'{':
        return 0
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        return 0
    if not (isinstance(data, dict) and (data.get(WRAPPER_KEY) or data.get(LEGACY_WRAPPER_KEY))):
        return 0
    payload = data.get('payload')
    if isinstance(payload, dict):
        opened = payload
    elif isinstance(payload, str):
        opened = keys.decrypt_record('archives', payload, file_context(root, 'archives', path))
    else:
        opened = None
    if not isinstance(opened, dict) or not isinstance(opened.get('bytes'), str):
        quarantined.append(str(path.relative_to(root)))
        return 0
    try:
        content = _b64d(opened['bytes'])
    except (ValueError, TypeError):
        quarantined.append(str(path.relative_to(root)))
        return 0
    if path.name in DATABASE_NAMES and content[:16] == b'SQLite format 3\x00':
        try:
            content, _ = _decrypt_database_image(content, path.name, keys, quarantined)
        except sqlite3.Error:
            quarantined.append(str(path.relative_to(root)))
            return 0
    durable_write(path, content)
    return 1


def _decrypt_all_databases(root, keys, quarantined):
    done = 0
    for path in database_paths(root):
        if not path.exists():
            continue
        try:
            with closing(sqlite3.connect(path, timeout=10)) as conn:
                conn.execute('BEGIN IMMEDIATE')
                done += _decrypt_database(conn, path, keys, quarantined)
                _drop_aux_objects(conn)
                conn.commit()
        except sqlite3.Error as exc:
            logger.warning(f'[统计-解密] {path.name} 暂时无法处理（{type(exc).__name__}），本次保留原样')
    return done


def _decrypt_all_files(root, keys, quarantined):
    done = 0
    for path in protected_files(root):
        if _decrypt_file(root, path, keys, quarantined):
            done += 1
    return done


def _decrypt_all_archives(root, keys, quarantined):
    done = 0
    for path in archive_files(root):
        done += _decrypt_archive(root, path, keys, quarantined)
    return done


def _cleanup_encryption(keys, root):
    """解密完成后的收尾：移除描述文件与标记文件，撤销本机密钥。"""
    directory = Path(root) / 'config' / 'opsi_secure'
    provider, slot = keys._provider, keys._slot
    for name in RESIDUE_FILES:
        (directory / name).unlink(missing_ok=True)
    if provider is not None and slot is not None:
        try:
            provider.delete(slot)
        except (ProviderUnavailable, OSError) as exc:
            logger.warning(f'[统计-解密] 本机统计密钥未能撤销（{type(exc).__name__}），描述文件已移除')
    rescue = sorted(path for path in directory.glob('rescue-*') if path.is_dir())
    if rescue:
        logger.warning(f'[统计-解密] 检测到 {len(rescue)} 个历史清空备份目录（rescue-*），按原样保留')


def _finish_if_clean(root):
    """无密文但仍有加密时代残留文件时的收尾（上次收尾被中断）。"""
    directory = Path(root) / 'config' / 'opsi_secure'
    if not directory.exists():
        return False
    if not any((directory / name).exists() for name in RESIDUE_FILES):
        return False
    keys = get_store().vault_keys()
    keys._ensure()
    _cleanup_encryption(keys, root)
    return True


def decrypt_all():
    """把本机全部旧密文解密为明文；可用性优先，失败保持原样等待重试。

    Returns:
        dict: {'pending': bool, 'decrypted': int, 'quarantined': int}
    """
    root = get_store().root
    pending = pending_blobs(root)
    if not pending:
        if _finish_if_clean(root):
            logger.info('[统计-解密] 统计描述文件与旧密钥已移除（历史数据均为明文）')
        return {'pending': False, 'decrypted': 0, 'quarantined': 0}
    keys = get_store().vault_keys()
    keys.retry()
    if not keys.available():
        logger.warning(f'[统计-解密] 检测到 {len(pending)} 处旧加密数据，但本机密钥暂不可用；保持原样稍后自动重试')
        return {'pending': True, 'decrypted': 0, 'quarantined': 0}
    directory = root / 'config' / 'opsi_secure'
    directory.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(str(directory / 'migration.lock'), timeout=MIGRATION_LOCK_TIMEOUT):
        if not pending_blobs(root):
            if _finish_if_clean(root):
                logger.info('[统计-解密] 统计描述文件与旧密钥已移除（历史数据均为明文）')
            return {'pending': False, 'decrypted': 0, 'quarantined': 0}
        quarantined = []
        decrypted = _decrypt_all_databases(root, keys, quarantined)
        decrypted += _decrypt_all_files(root, keys, quarantined)
        decrypted += _decrypt_all_archives(root, keys, quarantined)
        leftovers = pending_blobs(root)
        if leftovers or quarantined:
            blocked = quarantined + leftovers
            preview = '、'.join(blocked[:5]) + ('、…' if len(blocked) > 5 else '')
            # 两轮名单会重复收录同一位置（行级隔离条目与只读重扫），按较大者计处数。
            count = max(len(quarantined), len(leftovers))
            logger.warning(f'[统计-解密] 仍有 {count} 处旧数据暂无法解密，已按原样保留: {preview}')
            return {'pending': True, 'decrypted': decrypted, 'quarantined': count}
        _cleanup_encryption(keys, root)
        logger.info(f'[统计-解密] 历史加密数据已全部解密为明文（{decrypted} 处），统计加密环境已移除')
        return {'pending': False, 'decrypted': decrypted, 'quarantined': 0}


_INIT_DONE = None


def initialize(timeout=30.0):
    """启动钩子：有界等待旧统计密文自动解密完成。

    解密包含本机凭据与磁盘 I/O；异常环境（锁竞争、凭据服务未就绪）不允许
    拖住应用启动——超时后解密转入后台继续，统计读写不依赖它。
    """
    global _INIT_DONE
    if _INIT_DONE is not None:
        return _INIT_DONE
    result = {}

    def worker():
        try:
            result.update(decrypt_all())
        except Exception:
            logger.exception('[统计-解密] 启动解密未完成（稍后自动重试）')

    thread = threading.Thread(target=worker, name='statistics-decrypt', daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        logger.warning(f'[统计-解密] 旧统计数据处理超过 {int(timeout)} 秒未完成，转入后台继续（不阻塞本次启动）')
        return False
    _INIT_DONE = bool(result) and result.get('pending') is False
    return _INIT_DONE
