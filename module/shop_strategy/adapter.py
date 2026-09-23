"""商店策略与现有商品对象之间的无状态适配层。

策略运行时只能接收 :class:`ShopCandidate` 和 :class:`ShopContext`。本模块
负责在进入运行时前投影现有商店的 ``Item``，并在返回后把不可信的计划动作
重新绑定到原对象。这样脚本永远拿不到设备、配置或原始商品对象。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from math import isfinite
from numbers import Integral
from types import MappingProxyType
from typing import TypeAlias

from module.shop_strategy.compiler import compile_strategy
from module.shop_strategy.errors import (
    ShopStrategyError,
    StrategyDiagnostic,
)
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
from module.shop_strategy.runtime import evaluate_strategy


ItemPredicate: TypeAlias = Callable[[object], bool]
QuantityResolver: TypeAlias = int | Callable[[object], int] | None
StockResolver: TypeAlias = int | Callable[[object], int] | None
CandidateIdResolver: TypeAlias = Callable[[object], str] | None
StrategySource: TypeAlias = str | CompiledStrategy


class _AdapterFailure(ValueError):
    """将适配器自身的输入或计划校验错误转换为结构化诊断。"""

    def __init__(self, code: str, message: str) -> None:
        self.diagnostic = StrategyDiagnostic(code, message)
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ShopStrategyProjection:
    """投影后的候选商品及其仅供适配器使用的原对象映射。"""

    candidates: tuple[ShopCandidate, ...]
    _items_by_id: Mapping[str, object] = field(repr=False, compare=False)

    def item_for(self, candidate_id: str) -> object | None:
        """按合成候选 ID 返回原商品对象，仅供 Python 购买流程使用。"""
        return self._items_by_id.get(candidate_id)


@dataclass(frozen=True, slots=True)
class ResolvedShopAction:
    """经二次校验后可由现有商店购买流程执行的一项动作。"""

    item: object = field(repr=False, compare=False)
    candidate: ShopCandidate
    quantity: int
    cost: str
    total_price: int
    cap_usage_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ShopStrategyResult:
    """运行策略后的结构化结果。

    ``success`` 为 ``False`` 时调用方应记录 ``diagnostic`` 并跳过本轮购买；
    不应回退到旧过滤器，以免用户误以为高级策略已经生效。
    """

    success: bool
    actions: tuple[ResolvedShopAction, ...] = ()
    plan: ShopPlan | None = None
    diagnostic: StrategyDiagnostic | None = None
    candidates: tuple[ShopCandidate, ...] = ()


def build_shop_context(
        domain: str,
        currency: Mapping[str, int],
        *,
    spent: Mapping[str, int] | None = None,
    purchased: Mapping[str, int] | None = None,
    inventory_purchased: Mapping[str, int] | None = None,
    cap_usage: Mapping[str, int] | None = None,
) -> ShopContext:
    """构造不可共享可变金额映射的策略上下文。

    Args:
        domain: 当前商店域，例如 ``general``、``event``、``opsi`` 或 ``private_quarters``。
        currency: 当前已识别的各货币余额。
        spent: 本次商店会话已经实际消耗的各货币金额。
        purchased: 脚本可读取的本次商店会话已购买记录。
        inventory_purchased: 仅内部使用的当前货架已购数量，用于库存扣减。
        cap_usage: 仅内部使用的跨货架分类配额已使用数量。

    Returns:
        只含基本类型字段的 :class:`ShopContext`。
    """
    return ShopContext(
        domain=domain,
        currency=currency,
        spent={} if spent is None else spent,
        purchased={} if purchased is None else purchased,
        inventory_purchased={} if inventory_purchased is None else inventory_purchased,
        cap_usage={} if cap_usage is None else cap_usage,
    )


def _normalise_text(value: object, default: str = '') -> str:
    """将商品展示字段压缩为脚本可见的字符串基本类型。"""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _normalise_optional_text(value: object) -> str | None:
    """将商品可选分类字段压缩为字符串或 ``None``。"""
    if value is None:
        return None
    return _normalise_text(value)


def _normalise_non_negative_int(value: object, field_name: str) -> int:
    """拒绝模糊的数值输入，防止数量和价格在边界处被截断。"""
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise _AdapterFailure('invalid_item_field', f'商品 {field_name} 必须为非负整数')
    value = int(value)
    if value < 0:
        raise _AdapterFailure('invalid_item_field', f'商品 {field_name} 必须为非负整数')
    return value


def _item_stock(item: object, resolver: StockResolver) -> int:
    """解析库存；无 OCR 库存的商店可显式传入保守静态上限。"""
    if resolver is None:
        value = getattr(item, 'stock', None)
        if value is None:
            value = getattr(item, 'count', 1)
    elif callable(resolver):
        value = resolver(item)
    else:
        value = resolver
    return _normalise_non_negative_int(value, 'stock')


def _item_is_available(item: object) -> bool:
    """将商品自身的有效性作为不可由脚本绕过的硬条件。"""
    value = getattr(item, 'available', None)
    if value is None:
        value = getattr(item, 'is_valid', True)
    return bool(value)


def _resolve_max_quantity(item: object, stock: int, resolver: QuantityResolver) -> int:
    """计算单个候选商品可购买数量，并始终受识别库存限制。"""
    if resolver is None:
        value = stock
    elif callable(resolver):
        value = resolver(item)
    else:
        value = resolver
    return min(stock, _normalise_non_negative_int(value, 'max_quantity'))


def _location_part(value: object) -> str | None:
    """将可识别的位置值转换为稳定、无对象引用的候选 ID 片段。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, float) and isfinite(value):
        return format(value, '.6g')
    return None


def _id_text(value: object) -> str:
    """仅接受基本类型作为稳定 ID 指纹，避免把宿主对象序列化进来。"""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, float) and isfinite(value):
        return format(value, '.6g')
    return ''


def _default_candidate_id(item: object) -> str:
    """以白名单字段、位置和重复出现序号构造稳定候选 ID 的基础部分。"""
    explicit = getattr(item, 'strategy_id', None)
    if isinstance(explicit, str) and explicit:
        return f'item-{explicit}'

    location: list[str] = []
    shop_index = _location_part(getattr(item, 'shop_index', None))
    if shop_index is not None:
        location.append(f'shop-{shop_index}')
    scroll_pos = _location_part(getattr(item, 'scroll_pos', None))
    if scroll_pos is not None:
        location.append(f'scroll-{scroll_pos}')
    area = getattr(item, 'area', None)
    if isinstance(area, (tuple, list)) and len(area) == 4:
        area_parts = [_location_part(value) for value in area]
        if all(value is not None for value in area_parts):
            location.append('area-' + '-'.join(str(value) for value in area_parts))

    # 库存会随购买变化，不能加入指纹；同类商品没有可用位置时，调用方会在
    # _resolve_candidate_id 中按出现顺序追加序号。这是无位置重复商品的最小限制。
    fingerprint = (
        _id_text(getattr(item, 'key', None)),
        _id_text(getattr(item, 'name', None)),
        _id_text(getattr(item, 'cost', None)),
        _id_text(getattr(item, 'price', None)),
        _id_text(getattr(item, 'group', None)),
        _id_text(getattr(item, 'sub_genre', None)),
        _id_text(getattr(item, 'tier', None)),
        tuple(location),
    )
    digest = sha256(repr(fingerprint).encode('utf-8')).hexdigest()[:16]
    return f'candidate-{digest}'


def _resolve_candidate_id(
        item: object,
        resolver: CandidateIdResolver,
        existing: Mapping[str, object],
) -> str:
    """构造唯一候选 ID；完全同构且无位置的商品按本轮出现顺序加后缀。"""
    value = resolver(item) if resolver is not None else _default_candidate_id(item)
    if not isinstance(value, str) or not value:
        raise _AdapterFailure('invalid_candidate_id', '候选商品 ID 必须为非空字符串')
    candidate_id = value
    duplicate = 2
    while candidate_id in existing:
        candidate_id = f'{value}-{duplicate}'
        duplicate += 1
    return candidate_id


def project_shop_items(
        items: Iterable[object],
        *,
        eligible: ItemPredicate | None = None,
        stock: StockResolver = None,
        max_quantity: QuantityResolver = None,
        candidate_id: CandidateIdResolver = None,
) -> ShopStrategyProjection:
    """将现有商店商品投影为严格白名单的候选 DTO。

    ``eligible`` 在 Python 侧先执行，适合承载余额、活动前置条件、CL1 等
    不可由脚本绕过的业务规则。``stock`` 可覆盖商品原始库存（适合常规商店
    在弹窗前无法识别库存时传入保守静态上限）；``max_quantity`` 可为固定整数，
    或按商品返回数量上限的回调，始终会受有效库存收紧。``candidate_id``
    可为跨刷新稳定 ID 的回调；不提供时优先依据商店位置生成。

    Args:
        items: 当前截图已识别的原始商品对象。
        eligible: 原商品满足所有硬性业务规则时返回真值的回调。
        stock: 每候选商品的固定或动态库存；默认使用 ``stock`` 或 ``count`` 属性。
        max_quantity: 每候选商品的固定或动态购买数量上限。
        candidate_id: 可选的原商品到稳定候选 ID 的映射回调。

    Returns:
        只含白名单字段的候选对象，以及仅限 Python 侧使用的原对象映射。
    """
    candidates: list[ShopCandidate] = []
    items_by_id: dict[str, object] = {}

    for item in items:
        if not _item_is_available(item):
            continue
        price = _normalise_non_negative_int(getattr(item, 'price', 0), 'price')
        # 价格为 0 通常表示 OCR 尚未稳定。必须在宿主资格检查与数量解析前
        # 排除，部分商店的硬性检查会按价格计算可购数量。
        if price <= 0:
            continue
        if eligible is not None:
            try:
                if not eligible(item):
                    continue
            except Exception as exc:
                raise _AdapterFailure('eligibility_error', f'商品硬性资格检查失败：{exc}') from exc

        item_stock = _item_stock(item, stock)
        quantity_limit = _resolve_max_quantity(item, item_stock, max_quantity)
        if item_stock <= 0 or quantity_limit <= 0:
            continue

        item_candidate_id = _resolve_candidate_id(item, candidate_id, items_by_id)
        name = _normalise_text(getattr(item, 'name', ''))
        key = _normalise_text(getattr(item, 'key', None), default=name)
        if not key:
            key = item_candidate_id
        cost = _normalise_text(getattr(item, 'cost', 'Coin'), default='Coin')
        if not cost:
            cost = 'Coin'

        candidate = ShopCandidate(
            id=item_candidate_id,
            key=key,
            name=name,
            group=_normalise_optional_text(getattr(item, 'group', None)),
            sub_genre=_normalise_optional_text(getattr(item, 'sub_genre', None)),
            tier=_normalise_optional_text(getattr(item, 'tier', None)),
            price=price,
            cost=cost,
            stock=item_stock,
            max_quantity=quantity_limit,
            available=True,
        )
        candidates.append(candidate)
        items_by_id[item_candidate_id] = item

    return ShopStrategyProjection(
        candidates=tuple(candidates),
        _items_by_id=MappingProxyType(items_by_id),
    )


def _normalise_plan_amounts(value: object, name: str) -> dict[str, int]:
    """读取引擎返回的金额表，拒绝未知形状和负数。"""
    if not isinstance(value, Mapping):
        raise _AdapterFailure('invalid_plan', f'策略计划的 {name} 必须为货币金额表')

    amounts: dict[str, int] = {}
    for currency, amount in value.items():
        if not isinstance(currency, str) or not currency:
            raise _AdapterFailure('invalid_plan', f'策略计划的 {name} 包含无效货币名称')
        amounts[currency] = _normalise_non_negative_int(amount, f'{name}[{currency}]')
    return amounts


def _validate_plan_budget(
        action_totals: Mapping[str, int],
        plan: ShopPlan,
        context: ShopContext,
) -> None:
    """在执行前根据真实上下文重新验证策略输出的资金边界。"""
    reserve = _normalise_plan_amounts(plan.reserve, 'reserve')
    max_spend = _normalise_plan_amounts(plan.max_spend, 'max_spend')
    plan_spent = _normalise_plan_amounts(plan.spent, 'spent')
    plan_remaining = _normalise_plan_amounts(plan.remaining, 'remaining')

    if plan_spent != dict(action_totals):
        raise _AdapterFailure('plan_spent_mismatch', '策略计划的 spent 与购买动作金额不一致')

    known_currency = set(context.currency)
    for currency in set(context.spent) | set(reserve) | set(max_spend) | set(plan_spent):
        if currency not in known_currency:
            raise _AdapterFailure('unknown_currency', f'策略计划引用了未提供余额的货币 {currency!r}')

    expected_remaining: dict[str, int] = {}
    for currency, balance in context.currency.items():
        already_spent = context.spent.get(currency, 0)
        reserved = reserve.get(currency, 0)
        total = action_totals.get(currency, 0)
        available = max(0, balance - reserved)
        if reserved + total > balance:
            raise _AdapterFailure('budget_exceeded', f'策略计划超出 {currency!r} 的可用余额')
        if currency in max_spend and already_spent + total > max_spend[currency]:
            raise _AdapterFailure('max_spend_exceeded', f'策略计划超出 {currency!r} 的消费上限')
        if currency in max_spend:
            available = min(available, max(0, max_spend[currency] - already_spent))
        expected_remaining[currency] = available - total

    if plan_remaining != expected_remaining:
        raise _AdapterFailure('remaining_mismatch', '策略计划的 remaining 与真实余额计算不一致')


def resolve_shop_plan(
        plan: ShopPlan,
        projection: ShopStrategyProjection,
        context: ShopContext,
) -> tuple[ResolvedShopAction, ...]:
    """把策略计划重新绑定到原商品，并执行不可信输出的二次校验。

    Args:
        plan: 策略引擎返回的购买计划。
        projection: 本轮策略运行前生成的商品投影。
        context: 本轮的真实余额与会话消费上下文。

    Returns:
        可安全交给既有购买流程执行的动作序列。

    Raises:
        _AdapterFailure: 计划引用未知商品、伪造价格/货币或超出边界时抛出。
    """
    if not isinstance(plan, ShopPlan):
        raise _AdapterFailure('invalid_plan', '策略引擎没有返回 ShopPlan')
    if not isinstance(plan.actions, tuple):
        raise _AdapterFailure('invalid_plan', '策略计划的 actions 必须为元组')

    candidates_by_id = {candidate.id: candidate for candidate in projection.candidates}
    if not isinstance(plan.caps, tuple) or not all(isinstance(cap, ShopCap) for cap in plan.caps):
        raise _AdapterFailure('invalid_plan', '策略计划的 caps 必须是 ShopCap 元组')
    # 运行时会合并 cap，但这里仍须把它视为不可信计划再次收紧。否则手工
    # 构造的重复 cap 会在同一动作中被重复累计，从而错误拒绝合法购买。
    caps = merge_caps(plan.caps)
    cap_usage = {
        cap_usage_key(cap.field, cap.value): context.cap_usage.get(cap_usage_key(cap.field, cap.value), 0)
        for cap in caps
    }
    actions: list[ResolvedShopAction] = []
    action_totals: dict[str, int] = {}
    used_ids: set[str] = set()

    for action in plan.actions:
        if not isinstance(action, ShopAction):
            raise _AdapterFailure('invalid_action', '策略计划包含无效购买动作')
        if not isinstance(action.candidate_id, str) or not action.candidate_id:
            raise _AdapterFailure('invalid_candidate_id', '策略计划的候选商品 ID 必须为非空字符串')
        if not isinstance(action.cost, str) or not action.cost:
            raise _AdapterFailure('invalid_cost', '策略计划的货币必须为非空字符串')
        if action.candidate_id in used_ids:
            raise _AdapterFailure('duplicate_action', '策略计划不能重复购买同一候选商品')
        used_ids.add(action.candidate_id)

        candidate = candidates_by_id.get(action.candidate_id)
        item = projection.item_for(action.candidate_id)
        if candidate is None or item is None or not candidate.available:
            raise _AdapterFailure('unknown_candidate', '策略计划引用了不可购买的商品')
        if isinstance(action.quantity, bool) or not isinstance(action.quantity, Integral):
            raise _AdapterFailure('invalid_quantity', '策略计划的购买数量必须为正整数')
        quantity = int(action.quantity)
        already_purchased = context.inventory_purchased.get(candidate.id, 0)
        quantity_limit = max(0, min(candidate.stock, candidate.max_quantity) - already_purchased)
        if quantity <= 0 or quantity > quantity_limit:
            raise _AdapterFailure('quantity_exceeded', '策略计划的购买数量超出商品上限')
        if action.cost != candidate.cost:
            raise _AdapterFailure('cost_mismatch', '策略计划的货币与商品实际货币不一致')

        total_price = candidate.price * quantity
        if isinstance(action.total_price, bool) or not isinstance(action.total_price, Integral):
            raise _AdapterFailure('invalid_total_price', '策略计划的购买金额必须为非负整数')
        if action.total_price != total_price:
            raise _AdapterFailure('price_mismatch', '策略计划的金额与商品实际价格不一致')

        cap_keys = []
        for cap in caps:
            if getattr(candidate, cap.field) != cap.value:
                continue
            key = cap_usage_key(cap.field, cap.value)
            if cap_usage[key] + quantity > cap.limit:
                raise _AdapterFailure('cap_exceeded', '策略计划超出分类数量配额')
            cap_usage[key] += quantity
            cap_keys.append(key)
        action_totals[candidate.cost] = action_totals.get(candidate.cost, 0) + total_price
        actions.append(ResolvedShopAction(
            item=item,
            candidate=candidate,
            quantity=quantity,
            cost=candidate.cost,
            total_price=total_price,
            cap_usage_keys=tuple(dict.fromkeys(cap_keys)),
        ))

    _validate_plan_budget(action_totals, plan, context)
    return tuple(actions)


def _failure_result(
        exc: Exception,
        candidates: tuple[ShopCandidate, ...] = (),
) -> ShopStrategyResult:
    """将所有策略和适配错误收敛为调用方可记录的失败结果。"""
    if isinstance(exc, ShopStrategyError):
        diagnostic = exc.diagnostic
    elif isinstance(exc, _AdapterFailure):
        diagnostic = exc.diagnostic
    else:
        diagnostic = StrategyDiagnostic('adapter_error', f'商店策略适配失败：{exc}')
    return ShopStrategyResult(
        success=False,
        diagnostic=diagnostic,
        candidates=candidates,
    )


def run_shop_strategy(
        strategy: StrategySource,
        items: Iterable[object],
        *,
        domain: str,
        currency: Mapping[str, int],
        eligible: ItemPredicate | None = None,
        stock: StockResolver = None,
        max_quantity: QuantityResolver = None,
        candidate_id: CandidateIdResolver = None,
        spent: Mapping[str, int] | None = None,
        purchased: Mapping[str, int] | None = None,
        inventory_purchased: Mapping[str, int] | None = None,
        cap_usage: Mapping[str, int] | None = None,
) -> ShopStrategyResult:
    """运行高级商店策略并返回已经二次校验的购买动作。

    调用方应在每次购买成功或货架刷新后重新调用此函数，并把真实余额、已消费
    金额、脚本可见购买历史、当前货架库存扣减和分类配额用量带回。任何脚本、
    投影或计划校验失败都会以 ``success=False`` 返回，而不会将异常泄漏到游戏
    状态循环。

    Args:
        strategy: 已编译策略或待编译的 Lua 风格源码。
        items: 当前截图识别出的原始商品对象。
        domain: 当前商店域。
        currency: 当前已识别的货币余额。
        eligible: Python 侧不可绕过的商品资格检查。
        stock: 可选的每商品库存解析器；用于尚未识别库存的商店。
        max_quantity: 每商品固定或动态购买上限。
        candidate_id: 可选的跨货架刷新稳定候选 ID 解析器。
        spent: 本会话已实际消耗的货币金额。
        purchased: 脚本可读取的本会话已实际购买记录。
        inventory_purchased: 当前货架已购买数量，用于防止重新扫描时重复购买。
        cap_usage: 跨货架已使用的分类配额，用于防止同类新品绕过上限。

    Returns:
        成功时包含已绑定原商品的动作；失败时包含结构化诊断。
    """
    projection: ShopStrategyProjection | None = None
    try:
        projection = project_shop_items(
            items,
            eligible=eligible,
            stock=stock,
            max_quantity=max_quantity,
            candidate_id=candidate_id,
        )
        context = build_shop_context(
            domain,
            currency,
            spent=spent,
            purchased=purchased,
            inventory_purchased=inventory_purchased,
            cap_usage=cap_usage,
        )
        if isinstance(strategy, str):
            compiled = compile_strategy(strategy)
        elif isinstance(strategy, CompiledStrategy):
            compiled = strategy
        else:
            raise _AdapterFailure('invalid_strategy', '策略必须是 Lua 源码或 CompiledStrategy')
        plan = evaluate_strategy(compiled, projection.candidates, context)
        actions = resolve_shop_plan(plan, projection, context)
        return ShopStrategyResult(
            success=True,
            actions=actions,
            plan=plan,
            candidates=projection.candidates,
        )
    except Exception as exc:
        candidates = () if projection is None else projection.candidates
        return _failure_result(exc, candidates)
