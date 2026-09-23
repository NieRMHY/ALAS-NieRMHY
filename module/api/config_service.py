"""参数定义驱动的配置服务，在跨进程事务内校验并合并字段修改。"""
import copy
import hashlib
import json
import math
import re
import threading
from datetime import datetime
from pathlib import Path

import yaml

from deploy.atomic import atomic_write
from module.api.protocol import ApiError
from module.config.transaction import config_transaction

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = 'template'
# 实例名会成为配置文件名。允许中日文、字母、数字、下划线、点号、空格与短横线，
# 也与上游一致：config/ 下除 template 外任何 *.json 都算实例。
HIRAGANA = r'\u3041-\u3096'
KATAKANA = r'\u30a1-\u30fa\u30fc\u31f0-\u31ff\uff66-\uff9f'
HAN = r'\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff'
CJK = HIRAGANA + KATAKANA + HAN
# 首字符不能是下划线、点号或空格，它们只出现在名称中段与末尾。
NAME = re.compile(r'[A-Za-z0-9' + CJK + r'][A-Za-z0-9_. ' + CJK + r'\-]{0,63}\Z')
# 名字里以点分段的基名与这些词相同时继续拦下：template 是模板，其余是 Windows 设备名。
RESERVED = {TEMPLATE, 'deploy', 'backup', 'con', 'prn', 'aux', 'nul',
            *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}


def validate_name(value):
    """校验实例名并返回它的规范形式。

    末尾的空白与点归一化掉：Windows 上 `ap .json` 落盘就是 `ap.json`，
    两者本就是同一个文件。前导点不削，`.` 与 `..` 是路径成分，`.隐藏` 这类名字一概拒。
    以点分段的基名命中 RESERVED 即拒：`template` 与 `template.fpy` 都是模板。
    """
    if not isinstance(value, str):
        raise ApiError('INVALID_PARAMS', '实例名无效')
    name = re.sub(r'[\s.]+\Z', '', value.strip())
    if not NAME.fullmatch(name) or name.split('.')[0].lower() in RESERVED:
        raise ApiError('INVALID_PARAMS', '实例名无效：不能含路径分隔符或 Windows 保留字符，不能以点开头，不能是保留名')
    return name


def accepts_name(value):
    """列举时用的宽松版：不合规的文件名当作不存在，不让一个坏文件名打断整份列表。"""
    try:
        return validate_name(value) == value
    except ApiError:
        return False

class ConfigService:
    """只访问白名单配置，读操作不会触发运行器的配置写回。"""

    def __init__(self, root: Path = ROOT):
        self.root = root
        self.directory = root / 'config'
        # 导入源单独一个目录：config/ 下的 *.json 都算实例，导入源不能与实例列表混在一起。
        self.import_directory = self.directory / 'import'
        self.lock = threading.RLock()
        argument = root / 'module/config/argument'
        self.args = self.read_json(argument / 'args.json')
        self.menu = self.read_json(argument / 'menu.json')
        self.translations = self.read_json(root / 'module/config/i18n/zh-CN.json')
        self.template = self.read_json(self.directory / 'template.json')

    @staticmethod
    def read_json(path):
        return json.loads(path.read_text(encoding='utf-8'))

    def translate(self, key):
        value = self.translations
        for part in key.split('.'):
            value = value.get(part, {}) if isinstance(value, dict) else {}
        return value if isinstance(value, str) and value != key else key.split('.')[-1]

    def path(self, name, exists=True):
        name = validate_name(name)
        path = self.directory / f'{name}.json'
        if path.is_symlink() or path.resolve().parent != self.directory.resolve():
            raise ApiError('INVALID_PARAMS', '配置路径无效')
        if exists and not path.is_file():
            raise ApiError('NOT_FOUND', '实例不存在')
        return path

    def names(self):
        return sorted(p.stem for p in self.directory.glob('*.json')
                      if accepts_name(p.stem) and not p.is_symlink() and self.is_instance(p))

    def save_import(self, name, content):
        """把上传的配置写进导入目录；先解成 JSON 并确认有 Alas 段，坏文件不入库。"""
        name = validate_name(name)
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise ApiError('INVALID_PARAMS', '不是合法的 JSON 配置文件') from exc
        if not isinstance(data, dict) or not isinstance(data.get('Alas'), dict):
            raise ApiError('INVALID_PARAMS', '配置文件缺少 Alas 段')
        self.import_directory.mkdir(parents=True, exist_ok=True)
        path = self.import_directory / f'{name}.json'
        if path.is_symlink() or path.resolve().parent != self.import_directory.resolve():
            raise ApiError('INVALID_PARAMS', '导入路径无效')
        with path.open('w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        return {'name': name}

    def is_instance(self, path):
        try:
            return isinstance(self.read_json(path).get('Alas'), dict)
        except (OSError, ValueError, AttributeError):
            return False

    def importable(self):
        """导入目录里可供挑选的配置文件，供创建实例时直接选一个来源。"""
        if not self.import_directory.is_dir():
            return []
        return [{'name': path.stem, 'modified': path.stat().st_mtime}
                for path in sorted(self.import_directory.glob('*.json'))
                if accepts_name(path.stem) and not path.is_symlink() and self.is_instance(path)]

    def read_import(self, name):
        """读导入目录里的一份配置；与实例名同样用白名单校验，不做任意路径读取。"""
        name = validate_name(name)
        path = self.import_directory / f'{name}.json'
        if path.is_symlink() or path.resolve().parent != self.import_directory.resolve():
            raise ApiError('INVALID_PARAMS', '导入路径无效')
        if not path.is_file() or not self.is_instance(path):
            raise ApiError('NOT_FOUND', '导入文件不存在')
        return self.read_json(path)

    def read(self, name):
        path = self.path(name)
        try:
            raw = path.read_bytes()
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get('Alas'), dict):
                raise ValueError()
        except (OSError, ValueError) as exc:
            raise ApiError('CONFIG_INVALID', '配置文件损坏，请从备份恢复') from exc
        # 旧配置缺失的参数在读时补齐，完整迁移仍由核心运行器负责。
        merged = copy.deepcopy(self.template)
        for task, groups in data.items():
            if isinstance(groups, dict):
                for group, fields in groups.items():
                    if isinstance(fields, dict):
                        merged.setdefault(task, {}).setdefault(group, {}).update(fields)
        return merged, hashlib.sha256(raw).hexdigest()

    def schema(self, language='zh-CN'):
        """按会话读取翻译，不修改运行器或其他浏览器的全局语言。"""
        if language not in {'zh-CN', 'zh-MIAO', 'en-US', 'ja-JP', 'zh-TW'}:
            raise ApiError('INVALID_PARAMS', '不支持的界面语言')
        translations = self.translations if language == 'zh-CN' else self.read_json(
            self.root / 'module/config/i18n' / f'{language}.json')
        return {'menu': self.menu, 'args': self.args, 'translations': translations}

    def get(self, name):
        data, revision = self.read(name)
        return {'instance': name, 'revision': revision, 'values': data}

    def create(self, name, source=None, import_file=None):
        # 先归一化，落盘名与返回给客户端的实例名才是同一个。
        name = validate_name(name)
        with self.lock:
            if import_file:
                data = self.read_import(import_file)
            elif source:
                data = self.read(source)[0]
            else:
                data = copy.deepcopy(self.template)
            path = self.path(name, exists=False)
            # 排他创建避免不同会话覆盖已有配置。
            try:
                with path.open('x', encoding='utf-8') as file:
                    json.dump(data, file, ensure_ascii=False, indent=2)
            except FileExistsError as exc:
                raise ApiError('ALREADY_EXISTS', '同名实例已存在') from exc
            return self.get(name)

    @staticmethod
    def validate_shop_strategy(script):
        """校验受限 Lua 风格商店策略，不执行脚本。"""
        from module.shop_strategy import validate_strategy

        result = validate_strategy(script)
        if not result['valid']:
            diagnostics = result.get('diagnostics', [])
            first = diagnostics[0]['message'] if diagnostics else '脚本不符合受限策略语法'
            raise ApiError('INVALID_PARAMS', f'高级商店策略脚本无效：{first}', diagnostics)
        return result

    def validate_shop_advanced_groups(self, data, tasks):
        """校验最终配置快照中的高级模式与脚本组合。

        ``Mode`` 与 ``Script`` 能在同一事务中一并修改，因此不能在逐字段
        校验阶段提前判定。高级模式必须保存可执行的非空脚本；简单模式允许
        清空脚本以恢复默认配置。
        """
        for task in tasks:
            group = data.get(task, {}).get('ShopAdvanced')
            if not isinstance(group, dict) or group.get('Mode') != 'advanced':
                continue
            script = group.get('Script')
            if not isinstance(script, str) or not script.strip():
                raise ApiError(
                    'INVALID_PARAMS',
                    f'{task} 的高级模式需要先保存非空且有效的策略脚本',
                )
            self.validate_shop_strategy(script)

    def validate(self, path, value):
        parts = path.split('.')
        if len(parts) != 3:
            raise ApiError('INVALID_PARAMS', '配置路径必须为 Task.Group.Argument')
        field = self.args
        for part in parts:
            field = field.get(part, {})
        # 存储区禁止编辑内容，但允许通过同一配置事务显式清空。
        if field.get('type') == 'storage' and field.get('display') != 'hide' and type(value) is dict and not value:
            return parts
        if not field or field.get('display') in ('hide', 'disabled', 'readonly') or field.get('type') in ('storage', 'stored', 'state', 'lock'):
            raise ApiError('READ_ONLY', f'参数不存在或不允许修改：{path}')
        default, kind = field.get('value'), field.get('type')
        options = field.get('option')
        if kind == 'multiselect':
            if not isinstance(value, list) or len(value) > len(options or []) or any(
                not any(type(selected) is type(item) and selected == item for item in options or [])
                for selected in value
            ) or len(set(map(str, value))) != len(value):
                raise ApiError('INVALID_PARAMS', f'多选参数包含无效或重复选项：{path}')
            return parts
        if options and not any(type(value) is type(item) and value == item for item in options):
            raise ApiError('INVALID_PARAMS', f'请选择有效选项：{path}')
        if kind == 'checkbox' or isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, int):
            valid = type(value) is int
        elif isinstance(default, float):
            valid = type(value) in (float, int)
        else:
            valid = isinstance(value, str) or (default is None and value is None)
        if not valid or (isinstance(value, str) and len(value) > 20000) or (type(value) is float and not math.isfinite(value)):
            raise ApiError('INVALID_PARAMS', f'参数类型或长度不正确：{path}')
        rule = field.get('validate')
        if rule == 'datetime' or kind == 'datetime':
            try:
                if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
                    raise ValueError()
                datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError) as exc:
                raise ApiError('INVALID_PARAMS', f'日期格式应为 YYYY-MM-DD HH:mm:ss：{path}') from exc
        elif isinstance(rule, list) and len(rule) == 2:
            if type(value) not in (int, float) or not rule[0] <= value <= rule[1]:
                raise ApiError('INVALID_PARAMS', f'参数必须在 {rule[0]} 到 {rule[1]} 之间：{path}')
        elif isinstance(rule, str) and isinstance(value, (str, int, float)):
            if not re.fullmatch(rule, str(value)):
                raise ApiError('INVALID_PARAMS', f'参数格式不正确：{path}')
        if field.get('mode') == 'restricted_lua':
            self.validate_shop_strategy(value)
        if field.get('mode') == 'yaml' or kind == 'yaml':
            try:
                parsed = yaml.safe_load(value)
            except (yaml.YAMLError, ValueError, RecursionError) as exc:
                mark = getattr(exc, 'problem_mark', None)
                location = f'（第 {mark.line + 1} 行，第 {mark.column + 1} 列）' if mark else ''
                raise ApiError('INVALID_PARAMS', f'YAML 格式不正确{location}：{path}') from exc
            if parsed is not None and not isinstance(parsed, dict):
                raise ApiError('INVALID_PARAMS', f'YAML 顶层必须是键值映射：{path}')
        return parts

    def patch(self, name, revision, changes):
        with self.lock, config_transaction(self.path(name)):
            # revision 仅为旧客户端兼容参数。字段赋值合并到锁内最新快照，
            # 无关字段的运行状态更新不应拒绝用户输入；同字段按事务顺序生效。
            data, _ = self.read(name)
            seen = set()
            affected_shop_tasks = set()
            for change in changes:
                task, group, arg = self.validate(change.path, change.value)
                if change.path in seen:
                    raise ApiError('INVALID_PARAMS', '同一次保存不能重复修改同一个参数')
                seen.add(change.path)
                data.setdefault(task, {}).setdefault(group, {})[arg] = change.value
                self._sync_record_time(data[task][group], arg)
                if group == 'ShopAdvanced':
                    affected_shop_tasks.add(task)
            self.validate_shop_advanced_groups(data, affected_shop_tasks)
            atomic_write(str(self.path(name)), json.dumps(data, ensure_ascii=False, indent=2))
            return self.get(name)

    @staticmethod
    def _sync_record_time(fields, arg):
        """把 Value 参数对应的时间戳重置为当前时间。

        情绪等参数由“值 + 记录时间”两个字段推算实时状态，改值不刷新时间戳时，
        下次计算会把旧时间戳之后的恢复量重复计入。
        """
        if not arg.endswith('Value'):
            return
        record = arg[:-len('Value')] + 'Record'
        if record in fields:
            fields[record] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def delete(self, name, revision):
        with self.lock, config_transaction(self.path(name)):
            if self.read(name)[1] != revision:
                raise ApiError('CONFLICT', '配置已变化，请重新加载后删除')
            # 删除操作保留备份，用户可从 config/backup 手动恢复。
            backup = self.directory / 'backup'
            backup.mkdir(exist_ok=True)
            target = backup / f'{name}-{datetime.now():%Y%m%d-%H%M%S-%f}.json'
            self.path(name).replace(target)
            return {'deleted': name}
