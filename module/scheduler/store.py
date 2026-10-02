"""按实例隔离的 SQLite 调度存储，JSON 仅用于图文档和分享格式。"""
import copy
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path
from uuid import uuid4

from module.config.transaction import config_transaction
from module.scheduler.templates import default_program


class ConflictError(Exception):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class ProgramStore:
    def __init__(self, directory='config'):
        self.directory = Path(directory).absolute() / 'scheduler'

    def path(self, instance, kind=None):
        from module.api.config_service import validate_name
        if validate_name(instance) != instance:
            raise ValueError('实例名不是规范形式')
        path = self.directory / f'{instance}.sqlite3'
        # 只解析父目录；Windows 在其他线程首次创建文件时解析文件本身可能返回不同的路径形式。
        if path.is_symlink() or os.path.normcase(str(path.parent.resolve())) != os.path.normcase(str(self.directory.resolve())):
            raise ValueError('调度路径无效')
        return path

    @contextmanager
    def connection(self, instance, write=False):
        path = self.path(instance)
        legacy = self.directory / 'programs' / f'{instance}.json'
        if not path.exists() and not write and not legacy.exists():
            yield None
            return
        write = write or legacy.exists()
        if write or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        with config_transaction(path):
            connection = sqlite3.connect(path, timeout=10) if write else sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True, timeout=10)
            connection.row_factory = sqlite3.Row
            try:
                if connection.execute('PRAGMA user_version').fetchone()[0] > 1:
                    raise ValueError('调度数据库版本高于当前程序支持版本')
                if write:
                    connection.execute('PRAGMA journal_mode=WAL')
                    connection.execute('PRAGMA synchronous=FULL')
                    connection.executescript('''
                    CREATE TABLE IF NOT EXISTS programs (
                        id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL,
                        draft TEXT NOT NULL, active TEXT, generation INTEGER NOT NULL,
                        revision TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS variables (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS records (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS runtime (id INTEGER PRIMARY KEY CHECK(id=1), in_flight TEXT);
                    CREATE TABLE IF NOT EXISTS observations (
                        resource TEXT PRIMARY KEY, value REAL, resource_limit REAL, total REAL,
                        observed_at TEXT NOT NULL, source TEXT NOT NULL);
                    PRAGMA user_version=1;
                ''')
                connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                if write and legacy.exists() and not connection.execute('SELECT 1 FROM programs').fetchone():
                    self._migrate(connection, instance)
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
            # 事务成功后保留迁移备份，避免删除数据库后重新导入旧方案。
            for kind in ('programs', 'variables', 'observations'):
                old = self.directory / kind / f'{instance}.json'
                if old.exists():
                    old.replace(old.with_suffix('.json.migrated'))

    @staticmethod
    def default():
        return {'mode': 'native', 'draft': default_program().model_dump(), 'active': None, 'generation': 0}

    @staticmethod
    def _read_program(connection):
        row = connection.execute('SELECT * FROM programs WHERE id=1').fetchone() if connection else None
        if row:
            return {'mode': row['mode'], 'draft': json.loads(row['draft']),
                    'active': json.loads(row['active']) if row['active'] else None,
                    'generation': row['generation'], 'revision': row['revision']}
        data = ProgramStore.default()
        return {**data, 'revision': hashlib.sha256(encode(data).encode()).hexdigest()}

    @staticmethod
    def _write_program(connection, data):
        connection.execute('INSERT OR REPLACE INTO programs VALUES (1, ?, ?, ?, ?, ?)', (
            data['mode'], encode(data['draft']), encode(data['active']) if data.get('active') else None,
            data['generation'], uuid4().hex))

    def _migrate(self, connection, instance):
        """兼容开发版 JSON，三类数据在同一事务内迁移。"""
        def read(kind):
            path = self.directory / kind / f'{instance}.json'
            if path.is_symlink() or path.resolve().parent != self.directory / kind:
                raise ValueError('旧调度路径无效')
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        data = read('programs')
        if data:
            self._write_program(connection, data)
        self._write_persistent(connection, read('variables'))
        for name, observation in read('observations').items():
            self._write_observation(connection, name, observation, observation['observedAt'], observation['source'])

    def exists(self, instance):
        with self.connection(instance) as connection:
            return bool(connection and connection.execute('SELECT 1 FROM programs WHERE id=1').fetchone())

    def get(self, instance):
        with self.connection(instance) as connection:
            return self._read_program(connection)

    def update(self, instance, revision, **changes):
        with self.connection(instance, write=True) as connection:
            current = self._read_program(connection)
            if current.pop('revision') != revision:
                raise ConflictError('调度方案已被其他窗口修改，请重新加载')
            current.update(copy.deepcopy(changes))
            self._write_program(connection, current)
            result = self._read_program(connection)
        return result

    @staticmethod
    def import_bundle(data):
        """方案格式只允许定义与模式，不接收运行变量、资源或账号信息。"""
        from module.scheduler.models import ProgramDocument
        if not isinstance(data, dict) or set(data) - {'mode', 'draft', 'active'} or data.get('mode') not in ('native', 'enhance', 'takeover'):
            raise ValueError('调度导入格式无效')
        draft = ProgramDocument.model_validate(data['draft'])
        active = ProgramDocument.model_validate(data['active']) if data.get('active') else None
        if data['mode'] != 'native':
            from module.scheduler.validation import validate
            if not active or not validate(active, mode=data['mode'])['valid']:
                raise ValueError('已应用的调度程序未通过校验')
        return {'mode': data['mode'], 'draft': draft.model_dump(), 'active': active.model_dump() if active else None, 'generation': 0}

    def export(self, instance):
        document = self.get(instance)
        return {key: document[key] for key in ('mode', 'draft', 'active')}

    def import_program(self, instance, data):
        with self.connection(instance, write=True) as connection:
            self._write_program(connection, self.import_bundle(data))

    def persistent(self, instance):
        with self.connection(instance) as connection:
            if not connection:
                return {}
            data = {kind: {row['name']: json.loads(row['value']) for row in connection.execute(f'SELECT * FROM {kind}')}
                    for kind in ('variables', 'records')}
            row = connection.execute('SELECT in_flight FROM runtime WHERE id=1').fetchone()
            if row and row['in_flight']:
                data['inFlight'] = row['in_flight']
            return data if any(data.values()) else {}

    @staticmethod
    def _write_persistent(connection, data):
        for kind in ('variables', 'records'):
            connection.execute(f'DELETE FROM {kind}')
            connection.executemany(f'INSERT INTO {kind} VALUES (?, ?)', [(key, encode(value)) for key, value in data.get(kind, {}).items()])
        connection.execute('INSERT OR REPLACE INTO runtime VALUES (1, ?)', (data.get('inFlight'),))

    def save_persistent(self, instance, data):
        with self.connection(instance, write=True) as connection:
            self._write_persistent(connection, data)

    def observations(self, instance):
        with self.connection(instance) as connection:
            if not connection:
                return {}
            return {row['resource']: {'Value': row['value'], 'Limit': row['resource_limit'], 'Total': row['total'],
                    'observedAt': row['observed_at'], 'source': row['source']}
                    for row in connection.execute('SELECT * FROM observations')}

    @staticmethod
    def _write_observation(connection, name, value, timestamp, source):
        values = value if isinstance(value, dict) else {'Value': value}
        connection.execute('''INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(resource) DO UPDATE SET value=excluded.value,
            resource_limit=COALESCE(excluded.resource_limit,observations.resource_limit),
            total=COALESCE(excluded.total,observations.total), observed_at=excluded.observed_at, source=excluded.source''',
            (name, values.get('Value'), values.get('Limit'), values.get('Total'), timestamp, source))

    def observe(self, instance, name, value, timestamp, source):
        with self.connection(instance, write=True) as connection:
            self._write_observation(connection, name, value, timestamp, source)

    def copy(self, source, target):
        if self.exists(source):
            self.import_program(target, self.export(source))

    def backup(self, instance, target):
        """原生备份包含已提交的 WAL 数据，不直接复制正在使用的数据库。"""
        path, target = self.path(instance), Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f'{target.name}.{uuid4().hex}.tmp')
        try:
            with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as source, closing(sqlite3.connect(temporary)) as destination:
                source.backup(destination)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def archive(self, instance, backup):
        path = self.path(instance)
        if path.exists():
            with config_transaction(path):
                self.backup(instance, Path(backup) / 'scheduler' / path.name)
                for suffix in ('', '-wal', '-shm'):
                    path.with_name(path.name + suffix).unlink(missing_ok=True)
