"""受限 Lua 风格商店策略的公开接口。"""

from module.shop_strategy.compiler import (
    compile_strategy,
    strategy_diagnostics,
    validate_strategy,
)
from module.shop_strategy.errors import (
    ShopStrategyError,
    StrategyCompileError,
    StrategyDiagnostic,
    StrategyRuntimeError,
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
from module.shop_strategy.runtime import evaluate_source, evaluate_strategy

__all__ = [
    'CompiledStrategy',
    'ShopAction',
    'ShopCap',
    'ShopCandidate',
    'ShopContext',
    'ShopPlan',
    'ShopStrategyError',
    'StrategyCompileError',
    'StrategyDiagnostic',
    'StrategyRuntimeError',
    'compile_strategy',
    'cap_usage_key',
    'merge_caps',
    'evaluate_source',
    'evaluate_strategy',
    'strategy_diagnostics',
    'validate_strategy',
]
