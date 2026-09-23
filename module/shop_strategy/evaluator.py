"""受限策略表达式的纯 AST 解释器。"""

from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from module.shop_strategy.compiler import CANDIDATE_FIELDS, _literal_value, _name_id, _node_location, _node_name
from module.shop_strategy.errors import StrategyDiagnostic, StrategyRuntimeError
from module.shop_strategy.models import ShopCandidate, ShopContext

MAX_ABSOLUTE_NUMBER = 10 ** 12
MAX_ABSOLUTE_EXPONENT = 64


def runtime_error(code: str, message: str, node: Any | None = None) -> StrategyRuntimeError:
    """创建带源码位置的运行期错误。"""
    line, column = _node_location(node)
    return StrategyRuntimeError(StrategyDiagnostic(code, message, line, column))


def lua_truthy(value: Any) -> bool:
    """Lua 只有 nil 和 false 为假，0 与空字符串仍为真。"""
    return value is not None and value is not False


def candidate_values(candidate: ShopCandidate) -> dict[str, Any]:
    """生成脚本可见字段，避免反射读取 dataclass 内部状态。"""
    return {field: getattr(candidate, field) for field in CANDIDATE_FIELDS}


def context_values(context: ShopContext) -> dict[str, Any]:
    """生成脚本可见的只读会话上下文。"""
    return {
        'domain': context.domain,
        'currency': context.currency,
        'spent': context.spent,
        'purchased': context.purchased,
    }


def number(value: Any, node: Any) -> int | float:
    """验证算术操作数或评分为有限数值。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise runtime_error('number_required', '此表达式必须返回有限数值', node)
    try:
        valid = isfinite(value) and abs(value) <= MAX_ABSOLUTE_NUMBER
    except OverflowError:
        valid = False
    if not valid:
        raise runtime_error('number_required', '此表达式必须返回有限且不超过安全范围的数值', node)
    return value


def _index_key(node: Any, env: Mapping[str, Any] | None = None) -> str:
    name = _name_id(node)
    if name is not None:
        return name
    try:
        value = _literal_value(node)
    except Exception:
        if env is None:
            raise runtime_error('invalid_index', '字段名必须是字符串', node)
        value = evaluate_expression(node, env)
    if isinstance(value, str):
        return value
    raise runtime_error('invalid_index', '字段名必须是字符串', node)


def evaluate_expression(node: Any, env: Mapping[str, Any]) -> Any:
    """解释一条已校验表达式，不使用 Python eval。"""
    name = _node_name(node)
    if name in {'Number', 'String', 'True', 'False', 'Nil'}:
        return _literal_value(node)
    if name == 'Name':
        identifier = _name_id(node)
        if identifier in env:
            return env[identifier]
        raise runtime_error('unknown_name', f'策略变量 {identifier!r} 不存在', node)
    if name == 'Index':
        value = evaluate_expression(getattr(node, 'value', None), env)
        key = _index_key(getattr(node, 'idx', None), env)
        if not isinstance(value, Mapping):
            raise runtime_error('invalid_field_access', '只能读取只读字段', node)
        # 未出现的货币和会话计数按 0 处理，减少无关分支的脚本失败。
        return value.get(key, 0)
    if name == 'LAndOp':
        left = evaluate_expression(getattr(node, 'left', None), env)
        return evaluate_expression(getattr(node, 'right', None), env) if lua_truthy(left) else left
    if name == 'LOrOp':
        left = evaluate_expression(getattr(node, 'left', None), env)
        return left if lua_truthy(left) else evaluate_expression(getattr(node, 'right', None), env)
    if name == 'ULNotOp':
        return not lua_truthy(evaluate_expression(getattr(node, 'operand', None), env))
    if name == 'UMinusOp':
        return -number(evaluate_expression(getattr(node, 'operand', None), env), node)
    left = evaluate_expression(getattr(node, 'left', None), env)
    right = evaluate_expression(getattr(node, 'right', None), env)
    if name == 'AddOp':
        return number(number(left, node) + number(right, node), node)
    if name == 'SubOp':
        return number(number(left, node) - number(right, node), node)
    if name == 'MultOp':
        return number(number(left, node) * number(right, node), node)
    if name in {'FloatDivOp', 'FloorDivOp', 'ModOp'}:
        divisor = number(right, node)
        if divisor == 0:
            raise runtime_error('division_by_zero', '除数不能为 0', node)
        dividend = number(left, node)
        if name == 'FloatDivOp':
            return number(dividend / divisor, node)
        if name == 'FloorDivOp':
            return number(dividend // divisor, node)
        return number(dividend % divisor, node)
    if name == 'ExpoOp':
        base = number(left, node)
        exponent = number(right, node)
        if abs(exponent) > MAX_ABSOLUTE_EXPONENT:
            raise runtime_error('exponent_limit', f'幂指数绝对值不能超过 {MAX_ABSOLUTE_EXPONENT}', node)
        try:
            value = base ** exponent
        except (OverflowError, ValueError, ZeroDivisionError) as error:
            raise runtime_error('invalid_number', '幂运算结果无效', node) from error
        return number(value, node)
    if name == 'REqOp':
        return left == right
    if name == 'RNotEqOp':
        return left != right
    if name in {'RLtOp', 'RLtEqOp', 'RGtOp', 'RGtEqOp'}:
        try:
            if name == 'RLtOp':
                return left < right
            if name == 'RLtEqOp':
                return left <= right
            if name == 'RGtOp':
                return left > right
            return left >= right
        except TypeError as error:
            raise runtime_error('invalid_comparison', '比较两侧的类型不兼容', node) from error
    raise runtime_error('forbidden_expression', f'不支持 {name} 表达式', node)


def run_item_function(node: Any, candidate: ShopCandidate, env: Mapping[str, Any]) -> Any:
    """以只读商品投影调用已验证的 ``function(item) return ... end``。"""
    body = getattr(node, 'body', None)
    statement = next(
        statement for statement in getattr(body, 'body', [])
        if _node_name(statement) != 'SemiColon'
    )
    expression = getattr(statement, 'values', [None])[0]
    item_env = dict(env)
    item_env['item'] = candidate_values(candidate)
    return evaluate_expression(expression, item_env)
