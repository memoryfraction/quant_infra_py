from dataclasses import dataclass, field
from typing import Tuple, Optional
from underlying import Underlying  # 假设这个模块是可用的


@dataclass(frozen=True)
class UnderlyingPair:
    """
    表示一个配对交易中的标的物对。
    使用 frozen=True 使其不可变，适合作为字典键或集合元素。
    兼容 Python 3.9 及更早版本。
    """
    underlying1: Underlying
    underlying2: Underlying

    # 兼容 Python 3.9 的 Union Type 语法
    pair_info: Optional[dict] = field(default=None)
    # Optional[dict] 是 typing.Union[dict, None] 的简写

    def __post_init__(self):
        # 确保 underlying1 和 underlying2 都是 Underlying 类的实例
        if not isinstance(self.underlying1, Underlying):
            raise TypeError("underlying1 must be an instance of Underlying")
        if not isinstance(self.underlying2, Underlying):
            raise TypeError("underlying2 must be an instance of Underlying")

        # 额外的检查：确保这不是与自身配对
        if self.underlying1.symbol == self.underlying2.symbol:
            raise ValueError("UnderlyingPair must consist of two different underlying assets.")

        # 内部规范化：始终保持 symbol 较小的标的在前，确保 (A, B) 和 (B, A) 在逻辑上视为同一个配对。
        # 由于 dataclass 是 frozen 的，我们需要使用 object.__setattr__
        if self.underlying1.symbol > self.underlying2.symbol:
            object.__setattr__(self, 'underlying1', self.underlying2)
            object.__setattr__(self, 'underlying2', self.underlying1)

    @property
    def symbols(self) -> Tuple[str, str]:
        """返回标的物的符号元组 (symbol1, symbol2)。"""
        return (self.underlying1.symbol, self.underlying2.symbol)

    def __str__(self):
        return f"UnderlyingPair({self.symbols[0]} <-> {self.symbols[1]})"