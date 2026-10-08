"""按实例记录资源收支；明确交易与库存复核共享同一本账，避免重复累计。"""
import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from module.config.time_source import now
from module.logger import logger
from module.statistics import resource_stats

_session = ContextVar('resource_session', default=None)
ROOT = Path(__file__).resolve().parents[2]
ALIASES = {
    'Coins': 'Coin', 'Gems': 'Gem', 'Cubes': 'Cube', 'CognitiveChips': 'Chip',
    'GuildCoins': 'GuildCoin', 'Oil': 'Oil', 'Fuel': 'Oil',
    'YellowCoins': 'YellowCoin', 'PurpleCoins': 'PurpleCoin',
    'pt': 'Pt', 'URpt': 'URPt', 'DecorCoins': 'FurnitureCoin',
}
LABELS = {
    'Oil': '石油', 'Coin': '物资', 'Gem': '钻石', 'Cube': '心智魔方', 'Pt': '活动 PT',
    'Core': '核心数据', 'Medal': '荣誉勋章', 'Merit': '功勋', 'GuildCoin': '舰队币',
    'ActionPoint': '行动力', 'YellowCoin': '作战补给凭证', 'PurpleCoin': '特别兑换凭证',
    'Chip': '心智单元', 'Food': '后宅粮食',
    'URPt': '活动 UR 点数', 'FurnitureCoin': '家具币', 'GachaTicket': '建造券',
}


def canonical(name):
    return ALIASES.get(name, name)


def connect():
    """跟随现有统计库路径，测试可隔离替换；连接在事务结束时释放。"""
    Path(resource_stats._LOCAL_DB).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resource_stats._LOCAL_DB, timeout=30,
                                 factory=resource_stats._ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS resource_flows (
            id INTEGER PRIMARY KEY, instance TEXT NOT NULL, ts TEXT NOT NULL,
            resource TEXT NOT NULL, amount INTEGER NOT NULL, task TEXT NOT NULL,
            operation TEXT NOT NULL, evidence TEXT NOT NULL, run_id TEXT,
            event_key TEXT NOT NULL, UNIQUE(instance, event_key, resource)
        );
        CREATE INDEX IF NOT EXISTS resource_flows_window ON resource_flows(instance, ts, id);
        CREATE TABLE IF NOT EXISTS resource_balances (
            instance TEXT NOT NULL, resource TEXT NOT NULL, value INTEGER NOT NULL,
            ts TEXT NOT NULL, run_id TEXT, cursor INTEGER NOT NULL,
            PRIMARY KEY(instance, resource)
        );
    ''')
    return connection


@contextmanager
def task_session(instance, task):
    """每次调用有独立身份；异常、恢复及下一任务不会继承上一轮的归因。"""
    state = {'instance': instance, 'task': task, 'id': uuid4().hex, 'tracker': None, 'rewards': {}}
    token = _session.set(state)
    try:
        yield state
    finally:
        _session.reset(token)


def session_for(config):
    state = _session.get()
    return state if state and state['instance'] == getattr(config, 'config_name', None) else None


def record(config, changes, operation, *, evidence='confirmed', event_key=None, task=None):
    """只提交已确认的有符号变化；一次交易的各资源原子写入且支持幂等重放。"""
    instance = getattr(config, 'config_name', None)
    if not isinstance(instance, str):
        return False
    state = session_for(config)
    task = task or (state['task'] if state else getattr(getattr(config, 'task', None), 'command', None)) or 'Unattributed'
    event_key = event_key or uuid4().hex
    stamp = now().isoformat(sep=' ')
    rows = [(instance, stamp, canonical(name), amount, task, operation, evidence,
             state['id'] if state else None, event_key) for name, amount in changes.items()
            if isinstance(name, str) and name and not name.isdigit() and type(amount) is int and amount != 0]
    if not rows:
        return False
    try:
        with connect() as connection:
            connection.executemany('''INSERT OR IGNORE INTO resource_flows
                (instance, ts, resource, amount, task, operation, evidence, run_id, event_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', rows)
        return True
    except (sqlite3.Error, OSError) as error:
        logger.warning(f'[资源管理] 收支记录失败：{type(error).__name__}')
        return False


def observe(config, resource, value, source=None):
    """复核库存：扣除上次读数后的明确交易，只把剩余差额记入账本。"""
    instance = getattr(config, 'config_name', None)
    if not isinstance(instance, str) or type(value) is not int or value < 0:
        return
    resource = canonical(resource)
    state = session_for(config)
    run_id = state['id'] if state else None
    stamp = now().isoformat(sep=' ')
    try:
        with connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            baseline = connection.execute('SELECT * FROM resource_balances WHERE instance=? AND resource=?',
                                          (instance, resource)).fetchone()
            if baseline:
                known = connection.execute('''SELECT COALESCE(SUM(amount), 0) FROM resource_flows
                    WHERE instance=? AND resource=? AND id>?''',
                    (instance, resource, baseline['cursor'])).fetchone()[0]
                residual = value - baseline['value'] - known
                same_run = run_id is not None and baseline['run_id'] == run_id
                # PT 跨活动归零不属于消费；读取任务也不能认领离线恢复和跨任务变化。
                reset = (resource == 'Pt' and value < baseline['value'] and not known
                         and not (same_run and state['task'] == 'EventShop'))
                if residual:
                    task = state['task'] if same_run and not reset else 'Unattributed'
                    operation = '活动切换或库存校正' if reset else '任务内库存变化' if same_run else '跨任务或离线变化'
                    connection.execute('''INSERT INTO resource_flows
                        (instance, ts, resource, amount, task, operation, evidence, run_id, event_key)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (instance, stamp, resource, residual, task, operation,
                         'observed' if same_run and not reset else 'adjustment', run_id, uuid4().hex))
            cursor = connection.execute('SELECT COALESCE(MAX(id), 0) FROM resource_flows WHERE instance=?',
                                        (instance,)).fetchone()[0]
            connection.execute('''INSERT INTO resource_balances VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(instance, resource) DO UPDATE SET
                    value=excluded.value, ts=excluded.ts, run_id=excluded.run_id, cursor=excluded.cursor''',
                (instance, resource, value, stamp, run_id, cursor))
    except (sqlite3.Error, OSError) as error:
        logger.warning(f'[资源管理] 库存复核失败：{type(error).__name__}')


def catalog():
    """货币、仓库和既有物品模板使用统一标识，不把未知模板的数字编号当作资源。"""
    items = {key: {'key': key, 'label': label, 'group': '货币' if key in resource_stats.RESOURCE_COLUMNS else '材料'}
             for key, label in LABELS.items()}
    data = json.loads((ROOT / 'assets/stats/storage_items/catalog.json').read_text(encoding='utf-8'))
    for item in data['items']:
        items[item['id']] = {'key': item['id'], 'label': item['name'], 'group': item['group']}
    return items


def report(instance, start, end, resource=None, task=None, offset=0, limit=100, through_id=None):
    """完整区间聚合与分页明细共用筛选；汇总不受明细页大小限制。"""
    if start.tzinfo or end.tzinfo or start >= end:
        raise ValueError('时间区间必须为递增的本地时间')
    filters = 'instance=? AND ts>=? AND ts<?'
    params = [instance, start.isoformat(sep=' '), end.isoformat(sep=' ')]
    with connect() as connection:
        through_id = through_id if through_id is not None else connection.execute(
            'SELECT COALESCE(MAX(id), 0) FROM resource_flows WHERE instance=?', (instance,)).fetchone()[0]
        filters += ' AND id<=?'
        params.append(through_id)
        tasks = [row[0] for row in connection.execute(f'SELECT DISTINCT task FROM resource_flows WHERE {filters} ORDER BY task', params)]
        if task:
            filters += ' AND task=?'
            params.append(task)
        balances = {row['resource']: dict(row) for row in connection.execute(
            'SELECT * FROM resource_balances WHERE instance=?', (instance,))}
        all_totals = [dict(row) for row in connection.execute(f'''SELECT resource,
            SUM(CASE WHEN amount>0 AND evidence!='adjustment' THEN amount ELSE 0 END) income,
            SUM(CASE WHEN amount<0 AND evidence!='adjustment' THEN -amount ELSE 0 END) expense,
            SUM(CASE WHEN evidence='adjustment' THEN amount ELSE 0 END) adjustment,
            COUNT(*) count FROM resource_flows WHERE {filters} GROUP BY resource''', params)]
        if resource:
            filters += ' AND resource=?'
            params.append(resource)
        flows = [dict(row) for row in connection.execute(f'''SELECT resource, task, operation, evidence,
            SUM(CASE WHEN amount>0 THEN amount ELSE 0 END) income,
            SUM(CASE WHEN amount<0 THEN -amount ELSE 0 END) expense, COUNT(*) count
            FROM resource_flows WHERE {filters} GROUP BY resource, task, operation, evidence
            ORDER BY resource, task, operation''', params)]
        total = connection.execute(f'SELECT COUNT(*) FROM resource_flows WHERE {filters}', params).fetchone()[0]
        entries = [dict(row) for row in connection.execute(f'''SELECT id, ts, resource, amount, task,
            operation, evidence, run_id FROM resource_flows WHERE {filters}
            ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?''', [*params, limit, offset])]
    items = catalog()
    totals = {row['resource']: row for row in all_totals}
    for key in balances.keys() | totals.keys():
        if key not in items:
            from module.statistics.research_stats import item_info
            items[key] = {'key': key, 'label': item_info(key)['zh'], 'group': '物品'}
    resources = [dict(item, **{key: totals.get(item['key'], {}).get(key, 0)
                              for key in ('income', 'expense', 'adjustment', 'count')},
                      current=balances.get(item['key'], {}).get('value'),
                      observedAt=balances.get(item['key'], {}).get('ts')) for item in items.values()]
    return {'instance': instance, 'start': start.isoformat(sep=' '), 'end': end.isoformat(sep=' '),
            'resources': resources, 'tasks': tasks, 'flows': flows, 'entries': entries,
            'total': total, 'offset': offset, 'limit': limit, 'throughId': through_id}


def reward_frame(config, image, *, clicked=False):
    """旁路读取现有截图，不发起截图、点击或游戏导航。"""
    state = session_for(config)
    if state is None:
        return
    if state['tracker'] is None:
        from module.statistics.resource_tracking import RewardTracker
        state['tracker'] = RewardTracker(config)
    state['tracker'].frame(image, clicked=clicked)
