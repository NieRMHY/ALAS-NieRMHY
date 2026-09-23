"""受限商店策略使用的纯数据模型。"""

from dataclasses import dataclass, field
import json
from typing import Any, Mapping


def _normalise_amounts(value: Mapping[str, int], name: str) -> dict[str, int]:
    """复制金额映射，阻止运行期共享调用方的可变字典。"""
    if not isinstance(value, Mapping):
        raise ValueError(f'{name} 必须是货币金额映射')
    output: dict[str, int] = {}
    for currency, amount in value.items():
        if not isinstance(currency, str) or not currency:
            raise ValueError(f'{name} 的货币名称必须为非空字符串')
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError(f'{name}[{currency!r}] 必须为非负整数')
        output[currency] = amount
    return output


def cap_usage_key(field: str, value: str | int | float | bool | None) -> str:
    """生成跨货架保存配额用量的稳定键，不暴露候选对象。"""
    if not isinstance(field, str) or not field:
        raise ValueError('配额字段必须为非空字符串')
    if isinstance(value, bool) or value is None or isinstance(value, (str, int, float)):
        return json.dumps([field, type(value).__name__, value], ensure_ascii=False, separators=(',', ':'))
    raise ValueError('配额值必须为 Lua 基本类型')


@dataclass(frozen=True, slots=True)
class ShopCandidate:
    """投影给策略脚本的单个商品。

    该模型刻意只包含基本类型字段，不能携带原始 Item、设备或配置对象。
    ``stock`` 和 ``max_quantity`` 都表示可购买次数上限，计划使用两者较小值。
    """

    id: str
    key: str
    name: str = ''
    group: str | None = None
    sub_genre: str | None = None
    tier: str | None = None
    price: int = 0
    cost: str = 'Coin'
    stock: int = 1
    max_quantity: int = 1
    available: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError('商品 id 必须为非空字符串')
        if not isinstance(self.key, str) or not self.key:
            raise ValueError('商品 key 必须为非空字符串')
        if not isinstance(self.cost, str) or not self.cost:
            raise ValueError('商品 cost 必须为非空字符串')
        for name in ('name', 'group', 'sub_genre', 'tier'):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f'商品 {name} 必须为字符串或 None')
        for name in ('price', 'stock', 'max_quantity'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f'商品 {name} 必须为非负整数')
        if not isinstance(self.available, bool):
            raise ValueError('商品 available 必须为布尔值')


@dataclass(frozen=True, slots=True)
class ShopContext:
    """策略运行时的只读会话上下文。"""

    domain: str
    currency: Mapping[str, int] = field(default_factory=dict)
    spent: Mapping[str, int] = field(default_factory=dict)
    purchased: Mapping[str, int] = field(default_factory=dict)
    inventory_purchased: Mapping[str, int] = field(default_factory=dict)
    cap_usage: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.domain, str) or not self.domain:
            raise ValueError('商店 domain 必须为非空字符串')
        object.__setattr__(self, 'currency', _normalise_amounts(self.currency, 'currency'))
        object.__setattr__(self, 'spent', _normalise_amounts(self.spent, 'spent'))
        object.__setattr__(self, 'purchased', _normalise_amounts(self.purchased, 'purchased'))
        object.__setattr__(self, 'inventory_purchased', _normalise_amounts(
            self.inventory_purchased, 'inventory_purchased',
        ))
        object.__setattr__(self, 'cap_usage', _normalise_amounts(self.cap_usage, 'cap_usage'))


@dataclass(frozen=True, slots=True)
class ShopCap:
    """经编译器确认的跨候选数量配额。"""

    field: str
    value: str | int | float | bool | None
    limit: int

    def __post_init__(self) -> None:
        cap_usage_key(self.field, self.value)
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit < 0:
            raise ValueError('配额上限必须为非负整数')


def merge_caps(caps: tuple[ShopCap, ...]) -> tuple[ShopCap, ...]:
    """合并同一字段值的重复配额，取最严格上限并保留首次声明顺序。"""
    merged: dict[str, ShopCap] = {}
    for cap in caps:
        key = cap_usage_key(cap.field, cap.value)
        previous = merged.get(key)
        if previous is None or cap.limit < previous.limit:
            merged[key] = ShopCap(cap.field, cap.value, cap.limit)
    return tuple(merged.values())


@dataclass(frozen=True, slots=True)
class ShopAction:
    """由适配器执行的一项购买动作。"""

    candidate_id: str
    quantity: int
    cost: str
    total_price: int


@dataclass(frozen=True, slots=True)
class ShopPlan:
    """策略生成的结构化购买计划。

    ``spent`` 是本次计划将要消耗的金额，而非 ``ShopContext.spent`` 的副本。
    ``remaining`` 是扣除保留额、会话消费上限和本次计划后仍可支配的金额。
    """

    actions: tuple[ShopAction, ...]
    reserve: Mapping[str, int]
    max_spend: Mapping[str, int]
    spent: Mapping[str, int]
    remaining: Mapping[str, int]
    search_states: int = 0
    caps: tuple[ShopCap, ...] = ()


@dataclass(frozen=True, slots=True)
class CompiledStrategy:
    """已经完成 AST 白名单校验的策略源码。"""

    source: str
    source_hash: str
    tree: Any
    ast_nodes: int
