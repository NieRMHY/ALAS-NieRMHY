"""基础卡片注册表：后端解释与前端属性面板共用同一份定义。"""
from typing import get_args
from module.scheduler.models import CardDefinition, PortDefinition, PortType


def port(name, kind='any', required=False):
    return PortDefinition(name=name, type=kind, required=required)


def card(card_type, label, category, inputs=(), outputs=(('value', 'any'),), exits=(), pure=None, entry=False, **params):
    return CardDefinition(type=card_type, label=label, category=category,
                          pure=not exits if pure is None else pure,
                          entry=entry,
                          inputs=[port(*p) for p in inputs], outputs=[port(*p) for p in outputs],
                          exits=list(exits), params=params)


CARDS = [
    card('entry', '程序入口', '流程', outputs=(), exits=('next',), entry=True),
    card('end', '结束程序', '流程', outputs=(), exits=(), pure=False),
    card('literal', '常量', '逻辑', value=0, valueType='number'),
    card('compare', '比较', '逻辑', inputs=(('a', 'any', True), ('b', 'any', True)), outputs=(('value', 'boolean'),), operator='>=', a=0, b=0),
    card('logic', '且 / 或 / 非', '逻辑', inputs=(('a', 'boolean'), ('b', 'boolean')), outputs=(('value', 'boolean'),), operator='and', a=True, b=True),
    card('math', '数值运算', '逻辑', inputs=(('a', 'number'), ('b', 'number')), outputs=(('value', 'number'),), operator='+', a=0, b=1),
    card('select', '选择值', '逻辑', inputs=(('condition', 'boolean'), ('yes', 'any'), ('no', 'any')), condition=True, yes=None, no=None),
    card('branch', '条件分支', '逻辑', inputs=(('condition', 'boolean'),), outputs=(), exits=('yes', 'no', 'unavailable'), condition=True),
    card('get_variable', '读取变量', '变量', name=''),
    card('set_variable', '设置变量', '变量', inputs=(('value', 'any'),), exits=('next',), name='', value=0),
    card('now', '当前时间', '时间', outputs=(('value', 'time'),)),
    card('weekday', '星期', '时间', outputs=(('value', 'number'),)),
    card('time_window', '时间窗口', '时间', outputs=(('value', 'boolean'),), start='08:00', end='22:00', weekdays=[1, 2, 3, 4, 5, 6, 7]),
    card('server_day', '服务器刷新日界', '时间', outputs=(('value', 'string'),), reset='00:00'),
    card('wait', '等待时长', '时间', inputs=(('seconds', 'duration'),), outputs=(), exits=('next',), seconds=300),
    card('wait_until', '等待到指定时间', '时间', inputs=(('time', 'time'),), outputs=(), exits=('next',), time='08:00', recheckOnConfigChange=False),
    card('resource', '读取资源', '资源', outputs=(('value', 'number'), ('record', 'resource'), ('fresh', 'boolean')), name='Oil', field='value', maxAge=300, autoRefresh=True),
    card('resource_fresh', '判断资源新鲜度', '资源', inputs=(('resource', 'resource', True),), outputs=(('value', 'boolean'),)),
    card('refresh', '刷新资源', '资源', outputs=(), exits=('success', 'unavailable'), resources=['Oil', 'Coin']),
    card('tasks', '读取任务列表', '任务', outputs=(('value', 'tasks'),), names=[]),
    card('task', '读取指定任务', '任务', outputs=(('value', 'task'),), name='Main'),
    card('field', '读取字段', '逻辑', inputs=(('object', 'any', True),), field='enabled'),
    card('last_result', '读取上次任务结果', '任务', outputs=(('value', 'result'),), task=''),
    card('requests', '读取任务派发请求', '任务', outputs=(('value', 'tasks'),)),
    card('original_plan', '读取原计划下一项', '调度', outputs=(('value', 'task'), ('deadline', 'time'))),
    card('original_settings', '读取原调度规则', '调度', outputs=(('order', 'list'), ('dueBefore', 'time'), ('deadline', 'time'))),
    card('execute', '执行任务', '任务', inputs=(('task', 'task'),), outputs=(('result', 'result'),), exits=('completed', 'yielded', 'recoverable', 'failed', 'empty'), task='Main', overrides={}, guard='', followOriginal=False),
    card('filter', '筛选任务列表', '列表', inputs=(('items', 'tasks', True), ('before', 'time')), outputs=(('value', 'tasks'),), rule='enabled', field='enabled', operator='==', value=True, strict=False),
    card('sort', '按字段排序', '列表', inputs=(('items', 'tasks', True),), outputs=(('value', 'tasks'),), field='nextRun', descending=False),
    card('priority', '按优先级排序', '调度', inputs=(('items', 'tasks', True), ('scores', 'object'), ('order', 'list')), outputs=(('value', 'tasks'),), order=['Commission', 'Research', 'Reward', 'Main']),
    card('first', '取第一项', '列表', inputs=(('items', 'tasks', True),), outputs=(('value', 'task'),)),
    card('empty', '判断空列表', '列表', inputs=(('items', 'list', True),), outputs=(('value', 'boolean'),)),
    card('oldest', '最长未执行优先', '调度', inputs=(('items', 'tasks', True),), outputs=(('value', 'tasks'),)),
    card('round_robin', '轮询选择', '调度', inputs=(('items', 'tasks', True),), outputs=(('value', 'task'),), key='rotation'),
    card('cooldown', '冷却判断', '调度', outputs=(('value', 'boolean'),), key='cooldown', seconds=3600),
    card('quota', '每日执行配额', '调度', outputs=(('value', 'boolean'),), key='daily', limit=1, reset='00:00'),
    card('record', '记录配额 / 冷却', '调度', outputs=(), exits=('next',), key='daily', kind='quota', reset='00:00'),
    card('loop', '条件 / 次数循环', '流程', inputs=(('condition', 'boolean'),), outputs=(('index', 'number'),), exits=('body', 'done'), count=-1, condition=True),
    card('foreach', '遍历列表', '流程', inputs=(('items', 'list', True),), outputs=(('item', 'any'), ('index', 'number')), exits=('body', 'done')),
    card('loop_end', '结束本轮循环', '流程', outputs=(), exits=(), pure=False, loop=''),
    card('call', '调用组合卡片', '流程', exits=('next',), graph=''),
    card('input', '组合卡片输入', '流程', name='value'),
    card('output', '组合数据输出', '流程', inputs=(('value', 'any'),)),
    card('return', '组合卡片输出', '流程', inputs=(('value', 'any'),), outputs=(), exits=(), pure=False, value=None),
    card('debug', '输出调试信息', '流程', inputs=(('value', 'any'),), outputs=(), exits=('next',), value=''),
]
REGISTRY = {c.type: c for c in CARDS}
RESOURCES = ['Oil', 'Coin', 'Gem', 'Pt', 'Cube', 'ActionPoint', 'YellowCoin', 'PurpleCoin', 'Core', 'Medal', 'Merit', 'GuildCoin', 'Emotion1', 'Emotion2']
REFRESHABLE = {'Oil', 'Coin', 'ActionPoint', 'YellowCoin', 'PurpleCoin'}
OVERRIDES = {'Campaign_Name': 'string', 'Campaign_Event': 'string', 'Campaign_Mode': ['normal', 'hard'],
             'StopCondition_RunCount': 'integer', 'StopCondition_OilLimit': 'integer'}
REGISTRY['execute'].inputs.extend(port(name, 'number' if kind == 'integer' else 'string') for name, kind in OVERRIDES.items())


def definition(node, document, graph=None):
    if node.type in ('get_variable', 'set_variable'):
        declared = next((v for v in document.variables if v.name == node.params.get('name')), None)
        if declared:
            field = 'outputs' if node.type == 'get_variable' else 'inputs'
            return REGISTRY[node.type].model_copy(update={field: [port('value', declared.type)]})
    if node.type == 'output' and graph is not None and hasattr(graph, 'outputs'):
        return REGISTRY['output'].model_copy(update={'inputs': graph.outputs, 'outputs': graph.outputs})
    if node.type == 'return' and graph is not None and hasattr(graph, 'outputs'):
        return REGISTRY['return'].model_copy(update={'inputs': graph.outputs})
    if node.type == 'input' and graph is not None and hasattr(graph, 'inputs'):
        declared = next((p for p in graph.inputs if p.name == node.params.get('name')), None)
        if declared:
            return REGISTRY['input'].model_copy(update={'outputs': [port('value', declared.type)]})
    if node.type == 'call':
        sub = next((g for g in document.subgraphs if g.id == node.params.get('graph')), None)
        if sub:
            return CardDefinition(type='call', label=sub.name, category='组合', pure=sub.pure,
                                  inputs=sub.inputs, outputs=sub.outputs, exits=[] if sub.pure else ['next'])
    if node.type == 'literal':
        kind = node.params.get('valueType', 'number')
        if kind not in get_args(PortType):
            return None
        return REGISTRY['literal'].model_copy(update={'outputs': [port('value', kind)]})
    return REGISTRY.get(node.type)
