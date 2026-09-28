"""潜艇高级配置解析、出击规划和单张地图的资源记录。"""

import fnmatch
import operator
import re
from dataclasses import dataclass

import yaml

from module.exception import ScriptError

OPERATORS = {
    '>': operator.gt, '>=': operator.ge, '<': operator.lt,
    '<=': operator.le, '=': operator.eq, '!=': operator.ne,
}


@dataclass(frozen=True)
class SubmarinePlan:
    """潜艇出击计划。

    一次可执行的出击；移动位置为空表示无需移动。

    Attributes:
        mode (str): 出击模式，'call' 为战斗中呼叫，'hunt' 为地图狩猎。
        support (bool): 是否使用远洋支援。默认为 False。
        location (tuple | None): 潜艇需移动到的目标网格坐标，为 None 表示无需移动。默认为 None。
    """

    mode: str
    support: bool = False
    location: tuple | None = None


class SubmarineAdvancedConfig:
    """潜艇高级配置解析器与出击规划器。

    只使用安全 YAML 和显式比较运算，不执行配置中的代码。

    Attributes:
        ammo (int): 当前潜艇弹药量。
        support (int): 当前远洋支援次数。
        offsets (set[tuple[int, int]]): 潜艇狩猎范围相对坐标集合。
        rules (list[tuple[int, dict]]): 规则列表，包含战斗序号与规则字典。
        plan (SubmarinePlan | None): 当前规划的出击计划。
        consumed (bool): 当前计划是否已消耗资源。
    """

    def __init__(self, text):
        """初始化潜艇高级配置。

        Args:
            text (str): YAML 格式的潜艇高级配置文本。

        Raises:
            ScriptError: 配置 YAML 无效或缺少必要键、字段类型错误时抛出。
        """
        try:
            # 兼容旧版默认示例在行尾注释前附带的制表符。
            data = yaml.safe_load(text.expandtabs(2))
        except (yaml.YAMLError, AttributeError) as error:
            raise ScriptError(f'潜艇高级配置 YAML 无效：{error}') from error
        self._mapping(data, {'ammo', 'support', 'range', 'rules'}, '配置')
        for name in ('ammo', 'support'):
            if type(data.get(name)) is not int or data[name] < 0:
                raise ScriptError(f'潜艇高级配置 {name} 必须是非负整数')
        self.ammo = data['ammo']
        self.support = data['support']
        rows = data.get('range')
        if (not isinstance(rows, list) or len(rows) != 7
                or any(not isinstance(row, str) or len(row) != 7 for row in rows)
                or any(char not in 'NOH' for row in rows for char in row)
                or rows[3][3] != 'H' or sum(row.count('H') for row in rows) != 1):
            raise ScriptError('潜艇高级配置 range 必须是 7×7 的 N/O/H 字符串，且唯一的 H 位于中心')
        self.offsets = {
            (x - 3, y - 3) for y, row in enumerate(rows)
            for x, char in enumerate(row) if char in 'NH'
        }
        rules = data.get('rules')
        if not isinstance(rules, dict):
            raise ScriptError('潜艇高级配置 rules 必须是规则字典')
        self.rules = []
        for name, rule in rules.items():
            if not isinstance(name, str) or not re.fullmatch(r'battle_-?\d+', name):
                raise ScriptError(f'潜艇高级配置战斗索引无效：{name}')
            # support 是旧版默认示例中的可选字段，保留其允许远洋支援的含义。
            self._mapping(rule, {'type', 'condition', 'move', 'support'}, name)
            if rule.get('type') not in ('hunt', 'call'):
                raise ScriptError(f'潜艇高级配置 {name}.type 必须是 hunt 或 call')
            for key in ('move', 'support'):
                if key in rule and type(rule[key]) is not bool:
                    raise ScriptError(f'潜艇高级配置 {name}.{key} 必须是布尔值')
            condition = rule.get('condition', {})
            self._mapping(condition, {'ammo', 'support', 'enemy', 'in_range'}, f'{name}.condition')
            for key in ('ammo', 'support'):
                if key in condition:
                    expression = condition[key]
                    if not isinstance(expression, str) or not re.fullmatch(
                            r'\s*(>=|<=|!=|>|<|=)\s*\d+\s*', expression):
                        raise ScriptError(f'潜艇高级配置 {name}.condition.{key} 比较表达式无效')
            if 'in_range' in condition and type(condition['in_range']) is not bool:
                raise ScriptError(f'潜艇高级配置 {name}.condition.in_range 必须是布尔值')
            if 'enemy' in condition:
                enemies = condition['enemy']
                if not isinstance(enemies, list) or any(
                        not isinstance(enemy, str) or not re.fullmatch(r'[0-3*][LMCTE*]', enemy)
                        for enemy in enemies):
                    raise ScriptError(f'潜艇高级配置 {name}.condition.enemy 必须是规模与舰种列表')
            self.rules.append((int(name[7:]), rule))
        self.plan = None
        self.consumed = False

    @staticmethod
    def _mapping(value, allowed, path):
        """校验字典键的合法性，拒绝拼写错误避免遗漏条件后意外消耗资源。

        Args:
            value (dict): 待校验的字典对象。
            allowed (set[str]): 允许存在的键集合。
            path (str): 字段路径说明，用于错误提示。

        Raises:
            ScriptError: 包含未允许的键或不是字典时抛出。
        """
        if not isinstance(value, dict) or set(value) - allowed:
            raise ScriptError(f'潜艇高级配置 {path} 必须是字典且只能包含：{", ".join(sorted(allowed))}')

    def in_range(self, target, origin):
        """以地图横纵坐标计算相对位置，判断目标是否在潜艇狩猎范围内。

        保留非对称狩猎范围特性。

        Args:
            target (tuple[int, int]): 目标敌舰坐标。
            origin (tuple[int, int]): 潜艇当前坐标。

        Returns:
            bool: 目标是否在潜艇覆盖范围内。
        """
        return bool(origin) and (target[0] - origin[0], target[1] - origin[1]) in self.offsets

    @staticmethod
    def _compare(value, expression):
        """执行条件表达式比较。

        Args:
            value (int): 当前资源数值。
            expression (str): 比较表达式，如 '>= 1'。

        Returns:
            bool: 比较结果。
        """
        match = re.fullmatch(r'\s*(>=|<=|!=|>|<|=)\s*(\d+)\s*', expression)
        return OPERATORS[match[1]](value, int(match[2]))

    def choose(self, battle, total, enemy, target, origin, positions=()):
        """按召唤、狩猎顺序选取满足条件且可以执行的规则。

        Args:
            battle (int): 当前战斗序号，从 1 开始。
            total (int | None): 预计最终战斗序号，无法确定时为 None。
            enemy (str): 已识别的规模与舰种，例如 '3M'。
            target (tuple[int, int]): 目标敌舰坐标。
            origin (tuple[int, int]): 潜艇当前位置。
            positions (Sequence[tuple[tuple[int, int], int]], optional): 可移动位置和移动代价组成的序列。默认为 ()。

        Returns:
            SubmarinePlan | None: 不突破弹药和覆盖范围限制的出击计划。
        """
        if self.ammo <= 0 or not origin:
            return None
        covered = self.in_range(target, origin)
        for mode in ('call', 'hunt'):
            for index, rule in self.rules:
                if rule['type'] != mode:
                    continue
                if index != 0 and index != battle and not (
                        index < 0 and total is not None and battle == total + index + 1):
                    continue
                condition = rule.get('condition', {})
                if any(key in condition and not self._compare(getattr(self, key), condition[key])
                       for key in ('ammo', 'support')):
                    continue
                if 'enemy' in condition and not any(
                        fnmatch.fnmatchcase(enemy, pattern) for pattern in condition['enemy']):
                    continue
                if covered:
                    return SubmarinePlan(mode)
                # in_range=false 表示不要求覆盖，不表示必须在范围外。
                # 狩猎永远不能使用远洋支援；要求覆盖的召唤也必须先移动。
                if (mode == 'call' and self.support > 0 and rule.get('support', True)
                        and not condition.get('in_range', False)):
                    return SubmarinePlan(mode, support=True)
                if rule.get('move', False):
                    candidates = [(cost, location) for location, cost in positions
                                  if self.in_range(target, location)]
                    if candidates:
                        return SubmarinePlan(mode, location=min(candidates)[1])
        return None

    def set_plan(self, plan):
        """设置当前出击计划，重置本次消耗标记。

        目标改变或新战斗开始时调用。

        Args:
            plan (SubmarinePlan | None): 新的出击计划。
        """
        self.plan = plan
        self.consumed = False

    def consume(self, mode):
        """扣减潜艇出击所消耗的弹药或远洋支援次数。

        狩猎进入战斗或确认召唤后仅扣减一次，点击重试不重复扣减。

        Args:
            mode (str): 出击模式（'hunt' 或 'call'）。

        Returns:
            bool: 是否成功扣减了资源。
        """
        if self.plan is None or self.plan.mode != mode or self.consumed or self.ammo <= 0:
            return False
        self.ammo -= 1
        if self.plan.support:
            self.support -= 1
        self.consumed = True
        return True
