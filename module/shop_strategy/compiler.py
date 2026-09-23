"""受限 Lua AST 的解析和白名单校验。

这里仅使用 ``luaparser`` 生成 AST；不会加载 Lua VM，也不会执行源码。
运行期解释器位于 :mod:`module.shop_strategy.runtime`。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from module.shop_strategy.errors import (
    ShopStrategyError,
    StrategyCompileError,
    StrategyDiagnostic,
)
from module.shop_strategy.models import CompiledStrategy

MAX_SOURCE_LENGTH = 20_000
MAX_AST_NODES = 500
MAX_PIPELINE_STEPS = 16
MAX_SCORE_TAKE = 20
MAX_TAKE = 100

CANDIDATE_FIELDS = frozenset({
    'id', 'key', 'name', 'group', 'sub_genre', 'tier', 'price', 'cost',
    'stock', 'max_quantity', 'available',
})
CONTEXT_FIELDS = frozenset({'domain', 'currency', 'spent', 'purchased'})
PIPELINE_METHODS = frozenset({'where', 'score', 'order_by', 'cap', 'take'})
ARITHMETIC_NODES = frozenset({
    'AddOp', 'SubOp', 'MultOp', 'FloatDivOp', 'FloorDivOp', 'ModOp', 'ExpoOp',
})
COMPARISON_NODES = frozenset({
    'REqOp', 'RNotEqOp', 'RLtOp', 'RLtEqOp', 'RGtOp', 'RGtEqOp',
})
BOOLEAN_NODES = frozenset({'LAndOp', 'LOrOp'})
LITERAL_NODES = frozenset({'Number', 'String', 'True', 'False', 'Nil'})


def _node_name(node: Any) -> str:
    return getattr(node, '_name', type(node).__name__)


def _node_location(node: Any) -> tuple[int | None, int | None]:
    """将 antlr 的零基列号转换为 UI 使用的一基行列。"""
    token = getattr(node, '_first_token', None)
    if token is None:
        return None, None
    line = getattr(token, 'line', None)
    column = getattr(token, 'column', None)
    if not isinstance(line, int):
        return None, None
    return line, column + 1 if isinstance(column, int) else None


def _error(code: str, message: str, node: Any | None = None) -> StrategyCompileError:
    line, column = _node_location(node)
    return StrategyCompileError(StrategyDiagnostic(code, message, line, column))


def _parse_error(error: Exception) -> StrategyCompileError:
    """从 luaparser 的稳定文本错误中提取位置。"""
    match = re.search(r'line\s+(\d+):(\d+)', str(error))
    line = int(match.group(1)) if match else None
    column = int(match.group(2)) + 1 if match else None
    return StrategyCompileError(StrategyDiagnostic(
        'syntax_error', 'Lua 语法无效', line, column,
    ))


def _iter_nodes(value: Any, seen: set[int] | None = None):
    """遍历 AST 节点，忽略 antlr token 和注释对象。"""
    if seen is None:
        seen = set()
    if not hasattr(value, '_name') or id(value) in seen:
        return
    seen.add(id(value))
    yield value
    for key, child in vars(value).items():
        if key in {'_first_token', '_last_token', 'comments'}:
            continue
        if isinstance(child, list):
            for item in child:
                yield from _iter_nodes(item, seen)
        else:
            yield from _iter_nodes(child, seen)


def _name_id(node: Any) -> str | None:
    return getattr(node, 'id', None) if _node_name(node) == 'Name' else None


def _literal_value(node: Any) -> str | int | float | bool | None:
    """返回 Lua 字面量；非字面量会被拒绝。"""
    name = _node_name(node)
    if name == 'Number':
        value = getattr(node, 'n', None)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _error('invalid_literal', '数值字面量无效', node)
        return value
    if name == 'String':
        value = getattr(node, 's', b'')
        if isinstance(value, bytes):
            return value.decode('utf-8')
        if isinstance(value, str):
            return value
        raise _error('invalid_literal', '字符串字面量无效', node)
    if name == 'True':
        return True
    if name == 'False':
        return False
    if name == 'Nil':
        return None
    raise _error('invalid_literal', '此处只能使用字面量', node)


class _Validator:
    """只接受策略语言需要的节点，拒绝 Lua 的其余全部语法。"""

    def __init__(self) -> None:
        self.locals: set[str] = set()
        self.pipeline_locals: dict[str, tuple[int, bool, bool]] = {}

    def validate(self, tree: Any) -> None:
        if _node_name(tree) != 'Chunk':
            raise _error('invalid_root', '策略必须是 Lua 代码块', tree)
        body = getattr(tree, 'body', None)
        self._validate_block(body, nested=False)
        if not self._always_returns(body):
            raise _error('missing_return', '每条策略分支都必须 return shop.plan {...}', body)

    def _validate_block(self, block: Any, nested: bool) -> None:
        if _node_name(block) != 'Block':
            raise _error('invalid_block', '策略代码块无效', block)
        statements = [
            statement for statement in getattr(block, 'body', [])
            if _node_name(statement) != 'SemiColon'
        ]
        for index, statement in enumerate(statements):
            name = _node_name(statement)
            if name == 'LocalAssign':
                if nested:
                    raise _error('local_scope', 'local 只能定义在策略顶层', statement)
                self._validate_local(statement)
            elif name == 'If':
                self._validate_if(statement)
            elif name == 'Return':
                self._validate_return(statement)
                if index != len(statements) - 1:
                    raise _error('unreachable_statement', 'return 后不能再定义语句', statements[index + 1])
            else:
                raise _error('forbidden_statement', f'不支持 {_node_name(statement)} 语句', statement)

    def _validate_local(self, node: Any) -> None:
        targets = getattr(node, 'targets', [])
        values = getattr(node, 'values', [])
        if len(targets) != 1 or len(values) != 1:
            raise _error('local_arity', 'local 必须只定义一个变量', node)
        target = _name_id(targets[0])
        if not target or target in {'candidates', 'context', 'shop'}:
            raise _error('invalid_local', 'local 变量名不可用', targets[0])
        if target in self.locals:
            raise _error('duplicate_local', f'local 变量 {target!r} 已定义', targets[0])
        value = values[0]
        if self._is_pipeline(value):
            self.pipeline_locals[target] = self._validate_pipeline(value, root=False)
        else:
            self._validate_expression(value, item_scope=False)
        self.locals.add(target)

    def _validate_if(self, node: Any) -> None:
        self._validate_expression(getattr(node, 'test', None), item_scope=False)
        self._validate_block(getattr(node, 'body', None), nested=True)
        orelse = getattr(node, 'orelse', None)
        if orelse is not None:
            if _node_name(orelse) == 'ElseIf':
                self._validate_if(orelse)
            else:
                self._validate_block(orelse, nested=True)

    def _validate_return(self, node: Any) -> None:
        values = getattr(node, 'values', [])
        if len(values) != 1:
            raise _error('return_arity', 'return 必须返回一个 shop.plan', node)
        self._validate_plan_call(values[0])

    def _validate_plan_call(self, node: Any) -> None:
        if _node_name(node) != 'Call':
            raise _error('invalid_return', 'return 只能返回 shop.plan {...}', node)
        func = getattr(node, 'func', None)
        if not self._is_index(func, 'shop', 'plan'):
            raise _error('invalid_plan_call', '仅允许调用 shop.plan', node)
        args = getattr(node, 'args', [])
        if len(args) != 1 or _node_name(args[0]) != 'Table':
            raise _error('plan_arguments', 'shop.plan 必须接收一个表', node)
        fields = self._named_table(args[0], '计划')
        unknown = set(fields) - {'reserve', 'max_spend', 'candidates'}
        if unknown:
            raise _error('unknown_plan_field', f'不支持计划字段 {sorted(unknown)[0]!r}', args[0])
        if 'candidates' not in fields:
            raise _error('missing_candidates', 'shop.plan 必须提供 candidates', args[0])
        for name in ('reserve', 'max_spend'):
            if name in fields:
                if _node_name(fields[name]) != 'Table':
                    raise _error('invalid_budget', f'{name} 必须是货币金额表', fields[name])
                for amount in self._named_table(fields[name], name).values():
                    self._validate_expression(amount, item_scope=False)
        self._validate_pipeline(fields['candidates'])

    def _named_table(self, node: Any, subject: str) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for field in getattr(node, 'fields', []):
            if _node_name(field) != 'Field':
                raise _error('invalid_table', f'{subject} 只能使用命名字段', field)
            key = getattr(field, 'key', None)
            key_name = _name_id(key)
            if key_name is None and _node_name(key) == 'String':
                key_name = _literal_value(key)
            if not isinstance(key_name, str) or not key_name:
                raise _error('invalid_table_key', f'{subject} 的字段名无效', field)
            if key_name in output:
                raise _error('duplicate_table_key', f'{subject} 重复字段 {key_name!r}', field)
            if getattr(field, 'between_brackets', False):
                raise _error('invalid_table_key', f'{subject} 不支持动态字段名', field)
            output[key_name] = getattr(field, 'value', None)
        return output

    def _is_pipeline(self, node: Any) -> bool:
        return (
            _name_id(node) == 'candidates'
            or _node_name(node) == 'Invoke'
            or _name_id(node) in self.pipeline_locals
        )

    def _validate_pipeline(self, node: Any, root: bool = True) -> tuple[int, bool, bool]:
        """校验候选管道，返回步骤数、是否评分、是否截断。"""
        name = _name_id(node)
        if name == 'candidates':
            result = (0, False, False)
        elif name in self.pipeline_locals:
            result = self.pipeline_locals[name]
        elif _node_name(node) != 'Invoke':
            raise _error('invalid_pipeline', 'candidates 必须是候选管道', node)
        else:
            source = getattr(node, 'source', None)
            steps, has_score, has_take = self._validate_pipeline(source, root=False)
            method = _name_id(getattr(node, 'func', None))
            if method not in PIPELINE_METHODS:
                raise _error('forbidden_call', '候选管道只允许 where、score、order_by、cap、take', node)
            steps += 1
            if steps > MAX_PIPELINE_STEPS:
                raise _error('pipeline_limit', f'候选管道最多 {MAX_PIPELINE_STEPS} 步', node)
            args = getattr(node, 'args', [])
            if method in {'where', 'score'}:
                if len(args) != 1:
                    raise _error('pipeline_arguments', f'{method} 需要一个 function(item)', node)
                self._validate_item_function(args[0], method)
                if method == 'score':
                    if has_score:
                        raise _error('duplicate_score', '候选管道只能使用一次 score', node)
                    if has_take:
                        raise _error('score_before_take', 'score 必须出现在 take 之前', node)
                    has_score = True
            elif method == 'order_by':
                if len(args) not in {1, 2}:
                    raise _error('pipeline_arguments', 'order_by 需要字段名和可选方向', node)
                field = self._string_argument(args[0], 'order_by 的字段名')
                self._validate_candidate_field(field, args[0])
                if len(args) == 2 and self._string_argument(args[1], 'order_by 的方向') not in {'asc', 'desc'}:
                    raise _error('invalid_order', 'order_by 方向只能是 asc 或 desc', args[1])
            elif method == 'cap':
                if len(args) != 3:
                    raise _error('pipeline_arguments', 'cap 需要字段名、字段值和数量上限', node)
                field = self._string_argument(args[0], 'cap 的字段名')
                self._validate_candidate_field(field, args[0])
                _literal_value(args[1])
                limit = _literal_value(args[2])
                if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                    raise _error('invalid_cap', 'cap 数量上限必须为非负整数', args[2])
            else:
                if len(args) != 1:
                    raise _error('pipeline_arguments', 'take 需要一个数量上限', node)
                limit = _literal_value(args[0])
                if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= MAX_TAKE:
                    raise _error('invalid_take', f'take 必须在 0 到 {MAX_TAKE} 之间', args[0])
                if has_take:
                    raise _error('duplicate_take', '候选管道只能使用一次 take', node)
                has_take = True
                if has_score and limit > MAX_SCORE_TAKE:
                    raise _error('score_take_limit', f'评分规划的 take 不能超过 {MAX_SCORE_TAKE}', args[0])
            result = (steps, has_score, has_take)
        if root and result[1] and not result[2]:
            raise _error('score_requires_take', f'评分规划必须使用 take，且不能超过 {MAX_SCORE_TAKE}', node)
        return result

    def _validate_item_function(self, node: Any, method: str) -> None:
        if _node_name(node) != 'AnonymousFunction':
            raise _error('invalid_function', f'{method} 只能接收 function(item)', node)
        args = getattr(node, 'args', [])
        if len(args) != 1 or _name_id(args[0]) != 'item':
            raise _error('function_arguments', '匿名函数参数必须为 item', node)
        body = getattr(node, 'body', None)
        statements = [
            statement for statement in getattr(body, 'body', [])
            if _node_name(statement) != 'SemiColon'
        ]
        if len(statements) != 1 or _node_name(statements[0]) != 'Return':
            raise _error('function_body', '匿名函数只能包含一个 return 表达式', body)
        values = getattr(statements[0], 'values', [])
        if len(values) != 1:
            raise _error('function_return', '匿名函数必须返回一个表达式', statements[0])
        self._validate_expression(values[0], item_scope=True)

    def _validate_expression(self, node: Any, item_scope: bool) -> None:
        name = _node_name(node)
        if name in LITERAL_NODES:
            _literal_value(node)
            return
        if name == 'Name':
            identifier = _name_id(node)
            if identifier in self.locals or identifier == 'context' or (item_scope and identifier == 'item'):
                return
            raise _error('unknown_name', f'不支持变量 {identifier!r}', node)
        if name == 'Index':
            self._validate_index(node, item_scope)
            return
        if name in ARITHMETIC_NODES | COMPARISON_NODES | BOOLEAN_NODES:
            self._validate_expression(getattr(node, 'left', None), item_scope)
            self._validate_expression(getattr(node, 'right', None), item_scope)
            return
        if name in {'ULNotOp', 'UMinusOp'}:
            self._validate_expression(getattr(node, 'operand', None), item_scope)
            return
        raise _error('forbidden_expression', f'不支持 {_node_name(node)} 表达式', node)

    def _validate_index(self, node: Any, item_scope: bool) -> None:
        value = getattr(node, 'value', None)
        idx = getattr(node, 'idx', None)
        if 'SQUARE' in str(getattr(node, 'notation', '')) and _name_id(idx) is not None:
            raise _error('invalid_index', '方括号索引必须使用字符串字面量', idx)
        root = _name_id(value)
        if root == 'item' and item_scope:
            field = self._index_key(idx)
            self._validate_candidate_field(field, node)
            return
        if root == 'context':
            field = self._index_key(idx)
            if field not in CONTEXT_FIELDS:
                raise _error('unknown_context_field', f'不支持 context.{field}', node)
            return
        if _node_name(value) == 'Index' and _name_id(getattr(value, 'value', None)) == 'context':
            parent = self._index_key(getattr(value, 'idx', None))
            if parent in {'currency', 'spent', 'purchased'}:
                if parent == 'purchased' and item_scope and self._is_index(idx, 'item', 'id'):
                    return
                field = self._index_key(idx)
                if not isinstance(field, str) or not field:
                    raise _error(
                        'invalid_context_key',
                        '货币和消费记录必须使用固定字符串键；购买记录可使用 item.id',
                        node,
                    )
                return
        raise _error('forbidden_field', '只能读取 item 和 context 的白名单字段', node)

    def _validate_candidate_field(self, field: str, node: Any) -> None:
        if field not in CANDIDATE_FIELDS:
            raise _error('unknown_candidate_field', f'不支持商品字段 {field!r}', node)

    def _index_key(self, node: Any) -> str:
        identifier = _name_id(node)
        if identifier is not None:
            return identifier
        value = _literal_value(node)
        if not isinstance(value, str):
            raise _error('invalid_index', '字段名必须是固定字符串', node)
        return value

    def _is_index(self, node: Any, root: str, field: str) -> bool:
        return (
            _node_name(node) == 'Index'
            and _name_id(getattr(node, 'value', None)) == root
            and _name_id(getattr(node, 'idx', None)) == field
        )

    def _string_argument(self, node: Any, subject: str) -> str:
        value = _literal_value(node)
        if not isinstance(value, str):
            raise _error('invalid_argument', f'{subject} 必须是字符串', node)
        return value

    def _always_returns(self, block: Any) -> bool:
        if _node_name(block) == 'ElseIf':
            orelse = getattr(block, 'orelse', None)
            return (
                self._always_returns(getattr(block, 'body', None))
                and orelse is not None
                and self._always_returns(orelse)
            )
        statements = [
            statement for statement in getattr(block, 'body', [])
            if _node_name(statement) != 'SemiColon'
        ]
        if not statements:
            return False
        last = statements[-1]
        if _node_name(last) == 'Return':
            return True
        if _node_name(last) != 'If':
            return False
        orelse = getattr(last, 'orelse', None)
        if orelse is None:
            return False
        return self._always_returns(getattr(last, 'body', None)) and self._always_returns(orelse)


def compile_strategy(source: str) -> CompiledStrategy:
    """解析并校验策略源码。

    空脚本在配置校验中可保留，但不能编译为可执行策略。调用方应在
    ``strategy_diagnostics`` 或 ``validate_strategy`` 中处理空字符串。
    """
    if not isinstance(source, str):
        raise _error('invalid_source', '策略源码必须是字符串')
    if not source.strip():
        raise _error('empty_script', '高级模式需要非空策略源码')
    if len(source) > MAX_SOURCE_LENGTH:
        raise _error('source_limit', f'策略源码不能超过 {MAX_SOURCE_LENGTH} 个字符')
    try:
        from luaparser import ast
    except ModuleNotFoundError as error:
        raise _error('dependency_missing', '缺少 luaparser 依赖，无法校验高级策略') from error
    try:
        tree = ast.parse(source)
    except Exception as error:
        raise _parse_error(error) from error
    nodes = list(_iter_nodes(tree))
    if len(nodes) > MAX_AST_NODES:
        raise _error('ast_limit', f'策略 AST 不能超过 {MAX_AST_NODES} 个节点', tree)
    _Validator().validate(tree)
    return CompiledStrategy(
        source=source,
        source_hash=hashlib.sha256(source.encode('utf-8')).hexdigest(),
        tree=tree,
        ast_nodes=len(nodes),
    )


def strategy_diagnostics(source: str) -> list[StrategyDiagnostic]:
    """返回配置编辑器使用的诊断；空脚本视为未启用高级模式。"""
    if isinstance(source, str) and not source.strip():
        return []
    try:
        compile_strategy(source)
    except ShopStrategyError as error:
        return [error.diagnostic]
    return []


def validate_strategy(source: str) -> dict[str, bool | list[dict[str, str | int | None]]]:
    """返回稳定、JSON 可序列化的校验结果。"""
    diagnostics = strategy_diagnostics(source)
    return {
        'valid': not diagnostics,
        'diagnostics': [diagnostic.as_dict() for diagnostic in diagnostics],
    }
