"""旧工具名的文本输出兼容层。

Add by MHY, 本地产线仍对外提供 18 个旧名称，而现有 MCP 客户端按旧文本解析结果
（例如 ``get_current_running_task`` 只取一段任务名）。上游把这些名称直接映射到
新工具后，结构化内容仍是新契约，文本却变成了中文摘要，旧调用会读不到数据。
本模块只负责把新契约的结构化结果翻译回旧文本，不重新实现业务。
"""
import json
from collections import deque

# 旧 get_status 返回的 state 数字与 WebUI 状态码一致。
STATE_CODES = {'running': 1, 'stopped': 2, 'error': 3, 'updating': 4}
# 配置里的内部节点不是任务，旧实现同样跳过。
INTERNAL_TASKS = {'Alas', 'Error', 'MUMU', 'MumuPlayer12', 'EmulatorManagement', 'Dashboard'}
# 旧 get_screenshot 只返回图像内容，不带文本摘要。
IMAGE_ONLY = {'get_screenshot'}


def dumps(value):
    """按旧实现的格式序列化：缩进两格、不转义中文。"""
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def list_instances(payload, arguments, tools):
    return dumps([item['name'] for item in payload.get('instances') or []])


def get_status(payload, arguments, tools):
    return dumps([{'instance': item['name'], 'running': item['status'] == 'running',
                   'state': STATE_CODES.get(item['status'], 2)}
                  for item in payload.get('instances') or []])


def list_tasks(payload, arguments, tools):
    # 旧实现返回 args.json 的全部任务名；新目录只按关键词返回前若干项。
    return dumps(list(tools.configs.args))


def get_task_help(payload, arguments, tools):
    """还原旧 get_task_help 的扁平结构，保留参数组与选项译名。"""
    groups = {}
    for group_name, group in (payload.get('groups') or {}).items():
        arguments_view = {}
        for arg_name, field in (group.get('arguments') or {}).items():
            arguments_view[arg_name] = {
                'display_name': field['display_name'],
                'help': field['help'],
                'type': field['type'],
                'default': field['default'],
                'options': field.get('option_labels') or None,
            }
        groups[group_name] = {'display_name': group['display_name'],
                              'help': group['help'], 'arguments': arguments_view}
    return dumps({'task_name': payload['task_name'], 'display_name': payload['display_name'],
                  'help': payload['help'], 'groups': groups})


def get_resources(payload, arguments, tools):
    """还原旧 get_resources 的 Dashboard 资源字典（record 字段名为 last_update）。"""
    resources = {}
    for name, item in (payload.get('resources') or {}).items():
        label = item.get('label')
        # 译名缺失时 translate 会回退到路径末段 name，旧实现则回退到资源键。
        if not label or label == 'name':
            label = name
        entry = {'label': label, 'value': item.get('value')}
        for key in ('limit', 'total'):
            if item.get(key) is not None:
                entry[key] = item[key]
        if item.get('record'):
            entry['last_update'] = item['record']
        resources[name] = entry
    return dumps(resources)


def get_config(payload, arguments, tools):
    return dumps(payload.get('values'))


def update_config(payload, arguments, tools):
    change = (payload.get('changes') or [{}])[0]
    return f"Success: Updated {change.get('path')} to {change.get('after')}"


def get_recent_logs(payload, arguments, tools):
    """旧实现直接回读日志文件尾部；新日志接口是结构化条目，正文格式不同。"""
    path = tools.log_path(arguments['instance'])
    if not path.exists():
        return f'Log file not found: {path}'
    with path.open(encoding='utf-8', errors='ignore') as stream:
        return ''.join(deque(stream, maxlen=min(arguments.get('lines', 50), 5000)))


def trigger_task(payload, arguments, tools):
    return f"Success: Task {arguments['task']} scheduled for immediately."


def start_instance(payload, arguments, tools):
    return f"Success: Started {arguments['instance']} (alas)"


def stop_instance(payload, arguments, tools):
    return f"Success: Stopped {arguments['instance']}"


def get_current_running_task(payload, arguments, tools):
    """旧调用只期待一段任务名，不能把整个上下文摘要塞给它。"""
    if payload.get('instance_status') != 'running':
        return 'Error: Instance is not running.'
    return payload.get('current_task') or 'Unknown'


def get_scheduler_queue(payload, arguments, tools):
    """旧实现返回完整队列；新上下文只带前 10 条计划，故这里直接读配置。"""
    data, _ = tools.configs.read(arguments['instance'])
    queue = []
    for task, groups in data.items():
        if not isinstance(groups, dict) or task in INTERNAL_TASKS:
            continue
        scheduler = groups.get('Scheduler') or {}
        if scheduler.get('Enable', False):
            queue.append({'task': task,
                          'next_run': str(scheduler.get('NextRun', '2050-01-01 00:00:00'))})
    queue.sort(key=lambda item: item['next_run'])
    return dumps(queue)


def clear_scheduler_queue(payload, arguments, tools):
    cleared = payload.get('cleared') or []
    text = f"Success: Cleared tasks: {', '.join(cleared)}"
    if payload.get('retained'):
        text += f"; 保留不可编辑的任务: {', '.join(payload['retained'])}"
    return text


def restart_emulator(payload, arguments, tools):
    return f"Success: Restarted emulator for {arguments['instance']}"


def restart_adb(payload, arguments, tools):
    return f"Success: Restarted ADB service using {payload.get('adb_path') or 'adb'}."


def update_alas(payload, arguments, tools):
    return 'Success: Triggered AzurPilot update in background.'


RENDERERS = {
    'list_instances': list_instances,
    'get_status': get_status,
    'list_tasks': list_tasks,
    'get_task_help': get_task_help,
    'get_resources': get_resources,
    'get_config': get_config,
    'update_config': update_config,
    'get_recent_logs': get_recent_logs,
    'trigger_task': trigger_task,
    'start_instance': start_instance,
    'stop_instance': stop_instance,
    'get_current_running_task': get_current_running_task,
    'get_scheduler_queue': get_scheduler_queue,
    'clear_scheduler_queue': clear_scheduler_queue,
    'restart_emulator': restart_emulator,
    'restart_adb': restart_adb,
    'update_alas': update_alas,
}


def render(name, payload, arguments, tools):
    """返回旧的文本结果；没有对应渲染器时返回 None，沿用新摘要。"""
    renderer = RENDERERS.get(name)
    return renderer(payload, arguments, tools) if renderer else None


def error_text(message):
    """旧实现的错误文本统一以 Error: 开头，不带错误码。"""
    return f'Error: {message}'
