"""商店策略的可展示诊断与异常类型。"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class StrategyDiagnostic:
    """可直接传递给 WebUI 的策略诊断。

    行列均为从 1 开始计数，缺少源码位置时使用 ``None``。
    """

    code: str
    message: str
    line: int | None = None
    column: int | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        """返回 API 可序列化的字段。"""
        return asdict(self)


class ShopStrategyError(ValueError):
    """受限策略不能编译或执行时抛出的基类。"""

    def __init__(self, diagnostic: StrategyDiagnostic):
        self.diagnostic = diagnostic
        location = ''
        if diagnostic.line is not None:
            location = f'（第 {diagnostic.line} 行，第 {diagnostic.column or 1} 列）'
        super().__init__(f'{diagnostic.message}{location}')


class StrategyCompileError(ShopStrategyError):
    """策略源码未通过语法或白名单校验。"""


class StrategyRuntimeError(ShopStrategyError):
    """策略在给定候选商品和上下文下无法生成有效计划。"""
