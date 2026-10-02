"""可展开的现成逻辑；组合卡片自身也是普通程序文档。"""
from module.scheduler.models import CardNode, Connection, ProgramDocument, SubgraphDefinition
from module.scheduler.catalog import port


def node(identifier, kind, x=0, y=0, **params):
    return CardNode(id=identifier, type=kind, params=params, position={'x': x, 'y': y})


def edge(source, target, source_port='next', target_port='in', data=False):
    return Connection(id=f'{source}.{source_port}-{target}.{target_port}', source=source, target=target,
                      sourcePort=source_port, targetPort=target_port, kind='data' if data else 'control')


def builtins():
    priority = SubgraphDefinition(id='builtin.priority', name='按优先级选择', pure=True, entry='first',
        inputs=[port('items', 'tasks', True)], outputs=[port('value', 'task')], nodes=[
            node('input', 'input', name='items'), node('order', 'priority', 250), node('first', 'first', 500)], edges=[
            edge('input', 'order', 'value', 'items', True), edge('order', 'first', 'value', 'items', True)])
    # 原队列包含用户优先级和囤积等待，不能用固定任务顺序重新模拟。
    original = SubgraphDefinition(id='builtin.original', name='按原计划筛选选择', pure=True, entry='plan',
        outputs=[port('value', 'task')], nodes=[node('plan', 'original_plan')])
    def execution_sub(identifier, label, nodes, edges, inputs=()):
        return SubgraphDefinition(id=identifier, name=label, entry='entry', inputs=list(inputs),
                                 nodes=[node('entry', 'entry'), *nodes], edges=edges)
    timed = execution_sub('builtin.window', '时间窗口内执行', [node('clock', 'time_window', 0, 180),
        node('branch', 'branch', 250), node('task', 'input', 250, 180, name='task'), node('run', 'execute', 500)],
        [edge('entry', 'branch'), edge('clock', 'branch', 'value', 'condition', True), edge('branch', 'run', 'yes'),
         edge('task', 'run', 'value', 'task', True)], [port('task', 'task', True)])
    guard = SubgraphDefinition(id='builtin.oil.guard', name='石油停止阈值', pure=True, entry='compare',
        outputs=[port('value', 'boolean')], nodes=[node('oil', 'resource', name='Oil', autoRefresh=False),
            node('compare', 'compare', 250, b=2000)], edges=[edge('oil', 'compare', 'value', 'a', True)])
    threshold = execution_sub('builtin.threshold', '资源阈值启动与停止', [node('oil', 'resource', 0, 200),
        node('check', 'compare', 240, 200, b=5000), node('branch', 'branch', 240),
        node('task', 'input', 480, 200, name='task'), node('run', 'execute', 480, guard=guard.id)],
        [edge('entry', 'branch'), edge('oil', 'check', 'value', 'a', True), edge('check', 'branch', 'value', 'condition', True),
         edge('branch', 'run', 'yes'), edge('task', 'run', 'value', 'task', True)], [port('task', 'task', True)])
    rotation = SubgraphDefinition(id='builtin.rotation', name='按列表轮流选择', pure=True, entry='choose',
        inputs=[port('items', 'tasks', True)], outputs=[port('value', 'task')],
        nodes=[node('input', 'input', name='items'), node('choose', 'round_robin', 250)],
        edges=[edge('input', 'choose', 'value', 'items', True)])
    quota = execution_sub('builtin.quota', '每日配额内执行', [node('quota', 'quota', 0, 200),
        node('branch', 'branch', 250), node('record', 'record', 500), node('task', 'input', 500, 200, name='task'),
        node('run', 'execute', 750), node('tomorrow', 'wait_until', 500, 400, time='00:00')],
        [edge('entry', 'branch'), edge('quota', 'branch', 'value', 'condition', True), edge('branch', 'record', 'yes'),
         edge('record', 'run'), edge('task', 'run', 'value', 'task', True), edge('branch', 'tomorrow', 'no')],
        [port('task', 'task', True)])
    idle = execution_sub('builtin.idle', '等待最近原计划', [node('plan', 'original_plan', 0, 200), node('wait', 'wait_until', 250)],
        [edge('entry', 'wait'), edge('plan', 'wait', 'deadline', 'time', True)])
    return [priority, original, timed, guard, threshold, rotation, quota, idle]


def default_program():
    """把原调度的业务选择规则直接展开，便于理解和修改。"""
    document = ProgramDocument(entry='start', name='原调度器 · 启用、到期、优先级与等待', subgraphs=builtins(), nodes=[
        node('start', 'entry', 0, 0), node('loop', 'loop', 320, 0),
        node('tasks', 'tasks', 0, 400),
        node('choose', 'first', 1280, 400),
        node('run', 'execute', 1920, 0, followOriginal=True), node('wait', 'wait_until', 1920, 720, recheckOnConfigChange=True),
        node('repeat', 'loop_end', 2240, 0, loop='loop'),
        node('enabled', 'filter', 320, 400, rule='enabled'), node('due', 'filter', 640, 400, rule='due', strict=True),
        node('order', 'priority', 960, 400), node('empty', 'empty', 1600, 400),
        node('branch', 'branch', 1600, 0), node('rules', 'original_settings', 640, 950),
        node('failed', 'end', 2240, 700)], edges=[
        edge('start', 'loop'), edge('loop', 'branch', 'body'),
        edge('tasks', 'enabled', 'value', 'items', True), edge('enabled', 'due', 'value', 'items', True),
        edge('due', 'order', 'value', 'items', True), edge('rules', 'due', 'dueBefore', 'before', True),
        edge('rules', 'order', 'order', 'order', True), edge('order', 'choose', 'value', 'items', True),
        edge('order', 'empty', 'value', 'items', True), edge('empty', 'branch', 'value', 'condition', True),
        edge('branch', 'wait', 'yes'), edge('branch', 'run', 'no'),
        edge('choose', 'run', 'value', 'task', True),
        *[edge('run', 'repeat', outcome) for outcome in ('completed', 'yielded', 'recoverable')],
        edge('run', 'wait', 'empty'), edge('run', 'failed', 'failed'),
        edge('rules', 'wait', 'deadline', 'time', True),
        edge('wait', 'repeat')])
    labels = {'start': '原调度业务入口', 'loop': '每轮重新读取任务状态', 'tasks': '读取实例全部业务任务',
              'enabled': '只保留已启用任务', 'due': '只保留已到期任务（含囤积规则）', 'order': '按当前实例优先级排序',
              'choose': '选择优先级最高的任务', 'empty': '没有到期任务？', 'branch': '没有任务则等待，有任务则执行',
              'run': '执行选中的任务', 'wait': '等待最近原计划时间', 'repeat': '回到下一轮判断',
              'rules': '读取当前优先级、囤积截止与最近计划', 'failed': '失败时结束并显示结果'}
    for card in document.nodes:
        card.comment = labels[card.id]
    return document


def enhance_program():
    return ProgramDocument(entry='start', name='原计划优先级增强', subgraphs=builtins(), nodes=[
        node('start', 'entry'), node('tasks', 'tasks', 0, 200), node('choose', 'call', 250, 200, graph='builtin.priority'),
        node('run', 'execute', 500)], edges=[edge('start', 'run'), edge('tasks', 'choose', 'value', 'items', True),
                                           edge('choose', 'run', 'value', 'task', True)])


def all_cards_program():
    """将注册表中的所有基础卡片按分类整齐排列成网格，便于可视化审阅与调试。"""
    from module.scheduler.catalog import CARDS
    categories = ['流程', '逻辑', '变量', '时间', '资源', '任务', '列表', '调度']
    col_spacing = 300
    row_spacing = 380
    nodes = []

    for col_idx, cat in enumerate(categories):
        cards = [c for c in CARDS if c.category == cat and c.type not in ('input', 'output', 'return')]
        for row_idx, c in enumerate(cards):
            params = dict(c.params)
            if c.type in ('get_variable', 'set_variable'):
                params['name'] = 'var1'
            elif c.type == 'loop_end':
                params['loop'] = 'loop'
            elif c.type == 'call':
                params['graph'] = 'builtin.original'
            elif c.type == 'task':
                params['name'] = 'Main'
            elif c.type == 'priority':
                params['order'] = ['Commission', 'Research', 'Reward', 'Main']
            elif c.type == 'execute':
                params['task'] = 'Main'
            nodes.append(CardNode(id=c.type, type=c.type, params=params, position={'x': col_idx * col_spacing, 'y': row_idx * row_spacing}))

    edges = [
        edge('tasks', 'filter', 'value', 'items', True),
        edge('tasks', 'sort', 'value', 'items', True),
        edge('tasks', 'first', 'value', 'items', True),
        edge('tasks', 'empty', 'value', 'items', True),
        edge('tasks', 'priority', 'value', 'items', True),
        edge('tasks', 'oldest', 'value', 'items', True),
        edge('tasks', 'round_robin', 'value', 'items', True),
        edge('tasks', 'foreach', 'value', 'items', True),
        edge('resource', 'resource_fresh', 'record', 'resource', True),
        edge('resource', 'field', 'record', 'object', True),
    ]

    return ProgramDocument(
        entry='entry',
        name='全卡片展示 · 整齐排列',
        subgraphs=builtins(),
        variables=[{'name': 'var1', 'type': 'number', 'initial': 0, 'persistent': False}],
        viewport={'x': 0, 'y': 0, 'zoom': 0.75},
        nodes=nodes,
        edges=edges
    )
