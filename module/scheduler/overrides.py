"""复用参数生成元数据验证本次调用的白名单覆盖。"""
import json
import math
import re
from functools import cache
from pathlib import Path

from module.scheduler.catalog import OVERRIDES


@cache
def arguments():
    path = Path(__file__).resolve().parents[1] / 'config/argument/args.json'
    return json.loads(path.read_text(encoding='utf-8'))


def check_overrides(task, overrides):
    for name, value in overrides.items():
        if name not in OVERRIDES:
            raise ValueError(f'临时参数不在白名单：{name}')
        group, argument = name.split('_', 1)
        field = arguments().get(task, {}).get(group, {}).get(argument)
        if not field:
            raise ValueError(f'任务 {task} 不支持参数 {name}')
        default = field.get('value')
        valid = type(value) is int and value >= 0 if OVERRIDES[name] == 'integer' else isinstance(value, str) and 0 < len(value) <= 200
        if type(default) is bool or (type(default) is int and type(value) is not int):
            valid = False
        options = field.get('option')
        if options and not any(type(value) is type(item) and value == item for item in options):
            valid = False
        rule = field.get('validate')
        if isinstance(rule, list) and len(rule) == 2:
            valid = valid and type(value) in (int, float) and math.isfinite(value) and rule[0] <= value <= rule[1]
        elif isinstance(rule, str):
            valid = valid and bool(re.fullmatch(rule, str(value)))
        if not valid:
            raise ValueError(f'临时参数类型、范围或选项无效：{name}')
