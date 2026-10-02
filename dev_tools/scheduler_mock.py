"""前端 mock 使用同一解释器；输入输出仅走管道，不读取实例或设备。"""
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta

from module.scheduler.catalog import CARDS, RESOURCES, REFRESHABLE, OVERRIDES
from module.scheduler.context import snapshot, simulation_plan
from module.scheduler.engine import simulate, parse_time
from module.scheduler.models import ProgramDocument
from module.scheduler.templates import all_cards_program, builtins, default_program, enhance_program
from module.scheduler.validation import validate


def dispatch(request):
    action = request['action']
    context = snapshot(request.get('config', {}), {}, datetime.now())
    if action == 'catalog':
        return {'cards': [c.model_dump() for c in CARDS], 'resources': [
            {'name': n, 'label': n, 'refreshable': n in REFRESHABLE} for n in RESOURCES],
            'tasks': context['tasks'], 'overrides': OVERRIDES, 'builtins': [s.model_dump() for s in builtins()],
            'templates': {'takeover': default_program().model_dump(), 'enhance': enhance_program().model_dump(),
                          'all': all_cards_program().model_dump()}}
    doc = ProgramDocument.model_validate(request['document'])
    result = validate(doc, {t['name'] for t in context['tasks']}, request.get('mode', 'takeover'))
    if action == 'validate':
        return result
    if not result['valid']:
        return {**result, 'state': {'status': 'error', 'trace': []}, 'effects': []}
    context.update(request.get('context', {}))
    instant = parse_time(context['now'])
    plan = simulation_plan(request.get('config', {}), context['tasks'], instant)
    for key, value in plan.items():
        context.setdefault(key, value)
    due = [task for name in plan['nativeOrder'] for task in context['tasks'] if task['name'] == name and task.get('enabled') and task.get('nextRun') and parse_time(task['nextRun']) < parse_time(plan['nativeDueBefore'])]
    if request.get('mode') == 'enhance':
        context['tasks'] = due
    return {**result, **simulate(doc, context, request.get('outcomes'), request.get('steps', 100))}


if __name__ == '__main__':
    try:
        # 优先级模块的首次导入会初始化日志，管道的标准输出只允许 JSON。
        with redirect_stdout(sys.stderr):
            result = dispatch(json.load(sys.stdin))
    except (ValueError, KeyError, TypeError) as exc:
        result = {'error': str(exc)}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
