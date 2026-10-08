"""设备无关的卡片解释器，执行动作以 Effect 返回给宿主。"""
import copy
import operator
from dataclasses import dataclass
from datetime import datetime, timedelta

from module.scheduler.catalog import REFRESHABLE, definition
from module.scheduler.models import ProgramState, ResourceObservation


class ProgramError(Exception):
    """程序不能继续；宿主必须停止派发，不得降级到原调度。"""
    def __init__(self, message, node=None):
        super().__init__(message)
        self.node = node


class RefreshNeeded(Exception):
    """资源快照过期时由卡片求值抛出；引擎捕获后转成 `refresh` 效果交宿主处理。"""

    def __init__(self, name):
        self.name = name


@dataclass
class Effect:
    """解释器交给宿主的动作：`kind` 为 `execute` 时带回任务调用，为 `refresh` 时带回待刷新资源。"""

    kind: str
    node: str | None
    payload: dict


def parse_time(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value)).replace(tzinfo=None)


def server_day(now, reset='00:00'):
    points = [datetime.strptime(t.strip(), '%H:%M').time() for t in reset.split(',')]
    reset_time = min(points)
    return (now - timedelta(hours=reset_time.hour, minutes=reset_time.minute)).date().isoformat()


def compare(a, b, op):
    if a is None or b is None:
        return None
    operations = {'==': operator.eq, '!=': operator.ne, '>': operator.gt, '>=': operator.ge, '<': operator.lt, '<=': operator.le}
    if op not in operations:
        raise ProgramError('未知比较运算')
    if type(a) in (int, float) and isinstance(b, str):
        try:
            b = float(b) if '.' in b else int(b)
        except ValueError:
            pass
    elif type(b) in (int, float) and isinstance(a, str):
        try:
            a = float(a) if '.' in a else int(a)
        except ValueError:
            pass
    try:
        return operations[op](a, b)
    except TypeError as exc:
        raise ProgramError(f'类型不兼容，无法进行大小比较：{type(a).__name__} {op} {type(b).__name__}') from exc


class Frame:
    def __init__(self, graph, inputs=None, owner=None):
        self.graph, self.pc = graph, graph.entry
        self.inputs, self.owner = inputs or {}, owner
        self.values, self.loops = {}, {}
        self.nodes = {n.id: n for n in graph.nodes}
        self.data = {(e.target, e.targetPort): (e.source, e.sourcePort) for e in graph.edges if e.kind == 'data'}
        self.control = {(e.source, e.sourcePort): e.target for e in graph.edges if e.kind == 'control'}


class Engine:
    def __init__(self, document, persistent=None):
        self.document = document
        self.subs = {s.id: s for s in document.subgraphs}
        self.variables = {v.name: copy.deepcopy(v.initial) for v in document.variables}
        self.records = copy.deepcopy((persistent or {}).get('records', {}))
        for v in document.variables:
            if v.persistent and v.name in (persistent or {}).get('variables', {}):
                self.variables[v.name] = copy.deepcopy(persistent['variables'][v.name])
        self.frames = [Frame(document)]
        self.state = ProgramState(variables=self.variables)
        self.pending = None
        self.context = {}
        self.cache, self.refresh_attempts = {}, {}
        self.eval_count = 0
        self.rotation_reads = set()

    @property
    def now(self):
        return parse_time(self.context['now'])

    def persistent(self):
        return {'variables': {v.name: self.variables[v.name] for v in self.document.variables if v.persistent},
                'records': copy.deepcopy(self.records)}

    def trace(self, node, **values):
        self.state.variables = copy.deepcopy(self.variables)
        self.state.node = node.id
        self.state.trace.append({'node': node.id, 'type': node.type, 'label': node.label,
                                 'graph': getattr(self.frames[-1].graph, 'id', 'main'), **copy.deepcopy(values)})
        self.state.trace = self.state.trace[-200:]

    def input(self, frame, node, name, default=None):
        link = frame.data.get((node.id, name))
        if link:
            return self.evaluate(frame, *link)
        spec = definition(node, self.document, frame.graph)
        return node.params.get(name, spec.params.get(name, default))

    def evaluate(self, frame, node_id, output='value'):
        try:
            return self._evaluate(frame, node_id, output)
        except ProgramError as exc:
            if exc.node is None:
                exc.node = node_id
            raise
        except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError, RecursionError) as exc:
            raise ProgramError(str(exc), node_id) from exc

    def _evaluate(self, frame, node_id, output='value'):
        self.eval_count += 1
        if self.eval_count > 1000:
            raise ProgramError('数据求值超过 1,000 步')
        # 保留帧引用，避免多个纯组合求值时 Python 重用对象地址导致串值。
        key = (frame, node_id, output)
        if key in self.cache:
            return self.cache[key]
        node = frame.nodes[node_id]
        p = {**definition(node, self.document, frame.graph).params, **node.params}
        get = lambda name, default=None: self.input(frame, node, name, default)
        kind = node.type
        if not definition(node, self.document, frame.graph).pure:
            value = frame.values.get((node_id, output))
        elif kind == 'literal':
            value = p['value']
        elif kind == 'compare':
            value = compare(get('a'), get('b'), p['operator'])
        elif kind == 'logic':
            a, b = get('a'), get('b')
            if p['operator'] == 'not':
                value = None if a is None else not a
            elif p['operator'] == 'and':
                value = False if a is False or b is False else None if a is None or b is None else bool(a and b)
            elif p['operator'] == 'or':
                value = True if a is True or b is True else None if a is None or b is None else bool(a or b)
            else:
                raise ProgramError('未知逻辑运算')
        elif kind == 'math':
            a, b = get('a'), get('b')
            ops = {'+': operator.add, '-': operator.sub, '*': operator.mul, '/': operator.truediv, '%': operator.mod, 'min': min, 'max': max}
            value = None if a is None or b is None else ops[p['operator']](a, b)
        elif kind == 'select':
            condition = get('condition')
            value = None if condition is None else get('yes' if condition else 'no')
        elif kind == 'get_variable':
            value = self.variables[p['name']]
        elif kind == 'now':
            value = self.now.isoformat(sep=' ')
        elif kind == 'weekday':
            value = self.now.isoweekday()
        elif kind == 'server_day':
            value = server_day(self.now, self.context.get('serverReset', p['reset']))
        elif kind == 'time_window':
            start, end = [datetime.strptime(p[x], '%H:%M').time() for x in ('start', 'end')]
            clock = self.now.time()
            value = self.now.isoweekday() in p['weekdays'] and (start <= clock < end if start < end else clock >= start or clock < end)
        elif kind == 'resource':
            observation = copy.deepcopy(self.context.get('resources', {}).get(p['name'], {}))
            at = observation.get('observedAt')
            fresh = bool(at and observation.get('status') not in ('unavailable', 'missing') and 0 <= (self.now - parse_time(at)).total_seconds() <= p['maxAge'])
            if not fresh and p['autoRefresh'] and p['name'] in REFRESHABLE and self.context.get('allowRefresh', True):
                last = self.refresh_attempts.get(p['name'])
                if last is None or (self.now - last).total_seconds() >= 60:
                    raise RefreshNeeded(p['name'])
            observation.update(name=p['name'], status='fresh' if fresh else 'unavailable' if observation.get('status') == 'unavailable' else 'stale' if at else 'missing', refreshable=p['name'] in REFRESHABLE)
            value = observation if output == 'record' else fresh if output == 'fresh' else observation.get(p['field']) if fresh else None
        elif kind == 'resource_fresh':
            value = (get('resource') or {}).get('status') == 'fresh'
        elif kind == 'tasks':
            value = [copy.deepcopy(t) for t in self.context.get('tasks', []) if not p['names'] or t['name'] in p['names']]
        elif kind == 'task':
            value = next((copy.deepcopy(t) for t in self.context.get('tasks', []) if t['name'] == p['name']), None)
        elif kind == 'field':
            obj = get('object')
            value = obj.get(p['field']) if isinstance(obj, dict) else None
        elif kind == 'last_result':
            value = self.records.get('results', {}).get(p['task']) if p['task'] else self.records.get('lastResult')
        elif kind == 'requests':
            names = {r['task'] for r in self.context.get('requests', [])}
            value = [t for t in self.context.get('tasks', []) if t['name'] in names]
        elif kind == 'original_plan':
            if 'nativeTask' in self.context:
                value = self.context.get('nativeTask') if output == 'value' else self.context.get('nativeDeadline')
            else:
                # 隔离模拟没有真实配置队列，按注入的任务状态和默认优先级计算。
                from module.scheduler.catalog import REGISTRY
                enabled = [t for t in self.context.get('tasks', []) if t.get('enabled') and t.get('nextRun')]
                due = [t for t in enabled if parse_time(t['nextRun']) <= self.now]
                order = {name: index for index, name in enumerate(REGISTRY['priority'].params['order'])}
                due.sort(key=lambda t: order.get(t['name'], len(order)))
                future = [parse_time(t['nextRun']) for t in enabled if parse_time(t['nextRun']) > self.now]
                value = (due[0] if due else None) if output == 'value' else (min(future) if future else self.now + timedelta(minutes=5)).isoformat(sep=' ')
        elif kind == 'original_settings':
            if output == 'order':
                from module.scheduler.catalog import REGISTRY
                value = self.context.get('nativeOrder', REGISTRY['priority'].params['order'])
            elif output == 'dueBefore':
                value = self.context.get('nativeDueBefore', self.now.isoformat(sep=' '))
            else:
                value = self.context.get('nativeDeadline')
                if not value:
                    future = [parse_time(t['nextRun']) for t in self.context.get('tasks', []) if t.get('enabled') and t.get('nextRun') and parse_time(t['nextRun']) > self.now]
                    value = (min(future) if future else self.now + timedelta(minutes=5)).isoformat(sep=' ')
        elif kind == 'filter':
            items = get('items') or []
            if p['rule'] == 'enabled':
                value = [t for t in items if t.get('enabled')]
            elif p['rule'] == 'due':
                cutoff = parse_time(get('before', self.now))
                value = [t for t in items if t.get('nextRun') and (parse_time(t['nextRun']) < cutoff if p['strict'] else parse_time(t['nextRun']) <= cutoff)]
            else:
                value = [t for t in items if compare(t.get(p['field']), p['value'], p['operator'])]
        elif kind == 'priority':
            items = get('items') or []
            scores = get('scores')
            order = {t: i for i, t in enumerate(get('order') or [])}
            value = sorted(items, key=lambda t: -scores.get(t['name'], 0) if isinstance(scores, dict) else order.get(t['name'], len(order)))
        elif kind == 'sort':
            value = sorted(get('items') or [], key=lambda t: (t.get(p['field']) is None, t.get(p['field']) or ''), reverse=p['descending'])
        elif kind == 'oldest':
            times = self.records.get('lastExecuted', {})
            value = sorted(get('items') or [], key=lambda t: times.get(t['name'], ''))
        elif kind in ('first', 'empty', 'round_robin'):
            items = get('items') or []
            value = not items if kind == 'empty' else items[(self.records.get('rotation', {}).get(p['key'], 0) % len(items)) if kind == 'round_robin' else 0] if items else None
            if kind == 'round_robin' and items:
                self.rotation_reads.add(p['key'])
        elif kind == 'cooldown':
            at = self.records.get('cooldowns', {}).get(p['key'])
            value = not at or (self.now - parse_time(at)).total_seconds() >= p['seconds']
        elif kind == 'quota':
            day = server_day(self.now, p['reset'])
            value = self.records.get('quotas', {}).get(p['key'], {}).get(day, 0) < p['limit']
        elif kind == 'input':
            value = frame.inputs.get(p['name'])
        elif kind == 'output':
            value = get(output)
        elif kind == 'call':
            sub = self.subs[p['graph']]
            subframe = Frame(sub, {port.name: get(port.name) for port in sub.inputs})
            value = self.evaluate(subframe, sub.entry, output)
        else:
            raise ProgramError(f'卡片没有求值实现：{kind}')
        self.cache[key] = value
        self.trace(node, graph=getattr(frame.graph, 'id', 'main'), output={output: value})
        return value

    def guard(self, graph_id, context):
        """安全检查点只执行无副作用求值；过期数据要求宿主先让出。"""
        self.context = {**context, 'allowRefresh': False}
        self.cache, self.eval_count = {}, 0
        sub = self.subs[graph_id]
        value = self.evaluate(Frame(sub), sub.entry, sub.outputs[0].name if sub.outputs else 'value')
        return value is True

    def next(self, frame, node, exit_name='next'):
        frame.pc = frame.control.get((node.id, exit_name))

    def advance(self, context, single_step=False):
        if self.pending:
            return self.pending
        self.context = context
        self.cache, self.eval_count = {}, 0
        self.rotation_reads = set()
        try:
            self.state.resources = {name: ResourceObservation.model_validate(row) for name, row in context.get('resources', {}).items() if isinstance(row, dict) and 'name' in row}
            for _ in range(1000):
                frame = self.frames[-1]
                if frame.pc is None:
                    if len(self.frames) > 1:
                        self.finish_frame(None)
                        continue
                    self.state.status = 'ended'
                    return Effect('end', self.state.node, {})
                node = frame.nodes[frame.pc]
                self.eval_count += 1
                if self.eval_count > 1000:
                    raise ProgramError('连续执行超过 1,000 个卡片，请检查循环', node.id)
                spec = definition(node, self.document, frame.graph)
                p = {**spec.params, **node.params}
                get = lambda name, default=None: self.input(frame, node, name, default)
                kind = node.type
                self.state.status = 'running'
                if kind == 'branch':
                    value = get('condition')
                    exit_name = 'unavailable' if value is None else 'yes' if value else 'no'
                    self.trace(node, input=value, exit=exit_name)
                    self.next(frame, node, exit_name)
                elif kind in ('execute', 'wait', 'wait_until', 'refresh'):
                    if kind == 'execute':
                        task = get('task')
                        if not task:
                            self.trace(node, exit='empty')
                            self.next(frame, node, 'empty')
                            continue
                        name = task.get('name') if isinstance(task, dict) else task
                        available = {t['name'] for t in context.get('tasks', [])}
                        if name not in available:
                            raise ProgramError('任务不在当前允许的候选列表中')
                        payload = {'task': name, 'overrides': p['overrides'], 'guard': p['guard'], 'followOriginal': p['followOriginal']}
                        from module.scheduler.catalog import OVERRIDES
                        payload['overrides'] = copy.deepcopy(payload['overrides'])
                        for parameter in OVERRIDES:
                            if (node.id, parameter) in frame.data or parameter in node.params:
                                value = get(parameter)
                                if value is None:
                                    raise ProgramError(f'本次任务参数不可用：{parameter}')
                                payload['overrides'][parameter] = value
                        from module.scheduler.overrides import check_overrides
                        check_overrides(name, payload['overrides'])
                        self.records.setdefault('lastExecuted', {})[name] = self.now.isoformat(sep=' ')
                        for rotation in self.rotation_reads:
                            rotations = self.records.setdefault('rotation', {})
                            rotations[rotation] = rotations.get(rotation, 0) + 1
                    elif kind == 'refresh':
                        names = p['resources']
                        payload = {'resources': names, 'automatic': False}
                        for name in names:
                            self.refresh_attempts[name] = self.now
                    else:
                        if kind == 'wait':
                            seconds = get('seconds')
                            if type(seconds) not in (int, float) or seconds <= 0:
                                raise ProgramError('等待时长必须大于零')
                            deadline = self.now + timedelta(seconds=seconds)
                        else:
                            target = get('time')
                            if len(str(target)) <= 5:
                                deadline = datetime.combine(self.now.date(), datetime.strptime(target, '%H:%M').time())
                                if deadline <= self.now:
                                    deadline += timedelta(days=1)
                            else:
                                deadline = parse_time(target)
                            if deadline <= self.now:
                                raise ProgramError('等待目标必须在未来')
                        payload = {'deadline': deadline.isoformat(sep=' ')}
                        if p.get('recheckOnConfigChange'):
                            payload['recheckOnConfigChange'] = True
                    self.trace(node, input=payload)
                    self.state.status = 'task' if kind == 'execute' else 'waiting' if kind.startswith('wait') else 'refreshing'
                    self.state.task = payload.get('task')
                    self.state.deadline = payload.get('deadline')
                    self.pending = Effect('wait' if kind.startswith('wait') else kind, node.id, payload)
                    return self.pending
                elif kind == 'set_variable':
                    value = get('value')
                    from module.scheduler.validation import valid_value
                    declared = next(v for v in self.document.variables if v.name == p['name'])
                    if value is not None and not valid_value(value, declared.type):
                        raise ProgramError('变量赋值与声明类型不一致')
                    self.variables[p['name']] = copy.deepcopy(value)
                    self.trace(node, value=value)
                    self.next(frame, node)
                elif kind == 'record':
                    if p['kind'] == 'quota':
                        day = server_day(self.now, p['reset'])
                        counter = self.records.setdefault('quotas', {}).setdefault(p['key'], {})
                        counter[day] = counter.get(day, 0) + 1
                        for old in list(counter):
                            if old != day:
                                del counter[old]
                    else:
                        self.records.setdefault('cooldowns', {})[p['key']] = self.now.isoformat(sep=' ')
                    self.trace(node)
                    self.next(frame, node)
                elif kind in ('loop', 'foreach'):
                    index = frame.loops.get(node.id, 0)
                    frame.values[(node.id, 'index')] = index
                    if kind == 'foreach':
                        items = get('items') or []
                        enter = index < len(items)
                        frame.values[(node.id, 'item')] = items[index] if enter else None
                    else:
                        condition = get('condition')
                        enter = condition is True and (p['count'] < 0 or index < p['count'])
                    self.trace(node, index=index, exit='body' if enter else 'done')
                    if not enter:
                        frame.loops.pop(node.id, None)
                    self.next(frame, node, 'body' if enter else 'done')
                elif kind == 'loop_end':
                    loop = p['loop']
                    frame.loops[loop] = frame.loops.get(loop, 0) + 1
                    frame.pc = loop
                    self.trace(node)
                elif kind == 'call':
                    sub = self.subs[p['graph']]
                    inputs = {port.name: get(port.name) for port in sub.inputs}
                    self.trace(node, input=inputs)
                    self.frames.append(Frame(sub, inputs, node.id))
                elif kind == 'return':
                    outputs = {p.name: get(p.name) for p in getattr(frame.graph, 'outputs', [])} or {'value': get('value')}
                    self.trace(node, output=outputs)
                    self.finish_frame(outputs)
                elif kind == 'end':
                    self.trace(node)
                    frame.pc = None
                elif kind in ('entry', 'debug'):
                    self.trace(node, value=get('value') if kind == 'debug' else None)
                    self.next(frame, node)
                else:
                    raise ProgramError('执行线连接到了数据卡片')
                self.cache = {}
                if single_step:
                    return Effect('step', node.id, {})
            raise ProgramError('连续执行超过 1,000 个卡片，请检查循环')
        except RefreshNeeded as needed:
            self.refresh_attempts[needed.name] = self.now
            self.pending = Effect('refresh', self.frames[-1].pc, {'resources': [needed.name], 'automatic': True})
            self.state.status = 'refreshing'
            return self.pending
        except (ProgramError, ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError, RecursionError) as exc:
            self.state.status, self.state.reason = 'error', str(exc)
            self.state.node = getattr(exc, 'node', None) or self.frames[-1].pc
            return Effect('error', self.state.node, {'reason': str(exc)})

    def finish_frame(self, outputs):
        frame = self.frames.pop()
        if not self.frames:
            self.frames = [frame]
            frame.pc = None
            return
        parent = self.frames[-1]
        for name, value in (outputs or {}).items():
            parent.values[(frame.owner, name)] = value
        self.next(parent, parent.nodes[frame.owner])

    def resume(self, outcome=None):
        effect, self.pending = self.pending, None
        if not effect:
            return
        frame = self.frames[-1]
        node = frame.nodes[effect.node]
        exit_name = 'next'
        if effect.kind == 'execute':
            outcome = outcome or {'task': effect.payload['task'], 'status': 'completed'}
            frame.values[(node.id, 'result')] = outcome
            self.records.setdefault('results', {})[effect.payload['task']] = outcome
            self.records['lastResult'] = outcome
            exit_name = outcome['status']
        elif effect.kind == 'refresh':
            if effect.payload.get('automatic'):
                return
            exit_name = 'success' if outcome else 'unavailable'
        self.trace(node, exit=exit_name, output=outcome)
        self.next(frame, node, exit_name)
        if effect.kind == 'execute' and outcome.get('status') == 'failed' and frame.pc is None:
            self.state.reason = outcome.get('reason') or '任务执行失败'
        self.state.task, self.state.deadline = None, None


def simulate(document, context, outcomes=None, steps=100, persistent=None):
    """模拟动作由输入数据完成，永远不触碰设备和持久存储。"""
    engine = Engine(document, persistent)
    context = copy.deepcopy(context)
    outcomes = copy.deepcopy(outcomes or [])
    effects = []
    for _ in range(steps):
        effect = engine.advance(context, single_step=True)
        effects.append({'kind': effect.kind, 'node': effect.node, **effect.payload})
        if effect.kind in ('end', 'error'):
            break
        if effect.kind == 'execute':
            status = outcomes.pop(0) if outcomes else 'completed'
            if 'nativeDueBefore' in context:
                context['nativeDueBefore'] = context['now']
            engine.resume({'task': effect.payload['task'], 'status': status, 'finishedAt': context['now']})
        elif effect.kind == 'wait':
            before = parse_time(context['now'])
            instant = parse_time(effect.payload['deadline']) + timedelta(microseconds=1)
            context['now'] = instant.isoformat(sep=' ')
            if 'nativeDueBefore' in context:
                context['nativeDueBefore'] = (parse_time(context['nativeDueBefore']) + (instant - before)).isoformat(sep=' ')
            if 'nativeDeadline' in context:
                future = [parse_time(t['nextRun']) for t in context.get('tasks', []) if t.get('enabled') and t.get('nextRun') and parse_time(t['nextRun']) > instant]
                context['nativeDeadline'] = (min(future) if future else instant + timedelta(minutes=5)).isoformat(sep=' ')
            engine.resume()
        elif effect.kind == 'refresh':
            # 注入的有效资源代表模拟刷新结果；没有观察值时明确不可用。
            success = True
            for name in effect.payload['resources']:
                resource = context.setdefault('resources', {}).setdefault(name, {})
                if resource.get('value') is None:
                    success = False
                    resource['status'] = 'unavailable'
                else:
                    resource.update(observedAt=context['now'], status='fresh')
            engine.resume(success)
    return {'state': engine.state.model_dump(), 'effects': effects, 'persistent': engine.persistent()}
