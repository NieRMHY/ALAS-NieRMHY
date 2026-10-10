"""侧栏内容检索：把任务名与配置项的名字、说明、选项标签建成可搜索引。

索引取自仓库的多语言文案（module/config/i18n/*.json）：每个任务的每个配置项都带 name
与 help，下拉项的标签也在同一层。简中与英文两套都索引，中文界面下用英文词也能搜到。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
I18N_DIR = ROOT / 'module' / 'config' / 'i18n'

# 索引这两套语言：中文界面下用英文词也能搜到同一条配置
SEARCH_LANGUAGES = ('zh-CN', 'en-US')
# 文案里的元信息键（name、help），不参与检索
META_KEYS = ('name', 'help')

_index_cache = {'stamp': None, 'entries': []}


def _build_entries() -> list:
    """读全部参与索引的语言，摊平成统一的检索条目。"""
    entries = []
    for language in SEARCH_LANGUAGES:
        path = I18N_DIR / f'{language}.json'
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for key, meta in data.get('Task', {}).items():
            if not isinstance(meta, dict):
                continue
            label, help_text = meta.get('name', ''), meta.get('help', '')
            entries.append({
                'kind': 'task', 'task': key, 'key': key, 'label': label, 'help': help_text,
                'values': '', 'haystack': f'{key} {label} {help_text}',
            })
        for task, node in data.items():
            if task == 'Task' or not isinstance(node, dict):
                continue
            info = node.get('_info')
            group_label = info.get('name', '') if isinstance(info, dict) else ''
            # 卡片标题（三级标题）也是页面上能看到的文字，单独成一条命中，点了定位到整张卡片
            if group_label:
                entries.append({
                    'kind': 'group', 'task': task, 'key': '', 'label': group_label, 'help': '',
                    'values': '', 'haystack': f'{task} {group_label}',
                })
            for option, meta in node.items():
                if option == '_info' or not isinstance(meta, dict):
                    continue
                label, help_text = meta.get('name', ''), meta.get('help', '')
                # 下拉项的标签（如 AttackMode 的「当期/档案」）也是页面上能看到的文字，一并索引
                values = ' '.join(
                    value for name, value in meta.items()
                    if name not in META_KEYS and isinstance(value, str)
                )
                entries.append({
                    'kind': 'option', 'task': task, 'key': option, 'label': label, 'help': help_text,
                    'values': values, 'haystack': f'{task} {option} {label} {help_text} {values}',
                })
    return entries


def _entries() -> list:
    """索引按文案文件的修改时间缓存：文件一改就重建。"""
    stamp = []
    for language in SEARCH_LANGUAGES:
        try:
            stamp.append((I18N_DIR / f'{language}.json').stat().st_mtime_ns)
        except OSError:
            stamp.append(0)
    stamp = tuple(stamp)
    if _index_cache['stamp'] != stamp:
        _index_cache['stamp'] = stamp
        _index_cache['entries'] = _build_entries()
    return _index_cache['entries']


def search_content(query: str) -> dict:
    """按子串检索任务与配置项，返回两组命中。

    Args:
        query: 检索词，大小写不敏感。

    Returns:
        dict: ``{'tasks': [...], 'groups': [...], 'options': [...]}``，每组条目为 ``{'task', 'key', 'label', 'help', 'values'}``；
            ``groups`` 是卡片标题命中（``key`` 为空），``values`` 是该配置项下拉标签的拼接，
            用来解释这条为什么被搜到。无命中时每组均为空列表。
    """
    needle = query.strip().lower()
    if not needle:
        return {'tasks': [], 'groups': [], 'options': []}

    seen = set()
    tasks, groups, options = [], [], []
    for entry in _entries():
        if needle not in entry['haystack'].lower():
            continue
        identity = (entry['kind'], entry['task'], entry['key'])
        if identity in seen:
            continue
        seen.add(identity)
        item = {key: entry[key] for key in ('task', 'key', 'label', 'help', 'values')}
        if entry['kind'] == 'task':
            tasks.append(item)
        elif entry['kind'] == 'group':
            groups.append(item)
        else:
            options.append(item)
    return {'tasks': tasks, 'groups': groups, 'options': options}
