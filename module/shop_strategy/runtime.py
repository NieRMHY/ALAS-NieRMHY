"""受限商店策略的 AST 解释和有界购买规划。

本模块只读取经过 ``compile_strategy`` 白名单校验的 AST。它不调用 Lua
运行时，也不把 Python 商店对象暴露给源码；运行期值仅为数据模型投影。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from module.shop_strategy.compiler import (
    _literal_value,
    _name_id,
    _node_name,
    compile_strategy,
)
from module.shop_strategy.evaluator import (
    context_values as _context_values,
    evaluate_expression as _evaluate_expression,
    lua_truthy as _lua_truthy,
    number as _number,
    run_item_function as _run_item_function,
    runtime_error as _runtime_error,
)
from module.shop_strategy.errors import StrategyRuntimeError
from module.shop_strategy.models import (
    CompiledStrategy,
    ShopAction,
    ShopCap,
    ShopCandidate,
    ShopContext,
    ShopPlan,
    cap_usage_key,
    merge_caps,
)

MAX_PLANNER_STATES = 50_000


@dataclass(frozen=True, slots=True)
class _Cap:
    """候选字段相等时适用的跨商品数量上限。"""

    field: str
    value: str | int | float | bool | None
    limit: int


@dataclass(frozen=True, slots=True)
class _RankedCandidate:
    """携带评分的候选商品，保留输入顺序以保证平局稳定。"""

    candidate: ShopCandidate
    source_index: int
    score: float | None = None


@dataclass(frozen=True, slots=True)
class _Pipeline:
    """管道中间值，不含任何宿主业务对象。"""

    items: tuple[_RankedCandidate, ...]
    caps: tuple[_Cap, ...] = ()
    scored: bool = False


def _table_fields(node: Any) -> dict[str, Any]:
    """读取已由编译期确认过的命名表。"""
    output: dict[str, Any] = {}
    for field in getattr(node, 'fields', []):
        key = getattr(field, 'key', None)
        name = _name_id(key)
        if name is None:
            name = _literal_value(key)
        output[name] = getattr(field, 'value', None)
    return output


def _sort_pipeline(items: tuple[_RankedCandidate, ...], field: str, direction: str) -> tuple[_RankedCandidate, ...]:
    """稳定排序且始终把 None 放在末尾。"""
    present = [item for item in items if getattr(item.candidate, field) is not None]
    absent = [item for item in items if getattr(item.candidate, field) is None]
    try:
        present.sort(key=lambda item: getattr(item.candidate, field), reverse=direction == 'desc')
    except TypeError as error:
        raise _runtime_error('invalid_order', f'字段 {field!r} 不能用于排序') from error
    return tuple((*present, *absent))


def _score_order(items: tuple[_RankedCandidate, ...]) -> tuple[_RankedCandidate, ...]:
    """评分高的候选优先，稳定保留前序 order_by 或输入顺序作为平局规则。"""
    return tuple(sorted(items, key=lambda item: item.score or 0, reverse=True))


def _run_pipeline(node: Any, env: Mapping[str, Any]) -> _Pipeline:
    """按链式调用顺序解释候选管道。"""
    name = _name_id(node)
    if name == 'candidates':
        value = env.get('candidates')
        if isinstance(value, _Pipeline):
            return value
    if name is not None and isinstance(env.get(name), _Pipeline):
        return env[name]
    if _node_name(node) != 'Invoke':
        raise _runtime_error('invalid_pipeline', '候选管道无效', node)
    pipeline = _run_pipeline(getattr(node, 'source', None), env)
    method = _name_id(getattr(node, 'func', None))
    args = getattr(node, 'args', [])
    if method == 'where':
        result = tuple(
            item for item in pipeline.items
            if _lua_truthy(_run_item_function(args[0], item.candidate, env))
        )
        return replace(pipeline, items=result)
    if method == 'score':
        result = []
        for item in pipeline.items:
            score = _number(_run_item_function(args[0], item.candidate, env), args[0])
            result.append(replace(item, score=float(score)))
        return replace(pipeline, items=tuple(result), scored=True)
    if method == 'order_by':
        field = _literal_value(args[0])
        direction = _literal_value(args[1]) if len(args) == 2 else 'asc'
        return replace(pipeline, items=_sort_pipeline(pipeline.items, field, direction))
    if method == 'cap':
        return replace(pipeline, caps=(*pipeline.caps, _Cap(
            _literal_value(args[0]), _literal_value(args[1]), _literal_value(args[2]),
        )))
    if method == 'take':
        items = _score_order(pipeline.items) if pipeline.scored else pipeline.items
        return replace(pipeline, items=items[:_literal_value(args[0])])
    raise _runtime_error('forbidden_call', '候选管道方法无效', node)


def _amount_table(node: Any, env: Mapping[str, Any], subject: str) -> dict[str, int]:
    amounts: dict[str, int] = {}
    for currency, expression in _table_fields(node).items():
        value = _evaluate_expression(expression, env)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _runtime_error('invalid_budget', f'{subject}[{currency!r}] 必须为非负整数', expression)
        amounts[currency] = value
    return amounts


def _candidate_limit(candidate: ShopCandidate, context: ShopContext) -> int:
    purchased = context.inventory_purchased.get(candidate.id, 0)
    return max(0, min(candidate.stock, candidate.max_quantity) - purchased)


def _budget_remaining(
    currencies: Mapping[str, int],
    prior_spent: Mapping[str, int],
    reserve: Mapping[str, int],
    max_spend: Mapping[str, int],
) -> dict[str, int]:
    """计算在保留金额和本会话消费上限后的可用预算。"""
    output: dict[str, int] = {}
    all_costs = set(currencies) | set(prior_spent) | set(reserve) | set(max_spend)
    for cost in all_costs:
        # currency 是本次重新识别到的实际余额；不能再次扣除已消费金额。
        value = max(0, currencies.get(cost, 0) - reserve.get(cost, 0))
        if cost in max_spend:
            value = min(value, max(0, max_spend[cost] - prior_spent.get(cost, 0)))
        output[cost] = value
    return output


def _initial_cap_usage(
    caps: tuple[_Cap, ...],
    items: tuple[_RankedCandidate, ...],
    context: ShopContext,
) -> tuple[int, ...]:
    # cap_usage 由适配器在实际购买后跨刷新维护。不能从当前 items 推导，
    # 因为此前已购买的同类商品可能已经售罄或滚出当前货架。
    return tuple(
        context.cap_usage.get(cap_usage_key(cap.field, cap.value), 0)
        for cap in caps
    )


def _quantity_limit(
    item: _RankedCandidate,
    budgets: Mapping[str, int],
    caps: tuple[_Cap, ...],
    cap_usage: tuple[int, ...],
    context: ShopContext,
) -> int:
    candidate = item.candidate
    limit = _candidate_limit(candidate, context)
    if candidate.price:
        limit = min(limit, budgets.get(candidate.cost, 0) // candidate.price)
    for index, cap in enumerate(caps):
        if getattr(candidate, cap.field) == cap.value:
            limit = min(limit, max(0, cap.limit - cap_usage[index]))
    return limit


def _apply_quantity(
    item: _RankedCandidate,
    quantity: int,
    budgets: Mapping[str, int],
    caps: tuple[_Cap, ...],
    cap_usage: tuple[int, ...],
) -> tuple[dict[str, int], tuple[int, ...]]:
    candidate = item.candidate
    next_budgets = dict(budgets)
    next_budgets[candidate.cost] = next_budgets.get(candidate.cost, 0) - candidate.price * quantity
    next_caps = list(cap_usage)
    for index, cap in enumerate(caps):
        if getattr(candidate, cap.field) == cap.value:
            next_caps[index] += quantity
    return next_budgets, tuple(next_caps)


def _greedy_plan(
    pipeline: _Pipeline,
    context: ShopContext,
    budgets: dict[str, int],
) -> tuple[tuple[int, ...], int]:
    """无评分时按管道顺序尽量购买，完全保留已有 Filter 的确定性偏好。"""
    quantities: list[int] = []
    cap_usage = _initial_cap_usage(pipeline.caps, pipeline.items, context)
    for item in pipeline.items:
        quantity = _quantity_limit(item, budgets, pipeline.caps, cap_usage, context)
        quantities.append(quantity)
        budgets, cap_usage = _apply_quantity(item, quantity, budgets, pipeline.caps, cap_usage)
    return tuple(quantities), len(pipeline.items)


def _scored_plan(
    pipeline: _Pipeline,
    context: ShopContext,
    budgets: dict[str, int],
) -> tuple[tuple[int, ...], int]:
    """在预算和配额约束下枚举有界组合，超出状态限制时安全失败。"""
    initial_caps = _initial_cap_usage(pipeline.caps, pipeline.items, context)
    best_score: float | None = None
    best_quantities: tuple[int, ...] = ()
    states = 0

    def search(
        index: int,
        remaining: dict[str, int],
        cap_usage: tuple[int, ...],
        quantities: tuple[int, ...],
        score: float,
    ) -> None:
        nonlocal best_score, best_quantities, states
        states += 1
        if states > MAX_PLANNER_STATES:
            raise _runtime_error('planner_limit', f'评分规划超过 {MAX_PLANNER_STATES} 个状态')
        if index == len(pipeline.items):
            if best_score is None or score > best_score or (
                score == best_score and quantities > best_quantities
            ):
                best_score = score
                best_quantities = quantities
            return
        item = pipeline.items[index]
        maximum = _quantity_limit(item, remaining, pipeline.caps, cap_usage, context)
        # 从大到小可以更早建立高价值候选，平局时也稳定偏向当前优先级商品。
        for quantity in range(maximum, -1, -1):
            next_budget, next_caps = _apply_quantity(
                item, quantity, remaining, pipeline.caps, cap_usage,
            )
            search(
                index + 1,
                next_budget,
                next_caps,
                (*quantities, quantity),
                score + (item.score or 0) * quantity,
            )

    search(0, dict(budgets), initial_caps, (), 0.0)
    return best_quantities, states


def _build_plan(
    pipeline: _Pipeline,
    reserve: dict[str, int],
    max_spend: dict[str, int],
    context: ShopContext,
) -> ShopPlan:
    """将一条已运行的候选链转换为可执行动作。"""
    pipeline = replace(pipeline, caps=merge_caps(tuple(
        ShopCap(cap.field, cap.value, cap.limit) for cap in pipeline.caps
    )))
    budgets = _budget_remaining(context.currency, context.spent, reserve, max_spend)
    if pipeline.scored:
        quantities, search_states = _scored_plan(pipeline, context, budgets)
    else:
        quantities, search_states = _greedy_plan(pipeline, context, budgets)
    spent: dict[str, int] = {}
    actions: list[ShopAction] = []
    for item, quantity in zip(pipeline.items, quantities):
        if quantity <= 0:
            continue
        candidate = item.candidate
        total = candidate.price * quantity
        spent[candidate.cost] = spent.get(candidate.cost, 0) + total
        actions.append(ShopAction(candidate.id, quantity, candidate.cost, total))
    remaining = dict(budgets)
    for cost, amount in spent.items():
        remaining[cost] = remaining.get(cost, 0) - amount
    return ShopPlan(
        actions=tuple(actions),
        reserve=reserve,
        max_spend=max_spend,
        spent=spent,
        remaining=remaining,
        search_states=search_states,
        caps=tuple(ShopCap(cap.field, cap.value, cap.limit) for cap in pipeline.caps),
    )


def _plan_from_return(node: Any, env: Mapping[str, Any], context: ShopContext) -> ShopPlan:
    """解释唯一允许的 ``return shop.plan {...}`` 形式。"""
    call = getattr(node, 'values', [None])[0]
    args = getattr(call, 'args', [])
    fields = _table_fields(args[0])
    reserve = _amount_table(fields['reserve'], env, 'reserve') if 'reserve' in fields else {}
    max_spend = _amount_table(fields['max_spend'], env, 'max_spend') if 'max_spend' in fields else {}
    pipeline = _run_pipeline(fields['candidates'], env)
    return _build_plan(pipeline, reserve, max_spend, context)


def _run_block(block: Any, env: dict[str, Any], context: ShopContext) -> ShopPlan | None:
    """顺序执行顶层声明和条件分支，直至返回计划。"""
    if _node_name(block) == 'ElseIf':
        if _lua_truthy(_evaluate_expression(getattr(block, 'test', None), env)):
            return _run_block(getattr(block, 'body', None), env, context)
        orelse = getattr(block, 'orelse', None)
        return _run_block(orelse, env, context) if orelse is not None else None
    for statement in getattr(block, 'body', []):
        name = _node_name(statement)
        if name == 'SemiColon':
            continue
        if name == 'LocalAssign':
            target = _name_id(getattr(statement, 'targets', [None])[0])
            value = getattr(statement, 'values', [None])[0]
            if _node_name(value) == 'Invoke' or _name_id(value) == 'candidates' or isinstance(env.get(_name_id(value)), _Pipeline):
                env[target] = _run_pipeline(value, env)
            else:
                env[target] = _evaluate_expression(value, env)
            continue
        if name == 'If' or name == 'ElseIf':
            if _lua_truthy(_evaluate_expression(getattr(statement, 'test', None), env)):
                return _run_block(getattr(statement, 'body', None), env, context)
            orelse = getattr(statement, 'orelse', None)
            if orelse is not None:
                return _run_block(orelse, env, context)
            return None
        if name == 'Return':
            return _plan_from_return(statement, env, context)
        raise _runtime_error('forbidden_statement', f'不支持 {name} 语句', statement)
    return None


def evaluate_strategy(
    compiled: CompiledStrategy,
    candidates: Iterable[ShopCandidate],
    context: ShopContext,
) -> ShopPlan:
    """运行已编译策略并返回结构化购买计划。

    Args:
        compiled: 由 :func:`compile_strategy` 返回的策略。
        candidates: 已通过业务层硬规则的商品投影列表。
        context: 当前商店会话的余额、已消费金额和购买记录。

    Raises:
        StrategyRuntimeError: 脚本输出、候选数据或规划状态无效。
    """
    if not isinstance(compiled, CompiledStrategy):
        raise TypeError('compiled 必须由 compile_strategy 返回')
    if not isinstance(context, ShopContext):
        raise TypeError('context 必须是 ShopContext')
    values = tuple(candidates)
    if not all(isinstance(candidate, ShopCandidate) for candidate in values):
        raise TypeError('candidates 必须全部是 ShopCandidate')
    identifiers = [candidate.id for candidate in values]
    if len(identifiers) != len(set(identifiers)):
        raise _runtime_error('duplicate_candidate_id', '候选商品 id 不能重复')
    initial = _Pipeline(tuple(
        _RankedCandidate(candidate, index) for index, candidate in enumerate(values)
        if candidate.available
    ))
    env: dict[str, Any] = {
        'candidates': initial,
        'context': _context_values(context),
    }
    result = _run_block(getattr(compiled.tree, 'body', None), env, context)
    if result is None:
        raise _runtime_error('missing_plan', '策略没有返回购买计划')
    return result


def evaluate_source(
    source: str,
    candidates: Iterable[ShopCandidate],
    context: ShopContext,
) -> ShopPlan:
    """编译并运行一段策略源码的便利入口。"""
    return evaluate_strategy(compile_strategy(source), candidates, context)
