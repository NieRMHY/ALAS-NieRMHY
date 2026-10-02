"""程序静态校验；不加载配置，不运行卡片。"""
import math
import re
from datetime import datetime
from module.scheduler.catalog import OVERRIDES, RESOURCES, REFRESHABLE, definition
from module.scheduler.models import Diagnostic, ProgramDocument


def compatible(source, target):
    families = {'duration': 'number', 'tasks': 'list', 'resource': 'object'}
    return 'any' in (source, target) or families.get(source, source) == families.get(target, target)


def valid_value(value, kind):
    if value is None or kind == 'any':
        return True
    if kind in ('number', 'duration'):
        return type(value) in (int, float) and math.isfinite(value)
    if kind == 'boolean':
        return type(value) is bool
    if kind in ('string', 'time'):
        return isinstance(value, str)
    if kind in ('list', 'tasks'):
        return isinstance(value, list)
    return isinstance(value, dict)


def validate(document: ProgramDocument, tasks=None, mode='takeover'):
    errors = []
    subs = {s.id: s for s in document.subgraphs}
    names = {v.name for v in document.variables}
    if len(subs) != len(document.subgraphs):
        errors.append(Diagnostic(message='组合卡片标识重复'))
    if len(names) != len(document.variables):
        errors.append(Diagnostic(message='变量名称重复'))
    for variable in document.variables:
        if not valid_value(variable.initial, variable.type):
            errors.append(Diagnostic(message=f'变量初始值与声明类型不一致：{variable.name}'))
    calls = {name: set() for name in ['main', *subs]}
    reachable = {'main'}
    def reach(graph):
        for n in graph.nodes:
            if n.type == 'call' and n.params.get('graph') in subs and n.params['graph'] not in reachable:
                reachable.add(n.params['graph'])
                reach(subs[n.params['graph']])
    reach(document)

    def guaranteed_yield(graph, ancestry):
        identifier = getattr(graph, 'id', 'main')
        if identifier in ancestry:
            return False
        nodes = {n.id: n for n in graph.nodes}
        links = {n: [] for n in nodes}
        for edge in graph.edges:
            if edge.kind == 'control' and edge.source in links and edge.target in nodes:
                links[edge.source].append(edge.target)
        def visit(n, seen):
            if n not in nodes or n in seen:
                return False
            card = nodes[n]
            if card.type in ('execute', 'wait', 'wait_until'):
                return True
            if card.type == 'call':
                child = subs.get(card.params.get('graph'))
                if child and not child.pure and guaranteed_yield(child, ancestry | {identifier}):
                    return True
            spec = definition(card, document, graph)
            connected = {e.sourcePort for e in graph.edges if e.kind == 'control' and e.source == n}
            if not spec or any(exit not in connected for exit in spec.exits):
                return False
            return bool(links[n]) and all(visit(target, seen | {n}) for target in links[n])
        return visit(graph.entry, set())

    def check(graph, name):
        nodes = {n.id: n for n in graph.nodes}
        defs = {n.id: definition(n, document, graph) for n in graph.nodes}
        def error(message, node=None):
            errors.append(Diagnostic(message=message, node=node, graph=name))
        if len(nodes) != len(graph.nodes):
            error('卡片标识重复')
        if graph.entry not in nodes:
            error('入口卡片不存在')
        elif not getattr(graph, 'pure', False) and nodes[graph.entry].type != 'entry':
            error('执行图必须从程序入口卡片开始', graph.entry)
        if sum(n.type == 'entry' for n in graph.nodes) > 1:
            error('执行图只能有一个程序入口')
        for ports in (getattr(graph, 'inputs', []), getattr(graph, 'outputs', [])):
            if len({p.name for p in ports}) != len(ports) or any(not p.name or ':' in p.name for p in ports):
                error('组合端口名称不能为空、重复或包含冒号')
        occupied = set()
        data_links = {n: [] for n in nodes}
        control = {n: [] for n in nodes}
        for edge in graph.edges:
            if edge.source not in nodes or edge.target not in nodes:
                error('连接引用了不存在的卡片')
                continue
            source, target = defs[edge.source], defs[edge.target]
            if not source or not target:
                continue
            if edge.kind == 'control':
                if edge.sourcePort not in source.exits or target.pure or getattr(target, 'entry', False) or target.type == 'entry' or edge.targetPort != 'in':
                    error('执行连接端口无效', edge.target)
                key = ('control', edge.source, edge.sourcePort)
                control[edge.source].append(edge.target)
            else:
                outputs = {p.name: p.type for p in source.outputs}
                inputs = {p.name: p.type for p in target.inputs}
                if edge.sourcePort not in outputs or edge.targetPort not in inputs:
                    error('数据连接端口无效', edge.target)
                elif not compatible(outputs[edge.sourcePort], inputs[edge.targetPort]):
                    error('数据端口类型不兼容', edge.target)
                key = ('data', edge.target, edge.targetPort)
                data_links[edge.target].append(edge.source)
            if key in occupied:
                error('同一端口连接重复', edge.target)
            occupied.add(key)
        if len({e.id for e in graph.edges}) != len(graph.edges):
            error('连接标识重复')
        for node in graph.nodes:
            spec = defs[node.id]
            if not spec:
                error('未知卡片类型', node.id)
                continue
            params = {**spec.params, **node.params}
            invalid_params = False
            for key, default in spec.params.items():
                value = params[key]
                # 可以由数据连接代替的输入在执行时求值，其他属性必须具有声明的形状。
                if key in ('value', 'a', 'b', 'yes', 'no') or ('data', node.id, key) in occupied:
                    continue
                valid = type(value) is type(default) if isinstance(default, (str, bool, list, dict)) else type(value) in (int, float) and math.isfinite(value)
                if not valid:
                    error(f'参数类型无效：{key}', node.id)
                    invalid_params = True
            if invalid_params:
                continue
            operators = {'compare': ['==','!=','>','>=','<','<='], 'logic':['and','or','not'], 'math':['+','-','*','/','%','min','max']}
            if node.type in operators and params['operator'] not in operators[node.type]:
                error('运算符无效', node.id)
            if node.type in ('time_window', 'server_day', 'quota', 'record', 'wait_until'):
                keys = ['start','end'] if node.type == 'time_window' else ['time'] if node.type == 'wait_until' else ['reset']
                for key in keys:
                    if ('data', node.id, key) in occupied:
                        continue
                    try:
                        parts = params[key].split(',') if key == 'reset' else [params[key]]
                        for part in parts:
                            part = part.strip()
                            if re.fullmatch(r'\d{2}:\d{2}', part):
                                datetime.strptime(part, '%H:%M')
                            elif node.type == 'wait_until' and ',' not in part:
                                datetime.fromisoformat(part)
                            else:
                                raise ValueError('需要 HH:MM 时间')
                    except ValueError:
                        error(f'时间格式无效：{key}', node.id)
            if node.type == 'time_window' and any(type(day) is not int or not 1 <= day <= 7 for day in params['weekdays']):
                error('星期必须为 1～7', node.id)
            if node.type in ('tasks', 'priority', 'refresh'):
                key = {'tasks':'names', 'priority':'order', 'refresh':'resources'}[node.type]
                if any(not isinstance(item, str) for item in params[key]):
                    error('列表只能包含名称', node.id)
            if node.type == 'loop' and (type(params['count']) is not int or params['count'] < -1):
                error('循环次数只能为 -1 或非负整数', node.id)
            if node.type == 'quota' and (type(params['limit']) is not int or params['limit'] < 1):
                error('每日配额必须为正整数', node.id)
            if getattr(graph, 'pure', False) and not spec.pure:
                error('继续条件和数据组合卡片不能执行副作用', node.id)
            if mode == 'enhance' and name in reachable and node.type in ('wait', 'wait_until', 'refresh', 'record', 'set_variable', 'loop', 'foreach'):
                error('增强调度仅允许候选变换、条件和任务输出；持续编排请使用完全接管', node.id)
            for p in spec.inputs:
                if p.required and ('data', node.id, p.name) not in occupied and p.name not in params:
                    error(f'缺少输入：{p.name}', node.id)
            if node.type == 'call':
                if params.get('graph') not in subs:
                    error('组合卡片不存在', node.id)
                else:
                    calls[name].add(params['graph'])
            if node.type in ('get_variable', 'set_variable') and params.get('name') not in names:
                error('变量未声明', node.id)
            elif node.type == 'set_variable' and ('data', node.id, 'value') not in occupied:
                declared = next(v for v in document.variables if v.name == params['name'])
                if not valid_value(params['value'], declared.type):
                    error('变量赋值与声明类型不一致', node.id)
            if node.type == 'literal' and not valid_value(params['value'], params['valueType']):
                error('常量与声明类型不一致', node.id)
            if node.type == 'input' and params.get('name') not in {p.name for p in getattr(graph, 'inputs', [])}:
                error('组合输入端口未声明', node.id)
            if node.type == 'refresh' and any(n not in REFRESHABLE for n in params['resources']):
                error('所选资源不支持主动刷新', node.id)
            if tasks is not None and node.type in ('tasks', 'priority', 'task'):
                selected = params['names'] if node.type == 'tasks' else params['order'] if node.type == 'priority' else [params['name']]
                if any(t not in tasks for t in selected):
                    error('列表包含不存在的业务任务', node.id)
            if node.type == 'resource' and params.get('name') not in RESOURCES:
                error('未知资源', node.id)
            if node.type == 'resource' and (not isinstance(params.get('maxAge'), (int, float)) or params['maxAge'] <= 0):
                error('资源有效期必须为正数', node.id)
            if node.type == 'wait' and ('data', node.id, 'seconds') not in occupied and (not isinstance(params.get('seconds'), (int, float)) or params['seconds'] <= 0):
                error('等待时长必须大于零', node.id)
            if node.type == 'loop_end':
                owner = nodes.get(params.get('loop'))
                if not owner or owner.type not in ('loop', 'foreach'):
                    error('结束循环必须指向循环卡片', node.id)
                else:
                    control[node.id].append(owner.id)
            if node.type == 'execute':
                guard = params.get('guard')
                if guard and (guard not in subs or not subs[guard].pure):
                    error('继续条件必须是无副作用的组合卡片', node.id)
                if tasks is not None and ('data', node.id, 'task') not in occupied and params.get('task') not in tasks:
                    error('任务不存在或不是可调度业务任务', node.id)
                for key, value in params.get('overrides', {}).items():
                    kind = OVERRIDES.get(key)
                    valid = key in OVERRIDES
                    if kind == 'integer':
                        valid = type(value) is int and value >= 0
                    elif kind == 'string':
                        valid = isinstance(value, str) and 0 < len(value) <= 200
                    elif isinstance(kind, list):
                        valid = value in kind
                    if not valid:
                        error(f'临时参数无效或不在白名单：{key}', node.id)
                if ('data', node.id, 'task') not in occupied and params.get('task'):
                    from module.scheduler.overrides import check_overrides
                    try:
                        check_overrides(params['task'], params.get('overrides', {}))
                    except ValueError as exc:
                        error(str(exc), node.id)
        if getattr(graph, 'pure', False) and graph.entry in defs and defs[graph.entry]:
            outputs = {p.name: p.type for p in defs[graph.entry].outputs}
            for p in graph.outputs:
                if p.name not in outputs or not compatible(outputs[p.name], p.type):
                    error('组合输出与入口数据端口不一致', graph.entry)
        # 数据图无环；普通执行线也无环，仅专用结束循环卡片允许回到循环。
        def acyclic(links, label):
            visited, active = set(), set()
            def walk(n):
                if n in active:
                    error(label, n)
                    return
                if n in visited:
                    return
                visited.add(n)
                active.add(n)
                for target in links[n]:
                    walk(target)
                active.remove(n)
            for n in nodes:
                walk(n)
        acyclic(data_links, '数据依赖存在循环')
        acyclic({n: [] if nodes[n].type == 'loop_end' else v for n, v in control.items()}, '请使用循环卡片，不能任意回连')
        # 每条从循环 body 到 loop_end 的路径都必须让出执行权。
        for node in graph.nodes:
            if node.type not in ('loop', 'foreach'):
                continue
            bodies = [e.target for e in graph.edges if e.kind == 'control' and e.source == node.id and e.sourcePort == 'body']
            def has_busy_path(n, yielded, seen):
                if n in seen:
                    return True
                current = nodes[n]
                if current.type in ('execute', 'wait', 'wait_until'):
                    yielded = True
                if current.type == 'call' and defs[n] and not defs[n].pure:
                    # 组合卡片内部也会校验循环；动态无让出路径由步数预算兜底。
                    # 检查组合入口至所有返回路径，而非只看是否存在一张等待卡片。
                    sub = subs.get(current.params.get('graph'))
                    yielded = yielded or (sub is not None and guaranteed_yield(sub, set()))
                if current.type == 'loop_end' and current.params.get('loop') == node.id:
                    return not yielded
                return any(has_busy_path(x, yielded, seen | {n}) for x in control[n] if x != node.id)
            if any(has_busy_path(n, False, set()) for n in bodies):
                error('循环每轮必须经过任务或正时长等待', node.id)

    check(document, 'main')
    for sub in document.subgraphs:
        check(sub, sub.id)
    active, visited = set(), set()
    def walk(name):
        if name in active:
            errors.append(Diagnostic(message='组合卡片禁止递归调用', graph=name))
            return
        if name in visited:
            return
        active.add(name)
        for child in calls.get(name, ()):
            walk(child)
        active.remove(name)
        visited.add(name)
    for name in calls:
        walk(name)
    return {'valid': not errors, 'diagnostics': [e.model_dump() for e in errors]}
